"""Runtime-owned cleanup values for one isolated sandbox session."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tools.install_sandbox.validation.protocol import OperationEvent


class SandboxFinishReason(StrEnum):
    COMPLETED = "completed"
    REJECTED = "rejected"
    ABORTED = "aborted"


class SandboxRuntimeState(StrEnum):
    ACTIVE = "active"
    CUSTODY_LOST = "custody_lost"
    FINISHED = "finished"


@dataclass(frozen=True, slots=True)
class SandboxRuntimeFailure:
    operation: str
    detail: str


@dataclass(frozen=True, slots=True)
class SandboxCleanupFact:
    """Raw evidence of performed or deliberately refused session-root cleanup.

    ``removed`` records whether the root was absent when cleanup finished.
    ``failures`` distinguishes deliberate refusal after custody loss from a
    failed removal attempt, even if the target independently removed the root.
    """

    reason: SandboxFinishReason
    removed: bool
    failures: tuple[SandboxRuntimeFailure, ...]
    chronology: tuple[OperationEvent, ...]
