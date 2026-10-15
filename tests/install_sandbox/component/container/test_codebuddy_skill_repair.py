"""Home skill repair uses retained sources and independently checked evidence."""

import shutil
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.codebuddy_support import (
    CodeBuddySkillRepairCase as SkillCase,
)
from tools.install_sandbox.container.environment import TestEnvironment as Environment
from tools.install_sandbox.contracts.results import FileAlterationPlan
from tools.install_sandbox.host.result_reader import read_result

_SKILL = ".codebuddy/skills/graphify/SKILL.md"
_SOURCE = b"# Synthetic skill\n"
_ALTERED = _SOURCE + b"\nSandbox skill repair witness.\n"


def test_home_skill_repair_survives_cleanup(tmp_path: Path) -> None:
    local = SkillCase(tmp_path)
    result = local.run()
    assert result.status == "passed", result
    assert len(local.calls) == 2
    assert (local.output / "steps/1/after/home" / _SKILL).read_bytes() == _SOURCE
    assert (local.output / "steps/1/after/home" / (_SKILL + ".bak")).read_bytes() == _ALTERED
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
        "no-op",
        "only-backup",
        "missing-skill-backup",
        "wrong-skill-backup",
        "wrong-reference",
        "wrong-version",
        "rolling-backup",
        "lost-personal",
        "json-format",
        "duplicate-markdown",
    ],
)
def test_home_skill_repair_rejects_incorrect_effects(tmp_path: Path, mode: str) -> None:
    local = SkillCase(tmp_path, mode)
    result = local.run()
    assert result.status == "failed", result
    assert len(local.calls) == 2
    assert read_result(local.output, local.retained_case()) == result


@pytest.mark.parametrize("mode", ["no-change", "wrong-content", "backup", "extra", "failure"])
def test_home_skill_preparation_blocks_second_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    original = Environment.prepare_skill_repair

    def prepare(environment: Environment, plan: FileAlterationPlan, content: bytes) -> str | None:
        if mode == "no-change":
            return None
        reason = original(environment, plan, content)
        skill = environment.home / _SKILL
        if mode == "wrong-content":
            skill.write_bytes(b"Wrong\n")
        elif mode == "backup":
            Path(str(skill) + ".bak").write_bytes(b"Unexpected\n")
        elif mode == "extra":
            (environment.home / "personal-notes.txt").write_bytes(b"Lost\n")
        return "Controlled failure" if mode == "failure" else reason

    monkeypatch.setattr(Environment, "prepare_skill_repair", prepare)
    local = SkillCase(tmp_path)
    result = local.run()
    assert result.status == "incomplete", result
    assert len(local.calls) == 1
    assert result.steps[1]["command"] is None
    assert read_result(local.output, local.retained_case()) == result


@pytest.mark.parametrize(
    "relative",
    [
        "steps/1/preparation/altered-content.bin",
        "steps/1/before/home/" + _SKILL,
        "steps/1/after/home/" + _SKILL + ".bak",
    ],
)
@pytest.mark.parametrize("missing", [False, True])
def test_home_skill_repair_requires_retained_evidence(
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


def test_home_skill_unreadable_backup_is_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = SkillCase(tmp_path)
    original = Path.read_bytes

    def read(path: Path) -> bytes:
        if path == tmp_path / "work/environment/home" / (_SKILL + ".bak"):
            raise PermissionError("Controlled backup observation denied")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    result = local.run()
    assert result.status == "incomplete", result
    verification = result.steps[1]["verification"]
    assert verification is not None and not verification.complete
    assert any(o["path"] == _SKILL + ".bak" for o in verification.obstacles)
    assert read_result(local.output, local.retained_case()) == result
