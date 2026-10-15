"""Home skill backup preservation uses retained sources and independently checked evidence."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.codebuddy_support import (
    CodeBuddySkillBackupCase as SkillCase,
)
from tools.install_sandbox.container.environment import TestEnvironment as Environment
from tools.install_sandbox.contracts.results import SkillBackupPlan
from tools.install_sandbox.host.result_reader import read_result

_SKILL = ".codebuddy/skills/graphify/SKILL.md"
_SOURCE = b"# Synthetic skill\n"
_BACKUP = _SOURCE + b"\nSandbox previous backup witness.\n"


def test_home_skill_backup_survives_cleanup(tmp_path: Path) -> None:
    local = SkillCase(tmp_path)
    result = local.run()
    assert result.status == "passed", result
    assert len(local.calls) == 2
    assert (local.output / "steps/1/after/home" / _SKILL).read_bytes() == _SOURCE
    assert (local.output / "steps/1/after/home" / (_SKILL + ".bak")).read_bytes() == _BACKUP
    assert (
        local.output / "steps/1/after/project/.codebuddy/settings.json.graphify-bak"
    ).read_bytes() == (
        local.output / "steps/0/before/project/.codebuddy/settings.json"
    ).read_bytes()
    shutil.rmtree(tmp_path / "work")
    shutil.rmtree(tmp_path / "subject")
    assert read_result(local.output, local.retained_case()) == result


@pytest.mark.parametrize(
    "mode",
    [
        "missing-skill-backup",
        "wrong-skill-backup",
        "wrong-skill",
        "registry",
        "duplicate-hook",
        "wrong-reference",
        "wrong-version",
        "rolling-backup",
        "lost-personal",
        "json-format",
        "duplicate-markdown",
    ],
)
def test_home_skill_backup_rejects_incorrect_effects(tmp_path: Path, mode: str) -> None:
    local = SkillCase(tmp_path, mode)
    result = local.run()
    assert result.status == "failed", result
    assert len(local.calls) == 2
    assert read_result(local.output, local.retained_case()) == result


@pytest.mark.parametrize(
    "mode", ["no-change", "wrong-content", "skill", "wrong-root", "extra", "failure"]
)
def test_home_skill_preparation_blocks_second_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    original = Environment.prepare_skill_backup

    def prepare(environment: Environment, plan: SkillBackupPlan, content: bytes) -> str | None:
        if mode == "no-change":
            return None
        reason = original(environment, plan, content)
        skill = environment.home / _SKILL
        if mode == "wrong-content":
            Path(str(skill) + ".bak").write_bytes(b"Wrong\n")
        elif mode == "skill":
            skill.write_bytes(b"Unexpected\n")
        elif mode == "wrong-root":
            Path(str(skill) + ".bak").unlink()
            wrong = environment.project / (_SKILL + ".bak")
            wrong.parent.mkdir(parents=True, exist_ok=True)
            wrong.write_bytes(content)
        elif mode == "extra":
            (environment.home / "personal-notes.txt").write_bytes(b"Lost\n")
        return "Controlled failure" if mode == "failure" else reason

    monkeypatch.setattr(Environment, "prepare_skill_backup", prepare)
    local = SkillCase(tmp_path)
    result = local.run()
    assert result.status == "incomplete", result
    assert len(local.calls) == 1
    assert result.steps[1]["command"] is None
    assert read_result(local.output, local.retained_case()) == result


@pytest.mark.parametrize(
    "relative",
    [
        "steps/1/preparation/backup-content.bin",
        "steps/1/before/home/" + _SKILL,
        "steps/1/after/home/" + _SKILL + ".bak",
    ],
)
@pytest.mark.parametrize("missing", [False, True])
def test_home_skill_backup_requires_retained_evidence(
    tmp_path: Path, relative: str, missing: bool
) -> None:
    local = SkillCase(tmp_path)
    assert local.run().status == "passed"
    evidence = local.output / relative
    if missing:
        evidence.unlink()
    else:
        evidence.write_bytes(b"Tampered\n")
    with pytest.raises((ValueError, OSError)):
        read_result(local.output, local.retained_case())


def test_home_skill_first_failure_prevents_preparation(tmp_path: Path) -> None:
    local = SkillCase(tmp_path, "first-failure")
    result = local.run()
    assert result.status == "failed"
    assert len(local.calls) == 1
    assert "preparation" not in result.steps[1]
    assert read_result(local.output, local.retained_case()) == result


@pytest.mark.parametrize("stage", ["preparation", "final"])
def test_home_skill_unreadable_backup_is_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    local = SkillCase(tmp_path)
    original = Path.read_bytes

    def read(path: Path) -> bytes:
        if path == tmp_path / "work/environment/home" / (_SKILL + ".bak") and (
            stage == "preparation" or len(local.calls) == 2
        ):
            raise PermissionError("Controlled backup observation denied")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    result = local.run()
    assert result.status == "incomplete", result
    if stage == "preparation":
        preparation = result.steps[1].get("preparation")
        assert preparation is not None
        verification = preparation["verification"]
    else:
        verification = result.steps[1]["verification"]
    assert len(local.calls) == (1 if stage == "preparation" else 2)
    assert verification is not None and not verification.complete
    assert any(o["path"] == _SKILL + ".bak" for o in verification.obstacles)
    assert read_result(local.output, local.retained_case()) == result


@pytest.mark.parametrize("phase", ["steps/0/after", "steps/1/before", "steps/1/after"])
def test_home_backup_readback_rejects_self_consistent_false_success(
    tmp_path: Path, phase: str
) -> None:
    local = SkillCase(tmp_path)
    assert local.run().status == "passed"
    # Rebind the digest as well as bytes, leaving the claimed successful verdict intact.
    snapshot_file = local.output / (phase + ".json")
    snapshot = json.loads(snapshot_file.read_bytes())
    path = _SKILL + ".bak" if phase != "steps/0/after" else _SKILL
    entry = next(e for e in snapshot["entries"] if e["root"] == "home" and e["path"] == path)
    content = b"Self-consistent forged observation\n"
    (local.output / entry["content_file"]).write_bytes(content)
    entry["sha256"] = hashlib.sha256(content).hexdigest()
    snapshot_file.write_text(json.dumps(snapshot))
    with pytest.raises(ValueError, match="contradicts"):
        read_result(local.output, local.retained_case())
