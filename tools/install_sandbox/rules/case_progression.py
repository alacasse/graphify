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
    operations: tuple[str, ...]
    requires_repair: bool

    @classmethod
    def from_case(cls, case: EffectInstallCase) -> "CaseShape":
        if len(case.operations) < 2:
            raise ValueError("A case requires at least two ordered operations")
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
    step_index: int | None = None


def _validate_shape(shape: CaseShape, facts: CaseFacts) -> None:
    if (
        type(shape.operations) is not tuple
        or len(shape.operations) < 2
        or any(type(operation) is not str or not operation for operation in shape.operations)
        or type(shape.requires_repair) is not bool
        or type(facts.steps) is not tuple
        or len(facts.steps) != len(shape.operations)
        or (len(shape.operations) != 2 and shape.requires_repair)
    ):
        raise ValueError("Invalid ordered case shape or facts")


def _validate(shape: CaseShape, facts: CaseFacts) -> tuple[Status, ...]:
    _validate_shape(shape, facts)
    initial_preparation.validate(facts.initial)
    statuses: tuple[Status, ...] = tuple(step_lifecycle.status(state) for state in facts.steps)
    if tuple(step.operation for step in facts.steps) != shape.operations:
        raise ValueError("Step operations contradict case order")
    repair = facts.repair
    if repair is not None:
        RepairCheckpoint.from_data(repair.checkpoint.to_data())
        if repair.outcome not in {"incomplete", "ready", "failed"}:
            raise ValueError("Invalid repair outcome")
    if repair is not None and not shape.requires_repair:
        raise ValueError("Case does not permit repair progress")
    repair_started = repair is not None and repair.checkpoint.stage != "not_started"
    if facts.initial.checkpoint != "ready" and (
        any(state.phase != "idle" for state in facts.steps) or repair_started
    ):
        raise ValueError("Installation requires ready initial preparation")
    if statuses[0] != "passed" and repair_started:
        raise ValueError("Dependent work requires a passed first installation")
    for index, state in enumerate(facts.steps):
        if state.phase != "idle" and any(value != "passed" for value in statuses[:index]):
            raise ValueError("Dependent work requires passed preceding operations")
        if (
            index == 1
            and shape.requires_repair
            and state.phase != "idle"
            and (repair is None or repair.outcome != "ready")
        ):
            raise ValueError("Reinstallation requires ready repair")
    return statuses


def evaluate(shape: CaseShape, facts: CaseFacts) -> CaseDecision:
    """Validate all dependencies before selecting the first unfinished operation."""
    statuses = _validate(shape, facts)
    if facts.initial.checkpoint != "ready":
        value = initial_preparation.status(facts.initial)
        return CaseDecision(value, "initial_preparation" if value == "incomplete" else None)
    for index, (state, value) in enumerate(zip(facts.steps, statuses, strict=True)):
        if (
            index == 1
            and shape.requires_repair
            and (facts.repair is None or facts.repair.outcome != "ready")
        ):
            value = (
                "failed"
                if facts.repair is not None and facts.repair.outcome == "failed"
                else "incomplete"
            )
            return CaseDecision(value, "repair" if value == "incomplete" else None)
        segment: Segment = (
            "uninstallation"
            if state.operation in {"uninstall", "purge"}
            else "reinstallation"
            if len(shape.operations) == 2 and index == 1
            else "installation"
        )
        step_index = index if len(shape.operations) > 2 else None
        if state.phase == "idle":
            return CaseDecision("incomplete", segment, step_index)
        if value != "passed":
            return CaseDecision(
                value,
                segment if value == "incomplete" and state.phase != "stopped" else None,
                step_index,
            )
    return CaseDecision("passed", None)
