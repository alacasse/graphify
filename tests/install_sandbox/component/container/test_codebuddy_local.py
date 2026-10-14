"""Opt-in isolated CodeBuddy qualification retaining the known product failure."""

import hashlib
import json
import os
import shutil
import sys
from email.parser import Parser
from pathlib import Path
from typing import Any

import pytest

from tools.install_sandbox.container.installer import InstallerDriver
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.case import InstallTestCase
from tools.install_sandbox.contracts.results import InstallTestResult
from tools.install_sandbox.host.coordinator import InstallTestCoordinator
from tools.install_sandbox.host.result_reader import read_result

_SUBJECT = os.environ.get("INSTALL_SANDBOX_CODEBUDDY_SUBJECT")
_EVIDENCE = os.environ.get("INSTALL_SANDBOX_CODEBUDDY_EVIDENCE")
_SPECS = Path(__file__).resolve().parents[4] / "tools/install_sandbox/specs/codebuddy-local"
pytestmark = pytest.mark.skipif(not _SUBJECT, reason="Supply INSTALL_SANDBOX_CODEBUDDY_SUBJECT")


def _require_isolation() -> None:
    interfaces = {
        line.split(":", 1)[0].strip()
        for line in Path("/proc/net/dev").read_text().splitlines()
        if ":" in line
    }
    assert interfaces == {"lo"}, "Qualification requires an isolated network namespace"
    masked_home = os.environ.get("INSTALL_SANDBOX_MASKED_HOME")
    assert masked_home, "Supply the original user's masked home path"
    home = Path(masked_home).resolve(strict=True)
    mounts = [
        line.split(" - ", 1) for line in Path("/proc/self/mountinfo").read_text().splitlines()
    ]
    assert any(
        left.split()[4] == str(home) and right.split()[0] == "tmpfs" for left, right in mounts
    ), "Qualification requires a tmpfs mount over the original user's home"
    projects = [_SPECS.parents[3]]
    if reference := os.environ.get("INSTALL_SANDBOX_REFERENCE_SUBJECT"):
        projects.append(Path(reference).resolve(strict=True))
    _check_exposed_projects(home, projects)


def _check_exposed_projects(home: Path, projects: list[Path]) -> None:
    allowed: dict[Path, set[str]] = {}
    for project in projects:
        assert project.is_relative_to(home)
        parent = home
        for part in project.relative_to(home).parts:
            allowed.setdefault(parent, set()).add(part)
            parent /= part
    for parent, names in allowed.items():
        assert {child.name for child in parent.iterdir()} == names, (
            "The masked home may expose only declared project checkouts"
        )


