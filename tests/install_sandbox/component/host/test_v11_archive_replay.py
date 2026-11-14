"""Replay an ordinary historical campaign and reject edits to either case copy."""

import json
from pathlib import Path
from unittest.mock import Mock
from zipfile import ZipFile

import pytest

from tests.install_sandbox.component.host.native_support import ControlledTransport, arrange
from tools.install_sandbox.__main__ import main
from tools.install_sandbox.host import coordinator
from tools.install_sandbox.host.campaign_replay import replay_campaign


@pytest.mark.parametrize("copy", ["submitted", "rendered", "manifest"])
def test_v11_archive_replays_and_rejects_one_altered_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, copy: str
) -> None:
    subject, spec, context = arrange(tmp_path, markdown_only=True)
    transport = ControlledTransport(tmp_path, markdown_only=True)
    monkeypatch.setattr(coordinator, "ContainerHarness", Mock(return_value=transport))
    output = tmp_path / "published"
    assert (
        main(
            [
                "--repo",
                str(subject),
                "--spec",
                str(spec),
                "--subject-context",
                str(context),
                "--output",
                str(output),
                "--case",
                "reinstall",
            ]
        )
        == 0
    )
    with ZipFile(output / "evidence.zip") as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    for name in files:
        if name == "evidence/definition.json":
            payload = json.loads(files[name])
            payload["context"]["rules"] = {"hook_timeout": 17, **payload["context"]["rules"]}
        elif (name.startswith("evidence/inputs/") and name.endswith(".json")) or name.endswith(
            "/case.json"
        ):
            payload = json.loads(files[name])
            payload["format"] = "explicit-expectations-v11"
            payload["subject"]["rules"] = {"hook_timeout": 17, **payload["subject"]["rules"]}
        else:
            continue
        files[name] = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode()
    historical = tmp_path / "historical.zip"
    with ZipFile(historical, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    assert replay_campaign(historical)["status"] == "partial_passed"
    if copy == "manifest":
        name = "evidence/definition.json"
        payload = json.loads(files[name])
        payload["context"]["rules"]["hook_timeout"] = 11
    else:
        name = next(
            name
            for name in files
            if (
                name.startswith("evidence/inputs/")
                if copy == "submitted"
                else name.startswith("evidence/cases/")
            )
            and (name.endswith(".json") if copy == "submitted" else name.endswith("/case.json"))
        )
        payload = json.loads(files[name])
        payload["subject"]["rules"]["hook_timeout"] = 11
    files[name] = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode()
    with ZipFile(historical, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    with pytest.raises(ValueError):
        replay_campaign(historical)
