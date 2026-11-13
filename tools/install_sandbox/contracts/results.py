"""Observed facts, verification diagnostics and durable local evidence."""

from dataclasses import dataclass, field
from typing import Literal, NotRequired, TypedDict, cast

from tools.install_sandbox.contracts.initial_preparation import InitialPreparationState
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


class CommandEvidence(TypedDict):
    args: list[str]
    cwd: str
    state: str
    exit_code: int | None
    reason: str | None
    stdout_file: str | None
    stderr_file: str | None


StepPhase = Literal[
    "idle",
    "preparation",
    "expectations",
    "command",
    "command_evidence",
    "observation",
    "verification",
    "verification_evidence",
    "termination",
    "terminal",
    "stopped",
]


@dataclass(frozen=True)
class CommandFacts:
    args: tuple[str, ...]
    cwd: str
    state: str
    exit_code: int | None
    reason: str | None
    stdout_file: str | None = None
    stderr_file: str | None = None

    @classmethod
    def from_data(cls, value: object) -> "CommandFacts":
        data = fields(value, "args cwd state exit_code reason stdout_file stderr_file")
        args = _verdict_list(data["args"])
        if not args or any(not isinstance(item, str) for item in args):
            raise ValueError("Command arguments must be nonempty strings")
        state = text(data["state"])
        code = data["exit_code"]
        if state not in {"completed", "interrupted", "not_started"}:
            raise ValueError("Invalid command state")
        if state == "completed" and type(code) is not int:
            raise ValueError("Completed command requires an exit code")
        if code is not None and type(code) is not int:
            raise ValueError("Command exit code must be an integer")
        if state == "not_started" and code is not None:
            raise ValueError("Unstarted command cannot have an exit code")
        return cls(
            tuple(cast(list[str], args)),
            text(data["cwd"]),
            state,
            code,
            _optional_text(data["reason"]),
            _optional_text(data["stdout_file"]),
            _optional_text(data["stderr_file"]),
        )

    def to_data(self) -> CommandEvidence:
        return {
            "args": list(self.args),
            "cwd": self.cwd,
            "state": self.state,
            "exit_code": self.exit_code,
            "reason": self.reason,
            "stdout_file": self.stdout_file,
            "stderr_file": self.stderr_file,
        }


@dataclass(frozen=True)
class VerificationFacts:
    complete: bool
    mismatches: tuple[VerificationMismatch, ...]
    obstacles: tuple[tuple[str, str, str, str], ...]

    @classmethod
    def capture(cls, verdict: VerificationResult) -> "VerificationFacts":
        return cls(
            verdict.complete,
            tuple(verdict.mismatches),
            tuple(
                (item["operation"], item["root"], item["path"], item["reason"])
                for item in verdict.obstacles
            ),
        )

    def result(self) -> VerificationResult:
        return VerificationResult(
            self.complete,
            list(self.mismatches),
            [
                {"operation": item[0], "root": item[1], "path": item[2], "reason": item[3]}
                for item in self.obstacles
            ],
        )


@dataclass(frozen=True)
class StepFacts:
    prepared: bool = False
    command: CommandFacts | None = None
    verification: VerificationFacts | None = None


@dataclass(frozen=True)
class StepRetained:
    before: str | None = None
    before_usable: bool = True
    expectations: str | None = None
    command: bool = False
    after: str | None = None
    verification: str | None = None


@dataclass(frozen=True)
class StepStop:
    phase: str
    reason: str


