"""Immutable, internally coherent values for one Validation Plan."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from .catalog import Scope, SurfaceRoot
from .protocol import (
    ActionId,
    ActionSubject,
    AggregateSubject,
    CommandRequest,
    FixtureFile,
    HarnessFileSurface,
    ManagedTreeSurface,
    ObservationRequest,
    ObservationSurface,
    PhaseKind,
    PreparationRequest,
    SandboxPath,
    SurfaceExpectation,
    TargetSubject,
)


@dataclass(frozen=True, slots=True)
class ValidationRequest:
    """Select catalog-derived targets and scopes for one validation."""

    targets: tuple[str, ...]
    scopes: tuple[Scope, ...]


def _purge_output_surface() -> ManagedTreeSurface:
    return ManagedTreeSurface(
        SurfaceRoot.PROJECT,
        "graphify-out",
    )


def _purge_fixtures() -> tuple[FixtureFile, ...]:
    return (
        FixtureFile(
            SandboxPath(SurfaceRoot.PROJECT, "graphify-out/nested/graph.json"),
            b"{}\n",
        ),
        FixtureFile(
            SandboxPath(SurfaceRoot.PROJECT, "user-owned.txt"),
            b"graphify sandbox unrelated user content\n",
        ),
    )


def _preservation_surfaces() -> tuple[ObservationSurface, ...]:
    return (
        ManagedTreeSurface(SurfaceRoot.PROJECT, "graphify-out"),
        HarnessFileSurface(
            SurfaceRoot.PROJECT,
            "user-owned.txt",
            b"graphify sandbox unrelated user content\n",
        ),
    )


@dataclass(frozen=True, slots=True)
class HarnessPolicy:
    """Cross-target lifecycle policy; catalog documents cannot override it."""

    install_argv: tuple[str, ...] = ("graphify", "install")
    uninstall_argv: tuple[str, ...] = ("graphify", "uninstall")
    purge_argv: tuple[str, ...] = ("graphify", "uninstall", "--purge")
    purge_output_surface: ManagedTreeSurface = field(default_factory=_purge_output_surface)
    purge_fixtures: tuple[FixtureFile, ...] = field(default_factory=_purge_fixtures)
    preservation_surfaces: tuple[ObservationSurface, ...] = field(
        default_factory=_preservation_surfaces
    )


@dataclass(frozen=True, slots=True)
class PhasePlan:
    """One coherent command/observation pair with adjacent action identity."""

    kind: PhaseKind
    first_action_id: ActionId
    subject: ActionSubject
    scope: Scope
    argv: tuple[str, ...]
    surfaces: tuple[ObservationSurface, ...]
    preserved_surfaces: tuple[ObservationSurface, ...] = ()

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
        aggregate_kinds = {
            PhaseKind.AGGREGATE_UNINSTALL,
            PhaseKind.ISOLATION_UNINSTALL,
            PhaseKind.PURGE,
        }
        if aggregate != (self.kind in aggregate_kinds):
            raise ValueError("only multi-target phases accept an aggregate subject")
        observed = (*self.surfaces, *self.preserved_surfaces)
        identities = tuple((surface.root, surface.path) for surface in observed)
        if not self.argv or not self.surfaces or len(identities) != len(set(identities)):
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
        mutation_expectation = (
            SurfaceExpectation.ABSENT
            if self.kind
            in {
                PhaseKind.TARGET_UNINSTALL,
                PhaseKind.AGGREGATE_UNINSTALL,
                PhaseKind.ISOLATION_UNINSTALL,
                PhaseKind.PURGE,
            }
            else SurfaceExpectation.INSTALLED
        )
        return ObservationRequest(
            ActionId(self.first_action_id.plan_id, self.first_action_id.ordinal + 1),
            self.subject,
            self.scope,
            self.kind,
            (*self.surfaces, *self.preserved_surfaces),
            (
                *(mutation_expectation for _surface in self.surfaces),
                *(SurfaceExpectation.INSTALLED for _surface in self.preserved_surfaces),
            ),
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
    preparation: PreparationRequest
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


@dataclass(frozen=True, slots=True)
class ScopeIsolationPlan:
    """One explicit selected-scope removal with the opposite scope preserved."""

    selected_scope: Scope
    preserved_scope: Scope
    preserved_preparations: tuple[PhasePlan, ...]
    selected_lifecycles: tuple[LifecyclePhasePlan, ...]
    selected_preparations: tuple[PhasePlan, ...]
    uninstall: PhasePlan
    runtime_limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_scope_isolation(self)


@dataclass(frozen=True, slots=True)
class PurgePlan:
    """One destructive purge after installing every selected surface family."""

    preparations: tuple[PhasePlan, ...]
    preparation: PreparationRequest
    output_surface: ManagedTreeSurface
    purge: PhasePlan
    runtime_limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_purge(self)


type ScenarioPlan = LifecyclePlan | UnsupportedPlan | AggregatePlan | ScopeIsolationPlan


@dataclass(frozen=True, slots=True)
class ValidationPlan:
    plan_id: str
    scenarios: tuple[ScenarioPlan, ...]
    purge: PurgePlan

    def __post_init__(self) -> None:
        if not self.plan_id or not self.scenarios:
            raise ValueError("validation plan requires identity and scenarios")
        action_ids = tuple(
            action_id
            for scenario in cast(tuple[object, ...], (*self.scenarios, self.purge))
            for action_id in _scenario_action_ids(scenario)
        )
        if any(action_id.plan_id != self.plan_id for action_id in action_ids):
            raise ValueError("validation plan identity disagrees with a planned action")
        if tuple(action_id.ordinal for action_id in action_ids) != tuple(range(len(action_ids))):
            raise ValueError("planned action sequence is not contiguous")


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
    if (
        type(cast(object, plan.scope)) is not Scope
        or not plan.preparations
        or not plan.preparation.files
    ):
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
    action_ids = (
        plan.preparation.action_id,
        *(
            action_id
            for phase in (*plan.preparations, plan.uninstall)
            for action_id in (phase.command.action_id, phase.observation.action_id)
        ),
    )
    if tuple(action_id.ordinal for action_id in action_ids) != tuple(
        range(action_ids[0].ordinal, action_ids[0].ordinal + len(action_ids))
    ):
        raise ValueError("aggregate action sequence is not contiguous")


def _validate_scope_isolation(plan: ScopeIsolationPlan) -> None:
    if (
        type(cast(object, plan.selected_scope)) is not Scope
        or type(cast(object, plan.preserved_scope)) is not Scope
        or plan.selected_scope is plan.preserved_scope
        or not plan.preserved_preparations
        or not plan.selected_lifecycles
        or not plan.selected_preparations
    ):
        raise ValueError("scope isolation requires two distinct prepared scopes")
    _validate_isolation_preparations(plan)
    _validate_isolation_lifecycles(plan)
    if (
        plan.uninstall.kind is not PhaseKind.ISOLATION_UNINSTALL
        or plan.uninstall.scope is not plan.selected_scope
        or not isinstance(plan.uninstall.subject, AggregateSubject)
    ):
        raise ValueError("scope isolation uninstall is invalid")
    _validate_action_sequence(_isolation_action_ids(plan))


def _validate_isolation_preparations(plan: ScopeIsolationPlan) -> None:
    if any(
        phase.kind is not PhaseKind.ISOLATION_PRESERVE or phase.scope is not plan.preserved_scope
        for phase in plan.preserved_preparations
    ):
        raise ValueError("scope isolation preservation preparation is invalid")
    if any(
        phase.kind is not PhaseKind.ISOLATION_PREPARE or phase.scope is not plan.selected_scope
        for phase in plan.selected_preparations
    ):
        raise ValueError("scope isolation selected preparation is invalid")


def _validate_isolation_lifecycles(plan: ScopeIsolationPlan) -> None:
    for phase in plan.selected_lifecycles:
        if isinstance(phase, NotApplicablePhasePlan):
            if phase.cleanup_scope is not plan.selected_scope:
                raise ValueError("scope isolation lifecycle cleanup scope is invalid")
        elif phase.scope is not plan.selected_scope or not phase.preserved_surfaces:
            raise ValueError("scope isolation lifecycle phase is invalid")


def _isolation_action_ids(plan: ScopeIsolationPlan) -> tuple[ActionId, ...]:
    phases = (
        *plan.preserved_preparations,
        *(phase for phase in plan.selected_lifecycles if isinstance(phase, PhasePlan)),
        *plan.selected_preparations,
        plan.uninstall,
    )
    return tuple(phase.first_action_id for phase in phases)


def _validate_purge(plan: PurgePlan) -> None:
    if any(phase.kind is not PhaseKind.PURGE_PREPARE for phase in plan.preparations):
        raise ValueError("purge preparations are invalid")
    if not plan.preparation.files or len(
        {fixture.location for fixture in plan.preparation.files}
    ) != len(plan.preparation.files):
        raise ValueError("purge fixture preparation is invalid")
    if (
        plan.purge.kind is not PhaseKind.PURGE
        or not isinstance(plan.purge.subject, AggregateSubject)
        or plan.output_surface not in plan.purge.surfaces
    ):
        raise ValueError("purge phase is invalid")
    action_ids = tuple(
        action_id
        for phase in plan.preparations
        for action_id in (phase.command.action_id, phase.observation.action_id)
    )
    action_ids = (
        *action_ids,
        plan.preparation.action_id,
        plan.purge.command.action_id,
        plan.purge.observation.action_id,
    )
    if len({action_id.plan_id for action_id in action_ids}) != 1 or tuple(
        action_id.ordinal for action_id in action_ids
    ) != tuple(range(action_ids[0].ordinal, action_ids[0].ordinal + len(action_ids))):
        raise ValueError("purge action sequence is not contiguous")


def _scenario_action_ids(scenario: object) -> tuple[ActionId, ...]:
    if isinstance(scenario, LifecyclePlan):
        return tuple(
            action_id
            for phase in scenario.phases
            if isinstance(phase, PhasePlan)
            for action_id in (phase.command.action_id, phase.observation.action_id)
        )
    if isinstance(scenario, AggregatePlan):
        commands = tuple(
            action_id
            for phase in (*scenario.preparations, scenario.uninstall)
            for action_id in (phase.command.action_id, phase.observation.action_id)
        )
        return (scenario.preparation.action_id, *commands)
    if isinstance(scenario, ScopeIsolationPlan):
        return tuple(
            action_id
            for phase in (
                *scenario.preserved_preparations,
                *(phase for phase in scenario.selected_lifecycles if isinstance(phase, PhasePlan)),
                *scenario.selected_preparations,
                scenario.uninstall,
            )
            for action_id in (phase.command.action_id, phase.observation.action_id)
        )
    if isinstance(scenario, PurgePlan):
        before = tuple(
            action_id
            for phase in scenario.preparations
            for action_id in (phase.command.action_id, phase.observation.action_id)
        )
        after = (scenario.purge.command.action_id, scenario.purge.observation.action_id)
        return (*before, scenario.preparation.action_id, *after)
    if isinstance(scenario, UnsupportedPlan):
        return ()
    raise ValueError("validation plan contains an unknown scenario variant")
