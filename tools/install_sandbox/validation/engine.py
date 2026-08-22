"""Validation Engine seam for strict planning and correlated fulfilment."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from .catalog import (
    CatalogAccepted,
    CatalogDocuments,
    CatalogRejected,
    compile_catalog,
)
from .completion import ValidationCompleted, ValidationRejected, ValidationResult
from .evaluation import evaluate_phase
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
    ScopeIsolationPlan,
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
    PreparationFact,
    RawFact,
)
from .results import PhaseStatus


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
) -> tuple[bool, str | None]:
    blocked = False
    for value in phases:
        if isinstance(value, NotApplicablePhasePlan):
            continue
        if not isinstance(value, PhasePlan):
            return blocked, "validation plan contains an unknown lifecycle phase variant"
        if blocked:
            continue
        blocked, rejection = _fulfil_phase(value, fulfil, facts)
        if rejection is not None:
            return blocked, rejection
    return blocked, None


def _scenario_phases(scenario: object) -> tuple[object, ...] | None | str:
    if isinstance(scenario, LifecyclePlan):
        return cast(tuple[object, ...], scenario.phases)
    if isinstance(scenario, AggregatePlan):
        return None
    if isinstance(scenario, ScopeIsolationPlan):
        return (
            *scenario.preserved_preparations,
            *scenario.selected_lifecycles,
            *scenario.selected_preparations,
            scenario.uninstall,
        )
    if isinstance(scenario, UnsupportedPlan):
        return None
    return "validation plan contains an unknown scenario variant"


def _fulfil_aggregate(
    plan: AggregatePlan,
    fulfil: Callable[[ActionRequest], object],
    facts: list[RawFact],
) -> str | None:
    preparation = _fulfil_action(plan.preparation, fulfil)
    if isinstance(preparation, str):
        return preparation
    chronology_rejection = validate_session_chronology((*facts, preparation))
    if chronology_rejection is not None:
        return chronology_rejection
    facts.append(preparation)
    if not isinstance(preparation, PreparationFact):
        return None
    for phase in plan.preparations:
        before = len(facts)
        _blocked, rejection = _fulfil_phase(phase, fulfil, facts)
        if rejection is not None:
            return rejection
        if any(
            isinstance(fact, (ActionFailureFact, CommandFailureFact)) for fact in facts[before:]
        ):
            return None
    _blocked, rejection = _fulfil_phase(plan.uninstall, fulfil, facts)
    return rejection


def _scenario_identity(index: int, scenario: object) -> str:
    if isinstance(scenario, LifecyclePlan):
        return f"{index:03d}-target-{scenario.target}-{scenario.scope.value}"
    if isinstance(scenario, AggregatePlan):
        return f"{index:03d}-aggregate-{scenario.scope.value}"
    if isinstance(scenario, ScopeIsolationPlan):
        return (
            f"{index:03d}-isolation-{scenario.selected_scope.value}"
            f"-preserves-{scenario.preserved_scope.value}"
        )
    assert isinstance(scenario, UnsupportedPlan)
    return f"{index:03d}-unsupported-{scenario.target}-{scenario.scope.value}"


def _fulfil_scenarios(
    plan: ValidationPlan,
    fulfil: Callable[[ActionRequest], object],
    facts: list[RawFact],
    begin_scenario: Callable[[str], None],
) -> bool | str:
    for index, scenario in enumerate(cast(tuple[object, ...], plan.scenarios)):
        if isinstance(scenario, UnsupportedPlan):
            continue
        try:
            begin_scenario(_scenario_identity(index, scenario))
        except Exception as error:
            return f"scenario allocation raised {type(error).__name__}: {error}"
        outcome = _fulfil_scenario(scenario, fulfil, facts)
        if outcome:
            return outcome
    return False


def _fulfil_scenario(
    scenario: object,
    fulfil: Callable[[ActionRequest], object],
    facts: list[RawFact],
) -> bool | str:
    if isinstance(scenario, AggregatePlan):
        rejection = _fulfil_aggregate(scenario, fulfil, facts)
        return rejection if rejection is not None else False
    phases = _scenario_phases(scenario)
    if isinstance(phases, str):
        return phases
    if phases is None:
        return False
    _blocked, rejection = _fulfil_phases(phases, fulfil, facts)
    if rejection is not None:
        return rejection
    return bool(facts and isinstance(facts[-1], CommandFailureFact))


def _fulfil_purge(
    plan: ValidationPlan,
    fulfil: Callable[[ActionRequest], object],
    facts: list[RawFact],
    begin_scenario: Callable[[str], None],
) -> str | None:
    try:
        begin_scenario("purge")
    except Exception as error:
        return f"scenario allocation raised {type(error).__name__}: {error}"
    blocked, rejection = _fulfil_phases(plan.purge.preparations, fulfil, facts)
    if rejection is not None or blocked:
        return rejection
    preparation = _fulfil_action(plan.purge.preparation, fulfil)
    if isinstance(preparation, str):
        return preparation
    chronology_rejection = validate_session_chronology((*facts, preparation))
    if chronology_rejection is not None:
        return chronology_rejection
    facts.append(preparation)
    if not isinstance(preparation, PreparationFact):
        return None
    _purge_blocked, rejection = _fulfil_phase(plan.purge.purge, fulfil, facts)
    return rejection


def _fulfil_plan(
    plan: ValidationPlan,
    fulfil: Callable[[ActionRequest], object],
    begin_scenario: Callable[[str], None],
) -> tuple[RawFact, ...] | str:
    facts: list[RawFact] = []
    scenario_outcome = _fulfil_scenarios(plan, fulfil, facts, begin_scenario)
    if isinstance(scenario_outcome, str):
        return scenario_outcome
    if not scenario_outcome:
        rejection = _fulfil_purge(plan, fulfil, facts, begin_scenario)
        if rejection is not None:
            return rejection
    return tuple(facts)


def validate(
    request: ValidationRequest,
    documents: CatalogDocuments,
    policy: HarnessPolicy,
    fulfil: Fulfil,
    begin_scenario: Callable[[str], None] = lambda _identity: None,
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
    fulfilled = _fulfil_plan(plan_result.plan, untrusted_fulfil, begin_scenario)
    if isinstance(fulfilled, str):
        return ValidationRejected((fulfilled,))
    raw_facts = fulfilled
    return ValidationCompleted.from_raw_facts(
        catalog_result.catalog,
        plan_result.plan,
        raw_facts,
        request,
    )
