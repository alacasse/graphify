"""Tests for graphify install payloads and host integrations."""
import os
from pathlib import Path
from unittest.mock import patch

from tests.install_test_support import (
    agents_install as _agents_install,
    agents_uninstall as _agents_uninstall,
    install_in_tmp as _install,
)


def test_codex_skill_contains_spawn_agent():
    """Codex skill file must reference spawn_agent."""
    import graphify

    skill = (Path(graphify.__file__).parent / "skill-codex.md").read_text()
    assert "spawn_agent" in skill


def test_codex_skill_uses_graphify_with_existing_graph():
    """Codex skill must keep graph-first orientation in the lean-core split.

    The progressive-disclosure split drops codex's old monolith-only "dirty
    graph output" blurb; the graph-first intent now lives in the shared core's
    fast-path block, which jumps straight to the query flow when a graph exists.
    """
    import graphify
    skill = (Path(graphify.__file__).parent / "skill-codex.md").read_text()
    assert "Fast path — existing graph" in skill
    assert "skip Steps 1–5 entirely and jump straight to `## For /graphify query`" in skill
    assert "graphify query" in skill
    assert "graphify explain" in skill
    assert "graphify path" in skill


def test_opencode_skill_contains_mention():
    """OpenCode skill file must reference @mention."""
    import graphify

    skill = (Path(graphify.__file__).parent / "skill-opencode.md").read_text()
    assert "@mention" in skill


def test_opencode_skill_uses_opencode_agent_guidance():
    """OpenCode's dispatch slot uses @mention, not the Claude Agent-tool example.

    The progressive split consolidates the bespoke v8 opencode prose into the
    shared core. opencode's distinguishing delta is the @mention dispatch block;
    its B2 slot must carry that and must NOT carry the Claude Agent-tool example.
    (The shared Step B3 re-run hint names the general-purpose agent type as the
    canonical example for every host; that lives in the shared core, not in
    opencode's dispatch slot.)
    """
    import graphify

    skill = (Path(graphify.__file__).parent / "skill-opencode.md").read_text()
    assert "@mention" in skill
    assert "@agent" in skill
    # Scope the agent-type check to opencode's dispatch slot (B2 -> B3).
    b2 = skill[skill.index("**Step B2"):skill.index("**Step B3")]
    assert "general-purpose" not in b2
    assert "Concrete example for 3 chunks" not in b2
    assert "OpenCode platform" in b2


def test_kilo_skill_mentions_task_tool():
    """Kilo skill file should use the native Task tool flow."""
    import graphify

    skill = (Path(graphify.__file__).parent / "skill-kilo.md").read_text()
    assert "Task" in skill


def test_kilo_skill_avoids_double_quoted_python_c_fstring_dict_keys():
    """Kilo runs snippets through double-quoted python -c strings."""
    import re
    import graphify

    skill = (Path(graphify.__file__).parent / "skill-kilo.md").read_text()
    assert not re.search(r"print\(f'.*\[[\"'][^\"']+[\"']\]", skill)


def test_claw_skill_uses_agent_tool_dispatch():
    """OpenClaw rides the shared Agent-tool disk-collect dispatch.

    The consolidated design moves claw off the v8 sequential OpenClaw flow onto
    the same agent-tool-disk dispatch as claude (per-platform-deltas), so its B2
    slot uses the Agent tool and must not carry the Codex or OpenCode mechanics.
    """
    import graphify

    skill = (Path(graphify.__file__).parent / "skill-claw.md").read_text()
    b2 = skill[skill.index("**Step B2"):skill.index("**Step B3")]
    assert 'subagent_type="general-purpose"' in b2
    assert "spawn_agent" not in skill
    assert "@mention" not in skill


def test_all_skill_files_exist_in_package():
    """All installable platform skill files must be present in the installed package."""
    import graphify

    pkg = Path(graphify.__file__).parent
    for name in (
        "skill.md",
        "skill-codex.md",
        "skill-opencode.md",
        "skill-kilo.md",
        "skill-claw.md",
        "skill-windows.md",
        "skill-droid.md",
        "skill-trae.md",
        "skill-kiro.md",
    ):
        assert (pkg / name).exists(), f"Missing: {name}"


