"""Pure derivation of the sole immutable Validation Plan."""

from __future__ import annotations

import hashlib
import itertools
from typing import cast

from .catalog import (
    InstallSurface,
    InstallTargetCatalog,
    RepairableBundleSurface,
    Scope,
    SupportedScopeFacts,
    TargetFacts,
    UnsupportedScopeFacts,
    surface_identity,
)
from .plan_types import (
    AggregatePlan,
    HarnessPolicy,
    LifecyclePhasePlan,
    LifecyclePlan,
    NotApplicablePhasePlan,
    PhasePlan,
    PlanAccepted,
    PlanCompilation,
    PlanRejected,
    ScenarioPlan,
    UnsupportedPlan,
    ValidationPlan,
    ValidationRequest,
)
from .protocol import (
    ActionId,
    ActionSubject,
    AggregateSubject,
    PhaseKind,
    TargetSubject,
)


def _install_command(policy: HarnessPolicy, target: str, scope: Scope) -> tuple[str, ...]:
    project = ("--project",) if scope is Scope.PROJECT else ()
    return (*policy.install_argv, *project, "--platform", target)


def _target_uninstall_command(
    policy: HarnessPolicy,
    target: str,
    scope: Scope,
) -> tuple[str, ...]:
    project = ("--project",) if scope is Scope.PROJECT else ()
    return (*policy.uninstall_argv, *project, "--platform", target)


def _aggregate_uninstall_command(policy: HarnessPolicy, scope: Scope) -> tuple[str, ...]:
    project = ("--project",) if scope is Scope.PROJECT else ()
    return (*policy.uninstall_argv, *project)


def _phase(
    plan_id: str,
    ordinal: int,
    kind: PhaseKind,
    subject: ActionSubject,
    scope: Scope,
    argv: tuple[str, ...],
    surfaces: tuple[InstallSurface, ...],
) -> tuple[PhasePlan, int]:
    return PhasePlan(kind, ActionId(plan_id, ordinal), subject, scope, argv, surfaces), ordinal + 2


def _phase_kinds(facts: SupportedScopeFacts) -> tuple[PhaseKind, ...]:
    kinds = [PhaseKind.INSTALL, PhaseKind.REINSTALL]
    if any(isinstance(surface, RepairableBundleSurface) for surface in facts.surfaces):
        kinds.append(PhaseKind.REPAIR)
    return tuple(kinds)


def _has_target_bounded_uninstall(scope: Scope) -> bool:
    """Reflect the public installer's target-selective command boundary."""

    return scope is Scope.PROJECT


def _plan_id(
    catalog: InstallTargetCatalog,
    request: ValidationRequest,
    policy: HarnessPolicy,
) -> str:
    payload = repr((catalog, request, policy)).encode()
    return "plan-" + hashlib.sha256(payload).hexdigest()[:16]


def _lifecycle(
    target: TargetFacts,
    scope: Scope,
    facts: SupportedScopeFacts,
    policy: HarnessPolicy,
    plan_id: str,
    ordinal: int,
) -> tuple[LifecyclePlan, int]:
    phases: list[LifecyclePhasePlan] = []
    for kind in _phase_kinds(facts):
        phase, ordinal = _phase(
            plan_id,
            ordinal,
            kind,
            TargetSubject(target.name),
            scope,
            _install_command(policy, target.name, scope),
            facts.surfaces,
        )
        phases.append(phase)
    if _has_target_bounded_uninstall(scope):
        kind = PhaseKind.TARGET_UNINSTALL
        phase, ordinal = _phase(
            plan_id,
            ordinal,
            kind,
            TargetSubject(target.name),
            scope,
            _target_uninstall_command(policy, target.name, scope),
            facts.surfaces,
        )
        phases.append(phase)
    else:
        phases.append(
            NotApplicablePhasePlan(
                PhaseKind.TARGET_UNINSTALL,
                "the public user-scope uninstall is aggregate-only",
                scope,
            )
        )
    return LifecyclePlan(target.name, scope, tuple(phases), facts.runtime_limitations), ordinal


def _aggregate_candidates(
    catalog: InstallTargetCatalog,
    selected_targets: frozenset[str],
    scope: Scope,
) -> tuple[tuple[TargetFacts, SupportedScopeFacts], ...]:
    candidates: list[tuple[TargetFacts, SupportedScopeFacts]] = []
    for target in catalog.targets:
        facts = target.facts_for(scope)
        if target.name in selected_targets and isinstance(facts, SupportedScopeFacts):
            candidates.append((target, facts))
    return tuple(candidates)


def _minimum_surface_cover(
    candidates: tuple[tuple[TargetFacts, SupportedScopeFacts], ...],
) -> tuple[tuple[TargetFacts, SupportedScopeFacts], ...]:
    universe = {surface_identity(surface) for _, facts in candidates for surface in facts.surfaces}
    for size in range(1, len(candidates) + 1):
        complete = tuple(
            selection
            for selection in itertools.combinations(candidates, size)
            if {surface_identity(surface) for _, facts in selection for surface in facts.surfaces}
            == universe
        )
        if complete:
            return min(
                complete,
                key=lambda selection: sum(len(facts.surfaces) for _, facts in selection),
            )
    return ()


