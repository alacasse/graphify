"""Skill payload and destination edge tests for graphify install."""
import os
from pathlib import Path
from unittest.mock import patch

from tests.install_test_support import install_in_tmp as _install


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


def test_hermes_skill_destination_windows_uses_localappdata():
    """#1403: on Windows, Hermes scans %LOCALAPPDATA%\\hermes\\skills, so the global
    skill must land there -- not ~/.hermes/skills (the POSIX path)."""
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
