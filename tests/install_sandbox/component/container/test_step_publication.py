"""Interrupt real persistence boundaries without executing an external installer."""

import json
from pathlib import Path
from typing import Any

import pytest

from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.container.evidence_writer import TestResultWriter as Writer
from tools.install_sandbox.container.installer import InstallerCommandResult, InstallerDriver
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.effect_case import build_effect_cases
from tools.install_sandbox.contracts.results import EvidenceWriteError, InstallTestResult
from tools.install_sandbox.host.result_reader import read_evidence

from tests.install_sandbox.component.container.native_case_support import NativeCase
from tests.install_sandbox.component.host.native_support import LiteralInstaller


class InterruptedPublication(BaseException):
    """Simulate process interruption outside the runner's operational errors."""


class ControlledRun:
    def __init__(self, root: Path, case_name: str = "reinstall") -> None:
        self.native = NativeCase(root)
        self.repair_installer = (
            LiteralInstaller(markdown_only=True) if case_name != "reinstall" else None
        )
        if self.repair_installer is not None:
            cases = build_effect_cases(self.native.case.effects, self.native.case.subject)
            next(case for case in cases.cases if case.name == case_name).write(root / "case.json")
        self.output = root / "results"
        self.calls: list[str] = []

    def execute(
        self, args: list[str], cwd: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        self.calls.append("command")
        if self.repair_installer is not None:
            return self.repair_installer.execute(args, cwd, environment, timeout)
        guide = cwd / "GUIDE.md"
        text = guide.read_text()
        if "## graphify" not in text:
            guide.write_text(text + "\n## graphify\nConsult the synthetic map.\n")
        return InstallerCommandResult(
            args, str(cwd), "completed", 0, None, b"output retained\n", b"diagnostic retained\n"
        )

    def run(self) -> InstallTestResult:
        root = self.native.root
        return InstallTestRunner(InstallerDriver(self.execute)).run_case(
            reference_sources=root / "subject",
            prepared_executable=root / "controlled-command",
            case_file=root / "case.json",
            work_directory=root / "work",
            output_directory=self.output,
        )

    def saved(self) -> dict[str, Any]:
        return json.loads((self.output / "result.json").read_text())


def assert_retained_result(subject: ControlledRun, phase: str, *, step: int = 0) -> None:
    saved = subject.saved()
    assert saved["steps"][step]["phase"] == phase
    replayed = read_evidence(subject.output)
    assert replayed.steps[step].phase == phase
    assert replayed.status == saved["status"]
    if step == 0:
        assert replayed.steps[1].phase == "idle"


@pytest.mark.parametrize("step", [0, 1], ids=["install", "reinstall"])
@pytest.mark.parametrize("publication", [2, 3, 4], ids=["start", "command", "terminal"])
@pytest.mark.parametrize("after", [False, True], ids=["before-write", "after-write"])
def test_interruption_preserves_last_publication_and_blocks_dependent_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, publication: int, after: bool, step: int
) -> None:
    subject = ControlledRun(tmp_path)
    original = Writer.write_result
    boundary = publication + 3 * step
    attempts: list[bytes] = []
    in_memory: list[InstallTestResult] = []

    def publish(writer: Writer, result: InstallTestResult) -> None:
        if not attempts:
            in_memory.append(result)
        attempts.append(result.steps[step].phase.encode())
        if len(attempts) == boundary and not after:
            raise InterruptedPublication()
        original(writer, result)
        if len(attempts) == boundary:
            raise InterruptedPublication()

    monkeypatch.setattr(Writer, "write_result", publish)
    with pytest.raises(InterruptedPublication):
        subject.run()
    assert len(attempts) == boundary
    assert len(subject.calls) == step + (0 if publication == 2 else 1)
    phases = ["idle", "preparation", "observation", "terminal"]
    assert in_memory[0].steps[step].phase == phases[publication - 2]
    phase = phases[publication - 2 + after]
    if step == 0 and publication == 2 and not after:
        # Initial preparation has no intermediate publication contract.
        assert subject.saved()["status"] == "not_run"
        assert subject.saved()["steps"][0]["phase"] == "idle"
    else:
        assert_retained_result(subject, phase, step=step)
        assert (subject.saved()["status"] == "passed") == (step == 1 and publication == 4 and after)
    if publication < 4:
        assert not (subject.output / f"steps/{step}/after.json").exists()
    if publication == 4 and not after:
        assert (subject.output / f"steps/{step}/verification.json").is_file()


