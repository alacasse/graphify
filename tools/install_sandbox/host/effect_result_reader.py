"""Validate native retained inputs, explicit phases, continuity and verdicts."""

from pathlib import Path, PurePosixPath
from typing import Literal, cast

from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import (
    CommandEvidence,
    InstallTestResult,
    StepState,
    VerificationResult,
)
from tools.install_sandbox.contracts.spec import fields, text
from tools.install_sandbox.host.evidence_reader import (
    check_environment,
    check_snapshot,
    read_json_evidence,
    retained_snapshot,
    safe_evidence_path,
)
from tools.install_sandbox.host.intermediate_reader import replay_intermediate
from tools.install_sandbox.host.step_artifacts import inventory
from tools.install_sandbox.rules.effect_verifier import EffectVerifier
from tools.install_sandbox.rules.expectation_builder import (
    bind_roots,
    build_initial_expectations,
    build_install_expectations,
    build_reinstall_expectations,
)
from tools.install_sandbox.rules.repair_protocol import RepairInputs
from tools.install_sandbox.rules.step_lifecycle import Artifact, RetainedFacts, inspect


def _snapshot(output: Path, relative: str) -> FilesystemSnapshot:
    snapshot = retained_snapshot(output, relative)
    entries = check_snapshot(output, relative, complete=False)
    for entry in entries:
        key = (str(entry["root"]), str(entry["path"]))
        obstructed = any((o["root"], o["path"]) == key for o in snapshot.obstacles)
        if entry["kind"] == "file" and key not in snapshot.contents and not obstructed:
            raise ValueError("Observation requires retained file bytes")
        if relative != "expected.json" and entry["path"] != ".":
            parent = str(PurePosixPath(str(entry["path"])).parent)
            observed = snapshot.entry(key[0], parent)
            if observed is None or observed["kind"] != "directory":
                raise ValueError("Observation requires each parent directory")
    return snapshot


def _same_observation(first: FilesystemSnapshot, second: FilesystemSnapshot) -> bool:
    def inventory(snapshot: FilesystemSnapshot) -> list[dict[str, object]]:
        return [
            {key: value for key, value in entry.items() if key not in {"content_file", "sha256"}}
            for entry in sorted(snapshot.entries, key=lambda e: (e["root"], e["path"]))
        ]

    return (
        inventory(first) == inventory(second)
        and first.contents == second.contents
        and first.obstacles == second.obstacles
    )


def _expectations(output: Path, expected: ExpectationSet) -> None:
    stored = ExpectationSet.from_data(
        read_json_evidence(output, f"expectations/{expected.phase}.json")
    )
    if stored != expected:
        raise ValueError(f"Stored {expected.phase} expectations contradict retained inputs")


def _roots(output: Path) -> dict[str, str]:
    data = fields(read_json_evidence(output, "roots.json"), "home project")
    roots = {key: text(value) for key, value in data.items()}
    project, home = (PurePosixPath(roots[key]) for key in ("project", "home"))
    if (
        not project.is_absolute()
        or project.name != "project"
        or home != project.parent / "home"
        or ".." in project.parts
        or str(project) != roots["project"]
        or str(home) != roots["home"]
    ):
        raise ValueError("Evidence requires canonical isolated roots")
    return roots


def check_effect_result(
    result: InstallTestResult, case: EffectInstallCase, output: Path
) -> str | None:
    steps_directory = safe_evidence_path(output, "steps")
    if steps_directory.exists():
        if not steps_directory.is_dir():
            raise ValueError("Steps evidence requires a directory")
        for child in steps_directory.iterdir():
            safe_evidence_path(output, child.relative_to(output).as_posix())
            if (
                child.name not in {str(index) for index in range(len(result.steps))}
                or not child.is_dir()
            ):
                raise ValueError("Unknown step evidence directory")
    retained = EffectInstallCase.from_json(
        safe_evidence_path(output, "case.json").read_text(encoding="utf-8")
    )
    if case.intermediate_preparation is None:
        _absent(output, ("intermediate", "expectations/intermediate.json"))
    if retained != case:
        raise ValueError("Retained case contradicts requested case")
    for relative in ("journal.log", result.preparation["log"]):
        safe_evidence_path(output, relative).read_bytes()
    failure = output / "construction-failure.json"
    if failure.exists() or failure.is_symlink():
        if result.preparation["ready"]:
            raise ValueError("Ready preparation contradicts retained construction failure")
        _failed_initial(result, case, output)
        return _unstarted_repair(result, output)
    roots = _roots(output)
    sources = _snapshot(output, "expected.json")
    initial = bind_roots(build_initial_expectations(case, sources), roots)
    return _initial_and_steps(result, case, output, roots, sources, initial)


