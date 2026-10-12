"""Explicit local reference-product evidence, without packaging or Docker."""

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from tools.install_sandbox.container.environment import TestEnvironment as Environment
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.case import InstallTestCase
from tools.install_sandbox.host.coordinator import InstallTestCoordinator
from tools.install_sandbox.host.result_reader import read_result

_SUBJECT = os.environ.get("INSTALL_SANDBOX_REFERENCE_SUBJECT")
pytestmark = pytest.mark.skipif(not _SUBJECT, reason="Supply INSTALL_SANDBOX_REFERENCE_SUBJECT")
_SPECS = Path(__file__).resolve().parents[4] / "tools/install_sandbox/specs/reference"


def _launcher(subject: Path, path: Path) -> None:
    path.write_text(
        f"#!{sys.executable}\n"
        "import importlib, json, os, sys\n"
        "from pathlib import Path\n"
        f"subject = Path({str(subject)!r})\n"
        "sys.path.insert(0, str(subject))\n"
        "sys.dont_write_bytecode = True\n"
        "config = Path(os.environ['TMPDIR']) / 'configuration'\n"
        "for name in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'XDG_STATE_HOME',\n"
        "             'CLAUDE_CONFIG_DIR', 'CODEX_HOME', 'APPDATA', 'LOCALAPPDATA'):\n"
        "    os.environ[name] = str(config / name.lower())\n"
        "os.environ['USERPROFILE'] = os.environ['HOME']\n"
        "origins = [str(Path(importlib.import_module(name).__file__).resolve())\n"
        "           for name in ('graphify', 'graphify.install')]\n"
        "assert origins == [str(subject / 'graphify/__init__.py'),\n"
        "                   str(subject / 'graphify/install.py')]\n"
        "print('Reference import origins: ' + json.dumps(origins), flush=True)\n"
        "os.environ['PYTHONPATH'] = str(subject)\n"
        "os.environ['PYTHONDONTWRITEBYTECODE'] = '1'\n"
        "args = [sys.executable, '-B', '-m', 'graphify', *sys.argv[1:]]\n"
        "os.execve(sys.executable, args, os.environ)\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _seed_cache(monkeypatch: pytest.MonkeyPatch, name: str) -> dict[Path, bytes]:
    original_prepare = Environment.prepare
    witnesses: dict[Path, bytes] = {}

    def prepare(environment: Environment) -> None:
        original_prepare(environment)
        assert environment.skill_lock is not None
        lock = environment.home / environment.skill_lock
        witnesses[lock.parent / "foreign.lock"] = b"Foreign lock bytes.\n"
        witnesses[lock.parent / "personal.txt"] = b"Personal cache document.\n"
        if name == "reinstall":
            witnesses[lock] = b"\x00Previous persistent lock.\xff"
        for path, content in witnesses.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    monkeypatch.setattr(Environment, "prepare", prepare)
    return witnesses


def _assert_cache(output: Path, witnesses: dict[Path, bytes], steps: int) -> None:
    assert all(path.read_bytes() == content for path, content in witnesses.items())
    expectation = json.loads((output / "skill-lock.json").read_bytes())
    lock = Path(expectation["home"]) / expectation["path"]
    expected_lock = witnesses.get(lock, b"")
    for index in range(steps):
        assert (
            output / f"steps/{index}/after/home" / expectation["path"]
        ).read_bytes() == expected_lock


@pytest.mark.parametrize("name", ["first-install", "reinstall"])
def test_real_reference_installer_retains_hooks_and_evidence(
    tmp_path: Path, name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _SUBJECT is not None
    subject = Path(_SUBJECT).resolve()
    assert (subject / "graphify/install.py").is_file()
    executable = tmp_path / "reference-graphify"
    _launcher(subject, executable)
    case_file = tmp_path / "case.json"
    case = InstallTestCoordinator().write_case(
        _SPECS, "sandbox-reference", case_file, case_name=name
    )
    witnesses = _seed_cache(monkeypatch, name)
    output = tmp_path / "evidence"
    work = tmp_path / "work"
    result = InstallTestRunner().run_case(
        reference_sources=subject,
        prepared_executable=executable,
        case_file=case_file,
        work_directory=work,
        output_directory=output,
    )
    assert result.status == "passed", result
    documents: list[dict[str, Any]] = []
    for index in range(len(case.operations)):
        path = output / f"steps/{index}/after/project/.sandbox-reference/settings.json"
        data = json.loads(path.read_bytes())
        hooks = [hook for group in data["hooks"]["PreToolUse"] for hook in group["hooks"]]
        assert hooks.count({"type": "command", "command": "graphify hook-guard search"}) == 1
        assert (
            hooks.count(
                {"type": "command", "command": "python personal_graphify_audit.py", "timeout": 17}
            )
            == 1
        )
        assert "Reference import origins:" in (output / f"steps/{index}/stdout.txt").read_text()
        documents.append(data)
    if name == "reinstall":
        assert documents[0] == documents[1]
        before = output / "steps/1/before/project/.sandbox-reference/settings.json"
        assert json.loads(before.read_bytes()) == documents[0]
    _assert_cache(output, witnesses, len(case.operations))
    shutil.rmtree(work)
    executable.unlink()
    assert read_result(output, InstallTestCase.from_json(case_file.read_text())) == result