@pytest.mark.parametrize("step", [0, 1], ids=["install", "reinstall"])
@pytest.mark.parametrize(
    "target",
    [
        "steps/0/environment.json",
        "steps/0/stdout.txt",
        "steps/0/stderr.txt",
        "steps/0/after/project/GUIDE.md",
        "steps/0/after.json",
        "steps/0/verification.json",
    ],
)
@pytest.mark.parametrize("partial", [False, True], ids=["no-bytes", "partial-bytes"])
def test_authoritative_write_failure_stops_without_retry_or_final_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str, partial: bool, step: int
) -> None:
    subject = ControlledRun(tmp_path)
    target = target.replace("steps/0/", f"steps/{step}/")
    original_bytes = Writer._write_bytes  # pyright: ignore[reportPrivateUsage]
    original_json = Writer._write_json  # pyright: ignore[reportPrivateUsage]
    original_result = Writer.write_result
    writes: list[str] = []
    publications: list[str] = []

    def fail(writer: Writer, relative: str) -> None:
        if partial:
            # JSON's final name remains atomic; the interrupted temporary is inspectable.
            path = writer.output_directory / relative
            if relative.endswith(".json"):
                path = path.with_name(f".{path.name}.controlled.tmp")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"partial")
        raise EvidenceWriteError("Controlled authoritative write failure")

    def write_bytes(writer: Writer, relative: str, data: bytes, *, append: bool = False) -> None:
        writes.append(relative)
        if relative == target:
            fail(writer, relative)
        original_bytes(writer, relative, data, append=append)

    def write_json(writer: Writer, relative: str, data: object) -> None:
        writes.append(relative)
        if relative == target:
            fail(writer, relative)
        original_json(writer, relative, data)

    def publish(writer: Writer, result: InstallTestResult) -> None:
        publications.append(result.steps[step].phase)
        original_result(writer, result)

    monkeypatch.setattr(Writer, "_write_bytes", write_bytes)
    monkeypatch.setattr(Writer, "_write_json", write_json)
    monkeypatch.setattr(Writer, "write_result", publish)
    with pytest.raises(EvidenceWriteError, match="Controlled authoritative"):
        subject.run()
    assert len(subject.calls) == step + 1
    assert writes.count(target) == 1
    assert all(path == "timings.json.tmp" for path in writes[writes.index(target) + 1 :])
    command_retained = "/after" in target or target.endswith("verification.json")
    before = ["idle"] * (1 + 3 * step)
    assert publications == before + (
        ["preparation", "observation"] if command_retained else ["preparation"]
    )
    assert_retained_result(subject, "observation" if command_retained else "preparation", step=step)
    assert not (subject.output / f"steps/{step}/failure.json").exists()
    if step == 0:
        assert not (subject.output / "steps/1").exists()


def inject_unusable_before(monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    original = EffectEnvironment.observe

    def observe(
        environment: EffectEnvironment,
        writer: Writer,
        name: str,
        *,
        step_index: int = 0,
    ) -> FilesystemSnapshot:
        if name != "before" or step_index != 1:
            return original(environment, writer, name, step_index=step_index)
        if kind == "divergent":
            (environment.project / "GUIDE.md").write_text("Unexpected intervening edit.\n")
            return original(environment, writer, name, step_index=step_index)
        snapshot = environment.observe_intermediate(name)
        snapshot.obstacles.append(
            {
                "operation": "read",
                "root": "project",
                "path": "GUIDE.md",
                "reason": "Controlled obstruction",
            }
        )
        writer.write_snapshot(snapshot, name, step_index=step_index)
        return snapshot

    monkeypatch.setattr(EffectEnvironment, "observe", observe)


@pytest.mark.parametrize("case_name", ["reinstall", "missing-section", "altered-section"])
@pytest.mark.parametrize("kind", ["divergent", "obstructed"])
@pytest.mark.parametrize("boundary", ["before-diagnostic", "after-diagnostic", "published"])
def test_unusable_before1_is_retained_and_never_authorizes_second_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, boundary: str, case_name: str
) -> None:
    subject = ControlledRun(tmp_path, case_name)
    inject_unusable_before(monkeypatch, kind)
    original = Writer.write_metadata

    def metadata(writer: Writer, relative: str, value: object) -> None:
        if relative == "steps/1/failure.json" and boundary == "before-diagnostic":
            raise InterruptedPublication()
        original(writer, relative, value)
        if relative == "steps/1/failure.json" and boundary == "after-diagnostic":
            raise InterruptedPublication()

    monkeypatch.setattr(Writer, "write_metadata", metadata)
    if boundary == "published":
        result = subject.run()
        assert result.status == "incomplete"
    else:
        with pytest.raises(InterruptedPublication):
            subject.run()
    assert len(subject.calls) == 1
    assert (subject.output / "steps/1/before.json").is_file()
    assert not (subject.output / "steps/1/environment.json").exists()
    assert_retained_result(subject, "stopped" if boundary == "published" else "preparation", step=1)
    assert (subject.output / "steps/1/failure.json").exists() == (boundary != "before-diagnostic")


