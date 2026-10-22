"""Component proof for execution ordering with directly supplied expectations."""

from pathlib import Path

import pytest

from tools.install_sandbox.container import runner
from tools.install_sandbox.container.installer import InstallerCommandResult, InstallerDriver
from tools.install_sandbox.contracts.effect_case import (
    EffectInstallCase,
    EffectRules,
    SubjectContext,
)
from tools.install_sandbox.contracts.effects import Destination, EffectSpec, MarkdownSectionEffect
from tools.install_sandbox.contracts.expectations import Expectation, ExpectationSet


def explicit_case() -> EffectInstallCase:
    return EffectInstallCase(
        "reinstall",
        "component",
        "project",
        EffectSpec((MarkdownSectionEffect("section.md", Destination("project", "GUIDE.md")),)),
        SubjectContext(
            "fake",
            ("install",),
            "version.py",
            EffectRules(10, "persistent", ".graphify-bak", ".bak", False),
        ),
        [
            {
                "root": "project",
                "path": "GUIDE.md",
                "content": "# My project\n\n## Language\nRespond in English.\n",
            },
            {
                "root": "project",
                "path": "personal-effect-0.txt",
                "content": "Personal document to preserve.\n",
            },
            {
                "root": "home",
                "path": "GUIDE.md",
                "content": "# My project\n\n## Language\nRespond in English.\n",
            },
        ],
        ["install", "install"],
    )


def install_verification_outcome(
    monkeypatch: pytest.MonkeyPatch, verification_failure: str
) -> None:
    from tools.install_sandbox.contracts.results import VerificationMismatch, VerificationResult

    def verify(
        self: runner.EffectVerifier, expected: ExpectationSet, observed: runner.FilesystemSnapshot
    ) -> VerificationResult:
        if expected.phase == "install" and verification_failure == "mismatch":
            return VerificationResult(
                mismatches=[
                    VerificationMismatch("content", "project", "GUIDE.md", "expected", "different")
                ]
            )
        if expected.phase == "install" and verification_failure == "obstacle":
            return VerificationResult(
                False,
                obstacles=[
                    {
                        "operation": "read",
                        "root": "project",
                        "path": "GUIDE.md",
                        "reason": "unavailable",
                    }
                ],
            )
        return VerificationResult()

    monkeypatch.setattr(runner.EffectVerifier, "verify", verify)


