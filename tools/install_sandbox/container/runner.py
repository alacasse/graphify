"""Execute native reinstall phases against expectations retained before commands."""

import time
from pathlib import Path
from dataclasses import replace

from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.container.evidence_writer import TestResultWriter
from tools.install_sandbox.container.installer import InstallerDriver
from tools.install_sandbox.container.intermediate_execution import conduct_intermediate
from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.observation import FilesystemSnapshot, same_observation
from tools.install_sandbox.contracts.results import (
    EvidenceWriteError,
    InstallTestResult,
    StepState,
)
from tools.install_sandbox.rules.effect_verifier import EffectVerifier
from tools.install_sandbox.rules.step_lifecycle import (
    CommandRetained,
    CommandReturned,
    ExpectationsRetained,
    ObservationRetained,
    PreparationObserved,
    Prepared,
    StopStep,
    Terminate,
    VerificationComputed,
    VerificationRetained,
    advance,
    start,
    status,
)
from tools.install_sandbox.rules.expectation_builder import (
    bind_roots,
    build_initial_expectations,
    build_install_expectations,
    build_reinstall_expectations,
)


def _check_directories(subject: Path, case_file: Path, work: Path, output: Path) -> None:
    for left, right in ((subject, work), (subject, output), (work, output)):
        if left.is_relative_to(right) or right.is_relative_to(left):
            raise ValueError("Subject, work and evidence directories must be separate")
    if case_file.is_relative_to(work) or case_file.is_relative_to(output):
        raise ValueError("Case file must be outside work and evidence directories")
    for path in (work, output):
        if path.exists() and (not path.is_dir() or any(path.iterdir())):
            raise ValueError(f"Directory must be fresh or empty: {path}")


def _new_result(case: EffectInstallCase) -> InstallTestResult:
    steps = [StepState.idle(operation) for operation in case.operations]
    return InstallTestResult(
        {"name": case.name, "target": case.target, "scope": case.scope},
        {
            "ready": False,
            "reason": None,
            "log": "preparation.log",
            "source": "campaign",
            "stage": "started",
        },
        steps,
        "not_run",
        {"journal": "journal.log", "expected_contents": None},
        None
        if case.intermediate_preparation is None
        else {"stage": "not_started", "generation": 0, "reason": None},
    )


def _publish_step(
    result: InstallTestResult, state: StepState, writer: TestResultWriter, index: int
) -> None:
    """Adopt a declaration only after its atomic result publication succeeds."""
    steps = list(result.steps)
    steps[index] = state
    outcome = status(state)
    case_status = "incomplete" if outcome == "passed" and index < len(steps) - 1 else outcome
    candidate = replace(result, steps=steps, status=case_status)
    if state.phase == "stopped" or (
        state.phase == "terminal" and (outcome != "passed" or index == len(steps) - 1)
    ):
        with writer.measure("finalize"):
            writer.write_result(candidate)
    else:
        writer.write_result(candidate)
    result.steps = candidate.steps
    result.status = candidate.status


