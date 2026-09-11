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

from tools.install_sandbox.coordinator import (
    CampaignResult,
    CoordinatedResult,
    InstallTestCoordinator,
)
from tools.install_sandbox.result_reader import safe_evidence_path
from tools.install_sandbox.timing_report import format_duration, render_campaign
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
    run = next(
        command
        for command in commands
        if command[0] == "run" and result.container.run_id in " ".join(command)
    )
    assert result.container.image_id is not None and result.container.image_id in run
    assert not Path(build[-1]).exists()
    assert build[build.index("--tag") + 1].startswith("install-sandbox-campaign:")
    mounts = [run[index + 1] for index, arg in enumerate(run) if arg == "--mount"]
    assert len(mounts) == 2
    assert sum("readonly" in mount for mount in mounts) == 1
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
            "/opt/install-sandbox/venv/bin/graphify",
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
    assert "inherited from campaign" in preparation
    assert "pip" not in preparation


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


def _assert_owned_cleanup(directory: Path, result: CampaignResult) -> None:
    runtime = str(directory / "record-docker")
    assert result.preparation is not None and result.cleanup is not None
    assert result.cleanup.cleanup_complete
    tag = f"install-sandbox-campaign:{result.preparation.run_id}"
    assert not subprocess.check_output(
        [runtime, "image", "ls", "--quiet", "--filter", f"reference={tag}"],
        text=True,
        timeout=15,
    ).strip()
    commands = [
        json.loads(line) for line in (directory / "docker-commands.jsonl").read_text().splitlines()
    ]
    for command in commands:
        if command[0] == "run":
            name = command[command.index("--name") + 1]
            assert not subprocess.check_output(
                [
                    runtime,
                    "container",
                    "ls",
                    "--all",
                    "--quiet",
                    "--filter",
                    f"name=^/{name}$",
                ],
                text=True,
                timeout=15,
            ).strip()


def run_proof(
    case_name: str,
    check_case: Callable[[CoordinatedResult], None] | None = None,
) -> CoordinatedResult:
    campaign = run_campaign_proof([case_name], check_case)
    result = campaign.cases[0].result
    assert result is not None
    return result


def run_campaign_proof(
    names: list[str],
    check_case: Callable[[CoordinatedResult], None] | None = None,
) -> CampaignResult:
    subject = Path(os.environ["INSTALL_SANDBOX_SUBJECT"]).resolve()
    directory = Path(os.environ["INSTALL_SANDBOX_EVIDENCE_DIRECTORY"]).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    result = InstallTestCoordinator().run_campaign(
        specs_directory=_ROOT / "tools/install_sandbox/specs/reference",
        target="sandbox-reference",
        case_names=names,
        subject_checkout=subject,
        output_directory=directory / "campaign",
        runtime_executable=_runtime(directory),
        build_timeout_seconds=float(os.environ.get("INSTALL_SANDBOX_BUILD_TIMEOUT", "300")),
        run_timeout_seconds=float(os.environ.get("INSTALL_SANDBOX_RUN_TIMEOUT", "900")),
    )
    checks = Timing("additional_checks")
    try:
        with measure(checks):
            assert result.passed, asdict(result)
            _assert_owned_cleanup(directory, result)
            for entry in result.cases:
                case = entry.result
                assert case is not None
                _assert_execution(directory, case)
                _assert_saved_evidence(case)
                if check_case is not None:
                    check_case(case)
                _assert_timings(case)
            _assert_shared_image(directory, result)
    finally:
        _write_summary(directory, result, checks)
    return result


def _assert_shared_image(directory: Path, result: CampaignResult) -> None:
    commands = [
        json.loads(line) for line in (directory / "docker-commands.jsonl").read_text().splitlines()
    ]
    runs = [c for c in commands if c[0] == "run"]
    assert len([c for c in commands if c[0] == "build"]) == 1
    assert len(runs) == len(result.cases) + 1
    assert any(argument.endswith("/verify_preparation.py") for argument in runs[0])
    assert result.preparation is not None
    assert all(result.preparation.image_id in c for c in runs)
    assert len({c[c.index("--name") + 1] for c in runs}) == len(runs)
    assert (result.output_directory / "preparation/build.log").stat().st_size > 0
    assert (result.output_directory / "preparation/verify.log").stat().st_size > 0


def _assert_timings(result: CoordinatedResult) -> None:
    assert result.duration_seconds is not None
    assert not result.container_timings.diagnostics, asdict(result.container_timings)
    assert result.container_timings.duration_seconds is not None
    assert all(record.state == "measured" for record in result.timings)
    assert all(record.state == "measured" for record in result.container_timings.phases)


def _write_summary(directory: Path, result: CampaignResult, checks: Timing) -> None:
    summary = {
        "duration_seconds": result.duration_seconds,
        "additional_checks": asdict(checks),
        "result": asdict(result),
    }
    (directory / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    (directory / "summary.txt").write_text(
        render_campaign(result)
        + f"Additional test checks: {format_duration(checks.duration_seconds)}\n",
        encoding="utf-8",
    )


def test_first_install_docker() -> None:
    run_proof("first-install")
