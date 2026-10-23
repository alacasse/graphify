"""Execute native reinstall phases against expectations retained before commands."""

import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.container.effect_verifier import EffectVerifier
from tools.install_sandbox.container.environment import FilesystemSnapshot, same_observation
from tools.install_sandbox.container.evidence_writer import TestResultWriter
from tools.install_sandbox.container.expectation_builder import (
    bind_roots,
    build_initial_expectations,
    build_install_expectations,
    build_reinstall_expectations,
)
from tools.install_sandbox.container.installer import InstallerDriver
from tools.install_sandbox.container.intermediate_execution import conduct_intermediate
from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.results import (
    EvidenceWriteError,
    InstallTestResult,
    StepEvidence,
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
    steps: list[StepEvidence] = [
        {
            "progress": "not_started",
            "operation": operation,
            "skip_reason": "Preparation not completed",
            "command": None,
            "verification": None,
            "observations": None,
        }
        for operation in case.operations
    ]
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
        else {
            "progress": "not_started",
            "operation_ref": None,
            "expectations_ref": None,
            "observations": {"before": None, "after": None},
            "verification": None,
            "reason": "First installation not completed",
        },
    )


def step_status(step: StepEvidence) -> Literal["passed", "failed", "incomplete"]:
    command, verdict = step["command"], step["verification"]
    assert command is not None and verdict is not None
    if command["state"] != "completed" or not verdict.complete:
        return "incomplete"
    return "failed" if command["exit_code"] != 0 or verdict.mismatches else "passed"


@contextmanager
def _phase(step: StepEvidence, stage: str) -> Generator[None]:
    step["failure"] = {"stage": stage, "reason": ""}
    yield
    del step["failure"]


def _record_failure(
    step: StepEvidence, error: Exception, writer: TestResultWriter, index: int
) -> None:
    failure = step.get("failure")
    if failure is None:
        raise error
    failure["reason"] = str(error)
    writer.write_metadata(f"steps/{index}/failure.json", failure)
    step["skip_reason"] = str(error) if step["command"] is None else None


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
        writer.write_metadata("evidence-format.json", {"format": "explicit-expectations-v3"})
        writer.initialize_timings(case.name, len(case.operations))
        result = _new_result(case)
        writer.write_result(result)
        writer.append_log("journal.log", "Validated native case; starting preparation\n")
        writer.append_log("preparation.log", "Package availability inherited from campaign\n")
        self._run(case, subject, prepared_executable, work, writer, result)
        with writer.measure("finalize"):
            writer.write_result(result)
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
        except (OSError, ValueError, EvidenceWriteError) as error:
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
        for index, step in enumerate(result.steps):
            if index and case.intermediate_preparation is not None:
                transition = conduct_intermediate(
                    case, sources, expectations, before, environment, writer, result
                )
                if transition is None:
                    return
                expectations, before = transition
            step["progress"] = "incomplete"
            step["skip_reason"] = None
            result.status = "incomplete"
            writer.write_result(result)
            try:
                expectations, after = self._step(
                    case, executable, environment, expectations, before, writer, result, index
                )
            except (OSError, ValueError, EvidenceWriteError) as error:
                _record_failure(step, error, writer, index)
                outcome = "incomplete"
            else:
                outcome = step_status(step)
                before = after
                step["progress"] = "incomplete" if outcome == "incomplete" else "finished"
            result.status = "incomplete" if outcome == "passed" and index == 0 else outcome
            writer.write_result(result)
            if outcome != "passed":
                for dependent in result.steps[index + 1 :]:
                    dependent["skip_reason"] = f"Step {index} {outcome}"
                return

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
    ) -> tuple[ExpectationSet, FilesystemSnapshot]:
        step = result.steps[index]
        with _phase(step, "preparation"):
            if index:
                with writer.measure("step_preparation", index):
                    expectations = self._prepare_second(
                        case, environment, expectations, before, writer, result
                    )
        with _phase(step, "expectations"):
            writer.write_metadata(f"expectations/{expectations.phase}.json", expectations.to_data())
        with _phase(step, "command"), writer.measure("command", index) as timing:
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
        with _phase(step, "command_evidence"):
            step["command"] = {
                "args": command.args,
                "cwd": command.cwd,
                "state": command.state,
                "exit_code": command.exit_code,
                "reason": command.reason,
                "stdout_file": None,
                "stderr_file": None,
            }
            step["command"] = writer.write_command(command, step_index=index)
            step["skip_reason"] = None
        writer.write_result(result)
        with writer.measure("checks", index):
            with _phase(step, "observation"):
                after = environment.observe(writer, "after", step_index=index)
                step["observations"] = {
                    "before": f"steps/{index}/before.json",
                    "after": f"steps/{index}/after.json",
                }
            with _phase(step, "verification"):
                verdict = self.verifier.verify(expectations, after)
                step["verification"] = verdict
            with _phase(step, "verification_evidence"):
                writer.write_verification(verdict, step_index=index)
        return expectations, after

    @staticmethod
    def _prepare_second(
        case: EffectInstallCase,
        environment: EffectEnvironment,
        expectations: ExpectationSet,
        before: FilesystemSnapshot,
        writer: TestResultWriter,
        result: InstallTestResult,
    ) -> ExpectationSet:
        previous = result.steps[0]["verification"]
        assert previous is not None
        if case.intermediate_preparation is None:
            expectations = build_reinstall_expectations(expectations, before, previous)
        observed = environment.observe(writer, "before", step_index=1)
        if not same_observation(before, observed):
            raise ValueError("Environment changed before the second installation")
        return expectations

    @staticmethod
    def _not_run(result: InstallTestResult, writer: TestResultWriter, reason: str) -> None:
        result.preparation["reason"] = reason
        for step in result.steps:
            step["skip_reason"] = reason
        writer.append_log("preparation.log", reason + "\n")
