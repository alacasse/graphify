"""Retained two-source CLI upgrade proof, requiring an explicitly supplied subject."""

import hashlib
import json
import os
import shutil
import sys
import tarfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

import pytest

from tools.install_sandbox.container.environment import TestEnvironment as Environment
from tools.install_sandbox.container.evidence_writer import TestResultWriter as Writer
from tools.install_sandbox.container.installer import InstallerDriver
from tools.install_sandbox.container.verifier import InstallVerifier
from tools.install_sandbox.contracts.case import InstallTestCase
from tools.install_sandbox.contracts.managed_json import resolution
from tools.install_sandbox.host.coordinator import InstallTestCoordinator

_SUBJECT = os.environ.get("INSTALL_SANDBOX_REFERENCE_SUBJECT")
pytestmark = pytest.mark.skipif(not _SUBJECT, reason="Supply INSTALL_SANDBOX_REFERENCE_SUBJECT")
_ROOT = Path(__file__).resolve().parents[4]
_SETTINGS = ".sandbox-reference/settings.json"
_V1: dict[str, object] = {"type": "command", "command": "graphify hook-guard search"}
_V2: dict[str, object] = {**_V1, "timeout": 10}


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


def _json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _read(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_bytes()))


def _sources(subject: Path, work: Path, evidence: Path) -> tuple[Path, Path]:
    first, second = work / "v1", work / "v2"
    shutil.copytree(
        subject / "graphify",
        first / "graphify",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copytree(first, second)
    source = second / "graphify/install.py"
    original = source.read_text()
    needle = 'command = {"type": "command", "command": "graphify hook-guard search"}'
    assert original.count(needle) == 1
    changed = original.replace(needle, needle[:-1] + ', "timeout": 10}')
    source.write_text(changed)
    _json(
        evidence / "delta.json",
        {
            "path": "graphify/install.py",
            "before": needle,
            "after": needle[:-1] + ', "timeout": 10}',
        },
    )
    for name, directory in (("v1", first), ("v2", second)):
        _archive(directory, evidence, name)
    one = _read(evidence / "v1-manifest.json")
    two = _read(evidence / "v2-manifest.json")
    assert one.keys() == two.keys()
    assert [key for key in one if one[key] != two[key]] == ["graphify/install.py"]
    return first, second


def _archive(directory: Path, evidence: Path, name: str) -> None:
    manifest = {
        str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }
    _json(evidence / f"{name}-manifest.json", manifest)
    with tarfile.open(evidence / f"{name}-sources.tar.gz", "w:gz") as archive:
        archive.add(directory / "graphify", arcname="graphify")


def _case(work: Path, evidence: Path, *, second: bool) -> InstallTestCase:
    specs = work / ("specs-v2" if second else "specs-v1")
    shutil.copytree(_ROOT / "tools/install_sandbox/specs/reference", specs)
    path = specs / "sandbox-reference.yaml"
    if second:
        path.write_text(path.read_text() + "        timeout: 10\n")
    return InstallTestCoordinator().write_case(
        specs,
        "sandbox-reference",
        evidence / ("v2-case.json" if second else "v1-case.json"),
        case_name="first-install",
    )


def _command(
    environment: Environment,
    subject: Path,
    work: Path,
    evidence: Path,
    name: str,
    consent: Path | None = None,
) -> int | None:
    launcher = work / f"launcher-{name}"
    _launcher(subject, launcher)
    temporary = work / f"temporary-{name}"
    temporary.mkdir()
    result = InstallerDriver().install(
        environment.case, launcher, environment.project, environment.home, temporary, consent
    )
    _json(evidence / f"{name}-command.json", asdict(result) | {"stdout": None, "stderr": None})
    (evidence / f"{name}-stdout.txt").write_bytes(result.stdout)
    (evidence / f"{name}-stderr.txt").write_bytes(result.stderr)
    return result.exit_code


def _step(
    environment: Environment,
    case: InstallTestCase,
    subject: Path,
    work: Path,
    evidence: Path,
    name: str,
    *,
    consent: Path | None = None,
    upgrade: bool = False,
) -> None:
    writer = Writer(evidence / name)
    expected = environment.preserve_expected(subject, writer)
    before = environment.observe(writer, "before")
    assert _command(environment, subject, work, evidence, name, consent) == 0
    after = environment.observe(writer, "after")
    verdict = InstallVerifier().verify(case, expected, before, after, allow_registry_update=upgrade)
    _json(evidence / name / "verification.json", asdict(verdict))
    assert verdict.complete and not verdict.mismatches and not verdict.obstacles, verdict


def _move_managed(environment: Environment, evidence: Path) -> None:
    path = environment.project / _SETTINGS
    document = _read(path)
    groups = document["hooks"]["PreToolUse"]
    managed = next(group for group in groups if group["hooks"] == [_V1])
    personal = next(
        group for group in groups if group is not managed and group["matcher"] == "Bash|Grep"
    )
    personal["hooks"].append(managed["hooks"][0])
    groups.remove(managed)
    _json(path, document)
    _json(evidence / "controlled-move.json", document)


def test_two_archives_upgrade_and_reinstall(tmp_path: Path) -> None:
    assert _SUBJECT is not None
    retained = os.environ.get("INSTALL_SANDBOX_MANAGED_JSON_EVIDENCE")
    evidence = Path(retained) / "upgrade" if retained else tmp_path / "evidence"
    evidence.mkdir(parents=True, exist_ok=False)
    work = tmp_path / "owned-work"
    work.mkdir()
    first, second = _sources(Path(_SUBJECT), work, evidence)
    initial, upgraded = _case(work, evidence, second=False), _case(work, evidence, second=True)
    environment = Environment(initial, work / "installation")
    environment.prepare()
    consent = evidence / "create-resolution.json"
    _json(consent, resolution(initial))
    _step(environment, initial, first, work, evidence, "create", consent=consent)
    _move_managed(environment, evidence)
    _step(environment, upgraded, second, work, evidence, "upgrade", upgrade=True)
    _step(environment, upgraded, second, work, evidence, "reinstall")
    _conflict(environment, second, work, evidence)
    adoption = Environment(initial, work / "adoption-installation")
    adoption.prepare()
    _adoption(adoption, second, work, evidence)
    shutil.rmtree(work)
    _retained(evidence)


def _adoption(environment: Environment, subject: Path, work: Path, evidence: Path) -> None:
    path = environment.project / _SETTINGS
    document = _read(path)
    document["hooks"]["PreToolUse"][0]["hooks"].append(_V1)
    _json(path, document)
    initial = path.read_bytes()
    selected = {
        "version": 1,
        "target": _SETTINGS,
        "snapshot_sha256": hashlib.sha256(initial).hexdigest(),
        "registry_absent": True,
        "effects": [
            {
                "id": "graphify.search",
                "action": "adopt",
                "event": "PreToolUse",
                "matcher": "Bash|Grep",
                "group_index": 0,
                "hook_index": 1,
                "content": _V1,
            }
        ],
    }
    consent = evidence / "adopt-resolution.json"
    _json(consent, selected)
    writer = Writer(evidence / "adoption")
    environment.observe(writer, "before")
    assert _command(environment, subject, work, evidence, "ambiguous") != 0
    assert path.read_bytes() == initial
    _json(path, document | {"personal_extra": True})
    stale = path.read_bytes()
    assert _command(environment, subject, work, evidence, "stale", consent) != 0
    assert path.read_bytes() == stale
    path.write_bytes(initial)
    assert _command(environment, subject, work, evidence, "adopt", consent) == 0
    environment.observe(writer, "after")
    installed = _read(path)
    expected = _read(evidence / "adoption/steps/0/before/project" / _SETTINGS)
    expected["hooks"]["PreToolUse"][0]["hooks"][1] = _V2
    expected["instructions"].append("skills/graphify/SKILL.md")
    assert installed == expected
    state = path.with_name(path.name + ".graphify-state.json")
    assert _read(state)["effects"] == [
        {"id": "graphify.search", "event": "PreToolUse", "matcher": "Bash|Grep", "content": _V2}
    ]
    previous = path.read_bytes(), state.read_bytes()
    assert _command(environment, subject, work, evidence, "consumed", consent) != 0
    assert (path.read_bytes(), state.read_bytes()) == previous
    _json(
        evidence / "adoption/verification.json",
        {
            "passed": True,
            "checks": [
                "ambiguous refusal",
                "stale refusal",
                "explicit adoption",
                "personal content preserved",
                "consumed resolution refusal",
            ],
        },
    )


def _conflict(environment: Environment, subject: Path, work: Path, evidence: Path) -> None:
    path = environment.project / _SETTINGS
    state = path.with_name(path.name + ".graphify-state.json")
    document = _read(path)
    hooks = document["hooks"]["PreToolUse"][0]["hooks"]
    owned = next(hook for hook in hooks if hook == _V2)
    owned["timeout"] = 99
    _json(path, document)
    previous = path.read_bytes(), state.read_bytes()
    writer = Writer(evidence / "customized-conflict")
    environment.observe(writer, "before")
    assert _command(environment, subject, work, evidence, "customized-conflict") != 0
    environment.observe(writer, "after")
    assert (path.read_bytes(), state.read_bytes()) == previous
    assert not path.with_name(path.name + ".graphify-journal.json").exists()
    _json(
        evidence / "customized-conflict/verification.json",
        {"passed": True, "configuration_and_registry_unchanged": True, "journal_absent": True},
    )


def _retained(evidence: Path) -> None:
    for name in ("create", "upgrade", "reinstall"):
        result = _read(evidence / name / "verification.json")
        assert result["complete"] and not result["mismatches"] and not result["obstacles"]
    for name in ("v1", "v2"):
        manifest = _read(evidence / f"{name}-manifest.json")
        observed: dict[str, str] = {}
        with tarfile.open(evidence / f"{name}-sources.tar.gz", "r:gz") as archive:
            for member in archive.getmembers():
                if member.isfile():
                    content = archive.extractfile(member)
                    assert content is not None
                    observed[member.name] = hashlib.sha256(content.read()).hexdigest()
        assert observed == manifest
    assert _read(evidence / "adoption/verification.json")["passed"]
    assert _read(evidence / "customized-conflict/verification.json")["passed"]
