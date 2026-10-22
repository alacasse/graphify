"""Validate native retained inputs, explicit phases, continuity and verdicts."""

from pathlib import Path, PurePosixPath

from tools.install_sandbox.container.effect_verifier import EffectVerifier
from tools.install_sandbox.container.environment import FilesystemSnapshot
from tools.install_sandbox.container.expectation_builder import (
    bind_roots,
    build_initial_expectations,
    build_install_expectations,
    build_reinstall_expectations,
)
from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.results import (
    CommandEvidence,
    InstallTestResult,
    StepEvidence,
    VerificationResult,
)
from tools.install_sandbox.contracts.spec import fields, text
from tools.install_sandbox.host.evidence_reader import (
    check_environment,
    check_snapshot,
    read_json_evidence,
    retained_snapshot,
    safe_evidence_path,
    verification,
)


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
            {key: value for key, value in entry.items() if key != "content_file"}
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


def check_effect_result(result: InstallTestResult, case: EffectInstallCase, output: Path) -> None:
    retained = EffectInstallCase.from_json(
        safe_evidence_path(output, "case.json").read_text(encoding="utf-8")
    )
    if retained != case:
        raise ValueError("Retained case contradicts requested case")
    for relative in ("journal.log", result.preparation["log"]):
        safe_evidence_path(output, relative).read_bytes()
    failure = output / "construction-failure.json"
    if failure.exists() or failure.is_symlink():
        if result.preparation["ready"]:
            raise ValueError("Ready preparation contradicts retained construction failure")
        _failed_initial(result, case, output)
        return
    roots = _roots(output)
    sources = _snapshot(output, "expected.json")
    initial = bind_roots(build_initial_expectations(case, sources), roots)
    _initial_and_steps(result, case, output, roots, sources, initial)


def _initial_and_steps(
    result: InstallTestResult,
    case: EffectInstallCase,
    output: Path,
    roots: dict[str, str],
    sources: FilesystemSnapshot,
    initial: ExpectationSet,
) -> None:
    _expectations(output, initial)
    before = _snapshot(output, "steps/0/before.json")
    computed = EffectVerifier().verify(initial, before)
    saved = verification(read_json_evidence(output, "initial-verification.json"))
    if result.preparation.get("stage") != "initial_verified" or computed != saved:
        raise ValueError("Initial stage or verification contradicts observations")
    if not result.preparation["ready"]:
        if computed.complete and not computed.mismatches:
            raise ValueError("Failed preparation contradicts conforming initial observations")
        _no_initial_execution(output)
        return
    if not computed.complete or computed.mismatches:
        raise ValueError("Installation requires successful initial verification")
    installed = build_install_expectations(case, sources, before, roots)
    _steps(result, case, output, roots, installed, before)


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
    saved = verification(read_json_evidence(output, "initial-verification.json"))
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
) -> None:
    first_command: tuple[list[str], str] | None = None
    previous_verdict: VerificationResult | None = None
    for index, step in enumerate(result.steps):
        if "failure" in step:
            _failed_phase(
                step,
                case,
                output,
                index,
                expected,
                previous,
                previous_verdict,
                roots,
                first_command,
            )
            for later in range(index + 1, len(result.steps)):
                _no_phase_evidence(output, later)
            return
        command = step["command"]
        if command is None:
            _no_phase_evidence(output, index)
            continue
        if index:
            assert previous_verdict is not None
            expected = build_reinstall_expectations(expected, previous, previous_verdict)
        _expectations(output, expected)
        first_command = _command_binding(command, case, output, index, roots, first_command)
        saved = _step_evidence(step, command, output, index)
        before = _snapshot(output, f"steps/{index}/before.json")
        if not _same_observation(previous, before):
            raise ValueError("Phase continuity contradicts previous observation")
        after = _snapshot(output, f"steps/{index}/after.json")
        if EffectVerifier().verify(expected, after) != saved:
            raise ValueError("Verification contradicts retained explicit expectations")
        previous, previous_verdict = after, saved


def _absent(output: Path, relatives: tuple[str, ...]) -> None:
    if any(
        (output / relative).exists() or (output / relative).is_symlink() for relative in relatives
    ):
        raise ValueError("Execution stage contradicts retained later evidence")


def _no_phase_evidence(output: Path, index: int) -> None:
    phase = "install" if index == 0 else "reinstall"
    _absent(output, (f"steps/{index}", f"expectations/{phase}.json"))


