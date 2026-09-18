"""Conservation failures never rewrite installation verdicts or discard recoverable evidence."""

import json
import signal
import zipfile
from pathlib import Path

import pytest

from tests.install_sandbox.component.host.output_support import refused, valid
from tools.install_sandbox.host import output_archive, output_lifecycle, output_report
from tools.install_sandbox.host.docker_runtime import SignalCapture
from tools.install_sandbox.host.output_report import OutputReport


@pytest.mark.parametrize("failure", ["read", "write", "verify"])
def test_archive_failure_preserves_raw_pass_and_reports_real_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise OSError(f"controlled archive {failure} failure")

    seam = {"read": "export_summary", "write": "_archive_entry", "verify": "_verify_archive"}[
        failure
    ]
    monkeypatch.setattr(output_archive, seam, fail)
    result = valid(tmp_path, monkeypatch)
    assert result.exit_code == 1 and result.report.execution["passed"] is True
    assert (
        result.output_directory is not None and result.output_directory.parent.name == "in-progress"
    )
    assert (result.output_directory / "evidence/cases/first-install/result.json").is_file()
    assert not (result.output_directory / "evidence.zip").exists()
    assert f"controlled archive {failure} failure" in result.report.render()


@pytest.mark.parametrize("partial", [False, True])
def test_raw_removal_failure_keeps_verified_archive_and_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, partial: bool
) -> None:
    remove = output_lifecycle.shutil.rmtree

    def denied(path: Path | str, *args: object, **kwargs: object) -> None:
        path = Path(path)
        if path.name == "evidence":
            if partial:
                (path / "campaign.txt").unlink()
            raise PermissionError("controlled raw removal failure")
        remove(path)

    monkeypatch.setattr(output_lifecycle.shutil, "rmtree", denied)
    result = valid(tmp_path, monkeypatch)
    assert result.exit_code == 0 and result.report.execution["passed"] is True
    assert (
        result.output_directory is not None and result.output_directory.parent.name == "in-progress"
    )
    assert result.report.archive == "verified" and result.report.raw_evidence
    with zipfile.ZipFile(result.output_directory / "evidence.zip") as archive:
        assert archive.testzip() is None
        assert archive.read("evidence/cases/first-install/result.json")
    assert "raw removal failure" in result.report.render()


def test_destination_created_during_execution_is_not_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = output_lifecycle.archive_evidence

    def race(directory: Path, interrupts: SignalCapture) -> None:
        archive(directory, interrupts)
        final = directory.parents[1] / directory.name
        final.mkdir()
        (final / "foreign.txt").write_text("Do not replace")

    monkeypatch.setattr(output_lifecycle, "archive_evidence", race)
    result = valid(tmp_path, monkeypatch)
    assert result.exit_code == 1 and result.report.execution["passed"] is True
    assert (
        result.output_directory is not None and result.output_directory.parent.name == "in-progress"
    )
    assert (result.output_directory / "evidence.zip").is_file()
    assert (Path(result.report.destination) / "foreign.txt").read_text() == "Do not replace"


@pytest.mark.parametrize("phase", ["before", "during", "after"])
@pytest.mark.parametrize("number", [signal.SIGINT, signal.SIGTERM])
def test_signal_preserves_recoverable_evidence_and_original_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str, number: signal.Signals
) -> None:
    archive = output_lifecycle.archive_evidence

    def interrupted(directory: Path, interrupts: SignalCapture) -> None:
        if phase == "before":
            signal.raise_signal(number)
        archive(directory, interrupts)
        if phase == "after":
            signal.raise_signal(number)

    def compare_interrupted(
        archive: zipfile.ZipFile, name: str, path: Path, interrupts: SignalCapture
    ) -> None:
        signal.raise_signal(number)
        output_archive.check_interrupt(interrupts)

    monkeypatch.setattr(output_lifecycle, "archive_evidence", interrupted)
    if phase == "during":
        monkeypatch.setattr(output_archive, "_compare_entry", compare_interrupted)
    result = valid(tmp_path, monkeypatch)
    assert result.exit_code == 128 + number and result.report.execution["passed"] is True
    assert (
        result.output_directory is not None and result.output_directory.parent.name == "in-progress"
    )
    raw = result.output_directory / "evidence/cases/first-install/result.json"
    assert raw.is_file()
    assert (result.output_directory / "evidence.zip").exists() == (phase == "after")


def test_unwritable_report_prevents_launch_and_never_promises_saved_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        raise PermissionError("controlled report write failure")

    monkeypatch.setattr(output_report, "atomic_text", denied)
    result = refused(tmp_path)
    assert result.exit_code != 0 and result.output_directory is not None
    assert "Cannot save output report" in result.report.render()
    assert result.report.writers == []
    assert not (result.output_directory / "campaign.json").exists()


@pytest.mark.parametrize("role", ["verify", "run"])
def test_writer_observer_write_failure_prevents_that_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    save = OutputReport.save

    def fail_intent(report: OutputReport, directory: Path) -> None:
        if any(writer.role == role and writer.state == "intent" for writer in report.writers):
            raise OSError("cannot persist writer")
        save(report, directory)

    monkeypatch.setattr(OutputReport, "save", fail_intent)
    result = valid(tmp_path, monkeypatch)
    assert result.exit_code != 0
    calls = [json.loads(p.read_text()) for p in (tmp_path / "runtime").glob("command-*")]
    runs = [call for call in calls if call[0] == "run"]
    assert len(runs) == (0 if role == "verify" else 1)


def test_retention_runs_even_after_current_archive_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import timedelta

    from tests.install_sandbox.component.host.output_support import START

    old = refused(tmp_path, START - timedelta(days=14)).output_directory
    assert old is not None

    def fail(*args: object) -> None:
        raise OSError("controlled archive failure")

    monkeypatch.setattr(output_lifecycle, "archive_evidence", fail)
    result = refused(tmp_path)
    assert not old.exists()
    assert result.output_directory is not None and result.output_directory.is_dir()
    assert result.exit_code != 0 and "controlled archive failure" in result.report.render()
