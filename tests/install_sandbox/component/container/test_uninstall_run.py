"""Uninstall needs its own command and independent removal and preservation checks."""

from pathlib import Path

import pytest

from tests.install_sandbox.component.container.uninstall_support import conduct_uninstall


def test_agents_uninstall_removes_skill_and_replays_after_workspace_cleanup(tmp_path: Path) -> None:
    result, calls = conduct_uninstall(tmp_path)
    assert result.status == "passed" and len(calls) == 2
    assert not (tmp_path / "work").exists() and not (tmp_path / "subject").exists()
    project = tmp_path / "proof/steps/1/after/project"
    skill = project / ".agents/skills/graphify"
    assert skill.is_dir()
    assert not (skill / "SKILL.md").exists()
    assert not (skill / ".graphify_version").exists()
    assert not (skill / "references").exists()
    assert (skill / "personal.txt").read_bytes() == b"Personal project skill content.\n"
    assert (skill / "SKILL.md.bak").read_bytes() == b"Personal previous skill backup.\n"
    assert (
        project / "graphify-out/personal.txt"
    ).read_bytes() == b"Personal graph output witness.\n"
    assert (project / ".agents/skills/personal-effect-0.txt").read_bytes() == (
        b"Personal document to preserve.\n"
    )


@pytest.mark.parametrize(
    "fault",
    [
        "uninstall-false-success",
        "personal",
        "skill-personal",
        "backup",
        "graph-output",
        "user-skill",
    ],
)
def test_exit_zero_cannot_hide_failed_removal_or_personal_file_damage(
    tmp_path: Path, fault: str
) -> None:
    result, calls = conduct_uninstall(tmp_path, fault=fault)
    assert result.status == "failed" and len(calls) == 2
    verification = result.steps[1].verification
    assert verification is not None and verification.complete and verification.mismatches
    paths = {(item.root, item.path) for item in verification.mismatches}
    if fault == "uninstall-false-success":
        assert ("project", ".agents/skills/graphify/SKILL.md") in paths
    else:
        expected_path = {
            "personal": ".agents/skills/personal-effect-0.txt",
            "skill-personal": ".agents/skills/graphify/personal.txt",
            "backup": ".agents/skills/graphify/SKILL.md.bak",
            "graph-output": "graphify-out/personal.txt",
            "user-skill": ".agents/skills/graphify/SKILL.md",
        }[fault]
        assert paths == {("home" if fault == "user-skill" else "project", expected_path)}


@pytest.mark.parametrize("fault", ["install-exit", "install-false-success"])
def test_failed_first_install_blocks_uninstall(tmp_path: Path, fault: str) -> None:
    result, calls = conduct_uninstall(tmp_path, fault=fault)
    assert result.status == "failed" and len(calls) == 1
    assert result.steps[1].phase == "idle"