@pytest.mark.parametrize(
    "first_exit, expected_calls, verification_failure",
    [
        (0, 2, ""),
        (7, 1, ""),
        (0, 1, "mismatch"),
        (0, 1, "obstacle"),
    ],
)
def test_expectations_precede_commands_and_failure_blocks_reinstall(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first_exit: int,
    expected_calls: int,
    verification_failure: str,
) -> None:
    case = explicit_case()
    case_file = tmp_path / "case.json"
    case.write(case_file)
    subject = tmp_path / "subject"
    subject.mkdir()
    (subject / "section.md").write_text("## graphify\nManaged.\n")
    output = tmp_path / "evidence"
    phases: list[str] = []

    def bundle(phase: str) -> ExpectationSet:
        return ExpectationSet(
            phase,
            (
                Expectation("directory", "project", ".", phase, "execution-test"),
                Expectation("directory", "home", ".", phase, "execution-test"),
            ),
            allowed_changes=(("project", "."), ("home", ".")),
            roots={"home": "/fake/home", "project": "/fake/project"},
        )

    def initial(*args: object) -> ExpectationSet:
        return bundle("initial")

    def install(*args: object) -> ExpectationSet:
        return bundle("install")

    def reinstall(*args: object) -> ExpectationSet:
        return bundle("reinstall")

    def bind(expected: ExpectationSet, roots: object) -> ExpectationSet:
        return expected

    monkeypatch.setattr(runner, "build_initial_expectations", initial)
    monkeypatch.setattr(runner, "bind_roots", bind)
    monkeypatch.setattr(runner, "build_install_expectations", install)
    monkeypatch.setattr(runner, "build_reinstall_expectations", reinstall)

    def execute(
        args: list[str], cwd: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        phase = "install" if not phases else "reinstall"
        assert (output / f"expectations/{phase}.json").is_file()
        assert (output / "expectations/initial.json").is_file()
        phases.append(phase)
        return InstallerCommandResult(
            args, str(cwd), "completed", first_exit if len(phases) == 1 else 0, None
        )

    install_verification_outcome(monkeypatch, verification_failure)
    result = runner.InstallTestRunner(InstallerDriver(execute)).run_case(
        reference_sources=subject,
        prepared_executable=tmp_path / "controlled-command",
        case_file=case_file,
        work_directory=tmp_path / "work",
        output_directory=output,
    )
    assert len(phases) == expected_calls
    expected_status = (
        "incomplete"
        if verification_failure == "obstacle"
        else ("failed" if first_exit or verification_failure else "passed")
    )
    assert result.status == expected_status
    if first_exit or verification_failure:
        assert result.steps[1]["command"] is None
        assert not (output / "expectations/reinstall.json").exists()


@pytest.mark.parametrize("missing_source", [False, True])
def test_partial_failure_remains_autonomously_readable(
    tmp_path: Path, missing_source: bool
) -> None:
    from tools.install_sandbox.host.result_reader import read_evidence

    case = explicit_case()
    case_file = tmp_path / "case.json"
    case.write(case_file)
    subject = tmp_path / "subject"
    subject.mkdir()
    if not missing_source:
        (subject / "section.md").write_text("## graphify\nManaged.\n")

    def execute(
        args: list[str], cwd: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        return InstallerCommandResult(args, str(cwd), "completed", 13, None)

    output = tmp_path / "evidence"
    result = runner.InstallTestRunner(InstallerDriver(execute)).run_case(
        reference_sources=subject,
        prepared_executable=tmp_path / "fake",
        case_file=case_file,
        work_directory=tmp_path / "work",
        output_directory=output,
    )
    assert result.status == ("not_run" if missing_source else "failed")
    assert read_evidence(output) == result


def inject_phase_failure(monkeypatch: pytest.MonkeyPatch, failure_stage: str) -> None:
    from tools.install_sandbox.container.effect_environment import EffectEnvironment
    from tools.install_sandbox.container.evidence_writer import TestResultWriter
    from tools.install_sandbox.contracts.results import EvidenceWriteError

    original_observe = EffectEnvironment.observe
    original_write = TestResultWriter.write_metadata

    def observe(
        self: EffectEnvironment, writer: TestResultWriter, phase: str, *, step_index: int = 0
    ) -> runner.FilesystemSnapshot:
        if failure_stage == "observation" and phase == "after":
            raise OSError("Controlled observation unavailable")
        return original_observe(self, writer, phase, step_index=step_index)

    def write(self: TestResultWriter, relative: str, value: object) -> None:
        if failure_stage == "expectations" and relative == "expectations/install.json":
            raise EvidenceWriteError("Controlled expectation persistence failure")
        original_write(self, relative, value)

    def prepare(*args: object) -> ExpectationSet:
        raise ValueError("Controlled second-step preparation failure")

    monkeypatch.setattr(EffectEnvironment, "observe", observe)
    monkeypatch.setattr(TestResultWriter, "write_metadata", write)
    if failure_stage == "preparation":
        monkeypatch.setattr(runner, "build_reinstall_expectations", prepare)


@pytest.mark.parametrize(
    "failure_stage", ["observation", "expectations", "preparation", "interrupted"]
)
def test_partial_execution_stages_remain_autonomously_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_stage: str
) -> None:
    from tools.install_sandbox.host.result_reader import read_evidence

    case = explicit_case()
    case_file = tmp_path / "case.json"
    case.write(case_file)
    subject = tmp_path / "subject"
    subject.mkdir()
    (subject / "section.md").write_text("## graphify\nManaged.\n")
    calls: list[str] = []

    def execute(
        args: list[str], cwd: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        calls.append("command")
        guide = cwd / "GUIDE.md"
        if "## graphify" not in guide.read_text():
            guide.write_text(guide.read_text() + "\n## graphify\nManaged.\n")
        state = "interrupted" if failure_stage == "interrupted" else "completed"
        return InstallerCommandResult(args, str(cwd), state, 0, None)

    inject_phase_failure(monkeypatch, failure_stage)
    output = tmp_path / "evidence"
    result = runner.InstallTestRunner(InstallerDriver(execute)).run_case(
        reference_sources=subject,
        prepared_executable=tmp_path / "controlled-command",
        case_file=case_file,
        work_directory=tmp_path / "work",
        output_directory=output,
    )
    assert result.status == "incomplete"
    assert len(calls) == (0 if failure_stage == "expectations" else 1)
    assert read_evidence(output) == result
    if failure_stage == "observation":
        assert result.steps[0]["command"] is not None
        assert result.steps[0]["verification"] is None


def inject_initial_persistence_failure(monkeypatch: pytest.MonkeyPatch, failed_file: str) -> None:
    from tools.install_sandbox.container.evidence_writer import TestResultWriter
    from tools.install_sandbox.contracts.results import EvidenceWriteError, VerificationResult

    original = TestResultWriter.write_metadata
    original_snapshot = TestResultWriter.write_snapshot
    original_verification = TestResultWriter.write_initial_verification

    def metadata(self: TestResultWriter, relative: str, data: object) -> None:
        if failed_file == relative:
            raise EvidenceWriteError("Controlled initial expectations persistence failure")
        original(self, relative, data)

    def snapshot(
        self: TestResultWriter,
        observed: runner.FilesystemSnapshot,
        name: str,
        *,
        step_index: int = 0,
    ) -> None:
        if failed_file == "steps/0/before.json" and name == "before":
            raise EvidenceWriteError("Controlled initial observation persistence failure")
        original_snapshot(self, observed, name, step_index=step_index)

    def verdict(self: TestResultWriter, data: VerificationResult) -> None:
        if failed_file == "initial-verification.json":
            raise EvidenceWriteError("Controlled initial verification persistence failure")
        original_verification(self, data)

    monkeypatch.setattr(TestResultWriter, "write_metadata", metadata)
    monkeypatch.setattr(TestResultWriter, "write_snapshot", snapshot)
    monkeypatch.setattr(TestResultWriter, "write_initial_verification", verdict)


@pytest.mark.parametrize(
    "failed_file",
    [
        "expectations/initial.json",
        "steps/0/before.json",
        "initial-verification.json",
    ],
)
def test_initial_persistence_failure_retains_replayable_substage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_file: str,
) -> None:
    from tools.install_sandbox.host.result_reader import read_evidence

    case_file = tmp_path / "case.json"
    explicit_case().write(case_file)
    subject = tmp_path / "subject"
    subject.mkdir()
    (subject / "section.md").write_text("## graphify\nManaged.\n")
    output = tmp_path / "evidence"

    def execute(*args: object) -> InstallerCommandResult:
        raise AssertionError("Initial failure must prevent every command")

    inject_initial_persistence_failure(monkeypatch, failed_file)
    result = runner.InstallTestRunner(InstallerDriver(execute)).run_case(
        reference_sources=subject,
        prepared_executable=tmp_path / "controlled-command",
        case_file=case_file,
        work_directory=tmp_path / "work",
        output_directory=output,
    )
    assert result.status == "not_run"
    assert result.preparation["stage"] == "sources_retained"
    assert read_evidence(output) == result
    if failed_file == "expectations/initial.json":
        import json

        failure_file = output / "construction-failure.json"
        failure = json.loads(failure_file.read_text())
        failure["kind"] = "validation"
        failure_file.write_text(json.dumps(failure))
        with pytest.raises(ValueError, match="successfully rebuilt expectations"):
            read_evidence(output)
