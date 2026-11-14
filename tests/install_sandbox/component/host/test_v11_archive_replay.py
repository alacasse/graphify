"""Replay an ordinary historical campaign and reject edits to either case copy."""

import json
from pathlib import Path
from unittest.mock import Mock
from zipfile import ZipFile

import pytest

from tests.install_sandbox.component.host.native_support import ControlledTransport, arrange
from tools.install_sandbox.__main__ import main
from tools.install_sandbox.contracts.effect_case import CaseKey
from tools.install_sandbox.host import coordinator
from tools.install_sandbox.host.campaign_replay import replay_campaign


@pytest.fixture
def v11_campaign(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
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
    return files


@pytest.mark.parametrize(
    ("copy", "edit"),
    [
        ("submitted", "timeout"),
        ("rendered", "timeout"),
        ("manifest", "timeout"),
        ("submitted", "line_endings"),
        ("rendered", "line_endings"),
    ],
)
def test_v11_archive_replays_and_rejects_one_altered_copy(
    tmp_path: Path, v11_campaign: dict[str, bytes], copy: str, edit: str
) -> None:
    files = v11_campaign
    key = json.loads(files["evidence/campaign.json"])["executed_keys"][0]
    case_id = CaseKey.from_data(key).storage_id
    name, context_field, diagnostic = {
        "submitted": (f"evidence/inputs/{case_id}.json", "subject", "Submitted case"),
        "rendered": (f"evidence/cases/{case_id}/case.json", "subject", "Retained case"),
        "manifest": ("evidence/definition.json", "context", "Submitted case"),
    }[copy]
    if edit == "timeout":
        payload = json.loads(files[name])
        payload[context_field]["rules"]["hook_timeout"] = 11
        files[name] = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode()
    else:
        assert b"\n" in files[name]
        files[name] = files[name].replace(b"\n", b"\r\n")
    historical = tmp_path / "altered.zip"
    with ZipFile(historical, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    with pytest.raises(ValueError, match=diagnostic):
        replay_campaign(historical)
