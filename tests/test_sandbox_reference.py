"""Local CLI evidence for the reference target's first project installation."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest


SUBJECT = Path(__file__).resolve().parents[1]
PACKAGE = SUBJECT / "graphify"
INSTRUCTIONS = (
    "# My project\n\n## Language\nRespond in English.\n\n## Changes\nExplain proposed changes.\n"
)
SETTINGS = '{\n  "theme": "dark",\n  "instructions": ["my-instructions.md"]\n}\n'
PERSONAL = "# My instructions\nDo not modify my personal documents.\n"
NOTES = "Personal document to preserve.\n"
ENTRY = "skills/graphify/SKILL.md"

HOOK = {"type": "command", "command": "graphify hook-guard search"}
PERSONAL_HOOK = {"type": "command", "command": "python personal_graphify_audit.py", "timeout": 17}
HOOKS = {"PreToolUse": [{"matcher": "Bash|Grep", "hooks": [HOOK]}]}


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _snapshot(root: Path) -> dict[str, tuple[int, bytes | None]]:
    return {
        path.relative_to(root).as_posix(): (
            stat.S_IMODE(path.stat().st_mode),
            None if path.is_dir() else path.read_bytes(),
        )
        for path in sorted(root.rglob("*"))
    }


def _run_cli(project: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-B", "-m", "graphify", *args],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    logs = list(project.parent.glob("cli-*.json"))
    (project.parent / f"cli-{len(logs)}.json").write_text(
        json.dumps(
            {
                "args": result.args,
                "cwd": str(project),
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return result


@pytest.fixture
def isolated_project(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    project = tmp_path / "project"
    home = tmp_path / "home"
    config = tmp_path / "configuration"
    project.mkdir()
    home.mkdir()
    config.mkdir()
    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT") if key in os.environ}
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "PYTHONPATH": str(SUBJECT),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    for key in (
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "XDG_STATE_HOME",
        "CLAUDE_CONFIG_DIR",
        "CODEX_HOME",
        "APPDATA",
        "LOCALAPPDATA",
    ):
        env[key] = str(config / key.lower())
    probe = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import graphify, importlib, json; "
            "print(json.dumps([graphify.__file__, importlib.import_module('graphify.install').__file__]))",
        ],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    expected = [str(PACKAGE / "__init__.py"), str(PACKAGE / "install.py")]
    assert json.loads(probe.stdout) == expected
    (tmp_path / "module-paths.json").write_text(probe.stdout, encoding="utf-8")
    _write(project / ".sandbox-reference/instructions.md", INSTRUCTIONS)
    _write(project / ".sandbox-reference/settings.json", SETTINGS)
    _write(project / ".sandbox-reference/my-instructions.md", PERSONAL)
    _write(home / "personal-notes.txt", NOTES)
    _write(project / "notes/neighbor.txt", "Keep this neighbor.\n")
    _write(project / ".sandbox-reference/neighbor.txt", "Keep this target neighbor.\n")
    (project / "empty-directory").mkdir()
    (project / "binary.dat").write_bytes(b"\x00\xff\n")
    return project, home, env


def test_first_project_install_preserves_user_files_and_home(isolated_project):
    project, home, env = isolated_project
    before = _snapshot(project)
    home_before = _snapshot(home)
    config = Path(env["XDG_CONFIG_HOME"]).parent
    config_before = _snapshot(config)
    skill = (PACKAGE / "skill.md").read_bytes()
    references = _snapshot(PACKAGE / "skills/claude/references")
    section = (PACKAGE / "always_on/agents-md.md").read_text(encoding="utf-8")

    result = _run_cli(project, env, "install", "--platform", "sandbox-reference", "--project")

    assert result.returncode == 0, result.stderr
    directory = project / ".sandbox-reference"
    installed = directory / "skills/graphify"
    assert (installed / "SKILL.md").read_bytes() == skill
    assert {key: value[1] for key, value in _snapshot(installed / "references").items()} == {
        key: value[1] for key, value in references.items()
    }
    assert (installed / ".graphify_version").is_file()
    markdown = (directory / "instructions.md").read_text(encoding="utf-8")
    assert markdown.splitlines().count("## graphify") == 1
    user_text, installed_section = markdown.split("## graphify", 1)
    assert user_text.rstrip("\n") == INSTRUCTIONS.rstrip("\n")
    assert ("## graphify" + installed_section).strip("\n") == section.strip("\n")
    assert json.loads((directory / "settings.json").read_text()) == {
        "theme": "dark",
        "instructions": ["my-instructions.md", ENTRY],
        "hooks": HOOKS,
    }
    assert (directory / "my-instructions.md").read_bytes() == PERSONAL.encode()

    after = _snapshot(project)
    changed = {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
    expected_changes = {
        ".sandbox-reference/skills",
        ".sandbox-reference/skills/graphify",
        ".sandbox-reference/skills/graphify/SKILL.md",
        ".sandbox-reference/skills/graphify/.graphify_version",
        ".sandbox-reference/skills/graphify/references",
        ".sandbox-reference/instructions.md",
        ".sandbox-reference/settings.json",
        *(f".sandbox-reference/skills/graphify/references/{name}" for name in references),
    }
    assert changed == expected_changes
    assert _snapshot(home) == home_before
    assert _snapshot(config) == config_before


@pytest.mark.parametrize("has_entry", [False, True])
def test_json_registration_preserves_values_and_order_without_duplicate(
    isolated_project, has_entry
):
    project, _, env = isolated_project
    settings_path = project / ".sandbox-reference/settings.json"
    entries = ["first.md", ENTRY, "last.md"] if has_entry else ["first.md", "last.md"]
    original = {"theme": "dark", "instructions": entries, "custom": {"enabled": False, "size": 3}}
    settings_path.write_text(json.dumps(original), encoding="utf-8")

    result = _run_cli(project, env, "install", "--platform", "sandbox-reference", "--project")

    assert result.returncode == 0, result.stderr
    expected = original | {"instructions": entries if has_entry else [*entries, ENTRY], "hooks": HOOKS}
    assert json.loads(settings_path.read_text()) == expected
    assert json.loads(settings_path.read_text())["instructions"].count(ENTRY) == 1


@pytest.mark.parametrize(
    "args",
    [
        ("install", "--platform", "sandbox-reference"),
        ("uninstall", "--platform", "sandbox-reference"),
        ("uninstall", "--platform", "sandbox-reference", "--project"),
    ],
)
def test_unsupported_cli_paths_fail_before_any_effect(isolated_project, args):
    project, home, env = isolated_project
    config = Path(env["XDG_CONFIG_HOME"]).parent
    # A general uninstall would remove these actual skill and rule destinations.
    for root in (home, project):
        for platform in (".claude", ".sandbox-reference"):
            _write(root / platform / "skills/graphify/SKILL.md", "Installed skill witness.\n")
            _write(root / platform / "skills/graphify/.graphify_version", "Witness stamp.\n")
            _write(root / platform / "skills/graphify/references/witness.md", "Keep reference.\n")
    _write(Path(env["CLAUDE_CONFIG_DIR"]) / "skills/graphify/SKILL.md", "Config skill witness.\n")
    _write(project / ".cursor/rules/graphify.mdc", "Installed Cursor rule.\n")
    _write(project / "AGENTS.md", "# Project\n\n## graphify\nInstalled section.\n")
    before = [_snapshot(root) for root in (project, home, config)]

    result = _run_cli(project, env, *args)

    assert result.returncode != 0
    assert "sandbox-reference" in result.stderr
    assert "not implemented" in result.stderr
    assert "only project installation" in result.stderr
    assert [_snapshot(root) for root in (project, home, config)] == before


def test_existing_project_cleanup_remains_available(isolated_project):
    project, home, env = isolated_project
    _write(project / ".cursor/rules/graphify.mdc", "Installed Cursor rule.\n")
    _write(project / ".claude/skills/graphify/SKILL.md", "Installed Claude skill.\n")
    home_before = _snapshot(home)

    result = _run_cli(project, env, "uninstall", "--project")

    assert result.returncode == 0, result.stderr
    assert not (project / ".cursor/rules/graphify.mdc").exists()
    assert not (project / ".claude/skills/graphify/SKILL.md").exists()
    assert _snapshot(home) == home_before


@pytest.mark.parametrize("existing_group", [False, True])
def test_reference_hooks_preserved_across_two_installations(isolated_project, existing_group):
    project, home, env = isolated_project
    settings_path = project / ".sandbox-reference/settings.json"
    groups = [{"matcher": "Bash|Grep", "hooks": [PERSONAL_HOOK]}]
    if existing_group:
        groups.append({"matcher": "Bash|Grep", "hooks": [HOOK | {"timeout": 23}]})
    original = {"theme": "dark", "instructions": ["my-instructions.md", ENTRY],
                "hooks": {"PreToolUse": groups}}
    settings_path.write_text(json.dumps(original), encoding="utf-8")
    home_before = _snapshot(home)
    installed = None
    for _ in range(2):
        result = _run_cli(project, env, "install", "--platform", "sandbox-reference", "--project")
        assert result.returncode == 0, result.stderr
        observed = json.loads(settings_path.read_bytes())
        hooks = [hook for group in observed["hooks"]["PreToolUse"] for hook in group["hooks"]]
        assert hooks.count(PERSONAL_HOOK) == 1
        assert sum(all(hook.get(k) == v for k, v in HOOK.items()) for hook in hooks) == 1
        assert observed["instructions"] == original["instructions"]
        assert observed["theme"] == "dark"
        assert _snapshot(home) == home_before
        if installed is not None:
            assert observed == installed
        installed = observed
