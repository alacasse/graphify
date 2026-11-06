"""Validate native retained inputs, explicit phases, continuity and verdicts."""

from pathlib import Path, PurePosixPath
from typing import Literal, cast

from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import (
    CommandEvidence,
    InstallTestResult,
    RepairProgress,
    StepState,
    VerificationResult,
)
from tools.install_sandbox.host.evidence_reader import (
    check_environment,
    check_snapshot,
    read_json_evidence,
    retained_snapshot,
    safe_evidence_path,
)
from tools.install_sandbox.host.initial_preparation_reader import replay_initial
from tools.install_sandbox.host.intermediate_reader import replay_intermediate
from tools.install_sandbox.host.step_artifacts import inventory
from tools.install_sandbox.rules.effect_verifier import EffectVerifier
from tools.install_sandbox.rules.expectation_builder import (
    build_group_expectations,
    build_reinstall_expectations,
    build_uninstall_expectations,
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


def check_effect_result(
    result: InstallTestResult, case: EffectInstallCase, output: Path
) -> RepairProgress | None:
    _check_steps_directory(result, output)
    retained = EffectInstallCase.from_json(
        safe_evidence_path(output, "case.json").read_text(encoding="utf-8")
    )
    if case.intermediate_preparation is None:
        _absent(output, ("intermediate", "expectations/intermediate.json"))
    if retained != case:
        raise ValueError("Retained case contradicts requested case")
    initial = replay_initial(result.preparation, case, output, _snapshot)
    if initial is None:
        _absent(output, tuple(f"expectations/{phase}.json" for phase in case.step_phases[1:]))
        for index in range(len(result.steps)):
            loaded, staged = inventory(output, index, _snapshot, case.step_phases)
            # Installation expectations belong to initial preparation, never an idle step.
            own = {key: value for key, value in loaded.items() if key.startswith(f"steps/{index}/")}
            if own or staged:
                raise ValueError(
                    "Incomplete initial preparation cannot own installation execution evidence"
                )
        return _unstarted_repair(result, output)
    return _steps(
        result, case, output, initial.roots, initial.expectations, initial.before, initial.sources
    )


def _check_steps_directory(result: InstallTestResult, output: Path) -> None:
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


def _unstarted_repair(result: InstallTestResult, output: Path) -> RepairProgress | None:
    if result.intermediate_preparation is None:
        return None
    inputs = RepairInputs(
        safe_evidence_path(output, "case.json").read_bytes(),
        FilesystemSnapshot(),
        ExpectationSet("install", ()),
        FilesystemSnapshot(),
        result.steps[0],
    )
    return replay_intermediate(result, output, inputs, _snapshot).progress


def _steps(
    result: InstallTestResult,
    case: EffectInstallCase,
    output: Path,
    roots: dict[str, str],
    expected: ExpectationSet,
    previous: FilesystemSnapshot,
    sources: FilesystemSnapshot,
) -> RepairProgress | None:
    first_executable: str | None = None
    previous_verdict: VerificationResult | None = None
    progress: RepairProgress | None = None
    installed = expected
    for index, step in enumerate(result.steps):
        if index and case.name == "group-uninstall-project":
            if step.phase != "idle":
                expected = build_group_expectations(case, sources, previous, roots, index)
        elif index:
            expected, previous, progress = _transition(
                result, case, output, sources, installed, expected, previous, previous_verdict
            )
        after, verdict = _inspect_step(
            step, case, output, index, roots, first_executable, previous, expected
        )
        if step.command is not None:
            first_executable = step.command["args"][0]
        if after is not None:
            previous = after
        previous_verdict = verdict
    return progress


def _transition(
    result: InstallTestResult,
    case: EffectInstallCase,
    output: Path,
    sources: FilesystemSnapshot,
    installed: ExpectationSet,
    expected: ExpectationSet,
    previous: FilesystemSnapshot,
    verdict: VerificationResult | None,
) -> tuple[ExpectationSet, FilesystemSnapshot, RepairProgress | None]:
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
            return expected, previous, inspection.progress
        return inspection.ready.expectations, inspection.ready.baseline, inspection.progress
    if result.steps[1].phase != "idle" and verdict is not None:
        builder = (
            build_uninstall_expectations
            if case.second_phase == "uninstall"
            else build_reinstall_expectations
        )
        expected = builder(expected, previous, verdict)
    return expected, previous, None


def _absent(output: Path, relatives: tuple[str, ...]) -> None:
    if any(
        (output / relative).exists() or (output / relative).is_symlink() for relative in relatives
    ):
        raise ValueError("Execution stage contradicts retained later evidence")


def _inspect_step(
    step: StepState,
    case: EffectInstallCase,
    output: Path,
    index: int,
    roots: dict[str, str],
    first_executable: str | None,
    previous: FilesystemSnapshot,
    expected: ExpectationSet,
) -> tuple[FilesystemSnapshot | None, VerificationResult | None]:
    loaded, staged = inventory(output, index, _snapshot, case.step_phases)
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
    phase = case.step_phases[index]
    expectation_reference = f"expectations/{phase}.json"
    has_expectations = safe_evidence_path(output, expectation_reference).exists()
    if has_expectations:
        _expectations(output, expected)
    before = loaded.get(f"{prefix}/before.json")
    after = loaded.get(f"{prefix}/after.json")
    before_usable = isinstance(before, FilesystemSnapshot) and _same_observation(previous, before)
    if isinstance(before, FilesystemSnapshot) and before.obstacles:
        before_usable = False
    if index == 0:
        before, before_usable = previous, not previous.obstacles
    for name, reference in claim.observations.items():
        if reference is None:
            continue
        expected_reference = (
            "initial/before.json" if index == 0 and name == "before" else f"{prefix}/{name}.json"
        )
        if reference != expected_reference:
            raise ValueError("Evidence references must belong to their own step")
        if reference not in loaded and not (index == 0 and name == "before"):
            raise ValueError("Missing referenced observation")
    command = claim.command
    if command is not None:
        _partial_command_binding(
            command, case.invocation_for(step.operation), roots, first_executable
        )
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
            "args": ["retained", *case.invocation_for(step.operation)],
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
    if verdict is not None and (
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
        expectations=has_expectations and not repair_owns_expectations and index != 0,
        external_expectations=has_expectations and (repair_owns_expectations or index == 0),
        external_before=index == 0,
        before=isinstance(before, FilesystemSnapshot) and index != 0,
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
            if not (
                (repair_owns_expectations or index == 0)
                and entry.owners == frozenset({expectation_reference})
            )
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
    invocation: tuple[str, ...],
    roots: dict[str, str],
    first_executable: str | None,
) -> None:
    if command["args"][1:] != list(invocation) or command["cwd"] != roots["project"]:
        raise ValueError("Partial command facts contradict invocation or retained roots")
    if first_executable is not None and command["args"][0] != first_executable:
        raise ValueError("All operations must use the same prepared executable")
