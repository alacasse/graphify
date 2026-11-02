"""Immutable statements for the initial case preparation protocol."""

from dataclasses import asdict, dataclass, field
from typing import cast

from tools.install_sandbox.contracts.spec import fields, text

OPERATIONS = (
    "environment",
    "sources",
    "expectations",
    "observation",
    "verification",
    "install_expectations",
)
CHECKPOINTS = (
    "started",
    "environment_retained",
    "sources_retained",
    "expectations_retained",
    "observed",
    "verified",
    "ready",
)
INITIAL_ARTIFACTS = (
    "environment",
    "sources",
    "expectations",
    "before",
    "verification",
    "install_expectations",
    "failure",
)
REFERENCES = {
    "environment": "roots.json",
    "sources": "expected.json",
    "expectations": "expectations/initial.json",
    "before": "initial/before.json",
    "verification": "initial-verification.json",
    "install_expectations": "expectations/install.json",
    "failure": "initial/failure.json",
}


@dataclass(frozen=True)
class InitialPreparationFacts:
    completed: tuple[str, ...] = ()
    verification_passed: bool | None = None

    @classmethod
    def from_data(cls, value: object) -> "InitialPreparationFacts":
        data = fields(value, "completed verification_passed")
        completed = data["completed"]
        passed = data["verification_passed"]
        if not isinstance(completed, list):
            raise ValueError("Invalid initial acquired operations")
        items = cast(list[object], completed)
        if any(not isinstance(item, str) for item in items):
            raise ValueError("Invalid initial acquired operations")
        if passed is not None and type(passed) is not bool:
            raise ValueError("Invalid initial verification outcome")
        return cls(tuple(cast(list[str], completed)), passed)

    def to_data(self) -> dict[str, object]:
        return {"completed": list(self.completed), "verification_passed": self.verification_passed}


@dataclass(frozen=True)
class InitialPreparationRetained:
    environment: str | None = None
    sources: str | None = None
    expectations: str | None = None
    before: str | None = None
    verification: str | None = None
    install_expectations: str | None = None
    failure: str | None = None


@dataclass(frozen=True)
class InitialPreparationStop:
    operation: str
    category: str
    reason: str
    facts: InitialPreparationFacts

    def to_data(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "category": self.category,
            "reason": self.reason,
            "facts": self.facts.to_data(),
        }


@dataclass(frozen=True)
class InitialPreparationState:
    checkpoint: str = "started"
    facts: InitialPreparationFacts = field(default_factory=InitialPreparationFacts)
    retained: InitialPreparationRetained = field(default_factory=InitialPreparationRetained)
    stop: InitialPreparationStop | None = None
    previous_checkpoint: str | None = None

    def to_data(self) -> dict[str, object]:
        return {
            "checkpoint": self.checkpoint,
            "facts": self.facts.to_data(),
            "retained": asdict(self.retained),
            "stop": self.stop.to_data() if self.stop else None,
            "previous_checkpoint": self.previous_checkpoint,
        }

    @classmethod
    def from_data(cls, value: object) -> "InitialPreparationState":
        data = fields(value, "checkpoint facts retained stop previous_checkpoint")
        retained = fields(data["retained"], " ".join(INITIAL_ARTIFACTS))
        refs = {key: None if val is None else text(val) for key, val in retained.items()}
        stop = None
        if data["stop"] is not None:
            stopped = fields(data["stop"], "operation category reason facts")
            stop = InitialPreparationStop(
                text(stopped["operation"]),
                text(stopped["category"]),
                text(stopped["reason"]),
                InitialPreparationFacts.from_data(stopped["facts"]),
            )
        return cls(
            text(data["checkpoint"]),
            InitialPreparationFacts.from_data(data["facts"]),
            InitialPreparationRetained(**refs),
            stop,
            None if data["previous_checkpoint"] is None else text(data["previous_checkpoint"]),
        )
