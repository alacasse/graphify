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
    ActionId,
    ActionRequest,
    CommandFact,
    CommandRequest,
    Fulfil,
    ObservationFact,
    ObservationRequest,
    RawFact,
)


@dataclass(frozen=True, slots=True)
class ValidationCompleted:
    """A complete plan and one correlated Raw Fact for every planned action."""

    catalog: InstallTargetCatalog
    plan: ValidationPlan
    raw_facts: tuple[RawFact, ...]


@dataclass(frozen=True, slots=True)
class ValidationRejected:
    """Fail-closed input, plan, or protocol rejection with no partial success."""

    reasons: tuple[str, ...]


type ValidationResult = ValidationCompleted | ValidationRejected


def _matches(request: ActionRequest, fact: RawFact) -> bool:
    if request.action_id != fact.action_id:
        return False
    return (isinstance(request, CommandRequest) and isinstance(fact, CommandFact)) or (
        isinstance(request, ObservationRequest) and isinstance(fact, ObservationFact)
    )


def _validated_fact(value: object) -> RawFact | str:
    if not isinstance(value, (CommandFact, ObservationFact)):
        return "fulfil returned an unknown Raw Fact variant"
    action_id = cast(object, value.action_id)
    if not isinstance(action_id, ActionId):
        return "Raw Fact action_id is invalid"
    plan_id = cast(object, action_id.plan_id)
    ordinal = cast(object, action_id.ordinal)
    if not isinstance(plan_id, str) or not plan_id or type(ordinal) is not int or ordinal < 0:
        return "Raw Fact action_id is invalid"
    if isinstance(value, CommandFact) and type(cast(object, value.exit_code)) is not int:
        return "Command Fact exit_code must be an integer"
    if isinstance(value, ObservationFact) and type(cast(object, value.matched)) is not bool:
        return "Observation Fact matched must be a boolean"
    return value


def _lifecycle_requests(scenario: LifecyclePlan) -> tuple[ActionRequest, ...] | str:
    requests: list[ActionRequest] = []
    for phase in cast(tuple[object, ...], scenario.phases):
        if isinstance(phase, NotApplicablePhasePlan):
            continue
        if not isinstance(phase, PhasePlan):
            return "validation plan contains an unknown lifecycle phase variant"
        requests.extend((phase.command, phase.observation))
    return tuple(requests)


def _scenario_requests(scenario: object) -> tuple[ActionRequest, ...] | str:
    if isinstance(scenario, LifecyclePlan):
        return _lifecycle_requests(scenario)
    if isinstance(scenario, AggregatePlan):
        phases = (*scenario.preparations, scenario.uninstall)
        return tuple(request for phase in phases for request in (phase.command, phase.observation))
    if isinstance(scenario, UnsupportedPlan):
        return ()
    return "validation plan contains an unknown scenario variant"


def _requests(plan: ValidationPlan) -> tuple[ActionRequest, ...] | str:
    requests: list[ActionRequest] = []
    for scenario in cast(tuple[object, ...], plan.scenarios):
        scenario_requests = _scenario_requests(scenario)
        if isinstance(scenario_requests, str):
            return scenario_requests
        requests.extend(scenario_requests)
    return tuple(requests)


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
    facts: list[RawFact] = []
    untrusted_fulfil = cast(Callable[[ActionRequest], object], fulfil)
    action_requests = _requests(plan_result.plan)
    if isinstance(action_requests, str):
        return ValidationRejected((action_requests,))
    for action in action_requests:
        fact_result = _validated_fact(untrusted_fulfil(action))
        if isinstance(fact_result, str):
            return ValidationRejected((fact_result,))
        fact = fact_result
        if not _matches(action, fact):
            return ValidationRejected(
                (f"Raw Fact does not match planned action {action.action_id!r}",)
            )
        facts.append(fact)
    return ValidationCompleted(catalog_result.catalog, plan_result.plan, tuple(facts))
