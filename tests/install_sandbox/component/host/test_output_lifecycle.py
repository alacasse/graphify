"""User output behavior with real evidence and the controlled Docker runtime."""

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.install_sandbox.component.host.output_support import RUNTIME, arrange_output
from tools.install_sandbox.host.output_lifecycle import CampaignOutput
from tools.install_sandbox.host.result_reader import read_evidence

NOW = datetime(2026, 9, 17, 14, 30, 12, tzinfo=UTC)


def test_archive_is_readable_after_move_and_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange_output(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_DISCARD_WORK", "1")
    result = CampaignOutput(managed_root=tmp_path / "out", now=lambda: NOW).run(
        spec_file=tmp_path / "effects.yaml",
        subject_context_file=tmp_path / "context.json",
        subject_checkout=tmp_path / "subject",
        runtime_executable=RUNTIME,
    )
    assert result.exit_code == 0, result.report.render()
    output = result.output_directory
    assert output is not None
    assert output == tmp_path / "out/20260917T143012Z"
    assert {p.name for p in output.iterdir()} == {"campaign.json", "campaign.txt", "evidence.zip"}
    with zipfile.ZipFile(output / "evidence.zip") as archive:
        archive.extractall(tmp_path / "extracted")
        assert not any(name.endswith("evidence.zip") for name in archive.namelist())
    evidence = tmp_path / "extracted/evidence"
    assert read_evidence(evidence / "cases/reinstall").status == "passed"
    assert read_evidence(evidence / "cases/missing-section").status == "passed"
    payload = json.loads((output / "campaign.json").read_text())
    assert (
        payload["passed"] and payload["cases"][0]["output_directory"] == "evidence/cases/reinstall"
    )
    assert len(payload["output_lifecycle"]["writers"]) == 3
    assert all(w["state"] == "stopped" for w in payload["output_lifecycle"]["writers"])


def test_refusal_has_report_without_starting_docker(tmp_path: Path) -> None:
    result = CampaignOutput(managed_root=tmp_path / "out", now=lambda: NOW).run(
        spec_file=tmp_path / "effects.yaml",
        subject_context_file=tmp_path / "context.json",
        subject_checkout=tmp_path,
    )
    # A result cannot be placed inside an arbitrary subject directory.
    assert result.exit_code == 2 and result.output_directory is None
    (tmp_path / "subject").mkdir()
    result = CampaignOutput(managed_root=tmp_path / "out", now=lambda: NOW).run(
        spec_file=tmp_path / "effects.yaml",
        subject_context_file=tmp_path / "context.json",
        subject_checkout=tmp_path / "subject",
    )
    assert result.exit_code == 2 and result.output_directory is not None
    assert (result.output_directory / "campaign.json").is_file()
    assert result.report.writers == [] and result.report.execution == {}
    assert result.report.finished_at == NOW.isoformat()
    assert "No such file" in result.report.render()


def test_existing_internal_destination_is_never_modified(tmp_path: Path) -> None:
    (tmp_path / "subject").mkdir()
    destination = tmp_path / "out/chosen"
    destination.mkdir(parents=True)
    result = CampaignOutput(managed_root=tmp_path / "out").run(
        spec_file=tmp_path / "effects.yaml",
        subject_context_file=tmp_path / "context.json",
        subject_checkout=tmp_path / "subject",
        output_directory=destination,
    )
    assert result.exit_code == 2 and result.output_directory is None
    assert list(destination.iterdir()) == []


def test_writer_identity_is_persisted_before_verification_and_case_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange_output(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_DISCARD_WORK", "1")
    wrapper = tmp_path / "observing-docker"
    adapter = RUNTIME
    wrapper.write_text(
        "#!/usr/bin/env python3\nimport json, runpy, sys\nfrom pathlib import Path\n"
        f"root = Path({str(tmp_path / 'out/in-progress')!r})\n"
        "if sys.argv[1] == 'run':\n"
        "    report = json.loads(next(root.glob('*/campaign.json')).read_text())\n"
        "    name = sys.argv[sys.argv.index('--name') + 1]\n"
        "    writers = report['output_lifecycle']['writers']\n"
        "    assert any(w['name'] == name and w['state'] == 'intent' for w in writers)\n"
        "    assert report['cases']\n"
        f"runpy.run_path({str(adapter)!r}, run_name='__main__')\n"
    )
    wrapper.chmod(0o755)
    result = CampaignOutput(managed_root=tmp_path / "out", now=lambda: NOW).run(
        spec_file=tmp_path / "effects.yaml",
        subject_context_file=tmp_path / "context.json",
        subject_checkout=tmp_path / "subject",
        runtime_executable=wrapper,
    )
    assert result.exit_code == 0, result.report.render()
    assert (
        len(
            [
                p
                for p in (tmp_path / "runtime").glob("command-*")
                if json.loads(p.read_text())[0] == "run"
            ]
        )
        == 3
    )


def test_failed_case_is_archived_after_confirmed_writer_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange_output(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_DISCARD_WORK", "1")
    monkeypatch.setenv("FAKE_DOCKER_MODE", "run_fail")
    result = CampaignOutput(managed_root=tmp_path / "out", now=lambda: NOW).run(
        spec_file=tmp_path / "effects.yaml",
        subject_context_file=tmp_path / "context.json",
        subject_checkout=tmp_path / "subject",
        runtime_executable=RUNTIME,
    )
    assert result.exit_code == 1 and result.output_directory is not None
    assert result.output_directory.parent == tmp_path / "out"
    assert result.report.archive == "verified"
    assert all(writer.state == "stopped" for writer in result.report.writers)
    with zipfile.ZipFile(result.output_directory / "evidence.zip") as archive:
        payload = json.loads(archive.read("evidence/campaign.json"))
    assert (
        payload["passed"] is False and payload["cases"][0]["result"]["test"]["status"] == "passed"
    )