def _source_manifest(subject: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for path in sorted(subject.rglob("*")):
        assert not path.is_symlink(), "Captured subject must contain no symlinks"
        if path.is_file():
            manifest[path.relative_to(subject).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    assert "graphify/install.py" in manifest
    assert "graphifyy.dist-info/METADATA" in manifest
    return manifest


def _launcher(subject: Path, path: Path) -> None:
    path.write_text(
        f"#!{sys.executable}\n"
        "import importlib, importlib.metadata, json, os, sys\n"
        "from pathlib import Path\n"
        f"subject = Path({str(subject)!r})\n"
        "sys.path.insert(0, str(subject))\n"
        "sys.dont_write_bytecode = True\n"
        "config = Path(os.environ['TMPDIR']) / 'configuration'\n"
        "for name in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'XDG_STATE_HOME',\n"
        "             'CLAUDE_CONFIG_DIR', 'CODEX_HOME', 'APPDATA', 'LOCALAPPDATA'):\n"
        "    os.environ[name] = str(config / name.lower())\n"
        "os.environ['USERPROFILE'] = os.environ['HOME']\n"
        "cli = importlib.import_module('graphify.__main__')\n"
        "installer = importlib.import_module('graphify.install')\n"
        "assert Path(cli.__file__).resolve() == subject / 'graphify/__main__.py'\n"
        "assert Path(installer.__file__).resolve() == subject / 'graphify/install.py'\n"
        "distribution = importlib.metadata.distribution('graphifyy')\n"
        "captured_metadata = (subject / 'graphifyy.dist-info/METADATA').read_text()\n"
        "assert distribution.read_text('METADATA') == captured_metadata\n"
        "version = distribution.version\n"
        "print('CodeBuddy package version: ' + version, flush=True)\n"
        "try:\n"
        "    cli.main()\n"
        "finally:\n"
        "    origins = {name: str(Path(module.__file__).resolve())\n"
        "               for name, module in list(sys.modules.items())\n"
        "               if (name == 'graphify' or name.startswith('graphify.'))\n"
        "               and getattr(module, '__file__', None)}\n"
        "    assert all(Path(origin).is_relative_to(subject) for origin in origins.values())\n"
        "    print('CodeBuddy import origins: '\n"
        "          + json.dumps(origins, sort_keys=True), flush=True)\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _assert_hook_diagnostics(
    case: InstallTestCase, document: dict[str, Any], result: InstallTestResult
) -> None:
    verification = result.steps[0]["verification"]
    assert verification is not None
    for expected in case.spec.json_hooks:
        groups = document["hooks"].get(expected.event, [])
        hooks = [
            hook
            for group in groups
            if group.get("matcher") == expected.matcher
            for hook in group["hooks"]
        ]
        matches = sum(
            all(hook.get(key) == value for key, value in expected.content.items()) for hook in hooks
        )
        diagnostics = [
            mismatch
            for mismatch in verification.mismatches
            if mismatch.type == "hook_count"
            and json.loads(mismatch.expected)["matcher"] == expected.matcher
        ]
        assert bool(diagnostics) == (matches != 1), (expected, hooks, verification)
        if diagnostics:
            assert json.loads(diagnostics[0].observed)["count"] == matches


def _assert_failure(result: InstallTestResult) -> None:
    assert result.status == "failed", result
    assert len(result.steps) == 1
    command = result.steps[0]["command"]
    assert command is not None and command["state"] == "completed" and command["exit_code"] == 0
    assert command["args"][1:] == ["codebuddy", "install"]
    verification = result.steps[0]["verification"]
    assert verification is not None and verification.complete
    mismatches = verification.mismatches
    assert any(
        mismatch.type == "personal_hook_count" and "personal_graphify_audit.py" in mismatch.expected
        for mismatch in mismatches
    ), mismatches
    assert any(
        mismatch.type == "user_content_lost" and mismatch.path == ".codebuddy/settings.json"
        for mismatch in mismatches
    ), mismatches


def _assert_provenance(output: Path, subject: Path) -> None:
    stdout = (output / "steps/0/stdout.txt").read_text()
    origin_line = next(
        line for line in stdout.splitlines() if line.startswith("CodeBuddy import origins: ")
    )
    origins = json.loads(origin_line.removeprefix("CodeBuddy import origins: "))
    assert origins["graphify.install"] == str(subject / "graphify/install.py")
    version = Parser().parsestr((subject / "graphifyy.dist-info/METADATA").read_text())["Version"]
    assert version is not None
    assert "CodeBuddy package version: " + version in stdout


def _run_once(subject: Path, retained: Path, temporary: Path, case_file: Path) -> InstallTestResult:
    manifest = _source_manifest(subject)
    (retained / "subject-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    executable = temporary / "codebuddy-graphify"
    _launcher(subject, executable)
    work = temporary / "work"
    try:
        return InstallTestRunner(InstallerDriver(timeout=60)).run_case(
            reference_sources=subject,
            prepared_executable=executable,
            case_file=case_file,
            work_directory=work,
            output_directory=retained / "result",
        )
    finally:
        assert _source_manifest(subject) == manifest, "Qualification changed captured sources"
        if work.exists():
            shutil.rmtree(work)
        executable.unlink(missing_ok=True)


def test_real_codebuddy_first_install_retains_known_failure(tmp_path: Path) -> None:
    _require_isolation()
    assert _SUBJECT is not None and _EVIDENCE is not None
    subject = Path(_SUBJECT).resolve(strict=True)
    retained = Path(_EVIDENCE).resolve()
    assert not retained.exists() or not any(retained.iterdir()), "Evidence must be fresh"
    retained.mkdir(parents=True, exist_ok=True)
    case_file = retained / "case.json"
    case = InstallTestCoordinator().write_case(_SPECS, "codebuddy", case_file)
    result = _run_once(subject, retained, tmp_path, case_file)
    output = retained / "result"
    assert read_result(output, InstallTestCase.from_json(case_file.read_text())) == result
    _assert_failure(result)
    _assert_provenance(output, subject)
    settings = json.loads((output / "steps/0/after/project/.codebuddy/settings.json").read_bytes())
    _assert_hook_diagnostics(case, settings, result)
