"""Conduct one validated local case and retain its established result and evidence."""

import json
from dataclasses import asdict
from pathlib import Path

from tools.install_sandbox.case import InstallTestCase
from tools.install_sandbox.driver import InstallerDriver
from tools.install_sandbox.environment import TestEnvironment
from tools.install_sandbox.preparer import GraphifyPreparer
from tools.install_sandbox.results import (
    FilesystemSnapshot,
    InstallTestResult,
    StepEvidence,
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
        result.preparation["ready"] = True
        writer.append_log("journal.log", "Preparation ready; attempting install\n")
        self._install(case, prepared.executable, environment, expected, before, writer, result)

    @staticmethod
    def _not_run(result: InstallTestResult, writer: TestResultWriter, reason: str) -> None:
        result.preparation["reason"] = reason
        result.steps[0]["skip_reason"] = reason
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
        result: InstallTestResult,
    ) -> None:
        command = self.driver.install(
            case,
            executable,
            environment.project,
            environment.home,
            environment.project.parent.parent / "command-tmp",
        )
        step = result.steps[0]
        step["skip_reason"] = None
        step["command"] = writer.write_command(command)
        writer.append_log(
            "journal.log", f"Command {command.state}: {command.exit_code}; {command.reason}\n"
        )
        after = environment.observe(writer, "after")
        verification = self.verifier.verify(case, expected, before, after)
        step["verification"] = verification
        step["observations"] = {"before": "steps/0/before.json", "after": "steps/0/after.json"}
        writer.write_verification(verification)
        if command.state != "completed" or not verification.complete:
            result.status = "incomplete"
        elif command.exit_code != 0 or verification.mismatches:
            result.status = "failed"
        else:
            result.status = "passed"
