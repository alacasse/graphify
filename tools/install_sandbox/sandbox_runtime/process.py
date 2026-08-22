"""Bounded subprocess and stream custody for the Sandbox Runtime."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from tools.install_sandbox.validation.protocol import OperationEvent, OperationKind

from .process_capture import BoundedCapture, pump_stream
from .process_types import (
    IncompleteProcessExecution,
    ProcessExecution,
    ProcessFailure,
    SpawnedProcess,
)
from .supervisor_status import SupervisorStatus

MINIMUM_TERMINATION_GRACE_SECONDS = 0.25
_SUPERVISOR_MODULE = "tools.install_sandbox.sandbox_runtime.supervisor"


def _supervisor_bootstrap() -> str:
    repository_root = str(Path(__file__).resolve().parents[3])
    return (
        "import sys; "
        f"sys.path.insert(0, {repository_root!r}); "
        f"from {_SUPERVISOR_MODULE} import main; "
        "raise SystemExit(main())"
    )


class LocalProcessRunner:
    """Own one process group and bound its lifetime and in-memory capture."""

    def __init__(
        self,
        timeout_seconds: float,
        termination_grace_seconds: float,
        capture_limit_bytes: int,
    ) -> None:
        if termination_grace_seconds < MINIMUM_TERMINATION_GRACE_SECONDS:
            raise ValueError("termination grace must cover the trusted supervisor shutdown budget")
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
        try:
            process.terminate()
            error = None
        except OSError as process_error:
            error = str(process_error)
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
    ) -> SpawnedProcess | ProcessFailure:
        started = event(OperationKind.COMMAND_STARTED)
        status_parent, status_supervisor = socket.socketpair(
            socket.AF_UNIX,
            socket.SOCK_SEQPACKET,
        )
        status_fd = status_supervisor.fileno()
        supervisor_environment = dict(environment)
        supervisor_environment["GRAPHIFY_SANDBOX_SUPERVISOR_STATUS_FD"] = str(status_fd)
        try:
            process = subprocess.Popen(
                (
                    sys.executable,
                    "-c",
                    _supervisor_bootstrap(),
                    *argv,
                ),
                cwd=cwd,
                env=supervisor_environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                start_new_session=True,
                pass_fds=(status_fd,),
            )
        except OSError as error:
            status_parent.close()
            status_supervisor.close()
            failed = event(OperationKind.COMMAND_FAILED)
            return ProcessFailure("spawn_command", str(error), (started, failed))
        status_supervisor.close()
        return SpawnedProcess(process, status_parent, started)

    def _read_status(self, status_socket: socket.socket) -> tuple[str, ...]:
        frames: list[str] = []
        try:
            with status_socket:
                while payload := status_socket.recv(16 * 1024):
                    frames.append(payload.decode(errors="replace"))
        except OSError as error:
            frames.append(f"STATUS_ERROR:{error}")
        return tuple(frames)

    def _start_pumps(
        self,
        process: subprocess.Popen[bytes],
    ) -> tuple[
        tuple[threading.Thread, threading.Thread],
        tuple[BoundedCapture, BoundedCapture],
    ]:
        assert process.stdout is not None
        assert process.stderr is not None
        captures = (
            BoundedCapture.open(self._capture_limit_bytes),
            BoundedCapture.open(self._capture_limit_bytes),
        )
        threads = (
            threading.Thread(target=pump_stream, args=(process.stdout, captures[0]), daemon=True),
            threading.Thread(target=pump_stream, args=(process.stderr, captures[1]), daemon=True),
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
        captures: tuple[BoundedCapture, BoundedCapture],
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
        captures: tuple[BoundedCapture, BoundedCapture],
        detail: str,
    ) -> None:
        for capture in captures:
            capture.error = capture.error or detail

    def _kill_open_pumps(
        self,
        process: subprocess.Popen[bytes],
        threads: tuple[threading.Thread, threading.Thread],
        captures: tuple[BoundedCapture, BoundedCapture],
        chronology: list[OperationEvent],
        event: Callable[[OperationKind], OperationEvent],
    ) -> None:
        if not any(item.kind is OperationKind.COMMAND_KILL_ESCALATED for item in chronology):
            chronology.append(event(OperationKind.COMMAND_KILL_ESCALATED))
        kill_error = self._signal_group(process, signal.SIGKILL)
        if kill_error is not None:
            self._record_capture_error(captures, kill_error)
        else:
            try:
                process.wait(timeout=self._termination_grace_seconds)
            except subprocess.TimeoutExpired:
                self._record_capture_error(captures, "process did not exit after SIGKILL")
        if not self._join_pumps(threads):
            self._record_capture_error(captures, "stream capture did not seal after SIGKILL")

    def _incomplete_execution(
        self,
        captures: tuple[BoundedCapture, BoundedCapture],
        chronology: list[OperationEvent],
        event: Callable[[OperationKind], OperationEvent],
        *,
        exit_code: int | None,
        timed_out: bool,
        operation: str,
        detail: str,
    ) -> IncompleteProcessExecution:
        self._record_capture_error(captures, detail)
        chronology.append(event(OperationKind.COMMAND_FAILED))
        return IncompleteProcessExecution(
            exit_code,
            -exit_code if exit_code is not None and exit_code < 0 else None,
            timed_out,
            captures[0].finish(process_complete=False),
            captures[1].finish(process_complete=False),
            chronology[0].occurred_ns,
            chronology[-1].occurred_ns,
            tuple(chronology),
            operation,
            detail,
        )

    def _unspawned_status_result(
        self,
        status: SupervisorStatus,
        captures: tuple[BoundedCapture, BoundedCapture],
        chronology: list[OperationEvent],
        event: Callable[[OperationKind], OperationEvent],
        *,
        timed_out: bool,
    ) -> IncompleteProcessExecution | ProcessFailure:
        detail = (
            status.spawn_error
            or status.custody_error
            or status.status_error
            or "supervisor did not prove whether the target spawned"
        )
        if status.transcript_valid:
            chronology.append(event(OperationKind.COMMAND_FAILED))
            operation = (
                "spawn_command" if status.spawn_error is not None else "establish_process_custody"
            )
            return ProcessFailure(operation, detail, tuple(chronology))
        return self._incomplete_execution(
            captures,
            chronology,
            event,
            exit_code=None,
            timed_out=timed_out,
            operation="establish_process_custody",
            detail=detail,
        )

    def _execution_from_status(
        self,
        status: SupervisorStatus,
        captures: tuple[BoundedCapture, BoundedCapture],
        chronology: list[OperationEvent],
        event: Callable[[OperationKind], OperationEvent],
        *,
        timed_out: bool,
    ) -> ProcessExecution | IncompleteProcessExecution:
        if status.descendants_terminated and not any(
            item.kind is OperationKind.COMMAND_TERMINATED for item in chronology
        ):
            chronology.append(event(OperationKind.COMMAND_TERMINATED))
        if status.kill_escalated and not any(
            item.kind is OperationKind.COMMAND_KILL_ESCALATED for item in chronology
        ):
            chronology.append(event(OperationKind.COMMAND_KILL_ESCALATED))
        if not status.transcript_valid or status.custody_error is not None:
            detail = (
                status.custody_error
                or status.status_error
                or (
                    "supervisor did not confirm quiescence"
                    if not status.quiescent
                    else "supervisor status transcript is invalid"
                )
            )
            return self._incomplete_execution(
                captures,
                chronology,
                event,
                exit_code=status.target_exit,
                timed_out=timed_out,
                operation="complete_process_custody",
                detail=detail,
            )
        assert status.quiescent and status.target_exit is not None
        finished = event(OperationKind.COMMAND_FINISHED)
        chronology.append(finished)
        return ProcessExecution(
            status.target_exit,
            -status.target_exit if status.target_exit < 0 else None,
            timed_out,
            captures[0].finish(process_complete=not timed_out),
            captures[1].finish(process_complete=not timed_out),
            chronology[0].occurred_ns,
            finished.occurred_ns,
            tuple(chronology),
        )

    def run(
        self,
        argv: tuple[str, ...],
        cwd: Path,
        environment: dict[str, str],
        event: Callable[[OperationKind], OperationEvent],
    ) -> ProcessExecution | IncompleteProcessExecution | ProcessFailure:
        """Run one command with bounded process-group and stream ownership."""

        spawned = self._spawn(argv, cwd, environment, event)
        if isinstance(spawned, ProcessFailure):
            return spawned
        process = spawned.process
        started = spawned.started
        threads, captures = self._start_pumps(process)
        chronology = [started]
        timed_out, termination_error = self._await_process(process, chronology, event)
        if termination_error is not None:
            self._record_capture_error(captures, termination_error)
            self._kill_open_pumps(process, threads, captures, chronology, event)
            spawned.status_socket.close()
            return self._incomplete_execution(
                captures,
                chronology,
                event,
                exit_code=None,
                timed_out=timed_out,
                operation="terminate_process_group",
                detail=termination_error,
            )
        self._seal_pumps(
            process,
            threads,
            captures,
            chronology,
            event,
            timed_out=timed_out,
        )
        status = SupervisorStatus.parse(self._read_status(spawned.status_socket))
        if not status.spawned:
            return self._unspawned_status_result(
                status,
                captures,
                chronology,
                event,
                timed_out=timed_out,
            )
        return self._execution_from_status(
            status,
            captures,
            chronology,
            event,
            timed_out=timed_out,
        )
