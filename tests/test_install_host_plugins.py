"""Host plugin, config, hook, and rule install tests for graphify install."""

import json
import re
from unittest.mock import patch

from tests.install_test_support import (
    agents_install as _agents_install,
    agents_uninstall as _agents_uninstall,
)


# --- CodeBuddy CODEBUDDY.md + hook install/uninstall tests ---


def test_codebuddy_install_writes_codebuddy_md(tmp_path):
    from graphify.__main__ import codebuddy_install

    codebuddy_install(tmp_path)
    md = tmp_path / "CODEBUDDY.md"
    assert md.exists()
    assert "graphify-out/GRAPH_REPORT.md" in md.read_text()


def test_codebuddy_install_writes_hook(tmp_path):
    from graphify.__main__ import codebuddy_install

    codebuddy_install(tmp_path)
    settings = json.loads((tmp_path / ".codebuddy" / "settings.json").read_text())
    hooks = settings["hooks"]["PreToolUse"]
    assert any("graphify" in str(h) for h in hooks)


def test_codebuddy_install_idempotent(tmp_path):
    from graphify.__main__ import codebuddy_install

    codebuddy_install(tmp_path)
    codebuddy_install(tmp_path)
    md = tmp_path / "CODEBUDDY.md"
    assert md.read_text().count("## graphify") == 1


def test_codebuddy_install_merges_existing_codebuddy_md(tmp_path):
    from graphify.__main__ import codebuddy_install

    (tmp_path / "CODEBUDDY.md").write_text("# My project rules\n")
    codebuddy_install(tmp_path)
    content = (tmp_path / "CODEBUDDY.md").read_text()
    assert "# My project rules" in content
    assert "graphify-out/GRAPH_REPORT.md" in content


def test_codebuddy_uninstall_removes_section(tmp_path):
    from graphify.__main__ import codebuddy_install, codebuddy_uninstall

    codebuddy_install(tmp_path)
    codebuddy_uninstall(tmp_path)
    md = tmp_path / "CODEBUDDY.md"
    assert not md.exists()


def test_codebuddy_uninstall_removes_hook(tmp_path):
    from graphify.__main__ import codebuddy_install, codebuddy_uninstall

    codebuddy_install(tmp_path)
    codebuddy_uninstall(tmp_path)
    settings_path = tmp_path / ".codebuddy" / "settings.json"
    if settings_path.exists():
        settings = json.loads(settings_path.read_text())
        hooks = settings.get("hooks", {}).get("PreToolUse", [])
        assert not any("graphify" in str(h) for h in hooks)


def test_codebuddy_uninstall_noop_if_not_installed(tmp_path):
    from graphify.__main__ import codebuddy_uninstall

    codebuddy_uninstall(tmp_path)  # should not raise


def _kilo_install(project_dir, home_dir):
    from graphify.__main__ import _kilo_install as _install_fn

    with patch("graphify.__main__.Path.home", return_value=home_dir):
        _install_fn(project_dir)


def _kilo_uninstall(project_dir, home_dir):
    from graphify.__main__ import _kilo_uninstall as _uninstall_fn

    with patch("graphify.__main__.Path.home", return_value=home_dir):
        _uninstall_fn(project_dir)


# --- OpenCode plugin tests ---


def test_opencode_agents_install_writes_plugin(tmp_path):
    """opencode install writes .opencode/plugins/graphify.js."""
    _agents_install(tmp_path, "opencode")
    plugin = tmp_path / ".opencode" / "plugins" / "graphify.js"
    assert plugin.exists()
    assert "tool.execute.before" in plugin.read_text()


def test_opencode_plugin_reminder_has_no_backticks(tmp_path):
    """The bash reminder string must not contain backticks or $(...) (regression test for #1413).

    The plugin prepends `echo "<reminder>" && <cmd>` to the user's bash command.
    Backticks or $() inside the reminder trigger bash command substitution
    when the echo runs, which both corrupts tool output and silently executes
    the very graphify command we are only suggesting.
    """
    _agents_install(tmp_path, "opencode")
    plugin = tmp_path / ".opencode" / "plugins" / "graphify.js"
    body = plugin.read_text()
    # Extract the echoed reminder string literal between the double-quotes
    # of the `output.args.command = 'echo "..." && ' +` line.
    m = re.search(r'echo "([^"]*)"', body)
    assert m, "echo reminder not found in plugin body"
    reminder = m.group(1)
    assert "`" not in reminder, f"backtick in reminder would trigger command substitution: {reminder!r}"
    assert "$(" not in reminder, f"$() in reminder would trigger command substitution: {reminder!r}"


def test_opencode_agents_install_registers_plugin_in_config(tmp_path):
    """opencode install registers the plugin in .opencode/opencode.json."""
    _agents_install(tmp_path, "opencode")
    config_file = tmp_path / ".opencode" / "opencode.json"
    assert config_file.exists()
    config = json.loads(config_file.read_text())
    assert any("graphify.js" in p for p in config.get("plugin", []))


