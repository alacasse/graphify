"""Route smoke tests for graphify install commands."""
import sys
from unittest.mock import patch

import pytest

from tests.install_test_support import install_in_tmp as _install


PLATFORMS = {
    "claude": (".claude/skills/graphify/SKILL.md",),
    "codebuddy": (".codebuddy/skills/graphify/SKILL.md",),
    "codex": (".codex/skills/graphify/SKILL.md",),
    "opencode": (".config/opencode/skills/graphify/SKILL.md",),
    "kilo": (
        ".config/kilo/skills/graphify/SKILL.md",
        ".config/kilo/command/graphify.md",
    ),
    "claw": (".openclaw/skills/graphify/SKILL.md",),
    "droid": (".factory/skills/graphify/SKILL.md",),
    "trae": (".trae/skills/graphify/SKILL.md",),
    "trae-cn": (".trae-cn/skills/graphify/SKILL.md",),
    "windows": (".claude/skills/graphify/SKILL.md",),
}


def test_install_default_claude(tmp_path):
    _install(tmp_path, "claude")
    assert (tmp_path / ".claude" / "skills" / "graphify" / "SKILL.md").exists()


def test_install_codebuddy(tmp_path):
    _install(tmp_path, "codebuddy")
    assert (tmp_path / ".codebuddy" / "skills" / "graphify" / "SKILL.md").exists()
    assert (tmp_path / ".codebuddy" / "CODEBUDDY.md").exists()
    assert (tmp_path / ".codebuddy" / "settings.json").exists()


def test_install_codex(tmp_path):
    _install(tmp_path, "codex")
    assert (tmp_path / ".codex" / "skills" / "graphify" / "SKILL.md").exists()


@pytest.mark.parametrize("platform", ["agents", "skills"])
def test_install_agents_user_scope_lands_in_agent_skills_not_amp(tmp_path, platform):
    _install(tmp_path, platform)
    assert (tmp_path / ".agents" / "skills" / "graphify" / "SKILL.md").exists()
    assert not (tmp_path / ".config" / "agents" / "skills" / "graphify" / "SKILL.md").exists()


def test_install_opencode(tmp_path):
    _install(tmp_path, "opencode")
    assert (
        tmp_path / ".config" / "opencode" / "skills" / "graphify" / "SKILL.md"
    ).exists()


def test_install_positional_platform_opencode(tmp_path, monkeypatch):
    from graphify.__main__ import main

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["graphify", "install", "opencode"])
    with patch("graphify.__main__.Path.home", return_value=tmp_path):
        main()
    assert (tmp_path / ".config" / "opencode" / "skills" / "graphify" / "SKILL.md").exists()
    assert not (tmp_path / ".claude" / "skills" / "graphify" / "SKILL.md").exists()


def test_install_help_does_not_install_default(tmp_path, monkeypatch, capsys):
    from graphify.__main__ import main

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["graphify", "install", "opencode", "--help"])
    with patch("graphify.__main__.Path.home", return_value=tmp_path):
        main()
    out = capsys.readouterr().out
    assert "Usage: graphify install" in out
    assert "opencode" in out
    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / ".config").exists()


def test_install_claw(tmp_path):
    _install(tmp_path, "claw")
    assert (tmp_path / ".openclaw" / "skills" / "graphify" / "SKILL.md").exists()


def test_install_droid(tmp_path):
    _install(tmp_path, "droid")
    assert (tmp_path / ".factory" / "skills" / "graphify" / "SKILL.md").exists()


def test_install_trae(tmp_path):
    _install(tmp_path, "trae")
    assert (tmp_path / ".trae" / "skills" / "graphify" / "SKILL.md").exists()


def test_install_trae_cn(tmp_path):
    _install(tmp_path, "trae-cn")
    assert (tmp_path / ".trae-cn" / "skills" / "graphify" / "SKILL.md").exists()


def test_install_windows(tmp_path):
    _install(tmp_path, "windows")
    assert (tmp_path / ".claude" / "skills" / "graphify" / "SKILL.md").exists()


def test_install_unknown_platform_exits(tmp_path):
    with pytest.raises(SystemExit):
        _install(tmp_path, "unknown")