def _unstarted_repair(result: InstallTestResult, output: Path) -> str | None:
    if result.intermediate_preparation is None:
        return None
    inputs = RepairInputs(
        safe_evidence_path(output, "case.json").read_bytes(),
        FilesystemSnapshot(),
        ExpectationSet("install", ()),
        FilesystemSnapshot(),
        result.steps[0],
    )
    return replay_intermediate(result, output, inputs, _snapshot).diagnostic


def _initial_and_steps(
    result: InstallTestResult,
    case: EffectInstallCase,
    output: Path,
    roots: dict[str, str],
    sources: FilesystemSnapshot,
    initial: ExpectationSet,
) -> str | None:
    _expectations(output, initial)
    before = _snapshot(output, "steps/0/before.json")
    computed = EffectVerifier().verify(initial, before)
    saved = VerificationResult.from_data(read_json_evidence(output, "initial-verification.json"))
    if result.preparation.get("stage") != "initial_verified" or computed != saved:
        raise ValueError("Initial stage or verification contradicts observations")
    if not result.preparation["ready"]:
        if computed.complete and not computed.mismatches:
            raise ValueError("Failed preparation contradicts conforming initial observations")
        _no_initial_execution(output)
        return _unstarted_repair(result, output)
    if not computed.complete or computed.mismatches:
        raise ValueError("Installation requires successful initial verification")
    installed = build_install_expectations(case, sources, before, roots)
    return _steps(result, case, output, roots, installed, before, sources)


def _failed_initial(result: InstallTestResult, case: EffectInstallCase, output: Path) -> None:
    data = fields(read_json_evidence(output, "construction-failure.json"), "stage kind reason")
    stage, kind = text(data["stage"]), text(data["kind"])
    text(data["reason"])
    phases = {
        "environment": "started",
        "sources": "started",
        "initial_expectations": "sources_retained",
        "initial_observation": "sources_retained",
        "initial_verification": "sources_retained",
        "install_expectations": "initial_verified",
    }
    if kind not in {"io", "validation"} or phases.get(stage) != result.preparation["stage"]:
        raise ValueError("Construction failure contradicts initial preparation substage")
    _no_initial_execution(output)
    if stage in {"environment", "sources"}:
        _absent(
            output,
            ("expectations/initial.json", "steps/0/before.json", "initial-verification.json"),
        )
        return
    _failed_initial_expectations(case, output, stage, kind)


def _no_initial_execution(output: Path) -> None:
    _no_phase_evidence(output, 1)
    _absent(
        output,
        (
            "expectations/install.json",
            "steps/0/after.json",
            "steps/0/after",
            "steps/0/environment.json",
            "steps/0/verification.json",
            "steps/0/failure.json",
            "steps/0/stdout.txt",
            "steps/0/stderr.txt",
        ),
    )


def _failed_initial_expectations(
    case: EffectInstallCase, output: Path, stage: str, kind: str
) -> None:
    roots, sources = _roots(output), _snapshot(output, "expected.json")
    try:
        initial = bind_roots(build_initial_expectations(case, sources), roots)
    except ValueError:
        if stage != "initial_expectations" or kind != "validation":
            raise
        _absent(
            output,
            ("expectations/initial.json", "steps/0/before.json", "initial-verification.json"),
        )
        return
    if stage == "initial_expectations":
        if kind != "io":
            raise ValueError("Failed construction contradicts successfully rebuilt expectations")
        _absent(output, ("steps/0/before.json", "initial-verification.json"))
        return
    _expectations(output, initial)
    if stage == "initial_observation":
        if kind != "io":
            raise ValueError("Initial observation failure requires an I/O diagnostic")
        _absent(output, ("initial-verification.json",))
        return
    _failed_initial_verification(case, output, stage, kind, sources, roots, initial)