def test_opencode_agents_install_merges_existing_config(tmp_path):
    """opencode install preserves existing .opencode/opencode.json keys."""
    config_file = tmp_path / ".opencode" / "opencode.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps({"model": "claude-opus-4-5", "plugin": []}))
    _agents_install(tmp_path, "opencode")
    config = json.loads(config_file.read_text())
    assert config["model"] == "claude-opus-4-5"
    assert any("graphify.js" in p for p in config["plugin"])


def test_opencode_agents_uninstall_removes_plugin(tmp_path):
    """opencode uninstall removes the plugin file and deregisters from opencode.json."""
    _agents_install(tmp_path, "opencode")
    _agents_uninstall(tmp_path, platform="opencode")
    plugin = tmp_path / ".opencode" / "plugins" / "graphify.js"
    assert not plugin.exists()
    config_file = tmp_path / ".opencode" / "opencode.json"
    if config_file.exists():
        config = json.loads(config_file.read_text())
        assert not any("graphify.js" in p for p in config.get("plugin", []))


def test_kilo_agents_install_writes_plugin(tmp_path):
    _agents_install(tmp_path, "kilo")
    plugin = tmp_path / ".kilo" / "plugins" / "graphify.js"
    assert plugin.exists()
    assert "tool.execute.before" in plugin.read_text()


def test_kilo_agents_install_registers_plugin_in_config(tmp_path):
    _agents_install(tmp_path, "kilo")
    config_file = tmp_path / ".kilo" / "kilo.json"
    assert config_file.exists()
    config = json.loads(config_file.read_text())
    assert (
        tmp_path / ".kilo" / "plugins" / "graphify.js"
    ).resolve().as_uri() in config.get("plugin", [])


def test_kilo_agents_install_merges_existing_config(tmp_path):
    config_file = tmp_path / ".kilo" / "kilo.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        json.dumps({"model": "anthropic/claude-sonnet", "plugin": []})
    )
    _agents_install(tmp_path, "kilo")
    config = json.loads(config_file.read_text())
    assert config["model"] == "anthropic/claude-sonnet"
    assert (
        tmp_path / ".kilo" / "plugins" / "graphify.js"
    ).resolve().as_uri() in config["plugin"]


def test_kilo_agents_install_preserves_existing_jsonc_config(tmp_path):
    config_file = tmp_path / ".kilo" / "kilo.jsonc"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    original = """// user comment\n{\n  // preferred model\n  \"model\": \"anthropic/claude-haiku\",\n  \"plugin\": []\n}\n"""
    config_file.write_text(original)
    _agents_install(tmp_path, "kilo")
    json_file = tmp_path / ".kilo" / "kilo.json"
    config = json.loads(json_file.read_text())
    assert config["model"] == "anthropic/claude-haiku"
    assert (
        tmp_path / ".kilo" / "plugins" / "graphify.js"
    ).resolve().as_uri() in config["plugin"]
    assert config_file.read_text() == original


def test_kilo_agents_uninstall_preserves_existing_jsonc_config(tmp_path):
    config_file = tmp_path / ".kilo" / "kilo.jsonc"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    original = """// user comment\n{\n  \"model\": \"anthropic/claude-haiku\",\n  \"plugin\": []\n}\n"""
    config_file.write_text(original)

    _agents_install(tmp_path, "kilo")
    _agents_uninstall(tmp_path, platform="kilo")

    json_file = tmp_path / ".kilo" / "kilo.json"
    config = json.loads(json_file.read_text())
    assert config_file.read_text() == original
    assert (
        tmp_path / ".kilo" / "plugins" / "graphify.js"
    ).resolve().as_uri() not in config.get("plugin", [])


def test_kilo_agents_install_idempotent(tmp_path):
    _agents_install(tmp_path, "kilo")
    _agents_install(tmp_path, "kilo")
    content = (tmp_path / "AGENTS.md").read_text()
    config = json.loads((tmp_path / ".kilo" / "kilo.json").read_text())
    plugin_uri = (tmp_path / ".kilo" / "plugins" / "graphify.js").resolve().as_uri()
    assert content.count("## graphify") == 1
    assert config["plugin"].count(plugin_uri) == 1


def test_kilo_install_writes_global_and_project_artifacts(tmp_path):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home_dir.mkdir()
    _kilo_install(project_dir, home_dir)
    assert (home_dir / ".config" / "kilo" / "skills" / "graphify" / "SKILL.md").exists()
    assert (home_dir / ".config" / "kilo" / "command" / "graphify.md").exists()
    assert (project_dir / "AGENTS.md").exists()
    assert (project_dir / ".kilo" / "plugins" / "graphify.js").exists()


