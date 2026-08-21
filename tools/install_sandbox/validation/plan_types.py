"""Immutable, internally coherent values for one Validation Plan."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from .catalog import InstallSurface, Scope
from .protocol import (
    ActionId,
    ActionSubject,
    AggregateSubject,
    CommandRequest,
    ObservationRequest,
    PhaseKind,
    SurfaceExpectation,
    TargetSubject,
)


@dataclass(frozen=True, slots=True)
class ValidationRequest:
    """Select catalog-derived targets and scopes for one validation."""

    targets: tuple[str, ...]
    scopes: tuple[Scope, ...]


@dataclass(frozen=True, slots=True)
class HarnessPolicy:
    """Cross-target lifecycle policy; catalog documents cannot override it."""

    install_argv: tuple[str, ...] = ("graphify", "install")
    uninstall_argv: tuple[str, ...] = ("graphify", "uninstall")


@dataclass(frozen=True, slots=True)
class PhasePlan:
    """One coherent command/observation pair with adjacent action identity."""

    kind: PhaseKind
    first_action_id: ActionId
    subject: ActionSubject
    scope: Scope
    argv: tuple[str, ...]
    surfaces: tuple[InstallSurface, ...]

    def __post_init__(self) -> None:
        if (
            type(cast(object, self.kind)) is not PhaseKind
            or type(cast(object, self.scope)) is not Scope
        ):
            raise ValueError("planned phase kind is not a closed variant")
        action_id = cast(object, self.first_action_id)
        if not isinstance(action_id, ActionId) or not action_id.plan_id or action_id.ordinal < 0:
            raise ValueError("planned phase action identity is invalid")
        aggregate = isinstance(self.subject, AggregateSubject)
        if aggregate != (self.kind is PhaseKind.AGGREGATE_UNINSTALL):
            raise ValueError("only aggregate uninstall accepts an aggregate subject")
        if not self.argv or not self.surfaces:
            raise ValueError("a planned phase requires a command and Install Surfaces")

    @property
    def command(self) -> CommandRequest:
        return CommandRequest(
            self.first_action_id,
            self.subject,
            self.scope,
            self.kind,
            self.argv,
        )

    @property
    def observation(self) -> ObservationRequest:
        expectation = (
            SurfaceExpectation.ABSENT
            if self.kind in {PhaseKind.TARGET_UNINSTALL, PhaseKind.AGGREGATE_UNINSTALL}
            else SurfaceExpectation.INSTALLED
        )
        return ObservationRequest(
            ActionId(self.first_action_id.plan_id, self.first_action_id.ordinal + 1),
            self.subject,
            self.scope,
            self.kind,
            self.surfaces,
            expectation,
        )


@dataclass(frozen=True, slots=True)
class NotApplicablePhasePlan:
    """A command-free phase whose cleanup is owned by an aggregate scenario."""

    kind: PhaseKind
    reason: str
    cleanup_scope: Scope

    def __post_init__(self) -> None:
        if (
            type(cast(object, self.kind)) is not PhaseKind
            or self.kind is not PhaseKind.TARGET_UNINSTALL
            or type(cast(object, self.cleanup_scope)) is not Scope
            or not self.reason
        ):
            raise ValueError("only target uninstall can be command-free")


type LifecyclePhasePlan = PhasePlan | NotApplicablePhasePlan


@dataclass(frozen=True, slots=True)
class LifecyclePlan:
    target: str
    scope: Scope
    phases: tuple[LifecyclePhasePlan, ...]
    runtime_limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_lifecycle(self)


@dataclass(frozen=True, slots=True)
class UnsupportedPlan:
    target: str
    scope: Scope
    reason: str
    runtime_limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(cast(object, self.scope)) is not Scope or not self.target or not self.reason:
            raise ValueError("unsupported plan requires a target and reason")


@dataclass(frozen=True, slots=True)
class AggregatePlan:
    """One surface-derived broad-uninstall scenario for a selected scope."""

    scope: Scope
    preparations: tuple[PhasePlan, ...]
    uninstall: PhasePlan
    runtime_limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_aggregate(self)

    @property
    def preparation_targets(self) -> tuple[str, ...]:
        subject = self.uninstall.subject
        if not isinstance(subject, AggregateSubject):
            raise ValueError("aggregate uninstall requires an aggregate subject")
        return subject.preparation_targets


type ScenarioPlan = LifecyclePlan | UnsupportedPlan | AggregatePlan


@dataclass(frozen=True, slots=True)
class ValidationPlan:
    plan_id: str
    scenarios: tuple[ScenarioPlan, ...]

    def __post_init__(self) -> None:
        if not self.plan_id or not self.scenarios:
            raise ValueError("validation plan requires identity and scenarios")
        action_ids = tuple(
            action_id
            for scenario in cast(tuple[object, ...], self.scenarios)
            for action_id in _scenario_action_ids(scenario)
        )
        if any(action_id.plan_id != self.plan_id for action_id in action_ids):
            raise ValueError("validation plan identity disagrees with a planned action")
        _validate_action_sequence(action_ids, first_ordinal=0)


@dataclass(frozen=True, slots=True)
class PlanAccepted:
    plan: ValidationPlan


@dataclass(frozen=True, slots=True)
class PlanRejected:
    reasons: tuple[str, ...]


type PlanCompilation = PlanAccepted | PlanRejected


_LIFECYCLE_KINDS = {
    (PhaseKind.INSTALL, PhaseKind.REINSTALL, PhaseKind.TARGET_UNINSTALL),
    (
        PhaseKind.INSTALL,
        PhaseKind.REINSTALL,
        PhaseKind.REPAIR,
        PhaseKind.TARGET_UNINSTALL,
    ),
}


def _validate_action_sequence(
    action_ids: tuple[ActionId, ...],
    *,
    first_ordinal: int | None = None,
) -> None:
    if not action_ids:
        return
    expected_first = action_ids[0].ordinal if first_ordinal is None else first_ordinal
    expected = tuple(range(expected_first, expected_first + 2 * len(action_ids), 2))
    if (
        len({action_id.plan_id for action_id in action_ids}) != 1
        or tuple(action_id.ordinal for action_id in action_ids) != expected
    ):
        raise ValueError("planned action pairs are not contiguous")


def _lifecycle_phase_action_id(
    phase: object,
    target: str,
    scope: Scope,
) -> ActionId | None:
    if isinstance(phase, NotApplicablePhasePlan):
        if phase.cleanup_scope is not scope:
            raise ValueError("command-free cleanup scope disagrees with its lifecycle")
        return None
    if not isinstance(phase, PhasePlan):
        raise ValueError("lifecycle contains an unknown phase variant")
    if phase.subject != TargetSubject(target) or phase.scope is not scope:
        raise ValueError("planned phase subject disagrees with its lifecycle")
    return phase.first_action_id


def _validate_lifecycle(plan: LifecyclePlan) -> None:
    if type(cast(object, plan.scope)) is not Scope:
        raise ValueError("lifecycle scope is not a closed variant")
    phases = cast(tuple[object, ...], plan.phases)
    if not all(isinstance(phase, (PhasePlan, NotApplicablePhasePlan)) for phase in phases):
        raise ValueError("lifecycle contains an unknown phase variant")
    kinds = tuple(phase.kind for phase in plan.phases)
    if not plan.target or kinds not in _LIFECYCLE_KINDS:
        raise ValueError("lifecycle phase sequence is incomplete")
    uninstall = plan.phases[-1]
    if (plan.scope is Scope.USER) != isinstance(uninstall, NotApplicablePhasePlan):
        raise ValueError("target-uninstall applicability disagrees with lifecycle scope")
    action_ids = tuple(
        action_id
        for phase in phases
        if (action_id := _lifecycle_phase_action_id(phase, plan.target, plan.scope)) is not None
    )
    _validate_action_sequence(action_ids)


def _validate_aggregate(plan: AggregatePlan) -> None:
    if type(cast(object, plan.scope)) is not Scope or not plan.preparations:
        raise ValueError("aggregate preparations are incomplete")
    names: list[str] = []
    for phase in plan.preparations:
        if (
            phase.kind is not PhaseKind.AGGREGATE_PREPARE
            or phase.scope is not plan.scope
            or not isinstance(phase.subject, TargetSubject)
        ):
            raise ValueError("aggregate preparations are incomplete")
        names.append(phase.subject.name)
    if (
        len(names) != len(set(names))
        or plan.uninstall.kind is not PhaseKind.AGGREGATE_UNINSTALL
        or plan.uninstall.scope is not plan.scope
        or plan.uninstall.subject != AggregateSubject(tuple(names))
    ):
        raise ValueError("aggregate uninstall does not match its preparations")
    _validate_action_sequence(
        tuple(phase.first_action_id for phase in (*plan.preparations, plan.uninstall))
    )


def _scenario_action_ids(scenario: object) -> tuple[ActionId, ...]:
    if isinstance(scenario, LifecyclePlan):
        return tuple(
            phase.first_action_id for phase in scenario.phases if isinstance(phase, PhasePlan)
        )
    if isinstance(scenario, AggregatePlan):
        return tuple(
            phase.first_action_id for phase in (*scenario.preparations, scenario.uninstall)
        )
    if isinstance(scenario, UnsupportedPlan):
        return ()
    raise ValueError("validation plan contains an unknown scenario variant")
