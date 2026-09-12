"""Explicit local reference-product evidence, without packaging or Docker."""

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from tools.install_sandbox.case import InstallTestCase
from tools.install_sandbox.coordinator import InstallTestCoordinator
from tools.install_sandbox.result_reader import read_result
from tools.install_sandbox.runner import InstallTestRunner

_SUBJECT = os.environ.get("INSTALL_SANDBOX_REFERENCE_SUBJECT")
pytestmark = pytest.mark.skipif(not _SUBJECT, reason="Supply INSTALL_SANDBOX_REFERENCE_SUBJECT")
_SPECS = Path(__file__).resolve().parents[3] / "tools/install_sandbox/specs/reference"


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


@pytest.mark.parametrize("name", ["first-install", "reinstall"])
def test_real_reference_installer_retains_hooks_and_evidence(tmp_path: Path, name: str) -> None:
    assert _SUBJECT is not None
    subject = Path(_SUBJECT).resolve()
    assert (subject / "graphify/install.py").is_file()
    executable = tmp_path / "reference-graphify"
    _launcher(subject, executable)
    case_file = tmp_path / "case.json"
    case = InstallTestCoordinator().write_case(
        _SPECS, "sandbox-reference", case_file, case_name=name
    )
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
    shutil.rmtree(work)
    executable.unlink()
    assert read_result(output, InstallTestCase.from_json(case_file.read_text())) == result
