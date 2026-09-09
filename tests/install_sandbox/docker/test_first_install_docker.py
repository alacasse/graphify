"""Explicitly opted-in, serial proof of one reference case through the coordinator."""

import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import cast

import pytest

from tools.install_sandbox.coordinator import FirstInstallResult, InstallTestCoordinator
from tools.install_sandbox.result_reader import safe_evidence_path

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INSTALL_SANDBOX_DOCKER") != "1",
    reason="Set RUN_INSTALL_SANDBOX_DOCKER=1 to run one real Docker case",
)
_ROOT = Path(__file__).resolve().parents[3]


def _git(subject: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(subject), *args], text=True)


def _subject_state(subject: Path) -> dict[str, object]:
    paths = _git(subject, "ls-files", "-z").split("\0")
    return {
        "head": _git(subject, "rev-parse", "HEAD").strip(),
        "branch": _git(subject, "branch", "--show-current").strip(),
        "status": _git(subject, "status", "--porcelain=v1", "--untracked-files=all"),
        "files": {
            name: hashlib.sha256((subject / name).read_bytes()).hexdigest()
            for name in paths
            if name and (subject / name).is_file()
        },
    }


def _runtime(directory: Path) -> Path:
    docker = shutil.which("docker")
    assert docker is not None, "Docker executable is required for the opted-in proof"
    wrapper = directory / "record-docker"
    wrapper.write_text(
        "#!/usr/bin/env python3\nimport json, os, sys\n"
        f"with open({str(directory / 'docker-commands.jsonl')!r}, 'a') as stream:\n"
        "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        f"os.execv({docker!r}, [{docker!r}, *sys.argv[1:]])\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return wrapper


def _assert_execution(directory: Path, result: FirstInstallResult) -> None:
    assert result.container.state == "completed", asdict(result)
    commands = [
        cast(list[str], json.loads(line))
        for line in (directory / "docker-commands.jsonl").read_text().splitlines()
    ]
    build = next(command for command in commands if command[0] == "build")
    run = next(command for command in commands if command[0] == "run")
    assert result.container.image_id is not None and result.container.image_id in run
    assert build[-1] == str(_ROOT / "tools/install_sandbox")
    assert build[build.index("--tag") + 1] == f"install-sandbox-case:{result.container.run_id}"
    mounts = [run[index + 1] for index, arg in enumerate(run) if arg == "--mount"]
    assert len(mounts) == 3
    assert sum("readonly" in mount for mount in mounts) == 2
    assert result.container.cleanup_complete
    assert result.container.phase == "complete"
    assert result.passed, asdict(result)


def _assert_saved_evidence(result: FirstInstallResult) -> None:
    output = result.output_directory
    count = 0
    for relative in ("expected.json", "steps/0/before.json", "steps/0/after.json"):
        snapshot = cast(
            dict[str, object], json.loads(safe_evidence_path(output, relative).read_bytes())
        )
        for entry in cast(list[dict[str, object]], snapshot["entries"]):
            reference = entry.get("content_file")
            if isinstance(reference, str):
                safe_evidence_path(output, reference).read_bytes()
                count += 1
    assert count > 0
    for relative in ("journal.log", "preparation.log", "steps/0/stdout.txt", "steps/0/stderr.txt"):
        safe_evidence_path(output, relative).read_bytes()
    assert result.test is not None
    command = result.test.steps[0]["command"]
    assert command is not None
    assert command["args"] == [
        "/sandbox/work/case/software/venv/bin/graphify",
        "install",
        "--platform",
        "sandbox-reference",
        "--project",
    ]
    preparation = (output / "preparation.log").read_text()
    assert "Successfully installed" in preparation
    assert "/sandbox/work/case/software/source" in preparation


def _assert_owned_cleanup(directory: Path, result: FirstInstallResult) -> None:
    runtime = str(directory / "record-docker")
    name = f"install-sandbox-case-{result.container.run_id}"
    tag = f"install-sandbox-case:{result.container.run_id}"
    for arguments in (
        ["container", "ls", "--all", "--quiet", "--filter", f"name=^/{name}$"],
        ["image", "ls", "--quiet", "--filter", f"reference={tag}"],
    ):
        assert not subprocess.check_output([runtime, *arguments], text=True).strip()


def test_first_install_docker() -> None:
    subject = Path(os.environ["INSTALL_SANDBOX_SUBJECT"]).resolve()
    directory = Path(os.environ["INSTALL_SANDBOX_EVIDENCE_DIRECTORY"]).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    before = _subject_state(subject)
    (directory / "subject-before.json").write_text(json.dumps(before, indent=2))
    start = time.monotonic()
    result = InstallTestCoordinator().run_first_install(
        specs_directory=_ROOT / "tools/install_sandbox/specs/reference",
        target="sandbox-reference",
        subject_checkout=subject,
        case_file=directory / "case.json",
        output_directory=directory / "results",
        runtime_executable=_runtime(directory),
        build_timeout_seconds=float(os.environ.get("INSTALL_SANDBOX_BUILD_TIMEOUT", "300")),
        run_timeout_seconds=float(os.environ.get("INSTALL_SANDBOX_RUN_TIMEOUT", "900")),
    )
    after = _subject_state(subject)
    summary = {
        "duration_seconds": time.monotonic() - start,
        "result": asdict(result),
        "subject_after": after,
        "subject_preserved": before == after,
    }
    (directory / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    assert before == after, "Subject checkout changed"
    _assert_execution(directory, result)
    _assert_owned_cleanup(directory, result)
    _assert_saved_evidence(result)
