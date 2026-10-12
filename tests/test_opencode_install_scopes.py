"""Public CLI proofs for OpenCode installation scope and bounded migration."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest


SUBJECT = Path(__file__).resolve().parents[1]
PACKAGE = SUBJECT / "graphify"
LEGACY = ".opencode/plugins/graphify.js"
PERSONAL_AGENTS = "# Personal guidance\n\n## Language\nRespond in French.\n"


def _write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def _snapshot(root: Path) -> dict[Path, tuple[int, bytes | None]]:
    result = {}
    for path in sorted(root.rglob("*")):
        mode = path.lstat().st_mode
        assert not stat.S_ISLNK(mode), f"Unexpected symlink: {path}"
        result[path] = (stat.S_IMODE(mode), None if path.is_dir() else path.read_bytes())
    return result


def _lock(home: Path, skill: Path) -> Path:
    identity = os.path.normcase(str(skill.resolve())).encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()[:16]
    return home / ".cache/graphify/skill-locks" / f"{digest}.lock"


def _with_parents(paths: set[Path], roots: tuple[Path, ...]) -> set[Path]:
    allowed = set(paths)
    for path in paths:
        root = next(root for root in roots if path.is_relative_to(root))
        allowed.update(
            parent for parent in path.parents if parent != root and parent.is_relative_to(root)
        )
    return allowed


@pytest.fixture
def isolated(tmp_path: Path):
    home, project, configuration = (
        tmp_path / name for name in ("home", "project", "configuration")
    )
    roots = (home, project, configuration)
    for root in roots:
        root.mkdir()
        _write(root / "personal/binary-witness", b"\x00\xffPersonal\n")
        (root / "empty-witness").mkdir()
    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT") if key in os.environ}
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        PYTHONPATH=str(SUBJECT),
        PYTHONNOUSERSITE="1",
        PYTHONDONTWRITEBYTECODE="1",
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
        env[key] = str(configuration / key.lower())

    def run(*arguments: str):
        result = subprocess.run(
            [sys.executable, "-B", *arguments],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        receipt = tmp_path / f"cli-{len(list(tmp_path.glob('cli-*.json'))):02d}.json"
        receipt.write_text(
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
        assert result.returncode == 0, result.stdout + result.stderr
        return result

    probe = run(
        "-c",
        "import graphify, importlib, json; print(json.dumps([graphify.__file__, "
        "importlib.import_module('graphify.install').__file__, "
        "importlib.import_module('graphify.__main__').__file__]))",
    )
    assert json.loads(probe.stdout) == [
        str(PACKAGE / name) for name in ("__init__.py", "install.py", "__main__.py")
    ]
    _write(project / "AGENTS.md", PERSONAL_AGENTS.encode())
    _write(home / "AGENTS.md", b"Home instructions must survive.\n")
    _write(project / ".opencode/plugins/personal.js", b"export default {};\n")
    _write(home / ".cache/graphify/skill-locks/unrelated.lock", b"Unrelated lock\n")
    _write(home / ".cache/graphify/personal-cache", b"Personal cache\n")
    return home, project, roots, run


@pytest.mark.parametrize("scope", ["user", "project"])
@pytest.mark.parametrize("scenario", ["missing", "no-legacy", "migration", "jsonc"])
def test_opencode_cli_install_and_reinstall(isolated, scope, scenario):
    home, project, roots, run = isolated
    skill = (
        (project / ".opencode/skills/graphify")
        if scope == "project"
        else (home / ".config/opencode/skills/graphify")
    )
    lock = _lock(home, skill)
    config = project / ".opencode/opencode.json"
    plugin = project / LEGACY
    original_config = None
    expected_config = None
    if scenario == "no-legacy":
        original_config = (
            '{\n "plugin": ["first", "./.opencode/plugins/graphify.js", "last"],'
            '\n "plugins": ["other"], "username": "Zoë", "custom": {"enabled": false}\n}\n'
        ).encode()
    elif scenario == "migration":
        original_config = json.dumps(
            {
                "plugin": [
                    "first",
                    LEGACY,
                    "./.opencode/plugins/graphify.js",
                    "middle",
                    LEGACY,
                    "last",
                ],
                "plugins": [LEGACY, LEGACY],
                "username": "Zoë 日本語",
                "custom": {"enabled": False, "limit": 7},
            },
            ensure_ascii=False,
        ).encode()
        expected_config = {
            "plugin": ["first", "./.opencode/plugins/graphify.js", "middle", "last"],
            "username": "Zoë 日本語",
            "custom": {"enabled": False, "limit": 7},
        }
        _write(lock, b"Existing target lock must survive.\n")
        _write(skill / "SKILL.md", (PACKAGE / "skill-opencode.md").read_bytes())
    elif scenario == "jsonc":
        original_config = (
            '{ // Personal comment: Zoë\n "plugin": ["' + LEGACY + '"]\n}\n'
        ).encode()
    if original_config is not None:
        _write(config, original_config)

    before = {path: value for root in roots for path, value in _snapshot(root).items()}
    references = PACKAGE / "skills/opencode/references"
    source_references = _snapshot(references)
    installed_files = {skill / "SKILL.md", skill / ".graphify_version", plugin, lock}
    installed_files.update(
        skill / "references" / path.relative_to(references) for path in source_references
    )
    # Include the references directory explicitly, even for an empty bundle.
    installed_files.add(skill / "references")
    if scope == "project":
        installed_files.add(project / "AGENTS.md")
    if scenario == "migration":
        installed_files.add(config)
    allowed = _with_parents(installed_files, roots)
    args = ["-m", "graphify", "install", "--platform", "opencode"]
    if scope == "project":
        args.append("--project")

    first_after = None
    for attempt in range(2):
        result = run(*args)
        assert (skill / "SKILL.md").read_bytes() == (PACKAGE / "skill-opencode.md").read_bytes()
        assert {
            path.relative_to(skill / "references"): value[1]
            for path, value in _snapshot(skill / "references").items()
        } == {path.relative_to(references): value[1] for path, value in source_references.items()}
        assert (skill / ".graphify_version").read_text().strip()
        body = plugin.read_text(encoding="utf-8")
        assert "tool.execute.before" in body and "export default" in body
        assert lock.is_file()
        assert lock.read_bytes() == (
            b"Existing target lock must survive.\n" if scenario == "migration" else b""
        )
        if lock in before:
            assert _snapshot(home)[lock] == before[lock]
        agents = (project / "AGENTS.md").read_text(encoding="utf-8")
        if scope == "project":
            assert agents.startswith(PERSONAL_AGENTS.rstrip() + "\n\n")
            assert agents.splitlines().count("## graphify") == 1
            assert (
                agents.split("## graphify", 1)[1].strip()
                == (PACKAGE / "always_on/agents-md.md")
                .read_text()
                .split("## graphify", 1)[1]
                .strip()
            )
        else:
            assert agents == PERSONAL_AGENTS
        if scenario == "missing":
            assert not config.exists()
        elif scenario == "migration":
            assert json.loads(config.read_text(encoding="utf-8")) == expected_config
        else:
            assert config.read_bytes() == original_config
        if scenario == "jsonc":
            assert f'remove "{LEGACY}" from its plugin list by hand' in result.stdout

        after = {path: value for root in roots for path, value in _snapshot(root).items()}
        assert set(after) == set(before) | allowed
        assert {path: after[path] for path in before if path not in installed_files} == {
            path: value for path, value in before.items() if path not in installed_files
        }
        if attempt == 0:
            first_after = after
        else:
            assert after == first_after, (
                "Reinstallation must preserve the complete observed filesystem"
            )
