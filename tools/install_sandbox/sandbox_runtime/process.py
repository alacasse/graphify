"""Bounded subprocess and stream custody for the Sandbox Runtime."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from tools.install_sandbox.validation.protocol import (
    OperationEvent,
    OperationKind,
    StreamCapture,
)


@dataclass(frozen=True, slots=True)
class ProcessExecution:
    exit_code: int
    signal: int | None
    timed_out: bool
    stdout: StreamCapture
    stderr: StreamCapture
    started_ns: int
    finished_ns: int
    chronology: tuple[OperationEvent, ...]


@dataclass(frozen=True, slots=True)
class ProcessFailure:
    operation: str
    detail: str
    chronology: tuple[OperationEvent, ...]


@dataclass(slots=True)
class _BoundedCapture:
    limit: int
    data: bytearray
    total_bytes: int = 0
    error: str | None = None

    @classmethod
    def open(cls, limit: int) -> _BoundedCapture:
        return cls(limit, bytearray())

    def append(self, chunk: bytes) -> None:
        self.total_bytes += len(chunk)
        remaining = self.limit - len(self.data)
        if remaining > 0:
            self.data.extend(chunk[:remaining])

    def finish(self, *, process_complete: bool) -> StreamCapture:
        omitted = self.total_bytes - len(self.data)
        return StreamCapture(
            bytes(self.data),
            process_complete and omitted == 0 and self.error is None,
            omitted,
            self.error,
        )


def _pump(stream: BinaryIO, capture: _BoundedCapture) -> None:
    try:
        while chunk := stream.read(64 * 1024):
            capture.append(chunk)
    except OSError as error:
        capture.error = str(error)
    finally:
        stream.close()


class LocalProcessRunner:
    """Own one process group and bound its lifetime and in-memory capture."""

    def __init__(
        self,
        timeout_seconds: float,
        termination_grace_seconds: float,
        capture_limit_bytes: int,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._termination_grace_seconds = termination_grace_seconds
        self._capture_limit_bytes = capture_limit_bytes

    def _signal_group(self, process: subprocess.Popen[bytes], value: int) -> str | None:
        try:
            os.killpg(process.pid, value)
        except ProcessLookupError:
            return None
        except OSError as error:
            return str(error)
        return None

    def _group_exists(self, process: subprocess.Popen[bytes]) -> bool:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            return True
        return True

    def _join_pumps(
        self,
        threads: tuple[threading.Thread, threading.Thread],
    ) -> bool:
        deadline = time.monotonic() + self._termination_grace_seconds
        for thread in threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        return not any(thread.is_alive() for thread in threads)

    def _terminate_group(
        self,
        process: subprocess.Popen[bytes],
        chronology: list[OperationEvent],
        event: Callable[[OperationKind], OperationEvent],
    ) -> str | None:
        error = self._signal_group(process, signal.SIGTERM)
        chronology.append(event(OperationKind.COMMAND_TERMINATED))
        if error is not None:
            return error
        try:
            process.wait(timeout=self._termination_grace_seconds)
            return None
        except subprocess.TimeoutExpired:
            chronology.append(event(OperationKind.COMMAND_KILL_ESCALATED))
        error = self._signal_group(process, signal.SIGKILL)
        if error is not None:
            return error
        try:
            process.wait(timeout=self._termination_grace_seconds)
        except subprocess.TimeoutExpired:
            return "process group did not terminate after SIGKILL"
        return None

    def _spawn(
        self,
        argv: tuple[str, ...],
        cwd: Path,
        environment: dict[str, str],
        event: Callable[[OperationKind], OperationEvent],
    ) -> tuple[subprocess.Popen[bytes], OperationEvent] | ProcessFailure:
        started = event(OperationKind.COMMAND_STARTED)
        try:
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                start_new_session=True,
            )
        except OSError as error:
            failed = event(OperationKind.COMMAND_FAILED)
            return ProcessFailure("spawn_command", str(error), (started, failed))
        return process, started

    def _start_pumps(
        self,
        process: subprocess.Popen[bytes],
    ) -> tuple[
        tuple[threading.Thread, threading.Thread],
        tuple[_BoundedCapture, _BoundedCapture],
    ]:
        assert process.stdout is not None
        assert process.stderr is not None
        captures = (
            _BoundedCapture.open(self._capture_limit_bytes),
            _BoundedCapture.open(self._capture_limit_bytes),
        )
        threads = (
            threading.Thread(target=_pump, args=(process.stdout, captures[0]), daemon=True),
            threading.Thread(target=_pump, args=(process.stderr, captures[1]), daemon=True),
        )
        for thread in threads:
            thread.start()
        return threads, captures

    def _await_process(
        self,
        process: subprocess.Popen[bytes],
        chronology: list[OperationEvent],
        event: Callable[[OperationKind], OperationEvent],
    ) -> tuple[bool, str | None]:
        try:
            process.wait(timeout=self._timeout_seconds)
        except subprocess.TimeoutExpired:
            chronology.append(event(OperationKind.COMMAND_TIMED_OUT))
            return True, self._terminate_group(process, chronology, event)
        return False, None

    def _seal_pumps(
        self,
        process: subprocess.Popen[bytes],
        threads: tuple[threading.Thread, threading.Thread],
        captures: tuple[_BoundedCapture, _BoundedCapture],
        chronology: list[OperationEvent],
        event: Callable[[OperationKind], OperationEvent],
        *,
        timed_out: bool,
    ) -> None:
        pumps_complete = self._join_pumps(threads)
        group_exists = self._group_exists(process)
        if pumps_complete and not group_exists:
            return
        if not timed_out:
            self._record_capture_error(captures, "command left descendant processes running")
            termination_error = self._terminate_group(process, chronology, event)
            if termination_error is not None:
                self._record_capture_error(captures, termination_error)
            pumps_complete = self._join_pumps(threads)
            group_exists = self._group_exists(process)
            if pumps_complete and not group_exists:
                return
        self._kill_open_pumps(process, threads, captures, chronology, event)

    def _record_capture_error(
        self,
        captures: tuple[_BoundedCapture, _BoundedCapture],
        detail: str,
    ) -> None:
        for capture in captures:
            capture.error = capture.error or detail

    def _kill_open_pumps(
        self,
        process: subprocess.Popen[bytes],
        threads: tuple[threading.Thread, threading.Thread],
        captures: tuple[_BoundedCapture, _BoundedCapture],
        chronology: list[OperationEvent],
        event: Callable[[OperationKind], OperationEvent],
    ) -> None:
        if not any(item.kind is OperationKind.COMMAND_KILL_ESCALATED for item in chronology):
            chronology.append(event(OperationKind.COMMAND_KILL_ESCALATED))
        kill_error = self._signal_group(process, signal.SIGKILL)
        if kill_error is not None:
            self._record_capture_error(captures, kill_error)
        if not self._join_pumps(threads):
            self._record_capture_error(captures, "stream capture did not seal after SIGKILL")

    def run(
        self,
        argv: tuple[str, ...],
        cwd: Path,
        environment: dict[str, str],
        event: Callable[[OperationKind], OperationEvent],
    ) -> ProcessExecution | ProcessFailure:
        """Run one command with bounded process-group and stream ownership."""

        spawned = self._spawn(argv, cwd, environment, event)
        if isinstance(spawned, ProcessFailure):
            return spawned
        process, started = spawned
        threads, captures = self._start_pumps(process)
        chronology = [started]
        timed_out, termination_error = self._await_process(process, chronology, event)
        if termination_error is not None:
            chronology.append(event(OperationKind.COMMAND_FAILED))
            return ProcessFailure(
                "terminate_process_group",
                termination_error,
                tuple(chronology),
            )
        self._seal_pumps(
            process,
            threads,
            captures,
            chronology,
            event,
            timed_out=timed_out,
        )
        exit_code = process.returncode
        if exit_code is None:
            chronology.append(event(OperationKind.COMMAND_FAILED))
            return ProcessFailure(
                "reap_process",
                "process has no terminal return code",
                tuple(chronology),
            )
        finished = event(OperationKind.COMMAND_FINISHED)
        chronology.append(finished)
        return ProcessExecution(
            exit_code,
            -exit_code if exit_code < 0 else None,
            timed_out,
            captures[0].finish(process_complete=not timed_out),
            captures[1].finish(process_complete=not timed_out),
            started.occurred_ns,
            finished.occurred_ns,
            tuple(chronology),
        )
