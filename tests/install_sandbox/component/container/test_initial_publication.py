"""Initial preparation advances only across successfully published checkpoints."""

import shutil
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.test_step_publication import (
    ControlledRun,
    InterruptedPublication,
    inject_write_error,
)
from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.container.evidence_writer import TestResultWriter as Writer
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import EvidenceWriteError, InstallTestResult
from tools.install_sandbox.host.result_reader import read_evidence

CHECKPOINTS = (
    "started",
    "environment_retained",
    "sources_retained",
    "expectations_retained",
    "observed",
    "verified",
    "ready",
)


@pytest.mark.parametrize("checkpoint", CHECKPOINTS)
@pytest.mark.parametrize("after", [False, True], ids=["before-replace", "after-replace"])
def test_initial_publication_interruptions_keep_actual_published_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checkpoint: str, after: bool
) -> None:
    subject = ControlledRun(tmp_path)
    original = Writer.write_result
    attempts: list[InstallTestResult] = []

    def publish(writer: Writer, candidate: InstallTestResult) -> None:
        if candidate.preparation.checkpoint == checkpoint:
            attempts.append(candidate)
            if after:
                original(writer, candidate)
            raise InterruptedPublication()
        original(writer, candidate)

    monkeypatch.setattr(Writer, "write_result", publish)
    with pytest.raises(InterruptedPublication):
        subject.run()
    assert len(attempts) == 1
    assert not subject.calls
    index = CHECKPOINTS.index(checkpoint)
    if index == 0 and not after:
        assert not (subject.output / "result.json").exists()
        with pytest.raises(ValueError):
            read_evidence(subject.output)
        return
    expected = checkpoint if after else CHECKPOINTS[index - 1]
    assert subject.saved()["preparation"]["checkpoint"] == expected
    replayed = read_evidence(subject.output)
    assert replayed.preparation.checkpoint == expected
    assert replayed.status == "incomplete"
    assert all(step.phase == "idle" for step in replayed.steps)
    # A candidate retained by the writer must not be mutated by later adoption.
    assert attempts[0].preparation.checkpoint == checkpoint


@pytest.mark.parametrize("case_name", ["reinstall", "missing-section", "altered-section"])
@pytest.mark.parametrize(
    ("target", "checkpoint"),
    [
        ("roots.json", "started"),
        ("expected/instructions.md", "environment_retained"),
        ("expected.json", "environment_retained"),
        ("expectations/initial.json", "sources_retained"),
        ("initial/before/project/GUIDE.md", "expectations_retained"),
        ("initial/before.json", "expectations_retained"),
        ("initial-verification.json", "observed"),
        ("expectations/install.json", "verified"),
    ],
)
@pytest.mark.parametrize("partial", [False, True], ids=["no-bytes", "partial-bytes"])
def test_initial_write_errors_stop_all_operations_and_replay_retained_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case_name: str,
    target: str,
    checkpoint: str,
    partial: bool,
) -> None:
    subject = ControlledRun(tmp_path, case_name)
    writes = inject_write_error(monkeypatch, target, partial)
    with pytest.raises(EvidenceWriteError, match="Controlled authoritative"):
        subject.run()
    assert writes.count(target) == 1
    assert all(name == "timings.json.tmp" for name in writes[writes.index(target) + 1 :])
    assert not subject.calls
    assert not (subject.output / "initial/failure.json").exists()
    shutil.rmtree(tmp_path / "work")
    shutil.rmtree(tmp_path / "subject")
    replayed = read_evidence(subject.output)
    assert replayed.preparation.checkpoint == checkpoint
    assert replayed.status == "incomplete"
    assert all(step.phase == "idle" for step in replayed.steps)


@pytest.mark.parametrize("boundary", ["before", "after", "published"])
def test_operational_diagnostic_interruption_never_promotes_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    subject = ControlledRun(tmp_path)
    original = Writer._write_json  # pyright: ignore[reportPrivateUsage]

    def prepare(environment: EffectEnvironment) -> None:
        raise OSError("Controlled environment failure")

    def write(writer: Writer, relative: str, value: object) -> None:
        if relative == "initial/failure.json" and boundary == "before":
            raise InterruptedPublication()
        original(writer, relative, value)
        if relative == "initial/failure.json" and boundary == "after":
            raise InterruptedPublication()

    monkeypatch.setattr(EffectEnvironment, "prepare", prepare)
    monkeypatch.setattr(Writer, "_write_json", write)
    if boundary == "published":
        assert subject.run().status == "not_run"
    else:
        with pytest.raises(InterruptedPublication):
            subject.run()
    assert not subject.calls
    replayed = read_evidence(subject.output)
    assert replayed.preparation.checkpoint == ("stopped" if boundary == "published" else "started")
    assert replayed.status == ("not_run" if boundary == "published" else "incomplete")


