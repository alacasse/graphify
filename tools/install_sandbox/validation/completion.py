"""Atomic validation completions bound to plans and Raw Facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from .catalog import InstallTargetCatalog
from .evaluation import derive_purge_result, derive_results
from .plan_types import (
    AggregatePlan,
    LifecyclePlan,
    ScenarioPlan,
    ScopeIsolationPlan,
    UnsupportedPlan,
    ValidationPlan,
    ValidationRequest,
)
from .protocol import PhaseKind, RawFact
from .results import (
    AggregateResult,
    DetailedScenarioResult,
    LifecycleResult,
    PurgeResult,
    ScopeIsolationResult,
    UnsupportedResult,
)


def _planned_phase_kinds(plan: ScenarioPlan) -> tuple[PhaseKind, ...]:
    if isinstance(plan, LifecyclePlan):
        return tuple(phase.kind for phase in plan.phases)
    if isinstance(plan, AggregatePlan):
        return tuple(phase.kind for phase in (*plan.preparations, plan.uninstall))
    if isinstance(plan, ScopeIsolationPlan):
        phases = (
            *plan.preserved_preparations,
            *plan.selected_lifecycles,
            *plan.selected_preparations,
            plan.uninstall,
        )
        return tuple(phase.kind for phase in phases)
    return ()


def _executed_result_matches_plan(
    plan: ScenarioPlan,
    result: LifecycleResult | AggregateResult | ScopeIsolationResult,
) -> bool:
    return result.runtime_limitations == plan.runtime_limitations and tuple(
        phase.kind for phase in result.phases
    ) == _planned_phase_kinds(plan)


def _result_matches_plan(plan: ScenarioPlan, result: DetailedScenarioResult) -> bool:
    if isinstance(plan, LifecyclePlan):
        return (
            isinstance(result, LifecycleResult)
            and result.target == plan.target
            and result.scope is plan.scope
            and _executed_result_matches_plan(plan, result)
        )
    if isinstance(plan, AggregatePlan):
        return (
            isinstance(result, AggregateResult)
            and result.scope is plan.scope
            and _executed_result_matches_plan(plan, result)
        )
    if isinstance(plan, ScopeIsolationPlan):
        return (
            isinstance(result, ScopeIsolationResult)
            and result.selected_scope is plan.selected_scope
            and result.preserved_scope is plan.preserved_scope
            and _executed_result_matches_plan(plan, result)
        )
    return (
        isinstance(result, UnsupportedResult)
        and result.target == plan.target
        and result.scope is plan.scope
        and result.reason == plan.reason
        and result.runtime_limitations == plan.runtime_limitations
    )


@dataclass(frozen=True, slots=True)
class ValidationCompleted:
    """One selection bound to its plan, facts, and closed semantic results."""

    catalog: InstallTargetCatalog
    plan: ValidationPlan
    raw_facts: tuple[RawFact, ...]
    scenario_results: tuple[DetailedScenarioResult, ...]
    purge_result: PurgeResult
    request: ValidationRequest

    @classmethod
    def from_raw_facts(
        cls,
        catalog: InstallTargetCatalog,
        plan: ValidationPlan,
        raw_facts: tuple[RawFact, ...],
        request: ValidationRequest,
    ) -> Self:
        """Derive all semantic results atomically from one plan and Raw Fact set."""

        return cls(
            catalog,
            plan,
            raw_facts,
            derive_results(plan, raw_facts),
            derive_purge_result(plan.purge, raw_facts),
            request,
        )

    def __post_init__(self) -> None:
        expected = {
            (target, scope) for target in self.request.targets for scope in self.request.scopes
        }
        planned = {
            (scenario.target, scenario.scope)
            for scenario in self.plan.scenarios
            if isinstance(scenario, (LifecyclePlan, UnsupportedPlan))
        }
        if (
            not self.request.targets
            or not self.request.scopes
            or expected != planned
            or len(self.scenario_results) != len(self.plan.scenarios)
            or not all(
                _result_matches_plan(plan, result)
                for plan, result in zip(
                    self.plan.scenarios,
                    self.scenario_results,
                    strict=True,
                )
            )
            or self.scenario_results != derive_results(self.plan, self.raw_facts)
            or self.purge_result != derive_purge_result(self.plan.purge, self.raw_facts)
        ):
            raise ValueError("validation completion evidence disagrees with its plan")


@dataclass(frozen=True, slots=True)
class ValidationRejected:
    """Fail-closed input, plan, or protocol rejection with no partial success."""

    reasons: tuple[str, ...]


type ValidationResult = ValidationCompleted | ValidationRejected
