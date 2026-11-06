"""Derive invocation status and authorized segment from published local facts."""

from dataclasses import dataclass
from typing import Literal

from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.initial_preparation import InitialPreparationState
from tools.install_sandbox.contracts.results import RepairCheckpoint, RepairProgress, StepState
from tools.install_sandbox.rules import initial_preparation, step_lifecycle

Status = Literal["not_run", "incomplete", "passed", "failed"]
Segment = Literal[
    "initial_preparation", "installation", "repair", "reinstallation", "uninstallation"
]


@dataclass(frozen=True)
class CaseShape:
    operations: tuple[str, str]
    requires_repair: bool

    @classmethod
    def from_case(cls, case: EffectInstallCase) -> "CaseShape":
        if len(case.operations) != 2:
            raise ValueError("A case requires exactly two ordered operations")
        return cls(
            (case.operations[0], case.operations[1]), case.intermediate_preparation is not None
        )


@dataclass(frozen=True)
class CaseFacts:
    initial: InitialPreparationState
    steps: tuple[StepState, StepState]
    repair: RepairProgress | None = None


@dataclass(frozen=True)
class CaseDecision:
    status: Status
    segment: Segment | None


def _validate_shape(shape: CaseShape, facts: CaseFacts) -> None:
    if (
        type(shape.operations) is not tuple
        or len(shape.operations) != 2
        or any(type(operation) is not str or not operation for operation in shape.operations)
        or type(shape.requires_repair) is not bool
        or type(facts.steps) is not tuple
        or len(facts.steps) != 2
    ):
        raise ValueError("Invalid two-operation case shape or facts")


def _validate(shape: CaseShape, facts: CaseFacts) -> tuple[Status, Status]:
    _validate_shape(shape, facts)
    initial_preparation.validate(facts.initial)
    statuses = (step_lifecycle.status(facts.steps[0]), step_lifecycle.status(facts.steps[1]))
    if tuple(step.operation for step in facts.steps) != shape.operations:
        raise ValueError("Step operations contradict case order")
    first, second = facts.steps
    repair = facts.repair
    if repair is not None:
        RepairCheckpoint.from_data(repair.checkpoint.to_data())
        if repair.outcome not in {"incomplete", "ready", "failed"}:
            raise ValueError("Invalid repair outcome")
    if repair is not None and not shape.requires_repair:
        raise ValueError("Case does not permit repair progress")
    repair_started = repair is not None and repair.checkpoint.stage != "not_started"
    if facts.initial.checkpoint != "ready" and (
        first.phase != "idle" or second.phase != "idle" or repair_started
    ):
        raise ValueError("Installation requires ready initial preparation")
    if statuses[0] != "passed" and (repair_started or second.phase != "idle"):
        raise ValueError("Dependent work requires a passed first installation")
    if (
        shape.requires_repair
        and second.phase != "idle"
        and (repair is None or repair.outcome != "ready")
    ):
        raise ValueError("Reinstallation requires ready repair")
    return statuses[0], statuses[1]


def _step_decision(step: StepState, status: Status, segment: Segment) -> CaseDecision:
    return CaseDecision(
        status, segment if status == "incomplete" and step.phase != "stopped" else None
    )


def evaluate(shape: CaseShape, facts: CaseFacts) -> CaseDecision:
    """Validate dependencies even when an earlier local result ends the invocation."""
    first_status, second_status = _validate(shape, facts)
    if facts.initial.checkpoint != "ready":
        status = initial_preparation.status(facts.initial)
        return CaseDecision(status, "initial_preparation" if status == "incomplete" else None)
    first, second = facts.steps
    if first.phase == "idle":
        return CaseDecision("incomplete", "installation")
    if first_status != "passed":
        return _step_decision(first, first_status, "installation")
    if shape.requires_repair and (facts.repair is None or facts.repair.outcome != "ready"):
        status = (
            "failed"
            if facts.repair is not None and facts.repair.outcome == "failed"
            else "incomplete"
        )
        return CaseDecision(status, "repair" if status == "incomplete" else None)
    segment: Segment = "uninstallation" if shape.operations[1] == "uninstall" else "reinstallation"
    if second.phase == "idle":
        return CaseDecision("incomplete", segment)
    return _step_decision(second, second_status, segment)
