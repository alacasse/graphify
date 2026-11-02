"""Prove the native user command through host, engine, archive and autonomous reread."""

import json
import shutil
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

import pytest

from tests.install_sandbox.component.host.native_support import ControlledTransport, arrange
from tools.install_sandbox.__main__ import main
from tools.install_sandbox.host import coordinator
from tools.install_sandbox.host.campaign_definition import load_campaign_definition
from tools.install_sandbox.host.result_reader import read_evidence


@pytest.mark.parametrize(
    ("markdown_only", "hooks", "expected_root", "installed_root", "passed"),
    [
        pytest.param(False, True, "home", "home", True, id="all-effects-home"),
        pytest.param(True, False, "home", "home", True, id="markdown-only"),
        pytest.param(False, False, "project", "project", True, id="skill-project-markdown"),
        pytest.param(False, False, "project", "home", False, id="wrong-skill-root"),
    ],
)
def test_cli_real_engine_and_autonomous_reread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    markdown_only: bool,
    hooks: bool,
    expected_root: Literal["home", "project"],
    installed_root: Literal["home", "project"],
    passed: bool,
) -> None:
    subject, spec, context = arrange(
        tmp_path, markdown_only=markdown_only, hooks=hooks, skill_root=expected_root
    )
    transport = ControlledTransport(
        tmp_path, markdown_only=markdown_only, hooks=hooks, skill_root=installed_root
    )

    def harness(**kwargs: object) -> ControlledTransport:
        return transport

    monkeypatch.setattr(coordinator, "ContainerHarness", harness)
    output = tmp_path / "published"
    assert main(
        [
            "--spec",
            str(spec),
            "--subject-context",
            str(context),
            "--repo",
            str(subject),
            "--output",
            str(output),
        ]
    ) == (0 if passed else 1)
    assert len(transport.installer.calls) == (6 if passed else 3)
    assert not (output / "evidence").exists()
    report = json.loads((output / "campaign.json").read_text())
    assert [case["name"] for case in report["cases"]] == [
        "reinstall",
        "missing-section",
        "altered-section",
    ]
    saved = {case["name"]: case["result"]["test"] for case in report["cases"]}
    for result in saved.values():
        assert result["status"] == ("passed" if passed else "failed")
        if not passed:
            _assert_wrong_root_stops_after_first_command(result)
    shutil.rmtree(subject)
    spec.unlink()
    context.unlink()
    assert not transport.executable.exists()
    assert not (tmp_path / "environment").exists()
    restored = tmp_path / "restored"
    with zipfile.ZipFile(output / "evidence.zip") as archive:
        archive.extractall(restored)
    for name in ("reinstall", "missing-section", "altered-section"):
        reread = read_evidence(restored / "evidence/cases" / name)
        assert reread.status == ("passed" if passed else "failed")
        decoded = asdict(reread)
        decoded["preparation"] = reread.preparation.to_data()
        decoded["steps"] = [step.to_data() for step in reread.steps]
        assert decoded == saved[name]


def _assert_wrong_root_stops_after_first_command(result: dict[str, Any]) -> None:
    first, second = result["steps"]
    assert first["facts"]["command"]["exit_code"] == 0
    assert first["phase"] == "terminal"
    mismatches = first["facts"]["verification"]["mismatches"]
    assert any(
        mismatch["type"] == "missing_file"
        and mismatch["root"] == "project"
        and mismatch["path"] == ".synthetic/skills/package/SKILL.md"
        for mismatch in mismatches
    )
    assert any(
        mismatch["type"] == "unexpected_change"
        and mismatch["root"] == "home"
        and mismatch["path"] == ".synthetic/skills/package/SKILL.md"
        for mismatch in mismatches
    )
    assert second["phase"] == "idle"
    assert second["facts"]["command"] is None


def test_unavailable_case_reason_is_retained_in_campaign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yaml

    subject, spec, context = arrange(tmp_path)
    data = yaml.safe_load(spec.read_text())
    data["effects"] = [effect for effect in data["effects"] if effect["kind"] != "markdown-section"]
    spec.write_text(yaml.safe_dump(data))
    transport = ControlledTransport(tmp_path)

    def harness(**kwargs: object) -> ControlledTransport:
        return transport

    monkeypatch.setattr(coordinator, "ContainerHarness", harness)
    result = coordinator.InstallTestCoordinator().run_campaign(
        definition=load_campaign_definition(
            spec_file=spec, subject_context_file=context, subject_checkout=subject
        ),
        output_directory=tmp_path / "proof",
    )
    unavailable = next(case for case in result.cases if case.name == "missing-section")
    assert unavailable.state == "not_run"
    assert unavailable.not_run_reason == "Requires exactly one Markdown section effect"
    assert not result.passed
    saved = json.loads((tmp_path / "proof/campaign.json").read_text())
    assert saved["cases"][1]["not_run_reason"] == unavailable.not_run_reason