def _failed_phase(
    step: StepEvidence,
    case: EffectInstallCase,
    output: Path,
    index: int,
    expected: ExpectationSet,
    previous: FilesystemSnapshot,
    previous_verdict: VerificationResult | None,
    roots: dict[str, str],
    first_command: tuple[list[str], str] | None,
) -> None:
    failure = step.get("failure")
    assert failure is not None
    if read_json_evidence(output, f"steps/{index}/failure.json") != failure:
        raise ValueError("Failed execution stage differs from saved failure evidence")
    stage = failure["stage"]
    if stage == "preparation":
        if not index:
            raise ValueError("First phase has no dependent step preparation")
        _absent(
            output,
            (
                "expectations/reinstall.json",
                f"steps/{index}/after.json",
                f"steps/{index}/verification.json",
                f"steps/{index}/environment.json",
            ),
        )
        return
    if index:
        assert previous_verdict is not None
        expected = build_reinstall_expectations(expected, previous, previous_verdict)
    before = _snapshot(output, f"steps/{index}/before.json")
    if not _same_observation(previous, before):
        raise ValueError("Failed phase continuity contradicts previous observation")
    if stage == "expectations":
        _absent(
            output,
            (
                f"steps/{index}/after.json",
                f"steps/{index}/verification.json",
                f"steps/{index}/environment.json",
            ),
        )
        return
    _expectations(output, expected)
    _failed_command_phase(step, case, output, index, expected, roots, first_command)


def _failed_command_phase(
    step: StepEvidence,
    case: EffectInstallCase,
    output: Path,
    index: int,
    expected: ExpectationSet,
    roots: dict[str, str],
    first_command: tuple[list[str], str] | None,
) -> None:
    failure = step.get("failure")
    assert failure is not None
    stage = failure["stage"]
    if stage == "command":
        _absent(
            output,
            (
                f"steps/{index}/after.json",
                f"steps/{index}/verification.json",
                f"steps/{index}/environment.json",
            ),
        )
        return
    command = step["command"]
    assert command is not None
    if stage == "command_evidence":
        _partial_command_binding(command, case, roots, first_command)
        _absent(output, (f"steps/{index}/after.json", f"steps/{index}/verification.json"))
        return
    _command_binding(command, case, output, index, roots, first_command)
    _command_outputs(command, output, index)
    if stage == "observation":
        _absent(output, (f"steps/{index}/verification.json",))
        return
    after = _snapshot(output, f"steps/{index}/after.json")
    if step["observations"] != {
        "before": f"steps/{index}/before.json",
        "after": f"steps/{index}/after.json",
    }:
        raise ValueError("Failed verification requires its phase observations")
    computed = EffectVerifier().verify(expected, after)
    if stage == "verification":
        _absent(output, (f"steps/{index}/verification.json",))
    elif computed != step["verification"]:
        raise ValueError("Partial verification contradicts retained explicit expectations")


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


def _command_outputs(command: CommandEvidence, output: Path, index: int) -> None:
    for key, filename in (("stdout_file", "stdout.txt"), ("stderr_file", "stderr.txt")):
        relative = f"steps/{index}/{filename}"
        if command[key] != relative:
            raise ValueError("Command requires its own retained output")
        safe_evidence_path(output, relative).read_bytes()


def _step_evidence(
    step: StepEvidence,
    command: CommandEvidence,
    output: Path,
    index: int,
) -> VerificationResult:
    if step["observations"] != {
        "before": f"steps/{index}/before.json",
        "after": f"steps/{index}/after.json",
    }:
        raise ValueError("Command requires its own observations")
    _command_outputs(command, output, index)
    saved = verification(read_json_evidence(output, f"steps/{index}/verification.json"))
    if saved != step["verification"]:
        raise ValueError("Verification differs from saved evidence")
    return saved


def _command_binding(
    command: CommandEvidence,
    case: EffectInstallCase,
    output: Path,
    index: int,
    roots: dict[str, str],
    first: tuple[list[str], str] | None,
) -> tuple[list[str], str]:
    if command["args"][1:] != list(case.subject.invocation) or command["cwd"] != roots["project"]:
        raise ValueError("Command contradicts invocation or retained roots")
    identity = command["args"], command["cwd"]
    if first is not None and identity != first:
        raise ValueError("Reinstallation must repeat the same command")
    check_environment(command, output, index)
    return identity