def test_kilo_command_file_exists_in_package():
    import graphify

    pkg = Path(graphify.__file__).parent
    assert (pkg / "command-kilo.md").exists()


def test_claude_install_registers_claude_md(tmp_path):
    """Claude platform install writes CLAUDE.md; others do not."""
    _install(tmp_path, "claude")
    assert (tmp_path / ".claude" / "CLAUDE.md").exists()


def test_codex_install_does_not_write_claude_md(tmp_path):
    _install(tmp_path, "codex")
    assert not (tmp_path / ".claude" / "CLAUDE.md").exists()


# --- CodeBuddy CODEBUDDY.md + hook install/uninstall tests ---

def test_codebuddy_install_writes_codebuddy_md(tmp_path):
    from graphify.__main__ import codebuddy_install
    codebuddy_install(tmp_path)
    md = tmp_path / "CODEBUDDY.md"
    assert md.exists()
    assert "graphify-out/GRAPH_REPORT.md" in md.read_text()


def test_codebuddy_install_writes_hook(tmp_path):
    import json as _json
    from graphify.__main__ import codebuddy_install
    codebuddy_install(tmp_path)
    settings = _json.loads((tmp_path / ".codebuddy" / "settings.json").read_text())
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
    import json as _json
    from graphify.__main__ import codebuddy_install, codebuddy_uninstall
    codebuddy_install(tmp_path)
    codebuddy_uninstall(tmp_path)
    settings_path = tmp_path / ".codebuddy" / "settings.json"
    if settings_path.exists():
        settings = _json.loads(settings_path.read_text())
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
    import re

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
    import json as _json

    config = _json.loads(config_file.read_text())
    assert any("graphify.js" in p for p in config.get("plugin", []))


def test_opencode_agents_install_merges_existing_config(tmp_path):
    """opencode install preserves existing .opencode/opencode.json keys."""
    import json as _json

    config_file = tmp_path / ".opencode" / "opencode.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(_json.dumps({"model": "claude-opus-4-5", "plugin": []}))
    _agents_install(tmp_path, "opencode")
    config = _json.loads(config_file.read_text())
    assert config["model"] == "claude-opus-4-5"
    assert any("graphify.js" in p for p in config["plugin"])


def test_opencode_agents_uninstall_removes_plugin(tmp_path):
    """opencode uninstall removes the plugin file and deregisters from opencode.json."""
    import json as _json

    _agents_install(tmp_path, "opencode")
    _agents_uninstall(tmp_path, platform="opencode")
    plugin = tmp_path / ".opencode" / "plugins" / "graphify.js"
    assert not plugin.exists()
    config_file = tmp_path / ".opencode" / "opencode.json"
    if config_file.exists():
        config = _json.loads(config_file.read_text())
        assert not any("graphify.js" in p for p in config.get("plugin", []))


def test_kilo_agents_install_writes_plugin(tmp_path):
    _agents_install(tmp_path, "kilo")
    plugin = tmp_path / ".kilo" / "plugins" / "graphify.js"
    assert plugin.exists()
    assert "tool.execute.before" in plugin.read_text()


def test_kilo_agents_install_registers_plugin_in_config(tmp_path):
    import json as _json

    _agents_install(tmp_path, "kilo")
    config_file = tmp_path / ".kilo" / "kilo.json"
    assert config_file.exists()
    config = _json.loads(config_file.read_text())
    assert (
        tmp_path / ".kilo" / "plugins" / "graphify.js"
    ).resolve().as_uri() in config.get("plugin", [])


def test_kilo_agents_install_merges_existing_config(tmp_path):
    import json as _json

    config_file = tmp_path / ".kilo" / "kilo.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        _json.dumps({"model": "anthropic/claude-sonnet", "plugin": []})
    )
    _agents_install(tmp_path, "kilo")
    config = _json.loads(config_file.read_text())
    assert config["model"] == "anthropic/claude-sonnet"
    assert (
        tmp_path / ".kilo" / "plugins" / "graphify.js"
    ).resolve().as_uri() in config["plugin"]


