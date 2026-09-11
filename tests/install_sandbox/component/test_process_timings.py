"""Observe process boundaries with local children, including delayed output readers."""

import json
import sys
import threading
import time
from pathlib import Path

import pytest

from tools.install_sandbox.container_harness import ContainerHarness


def _saved(root: Path) -> dict[str, dict[str, object]]:
    prefix = "INSTALL_SANDBOX_PROCESS_TIMINGS "
    line = next(
        line for line in (root / "cleanup.log").read_text().splitlines() if line.startswith(prefix)
    )
    return {p["phase"]: p for p in json.loads(line.removeprefix(prefix))["phases"]}


def test_waiting_child_is_not_charged_to_launch_reap_or_reader_joins(tmp_path: Path) -> None:
    with ContainerHarness(runtime_executable=sys.executable) as harness:
        harness.logs = tmp_path
        started = time.monotonic()
        result = harness._cleanup_command(  # pyright: ignore[reportPrivateUsage]
            ["-I", "-B", "-c", "import time; time.sleep(0.4); print('complete')"], 3
        )
        duration = time.monotonic() - started
    assert result.exit_code == 0 and "complete" in result.stdout_tail
    phases = _saved(tmp_path)
    assert set(phases) == {"client_launch", "post_detection_recovery", "stdout_join", "stderr_join"}
    measured = [r.duration_seconds for r in result.process_timings]
    assert all(value is not None and value >= 0 for value in measured)
    # The four measured intervals exclude the child's 0.4 second work/wait envelope.
    assert duration - sum(value or 0 for value in measured) >= 0.4
    assert all(p["state"] == "measured" and p["diagnostic"] is None for p in phases.values())


class _BlockedOutput:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.reader: threading.Thread | None = None

    def write(self, value: str) -> int:
        self.reader = threading.current_thread()
        self.release.wait(timeout=5)
        return len(value)

    def flush(self) -> None:
        pass


def test_join_reports_reader_still_alive_without_inventing_complete_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = _BlockedOutput()
    monkeypatch.setattr(sys, "stdout", output)
    try:
        with ContainerHarness(runtime_executable=sys.executable) as harness:
            harness.logs = tmp_path
            result = harness._cleanup_command(  # pyright: ignore[reportPrivateUsage]
                ["-I", "-B", "-c", "print('retained output')"], 3
            )
        assert result.exit_code == 0 and "retained output" in result.stdout_tail
        phases = _saved(tmp_path)
        assert "Reader still alive" in str(phases["stdout_join"]["diagnostic"])
        assert phases["stderr_join"]["diagnostic"] is None
        assert output.reader is not None and output.reader.is_alive()
    finally:
        output.release.set()
        if output.reader is not None:
            output.reader.join(timeout=2)
            assert not output.reader.is_alive()


def test_timeout_marks_recovery_as_forced_termination(tmp_path: Path) -> None:
    with ContainerHarness(
        runtime_executable=sys.executable, graceful_termination_seconds=0.1
    ) as harness:
        harness.logs = tmp_path
        result = harness._cleanup_command(  # pyright: ignore[reportPrivateUsage]
            ["-I", "-B", "-c", "import time; time.sleep(30)"], 0.1
        )
    assert result.timed_out and result.exit_code != 0
    assert _saved(tmp_path)["post_detection_recovery"]["diagnostic"] == (
        "Includes forced process-group termination"
    )


def test_failed_launch_has_no_fabricated_reap_or_join_durations(tmp_path: Path) -> None:
    with ContainerHarness(runtime_executable=tmp_path / "missing-executable") as harness:
        harness.logs = tmp_path
        result = harness._cleanup_command([], 1)  # pyright: ignore[reportPrivateUsage]
    assert result.exit_code == 127
    phases = _saved(tmp_path)
    assert set(phases) == {"client_launch"}
    assert phases["client_launch"]["state"] == "measured"
    assert "FileNotFoundError" in str(phases["client_launch"]["diagnostic"])