@dataclass(frozen=True)
class StepState:
    operation: str
    phase: StepPhase = "idle"
    facts: StepFacts = field(default_factory=StepFacts)
    retained: StepRetained = field(default_factory=StepRetained)
    stop: StepStop | None = None

    intent: dict[str, object] | None = None
    # Campaign v4 serializes the dataclass fields as well as the step receipt.
    assessment: None = field(default=None, init=False)

    @classmethod
    def idle(cls, operation: str) -> "StepState":
        return cls(text(operation))

    @property
    def command(self) -> CommandEvidence | None:
        return self.facts.command.to_data() if self.facts.command is not None else None

    @property
    def verification(self) -> VerificationResult | None:
        return self.facts.verification.result() if self.facts.verification is not None else None

    @property
    def observations(self) -> dict[str, str | None]:
        return {"before": self.retained.before, "after": self.retained.after}

    def to_data(self) -> dict[str, object]:
        from dataclasses import asdict

        verdict = self.verification
        return {
            "operation": self.operation,
            "phase": self.phase,
            "intent": self.intent,
            "assessment": None,
            "facts": {
                "prepared": self.facts.prepared,
                "command": self.command,
                "verification": asdict(verdict) if verdict is not None else None,
            },
            "retained": asdict(self.retained),
            "stop": asdict(self.stop) if self.stop else None,
        }

    @classmethod
    def from_data(cls, value: object) -> "StepState":
        data = fields(value, "operation phase facts retained stop intent assessment")
        if data["assessment"] is not None:
            raise ValueError("Ordinary steps cannot carry grouped assessments")
        fact = fields(data["facts"], "prepared command verification")
        retained = fields(
            data["retained"], "before before_usable expectations command after verification"
        )
        if any(
            type(item) is not bool
            for item in (fact["prepared"], retained["before_usable"], retained["command"])
        ):
            raise ValueError("Step flags must be booleans")
        phases = {
            "idle",
            "preparation",
            "expectations",
            "command",
            "command_evidence",
            "observation",
            "verification",
            "verification_evidence",
            "termination",
            "terminal",
            "stopped",
        }
        if not isinstance(data["phase"], str) or data["phase"] not in phases:
            raise ValueError("Unknown step phase")
        stop = None
        if data["stop"] is not None:
            stopped = fields(data["stop"], "phase reason")
            stop = StepStop(text(stopped["phase"]), text(stopped["reason"]))
        return cls(
            text(data["operation"]),
            cast(StepPhase, data["phase"]),
            StepFacts(
                cast(bool, fact["prepared"]),
                CommandFacts.from_data(fact["command"]) if fact["command"] is not None else None,
                VerificationFacts.capture(VerificationResult.from_data(fact["verification"]))
                if fact["verification"] is not None
                else None,
            ),
            StepRetained(
                _optional_text(retained["before"]),
                cast(bool, retained["before_usable"]),
                _optional_text(retained["expectations"]),
                cast(bool, retained["command"]),
                _optional_text(retained["after"]),
                _optional_text(retained["verification"]),
            ),
            stop,
            _optional_object(data["intent"]),
        )


def _optional_object(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Expected a structured step record")
    return cast(dict[str, object], value)


def _optional_text(value: object) -> str | None:
    return None if value is None else text(value)


class IntermediateEvidence(TypedDict):
    stage: str
    generation: int
    reason: str | None


@dataclass(frozen=True)
class RepairCheckpoint:
    stage: str
    generation: int
    reason: str | None = None

    def to_data(self) -> IntermediateEvidence:
        return {"stage": self.stage, "generation": self.generation, "reason": self.reason}

    @classmethod
    def from_data(cls, value: object) -> "RepairCheckpoint":
        data = fields(value, "stage generation reason")
        if type(data["generation"]) is not int or data["generation"] < 0:
            raise ValueError("Checkpoint generation must be a nonnegative integer")
        return cls(text(data["stage"]), data["generation"], _optional_text(data["reason"]))


@dataclass(frozen=True)
class RepairProgress:
    checkpoint: RepairCheckpoint
    outcome: Literal["incomplete", "ready", "failed"]


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
    case: dict[str, object]
    preparation: InitialPreparationState
    steps: list[StepState]
    status: Literal["passed", "failed", "not_run", "incomplete"]
    evidence: dict[str, str | None]
    intermediate_preparation: IntermediateEvidence | None = None


class EvidenceWriteError(RuntimeError):
    """Evidence could not be saved; no completed result is promised."""
