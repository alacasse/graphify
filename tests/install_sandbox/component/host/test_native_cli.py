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


@pytest.mark.parametrize(("hooks", "wrong_skill"), [(False, False), (True, False), (False, True)])
def test_campaign_without_markdown_preserves_effects_and_replays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hooks: bool, wrong_skill: bool
) -> None:
    subject, spec, context = arrange(tmp_path, markdown=False, hooks=hooks, skill_root="project")
    transport = ControlledTransport(
        tmp_path,
        markdown=False,
        hooks=hooks,
        skill_root="home" if wrong_skill else "project",
    )
    _assert_partial_campaign(
        tmp_path,
        monkeypatch,
        subject,
        spec,
        context,
        transport,
        construction="not_applicable",
        reason="No Markdown effect declared",
        passed=not wrong_skill,
        calls=1 if wrong_skill else 2,
    )


def test_multiple_markdown_campaign_runs_reinstall_and_reports_builder_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import copy

    import yaml

    subject, spec, context = arrange(tmp_path, markdown_only=True)
    data = yaml.safe_load(spec.read_text())
    second = copy.deepcopy(data["effects"][0])
    second["destination"]["path"] = "SECOND.md"
    second["source"] = "second-instructions.md"
    data["effects"].append(second)
    spec.write_text(yaml.safe_dump(data))
    (subject / "second-instructions.md").write_text("## graphify\nSecond synthetic map.\n")
    transport = ControlledTransport(tmp_path, markdown_only=True)
    execute = transport.installer.execute

    def install_two(
        args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> Any:
        result = execute(args, project, environment, timeout)
        document = project / "SECOND.md"
        content = document.read_text()
        section = "## graphify\nSecond synthetic map.\n"
        if "Replace this placeholder." in content:
            document.write_text(
                content.replace("## graphify\nReplace this placeholder.\n\n", section)
            )
        elif "## graphify" not in content:
            document.write_text(content + "\n" + section)
        return result

    transport.installer.execute = install_two
    _assert_partial_campaign(
        tmp_path,
        monkeypatch,
        subject,
        spec,
        context,
        transport,
        construction="unconstructible",
        reason="The case builder currently supports only one Markdown effect",
        passed=False,
        calls=2,
    )


def _assert_partial_campaign(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    subject: Path,
    spec: Path,
    context: Path,
    transport: ControlledTransport,
    *,
    construction: str,
    reason: str,
    passed: bool,
    calls: int,
) -> None:
    def harness(**kwargs: object) -> ControlledTransport:
        return transport

    monkeypatch.setattr(coordinator, "ContainerHarness", harness)
    output = root / "published"
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
    assert len(transport.installer.calls) == calls
    report = json.loads((output / "campaign.json").read_text())
    external_text = (output / "campaign.txt").read_text()
    assert report["version"] == 3
    assert report["passed"] is passed
    first, *repairs = report["cases"]
    expected_status = "failed" if calls == 1 else "passed"
    assert first["result"]["test"]["status"] == expected_status
    if calls == 1:
        _assert_wrong_root_stops_after_first_command(first["result"]["test"])
    assert [case["name"] for case in repairs] == ["missing-section", "altered-section"]
    for case in repairs:
        assert case["construction"] == construction
        assert case["construction_reason"] == reason
        assert all(case[field] is None for field in ("state", "result", "output_directory"))
    shutil.rmtree(subject)
    spec.unlink()
    context.unlink()
    assert not transport.executable.exists()
    assert not (root / "environment").exists()
    _assert_archived_partial_campaign(root, output, report, external_text, construction, reason)


def _assert_archived_partial_campaign(
    root: Path,
    output: Path,
    report: dict[str, Any],
    external_text: str,
    construction: str,
    reason: str,
) -> None:
    first, *repairs = report["cases"]
    restored = root / "restored"
    with zipfile.ZipFile(output / "evidence.zip") as archive:
        archive.extractall(restored)
        names = archive.namelist()
    archived = json.loads((restored / "evidence/campaign.json").read_text())
    assert archived["version"] == 3
    assert archived["cases"][1:] == repairs
    archived_text = (restored / "evidence/campaign.txt").read_text()
    label = (
        "not applicable" if construction == "not_applicable" else "applicable but not constructible"
    )
    for text in (external_text, archived_text):
        assert label in text and reason in text
    assert not any(
        name.startswith(f"evidence/cases/{case['name']}")
        or name == f"evidence/inputs/{case['name']}.json"
        for case in repairs
        for name in names
    )
    reread = read_evidence(restored / "evidence/cases/reinstall")
    decoded = asdict(reread)
    decoded["preparation"] = reread.preparation.to_data()
    decoded["steps"] = [step.to_data() for step in reread.steps]
    assert decoded == first["result"]["test"]
