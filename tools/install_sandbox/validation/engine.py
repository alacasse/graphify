"""Validation Engine seam for strict planning and correlated fulfilment."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from .catalog import (
    CatalogAccepted,
    CatalogDocuments,
    CatalogRejected,
    InstallTargetCatalog,
    compile_catalog,
)
from .evaluation import derive_results, evaluate_phase
from .fact_validation import validate_raw_fact, validate_session_chronology
from .plan import build_validation_plan
from .plan_types import (
    AggregatePlan,
    HarnessPolicy,
    LifecyclePlan,
    NotApplicablePhasePlan,
    PhasePlan,
    PlanAccepted,
    PlanRejected,
    UnsupportedPlan,
    ValidationPlan,
    ValidationRequest,
)
from .protocol import (
    ActionFailureFact,
    ActionRequest,
    CommandFact,
    CommandFailureFact,
    Fulfil,
    RawFact,
)
from .results import DetailedScenarioResult, PhaseStatus


@dataclass(frozen=True, slots=True)
class ValidationCompleted:
    """A complete plan and one correlated Raw Fact for every planned action."""

    catalog: InstallTargetCatalog
    plan: ValidationPlan
    raw_facts: tuple[RawFact, ...]
    scenario_results: tuple[DetailedScenarioResult, ...]


@dataclass(frozen=True, slots=True)
class ValidationRejected:
    """Fail-closed input, plan, or protocol rejection with no partial success."""

    reasons: tuple[str, ...]


type ValidationResult = ValidationCompleted | ValidationRejected


def _fulfil_action(
    action: ActionRequest,
    fulfil: Callable[[ActionRequest], object],
) -> RawFact | str:
    try:
        value = fulfil(action)
    except Exception as error:
        return f"Raw Fact fulfilment raised {type(error).__name__}: {error}"
    return validate_raw_fact(action, value)


def _fulfil_phase(
    phase: PhasePlan,
    fulfil: Callable[[ActionRequest], object],
    facts: list[RawFact],
) -> tuple[bool, str | None]:
    command = _fulfil_action(phase.command, fulfil)
    if isinstance(command, str):
        return False, command
    chronology_rejection = validate_session_chronology((*facts, command))
    if chronology_rejection is not None:
        return False, chronology_rejection
    facts.append(command)
    if isinstance(command, (ActionFailureFact, CommandFailureFact)):
        return True, None
    assert isinstance(command, CommandFact)
    observation = _fulfil_action(phase.observation, fulfil)
    if isinstance(observation, str):
        return False, observation
    chronology_rejection = validate_session_chronology((*facts, observation))
    if chronology_rejection is not None:
        return False, chronology_rejection
    facts.append(observation)
    result = evaluate_phase(
        phase,
        {fact.action_id: fact for fact in (command, observation)},
    )
    blocked = command.timed_out or command.exit_code != 0 or result.status is PhaseStatus.INCOMPLETE
    return blocked, None


def _fulfil_phases(
    phases: tuple[object, ...],
    fulfil: Callable[[ActionRequest], object],
    facts: list[RawFact],
) -> str | None:
    blocked = False
    for value in phases:
        if isinstance(value, NotApplicablePhasePlan):
            continue
        if not isinstance(value, PhasePlan):
            return "validation plan contains an unknown lifecycle phase variant"
        if blocked:
            continue
        blocked, rejection = _fulfil_phase(value, fulfil, facts)
        if rejection is not None:
            return rejection
    return None


def _fulfil_plan(
    plan: ValidationPlan,
    fulfil: Callable[[ActionRequest], object],
) -> tuple[RawFact, ...] | str:
    facts: list[RawFact] = []
    for scenario in cast(tuple[object, ...], plan.scenarios):
        if isinstance(scenario, LifecyclePlan):
            phases = cast(tuple[object, ...], scenario.phases)
        elif isinstance(scenario, AggregatePlan):
            phases = (*scenario.preparations, scenario.uninstall)
        elif isinstance(scenario, UnsupportedPlan):
            continue
        else:
            return "validation plan contains an unknown scenario variant"
        rejection = _fulfil_phases(phases, fulfil, facts)
        if rejection is not None:
            return rejection
    return tuple(facts)


def validate(
    request: ValidationRequest,
    documents: CatalogDocuments,
    policy: HarnessPolicy,
    fulfil: Fulfil,
) -> ValidationResult:
    """Compile one catalog and plan, then fulfil every correlated closed request."""

    catalog_result = compile_catalog(documents)
    if isinstance(catalog_result, CatalogRejected):
        return ValidationRejected(catalog_result.reasons)
    assert isinstance(catalog_result, CatalogAccepted)
    plan_result = build_validation_plan(catalog_result.catalog, request, policy)
    if isinstance(plan_result, PlanRejected):
        return ValidationRejected(plan_result.reasons)
    assert isinstance(plan_result, PlanAccepted)
    untrusted_fulfil = cast(Callable[[ActionRequest], object], fulfil)
    fulfilled = _fulfil_plan(plan_result.plan, untrusted_fulfil)
    if isinstance(fulfilled, str):
        return ValidationRejected((fulfilled,))
    raw_facts = fulfilled
    return ValidationCompleted(
        catalog_result.catalog,
        plan_result.plan,
        raw_facts,
        derive_results(plan_result.plan, raw_facts),
    )
