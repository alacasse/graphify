"""Runtime-owned cleanup values for one isolated sandbox session."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tools.install_sandbox.validation.protocol import OperationEvent


class SandboxFinishReason(StrEnum):
    COMPLETED = "completed"
    REJECTED = "rejected"
    ABORTED = "aborted"


@dataclass(frozen=True, slots=True)
class SandboxRuntimeFailure:
    operation: str
    detail: str


@dataclass(frozen=True, slots=True)
class SandboxCleanupFact:
    reason: SandboxFinishReason
    removed: bool
    failures: tuple[SandboxRuntimeFailure, ...]
    chronology: tuple[OperationEvent, ...]
