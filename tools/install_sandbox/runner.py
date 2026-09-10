"""Conduct one validated local case and retain its established result and evidence."""

import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from tools.install_sandbox.case import InstallTestCase
from tools.install_sandbox.driver import InstallerDriver
from tools.install_sandbox.environment import (
    TestEnvironment,
    reference_repair_plan,
    skill_backup_plan,
    skill_repair_plan,
)
from tools.install_sandbox.preparer import GraphifyPreparer
from tools.install_sandbox.results import (
    FilesystemSnapshot,
    InstallTestResult,
    StepEvidence,
    StepPreparationEvidence,
    TestResultWriter,
)
from tools.install_sandbox.verifier import InstallVerifier


def _check_directories(subject: Path, case_file: Path, work: Path, output: Path) -> None:
    for left, right in ((subject, work), (subject, output), (work, output)):
        if left.is_relative_to(right) or right.is_relative_to(left):
            raise ValueError("Subject, work and evidence directories must be separate")
    if case_file.is_relative_to(work) or case_file.is_relative_to(output):
        raise ValueError("Case file must be outside work and evidence directories")
    for path in (work, output):
        if path.exists() and (not path.is_dir() or any(path.iterdir())):
            raise ValueError(f"Directory must be fresh or empty: {path}")


def _new_result(case: InstallTestCase) -> InstallTestResult:
    steps: list[StepEvidence] = [
        {
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
        {"ready": False, "reason": None, "log": "preparation.log"},
        steps,
        "not_run",
        {"journal": "journal.log", "expected_contents": None},
    )


class InstallTestRunner:
    def __init__(
        self, preparer: GraphifyPreparer | None = None, driver: InstallerDriver | None = None
    ):
        self.preparer = preparer if preparer is not None else GraphifyPreparer()
        self.driver = driver if driver is not None else InstallerDriver()
        self.verifier = InstallVerifier()

    def run_case(
        self,
        *,
        subject_checkout: Path,
        case_file: Path,
        work_directory: Path,
        output_directory: Path,
    ) -> InstallTestResult:
        subject, case_path, work, output = (
            path.resolve()
            for path in (subject_checkout, case_file, work_directory, output_directory)
        )
        case = InstallTestCase.from_json(case_path.read_text(encoding="utf-8"))
        _check_directories(subject, case_path, work, output)
        writer = TestResultWriter(output)
        result = _new_result(case)
        writer.append_log("journal.log", "Validated case; starting preparation\n")
        self._run(case, subject, work, writer, result)
        writer.append_log("journal.log", f"Case status: {result.status}; saving result\n")
        writer.write_result(result)
        return result

    def _run(
        self,
        case: InstallTestCase,
        subject: Path,
        work: Path,
        writer: TestResultWriter,
        result: InstallTestResult,
    ) -> None:
        prepared = self.preparer.prepare(subject, work / "software", writer)
        if not prepared.ready or prepared.executable is None:
            self._not_run(result, writer, prepared.reason or "Prepared command unavailable")
            return
        try:
            environment = TestEnvironment(case, work / "environment")
            environment.prepare()
            (work / "command-tmp").mkdir()
            expected = environment.preserve_expected(subject, writer)
            result.evidence["expected_contents"] = "expected/"
            before = environment.observe(writer, "before")
        except OSError as error:
            self._not_run(result, writer, f"Initial preparation failed: {error}")
            return
        initial = self.verifier.verify_initial(case, expected, before)
        writer.append_log("preparation.log", json.dumps(asdict(initial)) + "\n")
        if not initial.complete or initial.mismatches:
            self._not_run(
                result, writer, "Initial verification failed: " + json.dumps(asdict(initial))
            )
            return
        if case.name == "repair-references":
            try:
                reference_repair_plan(case, expected)
            except ValueError as error:
                self._not_run(result, writer, str(error))
                return
        result.preparation["ready"] = True
        self._run_steps(case, prepared.executable, environment, expected, before, writer, result)

    def _run_steps(
        self,
        case: InstallTestCase,
        executable: Path,
        environment: TestEnvironment,
        expected: FilesystemSnapshot,
        before: FilesystemSnapshot,
        writer: TestResultWriter,
        result: InstallTestResult,
    ) -> None:
        writer.append_log("journal.log", "Preparation ready; attempting install\n")
        for index, step in enumerate(result.steps):
            installed = before
            if index:
                if case.name in {"repair-references", "repair-skill", "preserve-skill-backup"}:
                    before = self._prepare_step(
                        case, environment, expected, installed, writer, step
                    )
                    preparation = step.get("preparation")
                    assert preparation is not None
                    if not preparation["ready"]:
                        result.status = "incomplete"
                        break
                else:
                    before = deepcopy(installed)
                    writer.write_snapshot(before, "before", step_index=index)
            before = self._install(
                case,
                executable,
                environment,
                expected,
                installed,
                writer,
                step,
                index,
            )
            result.status = self._step_status(step)
            if result.status != "passed":
                reason = f"Step {index} {result.status}; dependent installation not attempted"
                for dependent in result.steps[index + 1 :]:
                    dependent["skip_reason"] = reason
                writer.append_log("journal.log", reason + "\n")
                break

    def _prepare_step(
        self,
        case: InstallTestCase,
        environment: TestEnvironment,
        expected: FilesystemSnapshot,
        installed: FilesystemSnapshot,
        writer: TestResultWriter,
        step: StepEvidence,
    ) -> FilesystemSnapshot:
        if case.name == "preserve-skill-backup":
            plan, content = skill_backup_plan(case, expected)
            writer.write_step_preparation_plan(plan, content)
            writer.append_log("journal.log", "Preparing previous skill backup witness\n")
            reason = environment.prepare_skill_backup(plan, content)
            prepared_state = environment.observe(writer, "before", step_index=1)
            verification = self.verifier.verify_skill_backup(
                plan, content, installed, prepared_state
            )
        elif case.name == "repair-skill":
            plan, content = skill_repair_plan(case, expected)
            writer.write_step_preparation_plan(plan, content)
            writer.append_log("journal.log", "Preparing skill alteration\n")
            reason = environment.prepare_skill_repair(plan, content)
            prepared_state = environment.observe(writer, "before", step_index=1)
            verification = self.verifier.verify_skill_repair(
                plan, content, installed, prepared_state
            )
        else:
            plan, content = reference_repair_plan(case, expected)
            writer.write_step_preparation_plan(plan, content)
            writer.append_log("journal.log", "Preparing reference deletion and alteration\n")
            reason = environment.prepare_reference_repair(plan, content)
            prepared_state = environment.observe(writer, "before", step_index=1)
            verification = self.verifier.verify_reference_repair(
                plan, content, installed, prepared_state
            )
        if reason is None and (not verification.complete or verification.mismatches):
            reason = "Step preparation verification failed"
        evidence: StepPreparationEvidence = {
            "plan": plan,
            "ready": reason is None,
            "reason": reason,
            "before": "steps/1/before.json",
            "verification": verification,
        }
        step["preparation"] = evidence
        writer.write_step_preparation(evidence)
        if reason is not None:
            step["skip_reason"] = reason
            writer.append_log("journal.log", reason + "; dependent installation not attempted\n")
        return prepared_state

    @staticmethod
    def _not_run(result: InstallTestResult, writer: TestResultWriter, reason: str) -> None:
        result.preparation["reason"] = reason
        for step in result.steps:
            step["skip_reason"] = reason
        writer.append_log("preparation.log", reason + "\n")
        writer.append_log("journal.log", "Preparation prevented installation\n")

    def _install(
        self,
        case: InstallTestCase,
        executable: Path,
        environment: TestEnvironment,
        expected: FilesystemSnapshot,
        before: FilesystemSnapshot,
        writer: TestResultWriter,
        step: StepEvidence,
        index: int,
    ) -> FilesystemSnapshot:
        command = self.driver.install(
            case,
            executable,
            environment.project,
            environment.home,
            environment.project.parent.parent / "command-tmp",
        )
        step["skip_reason"] = None
        step["command"] = writer.write_command(command, step_index=index)
        writer.append_log(
            "journal.log",
            f"Step {index} command {command.state}: {command.exit_code}; {command.reason}\n",
        )
        after = environment.observe(writer, "after", step_index=index)
        backup = None
        if index and case.name == "repair-skill":
            backup = skill_repair_plan(case, expected)[1]
        elif index and case.name == "preserve-skill-backup":
            backup = skill_backup_plan(case, expected)[1]
        verification = self.verifier.verify(case, expected, before, after, skill_backup=backup)
        step["verification"] = verification
        step["observations"] = {
            "before": f"steps/{index}/before.json",
            "after": f"steps/{index}/after.json",
        }
        writer.write_verification(verification, step_index=index)
        return after

    @staticmethod
    def _step_status(step: StepEvidence) -> Literal["passed", "failed", "incomplete"]:
        command, verification = step["command"], step["verification"]
        assert command is not None and verification is not None
        if command["state"] != "completed" or not verification.complete:
            return "incomplete"
        if command["exit_code"] != 0 or verification.mismatches:
            return "failed"
        return "passed"