class InstallTestRunner:
    def __init__(self, driver: InstallerDriver | None = None):
        self.driver = driver if driver is not None else InstallerDriver()
        self.verifier = EffectVerifier()

    def run_case(
        self,
        *,
        reference_sources: Path,
        prepared_executable: Path,
        case_file: Path,
        work_directory: Path,
        output_directory: Path,
    ) -> InstallTestResult:
        started = time.monotonic_ns()
        subject, case_path, work, output = (
            p.resolve() for p in (reference_sources, case_file, work_directory, output_directory)
        )
        case = EffectInstallCase.from_json(case_path.read_text(encoding="utf-8"))
        _check_directories(subject, case_path, work, output)
        writer = TestResultWriter(output)
        case.write(output / "case.json")
        writer.write_metadata("evidence-format.json", {"format": "explicit-expectations-v6"})
        writer.initialize_timings(case.name, len(case.operations))
        result = _new_result(case)
        writer.write_result(result)
        writer.append_log("journal.log", "Validated native case; starting preparation\n")
        writer.append_log("preparation.log", "Package availability inherited from campaign\n")
        try:
            self._run(case, subject, prepared_executable, work, writer, result)
        except BaseException:
            writer.halted = True
            raise
        finally:
            # Timings never authorize progression or overwrite the last result.
            writer.finish_timings(started)
        return result

    def _run(
        self,
        case: EffectInstallCase,
        subject: Path,
        executable: Path,
        work: Path,
        writer: TestResultWriter,
        result: InstallTestResult,
    ) -> None:
        failure_stage = "environment"
        try:
            with writer.measure("initial"):
                environment = EffectEnvironment(case, work / "environment")
                environment.prepare()
                (work / "command-tmp").mkdir()
                roots = {"home": str(environment.home), "project": str(environment.project)}
                writer.write_metadata("roots.json", roots)
                failure_stage = "sources"
                sources = environment.preserve_expected(subject, writer)
                result.evidence["expected_contents"] = "expected/"
                result.preparation["stage"] = "sources_retained"
                failure_stage = "initial_expectations"
                initial = bind_roots(build_initial_expectations(case, sources), roots)
                writer.write_metadata("expectations/initial.json", initial.to_data())
                failure_stage = "initial_observation"
                before = environment.observe(writer, "before")
                failure_stage = "initial_verification"
                verdict = self.verifier.verify(initial, before)
                writer.write_initial_verification(verdict)
                result.preparation["stage"] = "initial_verified"
                if not verdict.complete or verdict.mismatches:
                    self._not_run(result, writer, "Initial verification failed")
                    return
                failure_stage = "install_expectations"
                expectations = build_install_expectations(case, sources, before, roots)
            result.preparation["ready"] = True
        except EvidenceWriteError:
            raise
        except (OSError, ValueError) as error:
            writer.write_metadata(
                "construction-failure.json",
                {
                    "stage": failure_stage,
                    "kind": "validation" if isinstance(error, ValueError) else "io",
                    "reason": str(error),
                },
            )
            self._not_run(result, writer, f"Initial preparation failed: {error}")
            return
        self._steps(case, executable, environment, sources, expectations, before, writer, result)

    def _steps(
        self,
        case: EffectInstallCase,
        executable: Path,
        environment: EffectEnvironment,
        sources: FilesystemSnapshot,
        expectations: ExpectationSet,
        before: FilesystemSnapshot,
        writer: TestResultWriter,
        result: InstallTestResult,
    ) -> None:
        for index, operation in enumerate(case.operations):
            if index and status(result.steps[index - 1]) != "passed":
                return
            if index and case.intermediate_preparation is not None:
                transition = conduct_intermediate(
                    case, sources, expectations, before, environment, writer, result
                )
                if transition is None:
                    return
                expectations, before = transition
            state = start(operation)
            _publish_step(result, state, writer, index)
            completed = self._step(
                case, executable, environment, expectations, before, writer, result, index, state
            )
            if completed is None:
                return
            expectations, before = completed

    def _step(
        self,
        case: EffectInstallCase,
        executable: Path,
        environment: EffectEnvironment,
        expectations: ExpectationSet,
        before: FilesystemSnapshot,
        writer: TestResultWriter,
        result: InstallTestResult,
        index: int,
        state: StepState,
    ) -> tuple[ExpectationSet, FilesystemSnapshot] | None:
        try:
            if index:
                with writer.measure("step_preparation", index):
                    previous = result.steps[0].verification
                    assert previous is not None
                    if case.intermediate_preparation is None:
                        expectations = build_reinstall_expectations(expectations, before, previous)
                    observed = environment.observe(writer, "before", step_index=index)
                    usable = not observed.obstacles and same_observation(before, observed)
                    state = advance(
                        state, PreparationObserved(f"steps/{index}/before.json", usable)
                    )
                    if not usable:
                        raise ValueError(
                            "Environment changed or was obstructed before the second installation"
                        )
            else:
                state = advance(state, PreparationObserved("steps/0/before.json"))
            state = advance(state, Prepared())
            if not (index and case.intermediate_preparation is not None):
                writer.write_metadata(
                    f"expectations/{expectations.phase}.json", expectations.to_data()
                )
            state = advance(state, ExpectationsRetained(f"expectations/{expectations.phase}.json"))
            with writer.measure("command", index) as timing:
                command = self.driver.install(
                    case,
                    executable,
                    environment.project,
                    environment.home,
                    environment.project.parent.parent / "command-tmp",
                )
                timing.duration_seconds = command.duration_seconds
                if command.duration_seconds is None:
                    timing.state = "unavailable"
                    timing.diagnostic = "Command executor did not supply a duration"
            state = advance(
                state,
                CommandReturned(
                    {
                        "args": command.args,
                        "cwd": command.cwd,
                        "state": command.state,
                        "exit_code": command.exit_code,
                        "reason": command.reason,
                        "stdout_file": None,
                        "stderr_file": None,
                    }
                ),
            )
            retained = writer.write_command(command, step_index=index)
            assert retained["stdout_file"] is not None and retained["stderr_file"] is not None
            state = advance(
                state, CommandRetained(retained["stdout_file"], retained["stderr_file"])
            )
            _publish_step(result, state, writer, index)
            with writer.measure("checks", index):
                after = environment.observe(writer, "after", step_index=index)
                state = advance(state, ObservationRetained(f"steps/{index}/after.json"))
                verdict = self.verifier.verify(expectations, after)
                state = advance(state, VerificationComputed(verdict))
                writer.write_verification(verdict, step_index=index)
                state = advance(state, VerificationRetained(f"steps/{index}/verification.json"))
            state = advance(state, Terminate())
        except EvidenceWriteError:
            # Authority was not retained. Keep the previous declaration and stop all effects.
            writer.halted = True
            raise
        except (OSError, ValueError) as error:
            state = advance(state, StopStep(str(error)))
            writer.write_metadata(f"steps/{index}/failure.json", state.to_data())
            _publish_step(result, state, writer, index)
            return None
        _publish_step(result, state, writer, index)
        return (expectations, after) if status(state) == "passed" else None

    @staticmethod
    def _not_run(result: InstallTestResult, writer: TestResultWriter, reason: str) -> None:
        result.preparation["reason"] = reason
        writer.append_log("preparation.log", reason + "\n")
        with writer.measure("finalize"):
            writer.write_result(result)
