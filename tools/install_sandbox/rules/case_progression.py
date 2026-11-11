"""Authorize the next operation solely from ordered, published local facts."""

from dataclasses import dataclass
from typing import Literal

from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.initial_preparation import InitialPreparationState
from tools.install_sandbox.contracts.results import RepairCheckpoint, RepairProgress, StepState
from tools.install_sandbox.rules import initial_preparation, step_lifecycle

Status = Literal["not_run", "incomplete", "passed", "failed"]
Segment = Literal["initial_preparation", "step", "repair"]


@dataclass(frozen=True)
class CaseShape:
    operations: tuple[str, ...]
    requires_repair: bool

    @classmethod
    def from_case(cls, case: EffectInstallCase) -> "CaseShape":
        return cls(tuple(case.operations), case.intermediate_preparation is not None)


@dataclass(frozen=True)
class CaseFacts:
    initial: InitialPreparationState
    steps: tuple[StepState, ...]
    repair: RepairProgress | None = None


@dataclass(frozen=True)
class CaseDecision:
    status: Status
    segment: Segment | None
    index: int | None = None


def _repair_ready(shape: CaseShape, facts: CaseFacts, first: Status) -> bool:
    repair = facts.repair
    if repair is None:
        return not shape.requires_repair
    RepairCheckpoint.from_data(repair.checkpoint.to_data())
    if not shape.requires_repair or repair.outcome not in {"incomplete", "ready", "failed"}:
        raise ValueError("Invalid repair progress for this case")
    if repair.checkpoint.stage != "not_started" and first != "passed":
        raise ValueError("Repair requires a verified first installation")
    return repair.outcome == "ready"


def _validated_prefix(shape: CaseShape, facts: CaseFacts) -> tuple[bool, tuple[Status, ...]]:
    """Check the entire prefix, including contradictory work after a failed receipt."""
    if not shape.operations or tuple(step.operation for step in facts.steps) != shape.operations:
        raise ValueError("Step operations contradict case order")
    initial_preparation.validate(facts.initial)
    statuses: tuple[Status, ...] = tuple(step_lifecycle.status(step) for step in facts.steps)
    ready = _repair_ready(shape, facts, statuses[0])
    authorized = facts.initial.checkpoint == "ready"
    for index, (step, status) in enumerate(zip(facts.steps, statuses, strict=True)):
        if index == 1 and not ready:
            authorized = False
        if not authorized and step.phase != "idle":
            raise ValueError("Dependent work requires verified preparation and preceding steps")
        authorized = authorized and status == "passed"

    return ready, statuses


def evaluate(shape: CaseShape, facts: CaseFacts) -> CaseDecision:
    ready, statuses = _validated_prefix(shape, facts)
    if facts.initial.checkpoint != "ready":
        status = initial_preparation.status(facts.initial)
        return CaseDecision(status, "initial_preparation" if status == "incomplete" else None)
    for index, (step, status) in enumerate(zip(facts.steps, statuses, strict=True)):
        if index == 1 and not ready:
            if facts.repair and facts.repair.outcome == "failed":
                return CaseDecision("failed", None)
            return CaseDecision("incomplete", "repair")
        if status == "not_run":
            return CaseDecision("incomplete", "step", index)
        if status != "passed":
            if step.phase in {"terminal", "stopped"}:
                return CaseDecision(status, None)
            return CaseDecision(status, "step", index)
    return CaseDecision("passed", None)
