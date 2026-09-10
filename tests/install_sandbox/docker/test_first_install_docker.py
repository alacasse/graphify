"""Explicitly opted-in, serial proof of one reference case through the coordinator."""

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import cast

import pytest

from tools.install_sandbox.coordinator import CoordinatedResult, InstallTestCoordinator
from tools.install_sandbox.result_reader import safe_evidence_path
from tools.install_sandbox.timing_report import render_timings
from tools.install_sandbox.timings import Timing, measure

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INSTALL_SANDBOX_DOCKER") != "1",
    reason="Set RUN_INSTALL_SANDBOX_DOCKER=1 to run one real Docker case",
)
_ROOT = Path(__file__).resolve().parents[3]


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


def _assert_execution(directory: Path, result: CoordinatedResult) -> None:
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


def _assert_saved_evidence(result: CoordinatedResult) -> None:
    output = result.output_directory
    assert result.test is not None
    references = ["expected.json"]
    for index, step in enumerate(result.test.steps):
        references.extend([f"steps/{index}/before.json", f"steps/{index}/after.json"])
        command = step["command"]
        assert command is not None
        assert command["args"] == [
            "/sandbox/work/case/software/venv/bin/graphify",
            "install",
            "--platform",
            "sandbox-reference",
            "--project",
        ]
        for name in ("stdout.txt", "stderr.txt", "verification.json"):
            safe_evidence_path(output, f"steps/{index}/{name}").read_bytes()
    for relative in references:
        _read_snapshot_contents(output, relative)
    for relative in ("journal.log", "preparation.log"):
        safe_evidence_path(output, relative).read_bytes()
    preparation = (output / "preparation.log").read_text()
    assert "Successfully installed" in preparation
    assert "/sandbox/work/case/software/source" in preparation


def _read_snapshot_contents(output: Path, relative: str) -> None:
    snapshot = cast(
        dict[str, object], json.loads(safe_evidence_path(output, relative).read_bytes())
    )
    assert not snapshot["obstacles"]
    references = [
        entry.get("content_file") for entry in cast(list[dict[str, object]], snapshot["entries"])
    ]
    count = 0
    for reference in references:
        if isinstance(reference, str):
            safe_evidence_path(output, reference).read_bytes()
            count += 1
    assert count > 0


def _assert_owned_cleanup(directory: Path, result: CoordinatedResult) -> None:
    runtime = str(directory / "record-docker")
    name = f"install-sandbox-case-{result.container.run_id}"
    tag = f"install-sandbox-case:{result.container.run_id}"
    for arguments in (
        ["container", "ls", "--all", "--quiet", "--filter", f"name=^/{name}$"],
        ["image", "ls", "--quiet", "--filter", f"reference={tag}"],
    ):
        assert not subprocess.check_output([runtime, *arguments], text=True).strip()


def run_proof(
    case_name: str, check_case: Callable[[CoordinatedResult], None] | None = None
) -> CoordinatedResult:
    subject = Path(os.environ["INSTALL_SANDBOX_SUBJECT"]).resolve()
    directory = Path(os.environ["INSTALL_SANDBOX_EVIDENCE_DIRECTORY"]).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    result = InstallTestCoordinator().run_case(
        specs_directory=_ROOT / "tools/install_sandbox/specs/reference",
        target="sandbox-reference",
        case_name=case_name,
        subject_checkout=subject,
        case_file=directory / "case.json",
        output_directory=directory / "results",
        runtime_executable=_runtime(directory),
        build_timeout_seconds=float(os.environ.get("INSTALL_SANDBOX_BUILD_TIMEOUT", "300")),
        run_timeout_seconds=float(os.environ.get("INSTALL_SANDBOX_RUN_TIMEOUT", "900")),
    )
    checks = Timing("additional_checks")
    try:
        with measure(checks):
            _assert_execution(directory, result)
            _assert_owned_cleanup(directory, result)
            _assert_saved_evidence(result)
            if check_case is not None:
                check_case(result)
            _assert_timings(result)
    finally:
        _write_summary(directory, result, checks)
    return result


def _assert_timings(result: CoordinatedResult) -> None:
    assert result.duration_seconds is not None
    assert not result.container_timings.diagnostics, asdict(result.container_timings)
    assert result.container_timings.duration_seconds is not None
    assert all(record.state == "measured" for record in result.timings)
    assert all(record.state == "measured" for record in result.container_timings.phases)


def _write_summary(directory: Path, result: CoordinatedResult, checks: Timing) -> None:
    summary = {
        "duration_seconds": result.duration_seconds,
        "additional_checks": asdict(checks),
        "result": asdict(result),
    }
    (directory / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    (directory / "summary.txt").write_text(render_timings(result, checks), encoding="utf-8")


def test_first_install_docker() -> None:
    run_proof("first-install")