def _failed_initial_verification(
    case: EffectInstallCase,
    output: Path,
    stage: str,
    kind: str,
    sources: FilesystemSnapshot,
    roots: dict[str, str],
    initial: ExpectationSet,
) -> None:
    before = _snapshot(output, "steps/0/before.json")
    computed = EffectVerifier().verify(initial, before)
    if stage == "initial_verification":
        if kind != "io":
            raise ValueError("Initial verification persistence failure requires an I/O diagnostic")
        return
    saved = VerificationResult.from_data(read_json_evidence(output, "initial-verification.json"))
    if computed != saved or not computed.complete or computed.mismatches:
        raise ValueError("Install expectations require conforming initial verification")
    try:
        build_install_expectations(case, sources, before, roots)
    except ValueError:
        if kind != "validation":
            raise
        return
    raise ValueError("Failed construction contradicts successfully rebuilt install expectations")


def _steps(
    result: InstallTestResult,
    case: EffectInstallCase,
    output: Path,
    roots: dict[str, str],
    expected: ExpectationSet,
    previous: FilesystemSnapshot,
    sources: FilesystemSnapshot,
) -> str | None:
    first_command: tuple[list[str], str] | None = None
    previous_verdict: VerificationResult | None = None
    diagnostic: str | None = None
    installed = expected
    for index, step in enumerate(result.steps):
        if index:
            expected, previous, diagnostic = _transition(
                result, case, output, sources, installed, expected, previous, previous_verdict
            )
        after, verdict = _inspect_step(
            step, case, output, index, roots, first_command, previous, expected
        )
        if step.command is not None:
            first_command = step.command["args"], step.command["cwd"]
        if after is not None:
            previous = after
        previous_verdict = verdict
    return diagnostic


def _transition(
    result: InstallTestResult,
    case: EffectInstallCase,
    output: Path,
    sources: FilesystemSnapshot,
    installed: ExpectationSet,
    expected: ExpectationSet,
    previous: FilesystemSnapshot,
    verdict: VerificationResult | None,
) -> tuple[ExpectationSet, FilesystemSnapshot, str | None]:
    if case.intermediate_preparation is not None:
        inspection = replay_intermediate(
            result,
            output,
            RepairInputs(
                safe_evidence_path(output, "case.json").read_bytes(),
                sources,
                installed,
                previous,
                result.steps[0],
            ),
            _snapshot,
        )
        if inspection.ready is None:
            if result.steps[1].phase != "idle":
                raise ValueError("Repair requires published conforming preparation")
            return expected, previous, inspection.diagnostic
        return inspection.ready.expectations, inspection.ready.baseline, inspection.diagnostic
    if result.steps[1].phase != "idle" and verdict is not None:
        expected = build_reinstall_expectations(expected, previous, verdict)
    return expected, previous, None


def _absent(output: Path, relatives: tuple[str, ...]) -> None:
    if any(
        (output / relative).exists() or (output / relative).is_symlink() for relative in relatives
    ):
        raise ValueError("Execution stage contradicts retained later evidence")


def _no_phase_evidence(output: Path, index: int) -> None:
    phase = "install" if index == 0 else "reinstall"
    _absent(output, (f"steps/{index}", f"expectations/{phase}.json"))


