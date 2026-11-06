"""User installation preserves independent project skill data and replays offline."""

import json
import shutil
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
import yaml

from tests.install_sandbox.component.host.native_support import ControlledTransport, arrange
from tools.install_sandbox.__main__ import main
from tools.install_sandbox.container.installer import InstallerCommandResult
from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.host import coordinator
from tools.install_sandbox.host.campaign_definition import load_campaign_definition
from tools.install_sandbox.host.effect_reader import EffectSpecReader
from tools.install_sandbox.host.result_reader import read_evidence


def arrange_user(root: Path) -> tuple[Path, Path, Path]:
    subject, spec, context = arrange(root, markdown=False, hooks=False)
    raw = yaml.safe_load(spec.read_text())
    raw["scope"] = "user"
    spec.write_text(yaml.safe_dump(raw))
    return subject, spec, context


def assert_project_witnesses(project: Path) -> None:
    skill = project / ".synthetic/skills/package"
    expected = {
        skill / "SKILL.md": b"# Project skill witness\nPreserve this project installation.\n",
        skill / ".graphify_version": b"project-witness-version\n",
        skill / "references/sandbox-project-witness.md": b"Project reference witness.\n",
        skill / "personal.txt": b"Personal project skill content.\n",
        project / "AGENTS.md": b"# Personal project instructions\nPreserve these instructions.\n",
    }
    for path, content in expected.items():
        assert path.read_bytes() == content


def run_user(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    damage_call: int = 0,
) -> tuple[int, dict[str, Any], Path]:
    subject, spec, context = arrange_user(root)
    transport = ControlledTransport(root, markdown=False, hooks=False)
    execute = transport.installer.execute

    def install(
        args: list[str],
        project: Path,
        environment: dict[str, str],
        timeout: float,
    ) -> InstallerCommandResult:
        if not transport.installer.calls:
            assert_project_witnesses(project)
        result = execute(args, project, environment, timeout)
        witness = project / ".synthetic/skills/package/SKILL.md"
        assert witness.is_file(), "Project skill must predate the first install"
        assert witness.read_bytes() != b"# Synthetic package\n"
        if len(transport.installer.calls) == damage_call:
            witness.unlink()
        return result

    transport.installer.execute = install
    monkeypatch.setattr(coordinator, "ContainerHarness", Mock(return_value=transport))
    output = root / "published"
    args = [
        "--repo",
        str(subject),
        "--spec",
        str(spec),
        "--subject-context",
        str(context),
        "--output",
        str(output),
    ]
    if damage_call:
        args.extend(["--case", "stale-version"])
    exit_code = main(args)
    shutil.rmtree(subject)
    spec.unlink()
    context.unlink()
    restored = root / "restored"
    with zipfile.ZipFile(output / "evidence.zip") as archive:
        archive.extractall(restored)
    return exit_code, json.loads((output / "campaign.json").read_text()), restored / "evidence"


def test_user_campaign_preserves_host_data_and_replays_without_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = tmp_path / "real-home/.synthetic/skills/package/SKILL.md"
    host.parent.mkdir(parents=True)
    host.write_bytes(b"Host skill is outside the disposable environment.\x00\n")
    original = host.read_bytes()
    monkeypatch.setenv("HOME", str(tmp_path / "real-home"))
    exit_code, report, evidence = run_user(tmp_path, monkeypatch)
    assert exit_code == 0 and report["passed"]
    assert host.read_bytes() == original
    saved = [entry for entry in report["cases"] if entry["construction"] == "constructed"]
    assert len(saved) == 8
    assert all(entry["result"]["test"]["case"]["scope"] == "user" for entry in saved)
    for entry in saved:
        reread = read_evidence(evidence / "cases" / entry["name"])
        decoded = asdict(reread)
        decoded["preparation"] = reread.preparation.to_data()
        decoded["steps"] = [step.to_data() for step in reread.steps]
        assert decoded == entry["result"]["test"]


@pytest.mark.parametrize("damage_call", [1, 2])
def test_user_false_success_cannot_remove_preexisting_project_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    damage_call: int,
) -> None:
    exit_code, report, evidence = run_user(tmp_path, monkeypatch, damage_call=damage_call)
    assert exit_code == 1 and not report["passed"]
    result = report["cases"][0]["result"]["test"]
    assert result["status"] == "failed"
    failed = result["steps"][damage_call - 1]
    assert failed["facts"]["command"]["exit_code"] == 0
    assert any(
        item["root"] == "project" and item["path"] == ".synthetic/skills/package/SKILL.md"
        for item in failed["facts"]["verification"]["mismatches"]
    )
    if damage_call == 1:
        assert result["steps"][1]["phase"] == "idle"
    assert read_evidence(evidence / "cases/stale-version").status == "failed"


@pytest.mark.parametrize("fault", ["case", "effects", "both", "result"])
def test_retained_user_evidence_rejects_forged_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    _, _, evidence = run_user(tmp_path, monkeypatch, damage_call=2)
    case = evidence / "cases/stale-version"
    path = case / ("result.json" if fault == "result" else "case.json")
    raw = json.loads(path.read_text())
    if fault == "result":
        raw["case"]["scope"] = "project"
    else:
        if fault in ("case", "both"):
            raw["scope"] = "project"
        if fault in ("effects", "both"):
            raw["effects"]["scope"] = "project"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        read_evidence(case)


@pytest.mark.parametrize("scope", ["global", "system", "", "USER"])
def test_invalid_scope_remains_rejected(tmp_path: Path, scope: str) -> None:
    _, spec, _ = arrange_user(tmp_path)
    raw = yaml.safe_load(spec.read_text())
    raw["scope"] = scope
    with pytest.raises(ValueError):
        EffectSpecReader().from_yaml(yaml.safe_dump(raw))


def test_case_scope_must_agree_with_effect_scope(tmp_path: Path) -> None:
    subject, spec, context = arrange_user(tmp_path)
    definition = load_campaign_definition(
        spec_file=spec,
        subject_context_file=context,
        subject_checkout=subject,
    )
    raw = json.loads(definition.built.cases[0].to_json())
    raw["scope"] = "project"
    with pytest.raises(ValueError):
        EffectInstallCase.from_json(json.dumps(raw))


@pytest.mark.parametrize("fault", ["project-destination", "markdown", "second-skill"])
def test_ordinary_user_campaign_rejects_effects_outside_single_skill_contract(
    tmp_path: Path,
    fault: str,
) -> None:
    subject, spec, context = arrange_user(tmp_path)
    raw = yaml.safe_load(spec.read_text())
    if fault == "project-destination":
        raw["effects"][0]["destination"]["root"] = "project"
    elif fault == "markdown":
        raw["effects"].append(
            {
                "kind": "markdown-section",
                "source": "instructions.md",
                "destination": {"root": "project", "path": "GUIDE.md"},
            }
        )
    else:
        raw["effects"].append(
            {
                "kind": "skill",
                "source": "package.md",
                "references": "reference-data",
                "destination": {"root": "home", "path": "another-skill"},
            }
        )
    spec.write_text(yaml.safe_dump(raw))
    reason = (
        "Multiple skill effects" if fault == "second-skill" else "User scope requires HOME skill"
    )
    with pytest.raises(ValueError, match=reason):
        load_campaign_definition(
            spec_file=spec,
            subject_context_file=context,
            subject_checkout=subject,
        )
