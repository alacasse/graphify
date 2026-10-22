"""Timing persistence and command measurements independent of installer expectations."""

import json
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.native_case_support import NativeCase
from tools.install_sandbox.container.evidence_writer import TestResultWriter as ResultWriter
from tools.install_sandbox.container.installer import command_environment, execute_command
from tools.install_sandbox.host.timing_reader import read_timings


def test_progress_writes_are_outside_phase_duration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks = [0]
    monkeypatch.setattr(time, "monotonic_ns", lambda: ticks[0])
    writer = ResultWriter(tmp_path)
    writer.initialize_timings("reinstall", 2)
    replace_file = Path.replace

    def slow_write(path: Path, target: Path) -> Path:
        ticks[0] += 1_000_000_000
        return replace_file(path, target)

    monkeypatch.setattr(Path, "replace", slow_write)
    with writer.measure("initial"):
        assert (
            json.loads((tmp_path / "timings.json").read_text())["phases"][0]["state"] == "running"
        )
        ticks[0] += 2_000_000_000
    writer.finish_timings(0)
    data = json.loads((tmp_path / "timings.json").read_text())
    assert data["phases"][0]["duration_seconds"] == 2.0
    assert data["duration_seconds"] == 4.0
    assert ticks[0] == 5_000_000_000  # Last timing write cannot measure itself.


def test_driver_uses_monotonic_elapsed_for_real_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks = iter([10_000_000_000, 12_250_000_000])
    monkeypatch.setattr(time, "monotonic_ns", lambda: next(ticks))
    result = execute_command(
        [sys.executable, "-c", "print('done')"],
        tmp_path,
        command_environment(tmp_path, tmp_path),
        5,
    )
    assert result.exit_code == 0 and result.stdout == b"done\n"
    assert result.duration_seconds == 2.25


def test_killed_process_leaves_completed_and_running_phases(tmp_path: Path) -> None:
    local = NativeCase(tmp_path)
    script = (
        "import sys, time\nfrom pathlib import Path\n"
        "from tools.install_sandbox.container.evidence_writer import TestResultWriter\n"
        "w = TestResultWriter(Path(sys.argv[1]))\n"
        "w.initialize_timings('reinstall', 2)\n"
        "with w.measure('initial'): pass\n"
        "with w.measure('command', 0):\n"
        "    print('ready', flush=True)\n    time.sleep(60)\n"
    )
    output = local.root / "results"
    with subprocess.Popen(
        [sys.executable, "-c", script, str(output)], stdout=subprocess.PIPE
    ) as process:
        try:
            assert process.stdout is not None
            assert select.select([process.stdout], [], [], 5)[0]
            assert process.stdout.readline() == b"ready\n"
        finally:
            process.kill()
            process.communicate(timeout=5)
    case = local.case
    result = read_timings(output, case)
    assert result.duration_seconds is None and result.diagnostics
    assert result.phases[0].state == "measured"
    assert result.phases[1].state == "running" and result.phases[1].duration_seconds is None
    assert result.phases[2].state == "pending"