@pytest.mark.parametrize("partial", [False, True])
def test_diagnostic_write_failure_keeps_old_result_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, partial: bool
) -> None:
    subject = ControlledRun(tmp_path)
    inject_unusable_before(monkeypatch, "divergent")
    original = Writer._write_json  # pyright: ignore[reportPrivateUsage]
    attempts: list[str] = []

    def write(writer: Writer, relative: str, value: object) -> None:
        attempts.append(relative)
        if relative == "steps/1/failure.json":
            if partial:
                path = writer.output_directory / "steps/1/.failure.json.controlled.tmp"
                path.write_bytes(b'{"stage":')
            raise EvidenceWriteError("Controlled diagnostic persistence failure")
        original(writer, relative, value)

    monkeypatch.setattr(Writer, "_write_json", write)
    with pytest.raises(EvidenceWriteError, match="Controlled diagnostic"):
        subject.run()
    assert len(subject.calls) == 1
    failure_index = attempts.index("steps/1/failure.json")
    assert attempts.count("steps/1/failure.json") == 1
    assert all(name == "timings.json.tmp" for name in attempts[failure_index + 1 :])
    assert_retained_result(subject, "preparation", step=1)
    assert not (subject.output / "steps/1/failure.json").exists()


@pytest.mark.parametrize("case_name", ["reinstall", "missing-section", "altered-section"])
@pytest.mark.parametrize("target", ["steps/1/before/project/GUIDE.md", "steps/1/before.json"])
def test_before1_partial_publication_remains_inspectable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case_name: str, target: str
) -> None:
    subject = ControlledRun(tmp_path, case_name)
    original_bytes = Writer._write_bytes  # pyright: ignore[reportPrivateUsage]
    original_json = Writer._write_json  # pyright: ignore[reportPrivateUsage]

    def fail(writer: Writer, relative: str) -> None:
        path = writer.output_directory / relative
        if relative.endswith(".json"):
            path = path.with_name(f".{path.name}.partial.tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"partial")
        raise EvidenceWriteError("Controlled before1 persistence failure")

    def write_bytes(writer: Writer, relative: str, data: bytes, *, append: bool = False) -> None:
        if relative == target:
            fail(writer, relative)
        original_bytes(writer, relative, data, append=append)

    def write_json(writer: Writer, relative: str, data: object) -> None:
        if relative == target:
            fail(writer, relative)
        original_json(writer, relative, data)

    monkeypatch.setattr(Writer, "_write_bytes", write_bytes)
    monkeypatch.setattr(Writer, "_write_json", write_json)
    with pytest.raises(EvidenceWriteError, match="before1"):
        subject.run()
    assert len(subject.calls) == 1
    assert not (subject.output / "steps/1/environment.json").exists()
    assert_retained_result(subject, "preparation", step=1)


@pytest.mark.parametrize("case_name", ["missing-section", "altered-section"])
def test_repair_command_prefix_before_checkpoint_uses_protocol_expectations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case_name: str
) -> None:
    subject = ControlledRun(tmp_path, case_name)
    original = Writer.write_result

    def publish(writer: Writer, result: InstallTestResult) -> None:
        if result.steps[1].phase == "observation":
            raise InterruptedPublication()
        original(writer, result)

    monkeypatch.setattr(Writer, "write_result", publish)
    with pytest.raises(InterruptedPublication):
        subject.run()
    assert len(subject.calls) == 2
    assert (subject.output / "steps/1/stderr.txt").is_file()
    assert not (subject.output / "steps/1/after.json").exists()
    assert_retained_result(subject, "preparation", step=1)


def test_terminal_publication_keeps_finalization_timing_without_extra_result_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject = ControlledRun(tmp_path)
    original = Writer.write_result
    publications: list[str] = []

    def publish(writer: Writer, result: InstallTestResult) -> None:
        publications.append(result.status)
        original(writer, result)

    monkeypatch.setattr(Writer, "write_result", publish)
    assert subject.run().status == "passed"
    assert len(publications) == 7  # Initial preparation, then three per step.
    timings = json.loads((subject.output / "timings.json").read_text())
    finalization = next(phase for phase in timings["phases"] if phase["phase"] == "finalize")
    assert finalization["state"] == "measured"
    assert finalization["diagnostic"] is None