def test_kilo_agents_install_preserves_existing_jsonc_config(tmp_path):
    import json as _json

    config_file = tmp_path / ".kilo" / "kilo.jsonc"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    original = """// user comment\n{\n  // preferred model\n  \"model\": \"anthropic/claude-haiku\",\n  \"plugin\": []\n}\n"""
    config_file.write_text(original)
    _agents_install(tmp_path, "kilo")
    json_file = tmp_path / ".kilo" / "kilo.json"
    config = _json.loads(json_file.read_text())
    assert config["model"] == "anthropic/claude-haiku"
    assert (
        tmp_path / ".kilo" / "plugins" / "graphify.js"
    ).resolve().as_uri() in config["plugin"]
    assert config_file.read_text() == original


def test_kilo_agents_uninstall_preserves_existing_jsonc_config(tmp_path):
    import json as _json

    config_file = tmp_path / ".kilo" / "kilo.jsonc"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    original = """// user comment\n{\n  \"model\": \"anthropic/claude-haiku\",\n  \"plugin\": []\n}\n"""
    config_file.write_text(original)

    _agents_install(tmp_path, "kilo")
    _agents_uninstall(tmp_path, platform="kilo")

    json_file = tmp_path / ".kilo" / "kilo.json"
    config = _json.loads(json_file.read_text())
    assert config_file.read_text() == original
    assert (
        tmp_path / ".kilo" / "plugins" / "graphify.js"
    ).resolve().as_uri() not in config.get("plugin", [])


def test_kilo_agents_install_idempotent(tmp_path):
    import json as _json

    _agents_install(tmp_path, "kilo")
    _agents_install(tmp_path, "kilo")
    content = (tmp_path / "AGENTS.md").read_text()
    config = _json.loads((tmp_path / ".kilo" / "kilo.json").read_text())
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
    import json as _json

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
        config = _json.loads(config_file.read_text())
        assert (
            project_dir / ".kilo" / "plugins" / "graphify.js"
        ).resolve().as_uri() not in config.get("plugin", [])


# ── Cursor ────────────────────────────────────────────────────────────────────


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


# ── Gemini CLI ────────────────────────────────────────────────────────────────


def test_gemini_install_writes_gemini_md(tmp_path):
    from graphify.__main__ import gemini_install

    gemini_install(tmp_path)
    md = tmp_path / "GEMINI.md"
    assert md.exists()
    assert "graphify-out/GRAPH_REPORT.md" in md.read_text()


def test_gemini_install_writes_hook(tmp_path):
    import json as _json
    from graphify.__main__ import gemini_install

    gemini_install(tmp_path)
    settings = _json.loads((tmp_path / ".gemini" / "settings.json").read_text())
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
    import json as _json
    from graphify.__main__ import gemini_install, gemini_uninstall

    gemini_install(tmp_path)
    gemini_uninstall(tmp_path)
    settings_path = tmp_path / ".gemini" / "settings.json"
    if settings_path.exists():
        settings = _json.loads(settings_path.read_text())
        hooks = settings.get("hooks", {}).get("BeforeTool", [])
        assert not any("graphify" in str(h) for h in hooks)


def test_gemini_uninstall_noop_if_not_installed(tmp_path):
    from graphify.__main__ import gemini_uninstall

    gemini_uninstall(tmp_path)  # should not raise


def test_hermes_skill_destination_windows_uses_localappdata():
    """#1403: on Windows, Hermes scans %LOCALAPPDATA%\\hermes\\skills, so the global
    skill must land there — not ~/.hermes/skills (the POSIX path)."""
    from graphify.__main__ import _platform_skill_destination
    with patch("graphify.__main__.platform.system", return_value="Windows"), \
         patch.dict(os.environ, {"LOCALAPPDATA": str(Path("/tmp/AppDataLocal"))}):
        dst = _platform_skill_destination("hermes", project=False)
    assert dst == Path("/tmp/AppDataLocal") / "hermes" / "skills" / "graphify" / "SKILL.md", dst


def test_hermes_skill_destination_posix_uses_home():
    """Non-Windows hermes destination is unchanged (~/.hermes/skills)."""
    from graphify.__main__ import _platform_skill_destination
    with patch("graphify.__main__.platform.system", return_value="Linux"):
        dst = _platform_skill_destination("hermes", project=False)
    assert str(dst).endswith(".hermes/skills/graphify/SKILL.md"), dst
