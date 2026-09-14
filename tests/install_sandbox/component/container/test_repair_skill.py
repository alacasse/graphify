"""Skill repair through the coordinator, literal controlled effects and real verification."""

import json
import shutil
from dataclasses import asdict
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.repair_skill_support import (
    ALTERED,
    SKILL,
    SOURCE,
    arrange_skill,
    run_skill,
)
from tools.install_sandbox.contracts.case import InstallTestCase
from tools.install_sandbox.host.result_reader import read_result


def test_skill_and_backup_proofs_survive_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange_skill(tmp_path, monkeypatch)
    original = {str(p): p.read_bytes() for p in (tmp_path / "subject").rglob("*") if p.is_file()}
    result = run_skill(tmp_path)
    assert result.passed and result.test is not None, asdict(result)
    assert original == {
        str(p): p.read_bytes() for p in (tmp_path / "subject").rglob("*") if p.is_file()
    }
    assert (tmp_path / "work/repair-skill/command-tmp/attempts").read_text() == "2"
    output = result.output_directory
    assert "inherited from campaign" in (output / "preparation.log").read_text()
    assert (output / "steps/0/after/project" / SKILL).read_bytes() == SOURCE
    assert (output / "steps/1/before/project" / SKILL).read_bytes() == ALTERED
    assert (output / "steps/1/after/project" / SKILL).read_bytes() == SOURCE
    assert (output / "steps/1/after/project" / (SKILL + ".bak")).read_bytes() == ALTERED
    assert (output / "steps/1/preparation/altered-content.bin").read_bytes() == ALTERED
    assert (output / "expected/graphify/skill.md").read_bytes() == SOURCE
    prep = result.test.steps[1].get("preparation")
    assert prep is not None and prep["ready"] and "deleted_path" not in prep["plan"]
    for phase in ("steps/0/after", "steps/1/before"):
        snapshot = json.loads((output / (phase + ".json")).read_bytes())
        assert not any(e["path"] == SKILL + ".bak" for e in snapshot["entries"])
    case = InstallTestCase.from_json((tmp_path / "campaign/inputs/repair-skill.json").read_text())
    shutil.rmtree(tmp_path / "work/repair-skill")
    shutil.rmtree(tmp_path / "subject")
    assert read_result(output, case) == result.test


@pytest.mark.parametrize(
    "mode,status,mismatch",
    [
        ("absent", "failed", "content_mismatch"),
        ("only_backup", "failed", "content_mismatch"),
        ("no_backup", "failed", "missing_file"),
        ("wrong_backup", "failed", "content_mismatch"),
        ("nonzero", "failed", None),
        ("signal", "incomplete", "missing_file"),
        ("timeout", "incomplete", "missing_file"),
        ("not_started", "incomplete", "missing_file"),
        ("version", "failed", "version_changed"),
        ("home", "failed", "unexpected_change"),
        ("extra_backup", "failed", "unexpected_change"),
        ("user_loss", "failed", "unexpected_change"),
        ("missing_reference", "failed", "missing_file"),
        ("duplicate_json", "failed", "json_entry_count"),
    ],
)
def test_incorrect_repair_retains_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    status: str,
    mismatch: str | None,
) -> None:
    arrange_skill(tmp_path, monkeypatch, mode)
    result = run_skill(tmp_path)
    assert result.test is not None and result.result_error is None, asdict(result)
    assert not result.passed and result.test.status == status
    verification = result.test.steps[1]["verification"]
    assert verification is not None and verification.complete
    assert not verification.obstacles
    if mismatch:
        assert mismatch in {m.type for m in verification.mismatches}
    else:
        assert not verification.mismatches
    assert (tmp_path / "campaign/cases/repair-skill/steps/1/after.json").exists()


@pytest.mark.parametrize(
    "mode",
    ["write_failure", "wrong_content", "no_change", "extra_change", "backup_created", "unreadable"],
)
def test_bad_preparation_blocks_second_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    arrange_skill(tmp_path, monkeypatch)
    monkeypatch.setenv("CONTROLLED_SKILL_PREPARATION", mode)
    result = run_skill(tmp_path)
    assert result.test is not None and result.result_error is None, asdict(result)
    assert not result.passed and result.test.status == "incomplete"
    assert (tmp_path / "work/repair-skill/command-tmp/attempts").read_text() == "1"
    step = result.test.steps[1]
    assert step["command"] is None and step["verification"] is None and step["observations"] is None
    prep = step.get("preparation")
    assert prep is not None and not prep["ready"] and prep["reason"] == step["skip_reason"]
    assert prep["verification"].complete == (mode != "unreadable")
    assert (
        prep["verification"].obstacles if mode == "unreadable" else prep["verification"].mismatches
    )
    assert not (tmp_path / "campaign/cases/repair-skill/steps/1/stdout.txt").exists()
    if mode == "write_failure":
        assert (
            tmp_path / "campaign/cases/repair-skill/steps/1/before/project" / SKILL
        ).read_bytes() == b"Partial skill write\n"


@pytest.mark.parametrize("mode", ["first_failure", "first_backup"])
def test_first_failure_prevents_alteration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    arrange_skill(tmp_path, monkeypatch, mode)
    result = run_skill(tmp_path)
    assert result.test is not None and result.result_error is None, asdict(result)
    assert result.test.status == "failed" and not result.passed
    assert "preparation" not in result.test.steps[1]
    assert not (tmp_path / "campaign/cases/repair-skill/steps/1").exists()


def test_unreadable_backup_is_incomplete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    arrange_skill(tmp_path, monkeypatch)
    monkeypatch.setenv("CONTROLLED_SKILL_PREPARATION", "backup_unreadable")
    result = run_skill(tmp_path)
    assert result.test is not None and result.result_error is None, asdict(result)
    assert not result.passed and result.test.status == "incomplete"
    verification = result.test.steps[1]["verification"]
    assert verification is not None and not verification.complete
    assert any(o["path"] == SKILL + ".bak" for o in verification.obstacles)
