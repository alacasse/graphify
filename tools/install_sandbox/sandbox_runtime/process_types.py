"""Mechanical process-runner values shared with the Sandbox Runtime."""

from __future__ import annotations

import socket
import subprocess
from dataclasses import dataclass

from tools.install_sandbox.validation.protocol import (
    OperationEvent,
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


@dataclass(frozen=True, slots=True)
class IncompleteProcessExecution:
    exit_code: int | None
    signal: int | None
    timed_out: bool
    stdout: StreamCapture
    stderr: StreamCapture
    started_ns: int
    finished_ns: int
    chronology: tuple[OperationEvent, ...]
    operation: str
    detail: str


@dataclass(frozen=True, slots=True)
class SpawnedProcess:
    process: subprocess.Popen[bytes]
    status_socket: socket.socket
    started: OperationEvent
