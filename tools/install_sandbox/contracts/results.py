"""Observed facts, verification diagnostics and durable local evidence."""

from dataclasses import dataclass, field
from typing import Literal, NotRequired, TypedDict, cast

from tools.install_sandbox.contracts.spec import fields, text


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

    @classmethod
    def from_data(cls, value: object) -> "VerificationResult":
        """Decode the strict verdict shared by execution evidence and repair replay."""
        data = fields(value, "complete mismatches obstacles")
        complete = data["complete"]
        if not isinstance(complete, bool):
            raise ValueError("Expected a boolean")
        result = cls(
            complete,
            [_verification_mismatch(item) for item in _verdict_list(data["mismatches"])],
            [parse_obstacle(item) for item in _verdict_list(data["obstacles"])],
        )
        if result.complete and result.obstacles:
            raise ValueError("Complete verification cannot contain observation obstacles")
        return result


def _verdict_list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Expected a list")
    return cast(list[object], value)


def _verification_mismatch(value: object) -> VerificationMismatch:
    data = fields(value, "type root path expected observed")
    expected, observed = data["expected"], data["observed"]
    if not isinstance(expected, str) or not isinstance(observed, str):
        raise ValueError("Expected a string")
    return VerificationMismatch(
        text(data["type"]), text(data["root"]), text(data["path"]), expected, observed
    )


def parse_obstacle(value: object) -> ObservationObstacle:
    data = fields(value, "operation root path reason")
    return {
        "operation": text(data["operation"]),
        "root": text(data["root"]),
        "path": text(data["path"]),
        "reason": text(data["reason"]),
    }


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
    stage: str
    generation: int
    reason: str | None


@dataclass(frozen=True)
class ArtifactReceipt:
    reference: str
    sha256: str


@dataclass(frozen=True)
class CheckpointReceipt:
    session_id: str
    generation: int
    sha256: str


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
