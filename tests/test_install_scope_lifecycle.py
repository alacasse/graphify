"""Scope lifecycle tests for graphify install commands."""
import sys
from unittest.mock import patch

def test_install_project_claude_writes_project_scope(tmp_path, monkeypatch, capsys):
    from graphify.__main__ import main
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setattr(sys, "argv", ["graphify", "install", "--project"])
    with patch("graphify.__main__.Path.home", return_value=home):
        main()
    assert (project / ".claude" / "skills" / "graphify" / "SKILL.md").exists()
    assert (project / ".claude" / "CLAUDE.md").exists()
    assert not (home / ".claude" / "skills" / "graphify" / "SKILL.md").exists()
    assert ".claude/skills/graphify/SKILL.md" in (project / ".claude" / "CLAUDE.md").read_text()
    assert "~/.claude/skills/graphify/SKILL.md" not in (project / ".claude" / "CLAUDE.md").read_text()
    assert "git add .claude/" in capsys.readouterr().out


def test_install_project_codex_writes_skill_and_agents(tmp_path, monkeypatch):
    from graphify.__main__ import main
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setattr(sys, "argv", ["graphify", "install", "--project", "--platform", "codex"])
    with patch("graphify.__main__.Path.home", return_value=home):
        main()
    assert (project / ".codex" / "skills" / "graphify" / "SKILL.md").exists()
    assert (project / "AGENTS.md").exists()
    assert (project / ".codex" / "hooks.json").exists()
    assert not (home / ".codex" / "skills" / "graphify" / "SKILL.md").exists()


def test_install_project_agents_writes_project_skill_only(tmp_path, monkeypatch):
    from graphify.__main__ import main

    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setattr(sys, "argv", ["graphify", "install", "--project", "--platform", "agents"])
    with patch("graphify.__main__.Path.home", return_value=home):
        main()

    assert (project / ".agents" / "skills" / "graphify" / "SKILL.md").exists()
    assert not (project / "AGENTS.md").exists()
    assert not (home / ".agents" / "skills" / "graphify" / "SKILL.md").exists()


def test_install_project_codebuddy_writes_project_scope(tmp_path, monkeypatch):
    from graphify.__main__ import main
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setattr(sys, "argv", ["graphify", "install", "--project", "--platform", "codebuddy"])
    with patch("graphify.__main__.Path.home", return_value=home):
        main()
    assert (project / ".codebuddy" / "skills" / "graphify" / "SKILL.md").exists()
    assert (project / "CODEBUDDY.md").exists()
    assert (project / ".codebuddy" / "settings.json").exists()
    assert not (home / ".codebuddy" / "skills" / "graphify" / "SKILL.md").exists()


def test_codebuddy_subcommand_project_install_and_uninstall_are_project_scoped(tmp_path, monkeypatch):
    from graphify.__main__ import main
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    user_skill = home / ".codebuddy" / "skills" / "graphify" / "SKILL.md"
    user_skill.parent.mkdir(parents=True)
    user_skill.write_text("user skill")
    monkeypatch.chdir(project)
    with patch("graphify.__main__.Path.home", return_value=home):
        monkeypatch.setattr(sys, "argv", ["graphify", "codebuddy", "install"])
        main()
        assert (project / ".codebuddy" / "skills" / "graphify" / "SKILL.md").exists()
        assert (project / "CODEBUDDY.md").exists()
        assert (project / ".codebuddy" / "settings.json").exists()
        assert user_skill.exists()

        monkeypatch.setattr(sys, "argv", ["graphify", "codebuddy", "uninstall"])
        main()

    assert user_skill.exists()
    assert not (project / ".codebuddy" / "skills" / "graphify" / "SKILL.md").exists()
    assert not (project / "CODEBUDDY.md").exists()
    settings_path = project / ".codebuddy" / "settings.json"
    if settings_path.exists():
        assert "graphify" not in settings_path.read_text()


def test_claude_subcommand_project_install_and_uninstall_are_project_scoped(tmp_path, monkeypatch):
    from graphify.__main__ import main
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    user_skill = home / ".claude" / "skills" / "graphify" / "SKILL.md"
    user_skill.parent.mkdir(parents=True)
    user_skill.write_text("user skill")
    monkeypatch.chdir(project)
    with patch("graphify.__main__.Path.home", return_value=home):
        monkeypatch.setattr(sys, "argv", ["graphify", "claude", "install", "--project"])
        main()
        assert (project / ".claude" / "skills" / "graphify" / "SKILL.md").exists()
        assert (project / ".claude" / "CLAUDE.md").exists()
        assert (project / "CLAUDE.md").exists()
        assert user_skill.exists()

        monkeypatch.setattr(sys, "argv", ["graphify", "claude", "uninstall", "--project"])
        main()

    assert user_skill.exists()
    assert not (project / ".claude" / "skills" / "graphify" / "SKILL.md").exists()
    assert not (project / ".claude" / "CLAUDE.md").exists()
    assert not (project / "CLAUDE.md").exists()