def _unique_surfaces(
    candidates: tuple[tuple[TargetFacts, SupportedScopeFacts], ...],
) -> tuple[InstallSurface, ...]:
    by_identity = {
        surface_identity(surface): surface for _, facts in candidates for surface in facts.surfaces
    }
    return tuple(
        by_identity[identity] for identity in sorted(by_identity, key=lambda item: item.sort_key)
    )


def _aggregate(
    catalog: InstallTargetCatalog,
    request: ValidationRequest,
    scope: Scope,
    policy: HarnessPolicy,
    plan_id: str,
    ordinal: int,
) -> tuple[AggregatePlan | None, int]:
    candidates = _aggregate_candidates(catalog, frozenset(request.targets), scope)
    if not candidates:
        return None, ordinal
    selected = _minimum_surface_cover(candidates)
    preparations: list[PhasePlan] = []
    for target, facts in selected:
        preparation, ordinal = _phase(
            plan_id,
            ordinal,
            PhaseKind.AGGREGATE_PREPARE,
            TargetSubject(target.name),
            scope,
            _install_command(policy, target.name, scope),
            facts.surfaces,
        )
        preparations.append(preparation)
    all_surfaces = _unique_surfaces(candidates)
    aggregate_subject = AggregateSubject(tuple(target.name for target, _ in selected))
    uninstall, ordinal = _phase(
        plan_id,
        ordinal,
        PhaseKind.AGGREGATE_UNINSTALL,
        aggregate_subject,
        scope,
        _aggregate_uninstall_command(policy, scope),
        all_surfaces,
    )
    limitations = tuple(
        sorted({limitation for _, facts in candidates for limitation in facts.runtime_limitations})
    )
    return (
        AggregatePlan(
            scope,
            tuple(preparations),
            uninstall,
            limitations,
        ),
        ordinal,
    )


def _selection_rejection(request: ValidationRequest) -> PlanRejected | None:
    targets = cast(object, request.targets)
    if not isinstance(targets, tuple) or not targets:
        return PlanRejected(("validation request requires unique selected targets",))
    target_items = cast(tuple[object, ...], targets)
    if any(not isinstance(target, str) or not target for target in target_items):
        return PlanRejected(("validation request contains an invalid target",))
    if len(target_items) != len(set(target_items)):
        return PlanRejected(("validation request requires unique selected targets",))
    scopes = cast(object, request.scopes)
    if not isinstance(scopes, tuple) or not scopes:
        return PlanRejected(("validation request requires unique selected scopes",))
    scope_items = cast(tuple[object, ...], scopes)
    if any(type(scope) is not Scope for scope in scope_items):
        return PlanRejected(("validation request contains an unknown scope variant",))
    if len(scope_items) != len(set(scope_items)):
        return PlanRejected(("validation request requires unique selected scopes",))
    return None


def _policy_rejection(policy: HarnessPolicy) -> PlanRejected | None:
    install_argv = cast(object, policy.install_argv)
    uninstall_argv = cast(object, policy.uninstall_argv)
    for label, argv in (("install", install_argv), ("uninstall", uninstall_argv)):
        if not isinstance(argv, tuple) or not argv:
            return PlanRejected((f"{label} command policy is invalid",))
        arguments = cast(tuple[object, ...], argv)
        if any(not isinstance(argument, str) or not argument for argument in arguments):
            return PlanRejected((f"{label} command policy is invalid",))
    return None


def _request_rejection(
    request: ValidationRequest,
    policy: HarnessPolicy,
) -> PlanRejected | None:
    return _selection_rejection(request) or _policy_rejection(policy)


type _ScenarioCompilation = tuple[list[ScenarioPlan], int] | PlanRejected


def _target_scenarios(
    catalog: InstallTargetCatalog,
    request: ValidationRequest,
    policy: HarnessPolicy,
    plan_id: str,
) -> _ScenarioCompilation:
    scenarios: list[ScenarioPlan] = []
    ordinal = 0
    for target_name in request.targets:
        target = catalog.target(target_name)
        if target is None:
            return PlanRejected((f"unknown Install Target: {target_name!r}",))
        for scope in request.scopes:
            facts = target.facts_for(scope)
            if isinstance(facts, UnsupportedScopeFacts):
                scenarios.append(
                    UnsupportedPlan(target.name, scope, facts.reason, facts.runtime_limitations)
                )
                continue
            lifecycle, ordinal = _lifecycle(target, scope, facts, policy, plan_id, ordinal)
            scenarios.append(lifecycle)
    return scenarios, ordinal


def build_validation_plan(
    catalog: InstallTargetCatalog,
    request: ValidationRequest,
    policy: HarnessPolicy,
) -> PlanCompilation:
    """Derive one ordered plan without consulting product behavior or legacy state."""

    rejection = _request_rejection(request, policy)
    if rejection is not None:
        return rejection
    plan_id = _plan_id(catalog, request, policy)
    compiled = _target_scenarios(catalog, request, policy, plan_id)
    if isinstance(compiled, PlanRejected):
        return compiled
    scenarios, ordinal = compiled
    for scope in request.scopes:
        aggregate, ordinal = _aggregate(catalog, request, scope, policy, plan_id, ordinal)
        if aggregate is not None:
            scenarios.append(aggregate)
    if not scenarios:
        return PlanRejected(("validation plan must contain at least one scenario",))
    return PlanAccepted(ValidationPlan(plan_id, tuple(scenarios)))