@pytest.mark.parametrize("partial", [False, True])
def test_initial_diagnostic_write_error_has_no_retry_or_final_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, partial: bool
) -> None:
    subject = ControlledRun(tmp_path)
    original = Writer._write_json  # pyright: ignore[reportPrivateUsage]
    attempts: list[str] = []

    def prepare(environment: EffectEnvironment) -> None:
        raise OSError("Controlled environment failure")

    def write(writer: Writer, relative: str, value: object) -> None:
        attempts.append(relative)
        if relative == "initial/failure.json":
            if partial:
                path = writer.output_directory / "initial/.failure.json.controlled.tmp"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"partial")
            raise EvidenceWriteError("Controlled diagnostic write error")
        original(writer, relative, value)

    monkeypatch.setattr(EffectEnvironment, "prepare", prepare)
    monkeypatch.setattr(Writer, "_write_json", write)
    with pytest.raises(EvidenceWriteError, match="Controlled diagnostic"):
        subject.run()
    assert attempts.count("initial/failure.json") == 1
    assert all(
        name == "timings.json.tmp"
        for name in attempts[attempts.index("initial/failure.json") + 1 :]
    )
    assert not subject.calls
    assert read_evidence(subject.output).preparation.checkpoint == "started"


@pytest.mark.parametrize("kind", ["divergent", "obstructed"])
def test_initial_verification_block_is_retained_without_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    subject = ControlledRun(tmp_path)
    original = EffectEnvironment.capture_initial

    def capture(environment: EffectEnvironment) -> FilesystemSnapshot:
        if kind == "divergent":
            (environment.project / "GUIDE.md").write_text("Unexpected initial edit.\n")
        observed = original(environment)
        if kind == "obstructed":
            observed.obstacles.append(
                {
                    "operation": "read",
                    "root": "project",
                    "path": "GUIDE.md",
                    "reason": "Controlled initial obstruction",
                }
            )
        return observed

    monkeypatch.setattr(EffectEnvironment, "capture_initial", capture)
    result = subject.run()
    assert result.status == "not_run"
    assert result.preparation.checkpoint == "blocked"
    assert not subject.calls
    assert (subject.output / "initial-verification.json").is_file()
    assert not (subject.output / "expectations/install.json").exists()
    assert read_evidence(subject.output) == result


@pytest.mark.parametrize("case_name", ["reinstall", "missing-section", "altered-section"])
def test_completed_initial_evidence_is_self_contained_without_logs_or_timings(
    tmp_path: Path, case_name: str
) -> None:
    subject = ControlledRun(tmp_path, case_name)
    result = subject.run()
    assert result.status == "passed"
    shutil.rmtree(tmp_path / "work")
    shutil.rmtree(tmp_path / "subject")
    for filename in ("journal.log", "preparation.log", "timings.json"):
        (subject.output / filename).unlink(missing_ok=True)
    replayed = read_evidence(subject.output)
    assert replayed.status == "passed"
    assert replayed.preparation.checkpoint == "ready"
    assert replayed.steps[0].retained.before == "initial/before.json"
    assert not (subject.output / "steps/0/before.json").exists()


@pytest.mark.parametrize("checkpoint", ["started", "observed", "ready"])
def test_checkpoint_write_error_is_not_retried_or_replaced_by_failure_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checkpoint: str
) -> None:
    subject = ControlledRun(tmp_path)
    original = Writer.write_result
    attempted: list[str] = []

    def publish(writer: Writer, candidate: InstallTestResult) -> None:
        attempted.append(candidate.preparation.checkpoint)
        if candidate.preparation.checkpoint == checkpoint:
            raise EvidenceWriteError("Controlled result publication error")
        original(writer, candidate)

    monkeypatch.setattr(Writer, "write_result", publish)
    with pytest.raises(EvidenceWriteError, match="Controlled result"):
        subject.run()
    assert attempted[-1] == checkpoint
    assert attempted.count(checkpoint) == 1
    assert not subject.calls
    assert not (subject.output / "initial/failure.json").exists()
    if checkpoint == "started":
        assert not (subject.output / "result.json").exists()
    else:
        assert (
            read_evidence(subject.output).preparation.checkpoint
            == CHECKPOINTS[CHECKPOINTS.index(checkpoint) - 1]
        )


