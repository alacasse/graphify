"""Replay an incomplete CLI archive and reject edits to the runner's copy of the case."""

import json
from pathlib import Path
from unittest.mock import Mock
from zipfile import ZipFile

import pytest

from tests.install_sandbox.component.host.native_support import (
    ControlledTransport,
    arrange,
    completed,
)
from tests.install_sandbox.component.host.test_case_selection import arguments
from tools.install_sandbox.__main__ import main
from tools.install_sandbox.host import coordinator
from tools.install_sandbox.host.campaign_replay import replay_campaign
from tools.install_sandbox.host.docker_runtime import ContainerRunResult
from tools.install_sandbox.host.output_report import relative_values


def _publish_incomplete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, evidence: str) -> Path:
    subject, spec, context = arrange(tmp_path)
    transport = ControlledTransport(tmp_path)
    run_case = transport.run_case

    def incomplete_run(*, case_file: Path, output_directory: Path) -> ContainerRunResult:
        if evidence == "truncated-result":
            receipt = run_case(case_file=case_file, output_directory=output_directory)
            (output_directory / "result.json").write_bytes(b"{")
            return receipt
        if evidence != "empty":
            (output_directory / "case.json").write_bytes(case_file.read_bytes())
            if evidence != "case-only":
                (output_directory / evidence).touch()
                return completed()
        raise KeyboardInterrupt

    monkeypatch.setattr(transport, "run_case", incomplete_run)
    monkeypatch.setattr(coordinator, "ContainerHarness", Mock(return_value=transport))
    output = tmp_path / "published"
    assert main([*arguments(subject, spec, context, output), "--case", "reinstall"]) == 1
    report = json.loads((output / "campaign.json").read_text())
    assert report["status"] == "partial_incomplete"
    archive = output / "evidence.zip"
    if evidence == "truncated-result":
        assert report["cases"][0]["result"]["result_error"]
    if evidence == "empty":
        assert report["interrupted"]
        assert transport.installer.calls == []
        assert report["executed_cases"] == report["executed_keys"] == []
        with ZipFile(archive) as source:
            entries = [
                info for info in source.infolist() if info.filename.startswith("evidence/cases/")
            ]
            assert len(entries) == 2 and all(info.is_dir() for info in entries)
    report.pop("output_lifecycle")
    assert replay_campaign(archive) == relative_values(report, Path("evidence"), ".")
    return archive


@pytest.mark.parametrize(
    ("evidence", "mutation"),
    [
        ("truncated-result", "replace"),
        ("truncated-result", "remove"),
        ("evidence-format.json", "remove"),
        ("result.json", "remove"),
        ("case-only", "replace"),
    ],
)
def test_incomplete_cli_archive_rejects_changed_retained_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, evidence: str, mutation: str
) -> None:
    archive = _publish_incomplete(tmp_path, monkeypatch, evidence)
    changed = tmp_path / "changed.zip"
    with ZipFile(archive) as source, ZipFile(changed, "w") as destination:
        (case_copy,) = [name for name in source.namelist() if name.endswith("/case.json")]
        for member in source.infolist():
            payload = source.read(member)
            if member.filename == case_copy:
                if mutation == "remove":
                    continue
                payload += b"\n"  # Same JSON value, different transport bytes.
            destination.writestr(member, payload)
    with pytest.raises(ValueError) as error:
        replay_campaign(changed)
    assert case_copy.removeprefix("evidence/") in str(error.value)


def test_cli_archive_interrupted_before_runner_writes_replays_as_unexecuted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _publish_incomplete(tmp_path, monkeypatch, "empty")
