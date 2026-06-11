from __future__ import annotations

import json
import os
import sys

from tools.install_sandbox import command_runner


def test_run_capture_timeout_serialization(tmp_path) -> None:
    artifact = tmp_path / "artifact"

    result = command_runner.run_capture(
        (sys.executable, "-c", "import time; time.sleep(1)"),
        cwd=tmp_path,
        env=os.environ.copy(),
        artifact_dir=artifact,
        command_class="unit_timeout",
        timeout_seconds=0,
    )

    saved = json.loads((artifact / "command-result.json").read_text(encoding="utf-8"))
    assert result.returncode == 124
    assert result.timed_out is True
    assert result.timeout_seconds == 0
    assert result.command_class == "unit_timeout"
    assert saved["timed_out"] is True
    assert saved["timeout_seconds"] == 0
    assert saved["command_class"] == "unit_timeout"
    assert (artifact / "exit-code.txt").read_text(encoding="utf-8") == "124\n"
    assert "[timed-out]\ntrue" in (artifact / "transcript.txt").read_text(encoding="utf-8")


def test_shell_safe_command_display_and_start_artifacts(tmp_path) -> None:
    artifact = tmp_path / "artifact"

    command_runner.run_capture(
        (sys.executable, "-c", "print('hello world')"),
        cwd=tmp_path,
        env=os.environ.copy(),
        artifact_dir=artifact,
        command_class="unit",
    )

    saved = json.loads((artifact / "command-result.json").read_text(encoding="utf-8"))
    command_text = saved["command_display"]
    assert "'hello world'" in command_text or '"hello world"' in command_text
    assert (artifact / "command.txt").read_text(encoding="utf-8").strip() == command_text
    assert saved["command"] == [sys.executable, "-c", "print('hello world')"]
    assert saved["command_class"] == "unit"
    assert saved["exit_code"] == 0
    assert isinstance(saved["duration_ms"], int)


def test_command_result_metadata_records_artifact_fields(tmp_path) -> None:
    metadata = command_runner.command_result_metadata(
        command_list=["graphify", "install", "--platform", "codex"],
        command_text="graphify install --platform codex",
        command_class="installer",
        cwd=tmp_path,
        started_at="2026-06-02T00:00:00Z",
        duration_ms=17,
        exit_code=2,
        timeout=120,
        timed_out=False,
    )

    assert metadata == {
        "command": ["graphify", "install", "--platform", "codex"],
        "command_display": "graphify install --platform codex",
        "command_class": "installer",
        "cwd": str(tmp_path),
        "started_at": "2026-06-02T00:00:00Z",
        "duration_ms": 17,
        "exit_code": 2,
        "timeout_seconds": 120,
        "timed_out": False,
    }