@pytest.mark.parametrize(
    ("operation", "owner", "method"),
    [
        ("sources", "environment", "capture_sources"),
        ("expectations", "runner", "build_initial_expectations"),
        ("observation", "environment", "capture_initial"),
        ("verification", "verifier", "verify"),
        ("install_expectations", "runner", "build_install_expectations"),
    ],
)
def test_operation_io_stop_keeps_only_previously_retained_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, owner: str, method: str
) -> None:
    from tools.install_sandbox.container import runner
    from tools.install_sandbox.rules.effect_verifier import EffectVerifier

    subject = ControlledRun(tmp_path)

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError(f"Controlled {operation} failure")

    with monkeypatch.context() as patch:
        target = {"environment": EffectEnvironment, "runner": runner, "verifier": EffectVerifier}[
            owner
        ]
        patch.setattr(target, method, fail)
        result = subject.run()
    assert not subject.calls
    assert result.status == "not_run"
    assert result.preparation.checkpoint == "stopped"
    assert result.preparation.stop is not None
    assert result.preparation.stop.operation == operation
    assert result.preparation.stop.category == "io"
    assert result.preparation.stop.reason == f"Controlled {operation} failure"
    shutil.rmtree(tmp_path / "work")
    shutil.rmtree(tmp_path / "subject")
    assert read_evidence(subject.output) == result


@pytest.mark.parametrize("checkpoint", ["blocked", "stopped"])
@pytest.mark.parametrize("after", [False, True], ids=["before-replace", "after-replace"])
def test_terminal_initial_publication_interruption_uses_last_disk_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checkpoint: str, after: bool
) -> None:
    subject = ControlledRun(tmp_path)
    original_publish = Writer.write_result
    original_capture = EffectEnvironment.capture_initial

    def prepare(environment: EffectEnvironment) -> None:
        raise OSError("Controlled environment failure")

    def capture(environment: EffectEnvironment) -> FilesystemSnapshot:
        (environment.project / "GUIDE.md").write_text("Unexpected initial edit.\n")
        return original_capture(environment)

    def publish(writer: Writer, result: InstallTestResult) -> None:
        if result.preparation.checkpoint == checkpoint:
            if after:
                original_publish(writer, result)
            raise InterruptedPublication()
        original_publish(writer, result)

    monkeypatch.setattr(Writer, "write_result", publish)
    if checkpoint == "stopped":
        monkeypatch.setattr(EffectEnvironment, "prepare", prepare)
    else:
        monkeypatch.setattr(EffectEnvironment, "capture_initial", capture)
    with pytest.raises(InterruptedPublication):
        subject.run()
    assert not subject.calls
    replayed = read_evidence(subject.output)
    assert replayed.preparation.checkpoint == (
        checkpoint if after else "observed" if checkpoint == "blocked" else "started"
    )
    assert replayed.status == ("not_run" if after else "incomplete")


@pytest.mark.parametrize("after", [False, True], ids=["before-replace", "after-replace"])
def test_interruption_at_result_atomic_replace_obeys_file_that_was_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, after: bool
) -> None:
    import json

    subject = ControlledRun(tmp_path)
    original = Path.replace
    replacements: list[str] = []

    def replace(path: Path, target: str | Path) -> Path:
        destination = Path(target)
        if destination == subject.output / "result.json":
            candidate = json.loads(path.read_text())
            if candidate["preparation"]["checkpoint"] == "ready":
                replacements.append("ready")
                if after:
                    original(path, target)
                raise InterruptedPublication()
        return original(path, target)

    monkeypatch.setattr(Path, "replace", replace)
    with pytest.raises(InterruptedPublication):
        subject.run()
    assert replacements == ["ready"]
    assert not subject.calls
    replayed = read_evidence(subject.output)
    assert replayed.preparation.checkpoint == ("ready" if after else "verified")
    assert replayed.status == "incomplete"