def test_codex_subcommand_project_install_and_uninstall_are_project_scoped(tmp_path, monkeypatch):
    from graphify.__main__ import main
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    user_skill = home / ".codex" / "skills" / "graphify" / "SKILL.md"
    user_skill.parent.mkdir(parents=True)
    user_skill.write_text("user skill")
    monkeypatch.chdir(project)
    with patch("graphify.__main__.Path.home", return_value=home):
        monkeypatch.setattr(sys, "argv", ["graphify", "codex", "install", "--project"])
        main()
        assert (project / ".codex" / "skills" / "graphify" / "SKILL.md").exists()
        assert (project / "AGENTS.md").exists()
        assert (project / ".codex" / "hooks.json").exists()
        assert user_skill.exists()

        monkeypatch.setattr(sys, "argv", ["graphify", "codex", "uninstall", "--project"])
        main()

    assert user_skill.exists()
    assert not (project / ".codex" / "skills" / "graphify" / "SKILL.md").exists()
    assert not (project / "AGENTS.md").exists()
    hooks_path = project / ".codex" / "hooks.json"
    assert hooks_path.exists()
    assert "graphify" not in hooks_path.read_text()


def test_antigravity_install_project_writes_project_skill(tmp_path, monkeypatch):
    from graphify.__main__ import main
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setattr(sys, "argv", ["graphify", "antigravity", "install", "--project"])
    with patch("graphify.__main__.Path.home", return_value=home):
        main()
    assert (project / ".agents" / "skills" / "graphify" / "SKILL.md").exists()
    assert not (home / ".agents" / "skills" / "graphify" / "SKILL.md").exists()


def test_uninstall_project_removes_project_skill_only(tmp_path, monkeypatch):
    from graphify.__main__ import main
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    user_skill = home / ".codex" / "skills" / "graphify" / "SKILL.md"
    user_skill.parent.mkdir(parents=True)
    user_skill.write_text("user skill")
    monkeypatch.chdir(project)
    with patch("graphify.__main__.Path.home", return_value=home):
        monkeypatch.setattr(sys, "argv", ["graphify", "install", "--project", "--platform", "codex"])
        main()
        monkeypatch.setattr(sys, "argv", ["graphify", "uninstall", "--project", "--platform", "codex"])
        main()
    assert user_skill.exists()
    assert not (project / ".codex" / "skills" / "graphify" / "SKILL.md").exists()
    assert not (project / "AGENTS.md").exists()


def test_uninstall_project_without_platform_removes_project_installs(tmp_path, monkeypatch):
    from graphify.__main__ import main
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    user_skill = home / ".claude" / "skills" / "graphify" / "SKILL.md"
    user_skill.parent.mkdir(parents=True)
    user_skill.write_text("user skill")
    monkeypatch.chdir(project)
    with patch("graphify.__main__.Path.home", return_value=home):
        monkeypatch.setattr(sys, "argv", ["graphify", "install", "--project"])
        main()
        monkeypatch.setattr(sys, "argv", ["graphify", "uninstall", "--project"])
        main()
    assert user_skill.exists()
    assert not (project / ".claude" / "skills" / "graphify" / "SKILL.md").exists()
    assert not (project / ".claude" / "CLAUDE.md").exists()


def test_antigravity_uninstall_project_removes_project_skill_only(tmp_path, monkeypatch):
    from graphify.__main__ import main
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    # Global skill lives at ~/.gemini/config/skills/ (per #1079 fix)
    global_skill = home / ".gemini" / "config" / "skills" / "graphify" / "SKILL.md"
    global_skill.parent.mkdir(parents=True)
    global_skill.write_text("global skill")
    monkeypatch.chdir(project)
    with patch("graphify.__main__.Path.home", return_value=home):
        monkeypatch.setattr(sys, "argv", ["graphify", "antigravity", "install", "--project"])
        main()
        monkeypatch.setattr(sys, "argv", ["graphify", "antigravity", "uninstall", "--project"])
        main()
    assert global_skill.exists(), "project uninstall must not touch global skill"
    assert not (project / ".agents" / "skills" / "graphify" / "SKILL.md").exists()


def test_antigravity_global_install_writes_gemini_config_skills(tmp_path, monkeypatch):
    """Global `graphify antigravity install` must write to ~/.gemini/config/skills/ (#1079)."""
    from graphify.__main__ import main
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    with patch("graphify.__main__.Path.home", return_value=home):
        monkeypatch.setattr(sys, "argv", ["graphify", "antigravity", "install"])
        main()
    global_skill = home / ".gemini" / "config" / "skills" / "graphify" / "SKILL.md"
    wrong_skill = home / ".agents" / "skills" / "graphify" / "SKILL.md"
    assert global_skill.exists(), f"skill missing from correct global path {global_skill}"
    assert not wrong_skill.exists(), f"skill incorrectly written to {wrong_skill}"
    # rules + workflow go workspace-local, not in home
    assert (project / ".agents" / "rules" / "graphify.md").exists()
    assert (project / ".agents" / "workflows" / "graphify.md").exists()