def test_kilo_uninstall_removes_plugin_registration_and_command(tmp_path):
    home_dir = tmp_path / "home"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home_dir.mkdir()
    _kilo_install(project_dir, home_dir)
    skill_dir = home_dir / ".config" / "kilo" / "skills" / "graphify"
    assert (skill_dir / "references").is_dir()
    refs_tmp = skill_dir / "references.tmp"
    refs_tmp.mkdir()
    (refs_tmp / "partial.md").write_text("partial staged reference", encoding="utf-8")
    _kilo_uninstall(project_dir, home_dir)
    assert not (home_dir / ".config" / "kilo" / "command" / "graphify.md").exists()
    assert not (
        skill_dir / "SKILL.md"
    ).exists()
    assert not skill_dir.exists()
    assert not (project_dir / ".kilo" / "plugins" / "graphify.js").exists()
    config_file = project_dir / ".kilo" / "kilo.json"
    if config_file.exists():
        config = json.loads(config_file.read_text())
        assert (
            project_dir / ".kilo" / "plugins" / "graphify.js"
        ).resolve().as_uri() not in config.get("plugin", [])


# -- Cursor -------------------------------------------------------------------


def test_cursor_install_writes_rule(tmp_path):
    """cursor install writes .cursor/rules/graphify.mdc."""
    from graphify.__main__ import _cursor_install

    _cursor_install(tmp_path)
    rule = tmp_path / ".cursor" / "rules" / "graphify.mdc"
    assert rule.exists()
    content = rule.read_text()
    assert "alwaysApply: true" in content
    assert "graphify-out/GRAPH_REPORT.md" in content


def test_cursor_install_idempotent(tmp_path):
    """cursor install does not overwrite an existing rule file."""
    from graphify.__main__ import _cursor_install

    _cursor_install(tmp_path)
    rule = tmp_path / ".cursor" / "rules" / "graphify.mdc"
    original = rule.read_text()
    _cursor_install(tmp_path)
    assert rule.read_text() == original


def test_cursor_uninstall_removes_rule(tmp_path):
    """cursor uninstall removes the rule file."""
    from graphify.__main__ import _cursor_install, _cursor_uninstall

    _cursor_install(tmp_path)
    _cursor_uninstall(tmp_path)
    rule = tmp_path / ".cursor" / "rules" / "graphify.mdc"
    assert not rule.exists()


def test_cursor_uninstall_noop_if_not_installed(tmp_path):
    """cursor uninstall does nothing if rule was never written."""
    from graphify.__main__ import _cursor_uninstall

    _cursor_uninstall(tmp_path)  # should not raise


# -- Gemini CLI ---------------------------------------------------------------


def test_gemini_install_writes_gemini_md(tmp_path):
    from graphify.__main__ import gemini_install

    gemini_install(tmp_path)
    md = tmp_path / "GEMINI.md"
    assert md.exists()
    assert "graphify-out/GRAPH_REPORT.md" in md.read_text()


def test_gemini_install_writes_hook(tmp_path):
    from graphify.__main__ import gemini_install

    gemini_install(tmp_path)
    settings = json.loads((tmp_path / ".gemini" / "settings.json").read_text())
    hooks = settings["hooks"]["BeforeTool"]
    assert any("graphify" in str(h) for h in hooks)


def test_gemini_install_idempotent(tmp_path):
    from graphify.__main__ import gemini_install

    gemini_install(tmp_path)
    gemini_install(tmp_path)
    md = tmp_path / "GEMINI.md"
    assert md.read_text().count("## graphify") == 1


def test_gemini_install_merges_existing_gemini_md(tmp_path):
    from graphify.__main__ import gemini_install

    (tmp_path / "GEMINI.md").write_text("# My project rules\n")
    gemini_install(tmp_path)
    content = (tmp_path / "GEMINI.md").read_text()
    assert "# My project rules" in content
    assert "graphify-out/GRAPH_REPORT.md" in content


def test_gemini_uninstall_removes_section(tmp_path):
    from graphify.__main__ import gemini_install, gemini_uninstall

    gemini_install(tmp_path)
    gemini_uninstall(tmp_path)
    md = tmp_path / "GEMINI.md"
    assert not md.exists()


def test_gemini_uninstall_removes_hook(tmp_path):
    from graphify.__main__ import gemini_install, gemini_uninstall

    gemini_install(tmp_path)
    gemini_uninstall(tmp_path)
    settings_path = tmp_path / ".gemini" / "settings.json"
    if settings_path.exists():
        settings = json.loads(settings_path.read_text())
        hooks = settings.get("hooks", {}).get("BeforeTool", [])
        assert not any("graphify" in str(h) for h in hooks)


def test_gemini_uninstall_noop_if_not_installed(tmp_path):
    from graphify.__main__ import gemini_uninstall

    gemini_uninstall(tmp_path)  # should not raise
