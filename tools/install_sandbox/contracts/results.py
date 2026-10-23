"""Observed facts, verification diagnostics and durable local evidence."""

from dataclasses import dataclass, field
from typing import Literal, NotRequired, TypedDict


class ObservationObstacle(TypedDict):
    operation: str
    root: str
    path: str
    reason: str


class SnapshotEntry(TypedDict):
    root: str
    path: str
    kind: str
    listing_complete: NotRequired[bool]
    content_file: NotRequired[str | None]
    sha256: NotRequired[str | None]


@dataclass(frozen=True)
class VerificationMismatch:
    type: str
    root: str
    path: str
    expected: str
    observed: str


@dataclass
class VerificationResult:
    complete: bool = True
    mismatches: list[VerificationMismatch] = field(default_factory=list[VerificationMismatch])
    obstacles: list[ObservationObstacle] = field(default_factory=list[ObservationObstacle])


class PreparationEvidence(TypedDict):
    source: Literal["campaign"]
    ready: bool
    reason: str | None
    log: str
    stage: Literal["started", "sources_retained", "initial_verified"]


class CommandEvidence(TypedDict):
    args: list[str]
    cwd: str
    state: str
    exit_code: int | None
    reason: str | None
    stdout_file: str | None
    stderr_file: str | None


class ExecutionFailure(TypedDict):
    stage: str
    reason: str


class StepEvidence(TypedDict):
    failure: NotRequired[ExecutionFailure]
    progress: Literal["not_started", "incomplete", "finished"]
    operation: str
    skip_reason: str | None
    command: CommandEvidence | None
    verification: VerificationResult | None
    observations: dict[str, str | None] | None


class IntermediateEvidence(TypedDict):
    progress: Literal["not_started", "incomplete", "finished"]
    operation_ref: str | None
    expectations_ref: str | None
    observations: dict[str, str | None]
    verification: VerificationResult | None
    reason: str | None


@dataclass
class InstallTestResult:
    case: dict[str, str]
    preparation: PreparationEvidence
    steps: list[StepEvidence]
    status: Literal["passed", "failed", "not_run", "incomplete"]
    evidence: dict[str, str | None]
    intermediate_preparation: IntermediateEvidence | None = None


class EvidenceWriteError(RuntimeError):
    """Evidence could not be saved; no completed result is promised."""