def _inspect_step(
    step: StepState,
    case: EffectInstallCase,
    output: Path,
    index: int,
    roots: dict[str, str],
    first_command: tuple[list[str], str] | None,
    previous: FilesystemSnapshot,
    expected: ExpectationSet,
) -> tuple[FilesystemSnapshot | None, VerificationResult | None]:
    loaded, staged = inventory(output, index, _snapshot)
    prefix = f"steps/{index}"
    failure = loaded.get(f"{prefix}/failure.json")
    stopped = None if failure is None else StepState.from_data(failure)
    claim = stopped or step
    repair_owns_expectations = bool(
        index
        and case.intermediate_preparation is not None
        and (
            claim.phase == "idle"
            or claim.phase == "preparation"
            or (claim.stop is not None and claim.stop.phase == "preparation")
        )
    )
    phase = "install" if index == 0 else "reinstall"
    expectation_reference = f"expectations/{phase}.json"
    has_expectations = safe_evidence_path(output, expectation_reference).exists()
    if has_expectations:
        _expectations(output, expected)
    before = loaded.get(f"{prefix}/before.json")
    after = loaded.get(f"{prefix}/after.json")
    before_usable = isinstance(before, FilesystemSnapshot) and _same_observation(previous, before)
    if isinstance(before, FilesystemSnapshot) and before.obstacles:
        before_usable = False
    if index == 0 and not before_usable:
        raise ValueError("Initial step continuity contradicts previous observation")
    for name, reference in claim.observations.items():
        if reference is None:
            continue
        if reference != f"{prefix}/{name}.json":
            raise ValueError("Evidence references must belong to their own step")
        if reference not in loaded:
            raise ValueError("Missing referenced observation")
    command = claim.command
    if command is not None:
        _partial_command_binding(command, case, roots, first_command)
        outputs: tuple[tuple[Literal["stdout_file", "stderr_file"], str], ...] = (
            ("stdout_file", "stdout.txt"),
            ("stderr_file", "stderr.txt"),
        )
        for key, filename in outputs:
            reference = command[key]
            if reference is not None and (
                reference != f"{prefix}/{filename}" or reference not in loaded
            ):
                raise ValueError("Command requires its own retained output")
    if f"{prefix}/environment.json" in loaded:
        binding = command or {
            "args": ["retained", *case.subject.invocation],
            "cwd": roots["project"],
            "state": "not_started",
            "exit_code": None,
            "reason": None,
            "stdout_file": None,
            "stderr_file": None,
        }
        check_environment(binding, output, index)
    saved = loaded.get(f"{prefix}/verification.json")
    verdict = None if saved is None else VerificationResult.from_data(saved)
    if verdict is not None:
        if (
            not isinstance(after, FilesystemSnapshot)
            or EffectVerifier().verify(expected, after) != verdict
        ):
            raise ValueError("Verification contradicts retained explicit expectations")
    if claim.verification is not None and (
        not isinstance(after, FilesystemSnapshot)
        or EffectVerifier().verify(expected, after) != claim.verification
    ):
        raise ValueError("Verification contradicts retained explicit expectations")
    stop = stopped.stop if stopped is not None else None
    kinds = {
        f"{prefix}/before.json": "before",
        f"{prefix}/after.json": "after",
        f"{prefix}/environment.json": "environment",
        f"{prefix}/verification.json": "verification",
        f"{prefix}/failure.json": "failure",
        expectation_reference: "expectations",
    }
    facts = RetainedFacts(
        expectations=has_expectations and not repair_owns_expectations,
        external_expectations=has_expectations and repair_owns_expectations,
        before=isinstance(before, FilesystemSnapshot) and not (index == 0 and step.phase == "idle"),
        before_usable=before_usable,
        environment=f"{prefix}/environment.json" in loaded,
        stdout=f"{prefix}/stdout.txt" in loaded,
        stderr=f"{prefix}/stderr.txt" in loaded,
        after=isinstance(after, FilesystemSnapshot),
        verification=verdict,
        stop=stop,
        stopped_state=stopped,
        staged=tuple(
            frozenset(cast(Artifact, kinds[owner]) for owner in entry.owners if owner in kinds)
            for entry in staged
            if not (repair_owns_expectations and entry.owners == frozenset({expectation_reference}))
        ),
    )
    if (
        claim.retained.expectations is not None
        and claim.retained.expectations != expectation_reference
    ):
        raise ValueError("Expectations reference must belong to its own step")
    if (
        claim.retained.verification is not None
        and claim.retained.verification != f"{prefix}/verification.json"
    ):
        raise ValueError("Verification reference must belong to its own step")
    inspect(step, facts)
    return after if isinstance(after, FilesystemSnapshot) else None, verdict


def _partial_command_binding(
    command: CommandEvidence,
    case: EffectInstallCase,
    roots: dict[str, str],
    first_command: tuple[list[str], str] | None,
) -> None:
    if command["args"][1:] != list(case.subject.invocation) or command["cwd"] != roots["project"]:
        raise ValueError("Partial command facts contradict invocation or retained roots")
    if first_command is not None and (command["args"], command["cwd"]) != first_command:
        raise ValueError("Partial reinstallation must repeat the same command")
