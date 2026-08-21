"""Trusted Linux subprocess supervisor for one sandbox command tree."""

from __future__ import annotations

import ctypes
import errno
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import FrameType
from typing import Protocol, cast

_PR_SET_CHILD_SUBREAPER = 36
_STATUS_FD_ENV = "GRAPHIFY_SANDBOX_SUPERVISOR_STATUS_FD"
_TERM_GRACE_SECONDS = 0.05
_KILL_GRACE_SECONDS = 0.1
_requested_signal: int | None = None


class _Prctl(Protocol):
    def __call__(
        self,
        option: int,
        argument_2: int,
        argument_3: int,
        argument_4: int,
        argument_5: int,
    ) -> int: ...


def _enable_subreaper() -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    prctl = cast(_Prctl, libc.prctl)
    if prctl(_PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))


def _record_signal(value: int, _frame: FrameType | None) -> None:
    global _requested_signal
    _requested_signal = value


def _read_parent_pid(path: Path) -> tuple[int, int] | None:
    try:
        pid = int(path.name)
        remainder = (path / "stat").read_text(encoding="ascii").rsplit(")", maxsplit=1)[1]
        parent_pid = int(remainder.split()[1])
    except (IndexError, OSError, ValueError):
        return None
    return pid, parent_pid


def _descendants() -> set[int]:
    parent_by_pid = dict(
        item
        for path in Path("/proc").iterdir()
        if path.name.isdigit() and (item := _read_parent_pid(path)) is not None
    )
    descendants: set[int] = set()
    frontier = {os.getpid()}
    while frontier:
        children = {
            pid
            for pid, parent_pid in parent_by_pid.items()
            if parent_pid in frontier and pid not in descendants
        }
        descendants.update(children)
        frontier = children
    return descendants


def _signal_all(process_ids: set[int], value: int) -> None:
    for process_id in process_ids:
        try:
            os.kill(process_id, value)
        except ProcessLookupError:
            continue


def _wait_for_no_descendants(deadline: float) -> bool:
    while time.monotonic() < deadline:
        _reap_adopted_children(None)
        if not _descendants():
            return True
        time.sleep(0.005)
    return not _descendants()


def _reap_adopted_children(target_pid: int | None) -> None:
    candidates = _descendants() if target_pid is not None else None
    while True:
        try:
            if candidates is None:
                child, _status = os.waitpid(-1, os.WNOHANG)
            else:
                child = 0
                for candidate in candidates - {target_pid}:
                    try:
                        child, _status = os.waitpid(candidate, os.WNOHANG)
                    except ChildProcessError:
                        continue
                    if child != 0:
                        break
        except ChildProcessError:
            return
        if child == 0:
            return


def _terminate_tree(process: subprocess.Popen[bytes]) -> tuple[bool, bool, bool]:
    descendants = _descendants()
    terminated = bool(descendants)
    _signal_all(descendants, signal.SIGTERM)
    term_deadline = time.monotonic() + _TERM_GRACE_SECONDS
    while time.monotonic() < term_deadline:
        process.poll()
        _reap_adopted_children(process.pid)
        if not _descendants():
            return terminated, False, True
        time.sleep(0.005)

    escalated = bool(_descendants())
    kill_deadline = time.monotonic() + _KILL_GRACE_SECONDS
    while time.monotonic() < kill_deadline:
        remaining = _descendants()
        if not remaining:
            break
        _signal_all(remaining, signal.SIGKILL)
        process.poll()
        _reap_adopted_children(process.pid)
        time.sleep(0.005)
    try:
        process.wait(timeout=max(0.0, kill_deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        return terminated, True, False
    _reap_adopted_children(None)
    return terminated, escalated, _wait_for_no_descendants(kill_deadline)


def _write_status(status_fd: int, value: str) -> None:
    try:
        os.write(status_fd, value.encode())
    except OSError as error:
        if error.errno != errno.EPIPE:
            raise


def _exit_like(returncode: int) -> None:
    if returncode >= 0:
        raise SystemExit(returncode)
    exit_signal = -returncode
    if exit_signal not in {signal.SIGKILL, signal.SIGSTOP}:
        signal.signal(exit_signal, signal.SIG_DFL)
    os.kill(os.getpid(), exit_signal)
    raise AssertionError("signal did not terminate supervisor")


def _start_process(
    argv: tuple[str, ...],
    status_fd: int,
) -> subprocess.Popen[bytes] | None:
    try:
        _enable_subreaper()
    except OSError as error:
        _write_status(status_fd, f"CUSTODY_ERROR:{error}")
        return None
    signal.signal(signal.SIGTERM, _record_signal)
    signal.signal(signal.SIGINT, _record_signal)
    try:
        process = subprocess.Popen(argv, shell=False)
    except OSError as error:
        _write_status(status_fd, f"SPAWN_ERROR:{error}")
        return None
    _write_status(status_fd, "SPAWNED")
    return process


def _supervise(process: subprocess.Popen[bytes], status_fd: int) -> int:
    while process.poll() is None and _requested_signal is None:
        time.sleep(0.005)
    returncode = process.returncode
    terminated, escalated, quiescent = _terminate_tree(process)
    if terminated:
        _write_status(status_fd, "DESCENDANTS_TERMINATED")
    if escalated:
        _write_status(status_fd, "KILL_ESCALATED")
    if not quiescent:
        _write_status(status_fd, "CUSTODY_ERROR:descendants did not reach quiescence")
    if returncode is None:
        returncode = process.wait()
    _write_status(status_fd, f"TARGET_EXIT:{returncode}")
    if quiescent:
        _write_status(status_fd, "QUIESCENT")
    if _requested_signal is not None and returncode >= 0:
        return -_requested_signal
    return returncode


def main() -> int:
    """Run argv under subreaper custody and reproduce its terminal status."""

    raw_status_fd = os.environ.pop(_STATUS_FD_ENV, None)
    if raw_status_fd is None:
        return 125
    status_fd = int(raw_status_fd)
    argv = tuple(sys.argv[1:])
    if not argv:
        _write_status(status_fd, "SPAWN_ERROR:command argv is empty")
        return 125
    process = _start_process(argv, status_fd)
    if process is None:
        return 127
    returncode = _supervise(process, status_fd)
    os.close(status_fd)
    _exit_like(returncode)
    return 125


if __name__ == "__main__":
    raise SystemExit(main())