def test_antigravity_global_uninstall_removes_gemini_config_skill(tmp_path, monkeypatch):
    """Global `graphify antigravity uninstall` must remove from ~/.gemini/config/skills/ (#1079)."""
    from graphify.__main__ import main
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    with patch("graphify.__main__.Path.home", return_value=home):
        monkeypatch.setattr(sys, "argv", ["graphify", "antigravity", "install"])
        main()
        global_skill = home / ".gemini" / "config" / "skills" / "graphify" / "SKILL.md"
        assert global_skill.exists(), "precondition: skill must exist before uninstall"
        monkeypatch.setattr(sys, "argv", ["graphify", "antigravity", "uninstall"])
        main()
    assert not global_skill.exists(), f"skill not removed from {global_skill} after uninstall"
    # workspace files also cleaned up
    assert not (project / ".agents" / "rules" / "graphify.md").exists()
    assert not (project / ".agents" / "workflows" / "graphify.md").exists()


def test_amp_user_install_lands_in_config_agents(tmp_path, monkeypatch):
    """`graphify amp install` (user scope) must drop the skill into an Amp search
    root: ~/.config/agents/skills, not the old ~/.amp/skills."""
    from graphify.__main__ import main

    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setattr(sys, "argv", ["graphify", "amp", "install"])
    with patch("graphify.__main__.Path.home", return_value=home):
        main()

    correct = home / ".config" / "agents" / "skills" / "graphify" / "SKILL.md"
    old = home / ".amp" / "skills" / "graphify" / "SKILL.md"
    assert correct.exists(), f"amp skill missing from Amp search root {correct}"
    assert not old.exists(), f"amp skill must not land at the unsearched {old}"
    # AGENTS.md still written in the project for the always-on rules.
    assert (project / "AGENTS.md").exists()


def test_amp_install_cleans_legacy_amp_skills_dir(tmp_path, monkeypatch):
    """A pre-fix ~/.amp/skills/graphify install is removed on the next install."""
    from graphify.__main__ import main

    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    legacy = home / ".amp" / "skills" / "graphify"
    legacy.mkdir(parents=True)
    (legacy / "SKILL.md").write_text("old amp skill", encoding="utf-8")
    monkeypatch.chdir(project)
    monkeypatch.setattr(sys, "argv", ["graphify", "amp", "install"])
    with patch("graphify.__main__.Path.home", return_value=home):
        main()

    assert not legacy.exists(), "legacy ~/.amp/skills/graphify should be cleaned up"
    assert (home / ".config" / "agents" / "skills" / "graphify" / "SKILL.md").exists()


def test_amp_user_uninstall_removes_skill_and_agents(tmp_path, monkeypatch):
    """`graphify amp uninstall` removes the user-scope skill and AGENTS.md section."""
    from graphify.__main__ import main

    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    with patch("graphify.__main__.Path.home", return_value=home):
        monkeypatch.setattr(sys, "argv", ["graphify", "amp", "install"])
        main()
        skill = home / ".config" / "agents" / "skills" / "graphify" / "SKILL.md"
        assert skill.exists()

        monkeypatch.setattr(sys, "argv", ["graphify", "amp", "uninstall"])
        main()

    assert not skill.exists()
    assert not (home / ".config" / "agents" / "skills").exists()
    assert not (project / "AGENTS.md").exists()


def test_amp_project_install_lands_in_dot_agents(tmp_path, monkeypatch):
    """Project-scope amp install lands in .agents/skills, an Amp project search root."""
    from graphify.__main__ import main

    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setattr(sys, "argv", ["graphify", "amp", "install", "--project"])
    with patch("graphify.__main__.Path.home", return_value=home):
        main()

    assert (project / ".agents" / "skills" / "graphify" / "SKILL.md").exists()
    assert not (project / ".amp" / "skills" / "graphify" / "SKILL.md").exists()
    assert (project / "AGENTS.md").exists()
    # User scope untouched.
    assert not (home / ".config" / "agents" / "skills" / "graphify" / "SKILL.md").exists()


def test_uninstall_all_removes_amp_user_skill(tmp_path, monkeypatch):
    """The user-scope `graphify uninstall` enumeration removes the amp skill."""
    from graphify.__main__ import main

    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    with patch("graphify.__main__.Path.home", return_value=home):
        monkeypatch.setattr(sys, "argv", ["graphify", "amp", "install"])
        main()
        skill = home / ".config" / "agents" / "skills" / "graphify" / "SKILL.md"
        assert skill.exists()

        monkeypatch.setattr(sys, "argv", ["graphify", "uninstall"])
        main()

    assert not skill.exists()
