from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

from tools.install_sandbox.validation.catalog import (
    CatalogAccepted,
    CatalogDocument,
    CatalogDocuments,
    Scope,
    SurfaceRoot,
    compile_catalog,
)
from tools.install_sandbox.validation.plan import build_validation_plan
from tools.install_sandbox.validation.plan_types import (
    AggregatePlan,
    HarnessPolicy,
    LifecyclePlan,
    NotApplicablePhasePlan,
    PhasePlan,
    PlanAccepted,
    PurgePlan,
    ScopeIsolationPlan,
    UnsupportedPlan,
    ValidationPlan,
    ValidationRequest,
)
from tools.install_sandbox.validation.protocol import (
    ActionId,
    AggregateSubject,
    HarnessFileSurface,
    ManagedTreeSurface,
    PhaseKind,
    PreparationRequest,
    TargetSubject,
)
from tools.install_sandbox.validation.results import (
    AggregateResult,
    LifecycleResult,
    PhaseResult,
    PhaseStatus,
    ProductFinding,
    PurgeResult,
    PurgeStatus,
    ScenarioStatus,
    ScopeIsolationResult,
    UnsupportedResult,
)


def _fictional_documents() -> CatalogDocuments:
    return CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                """
scopes:
  user:
    supported: true
    runtime_limitations:
      - The fictional user target proves filesystem effects only.
    surfaces:
      - kind: owned_file
        root: home
        path: .fictional/user.txt
        source: fixtures/user.txt
  project:
    supported: true
    runtime_limitations:
      - The fictional project target proves filesystem effects only.
    surfaces:
      - kind: owned_file
        root: project
        path: .fictional/project.txt
        source: fixtures/project.txt
""".lstrip(),
            ),
        )
    )


def _complete_plan() -> ValidationPlan:
    compiled = compile_catalog(_fictional_documents())
    assert isinstance(compiled, CatalogAccepted)
    result = build_validation_plan(
        compiled.catalog,
        ValidationRequest(("fictional",), (Scope.USER, Scope.PROJECT)),
        HarnessPolicy(),
    )
    assert isinstance(result, PlanAccepted)
    return result.plan


def test_both_scope_plan_includes_bidirectional_isolation_and_purge() -> None:
    plan = _complete_plan()
    isolation = tuple(
        scenario for scenario in plan.scenarios if isinstance(scenario, ScopeIsolationPlan)
    )
    assert {(scenario.selected_scope, scenario.preserved_scope) for scenario in isolation} == {
        (Scope.USER, Scope.PROJECT),
        (Scope.PROJECT, Scope.USER),
    }
    assert all(scenario.preserved_preparations for scenario in isolation)
    assert all(scenario.selected_lifecycles for scenario in isolation)
    assert all(scenario.selected_preparations for scenario in isolation)
    for scenario in isolation:
        preserved = {
            (surface.root, surface.path)
            for phase in scenario.preserved_preparations
            for surface in phase.surfaces
        }
        selected_phases = tuple(
            phase for phase in scenario.selected_lifecycles if isinstance(phase, PhasePlan)
        )
        assert selected_phases
        assert all(
            {(surface.root, surface.path) for surface in phase.preserved_surfaces} == preserved
            for phase in (*selected_phases, *scenario.selected_preparations, scenario.uninstall)
        )

    aggregates = tuple(
        scenario for scenario in plan.scenarios if isinstance(scenario, AggregatePlan)
    )
    assert aggregates
    for aggregate in aggregates:
        assert aggregate.preparation.files
        assert any(
            isinstance(surface, ManagedTreeSurface)
            for surface in aggregate.uninstall.preserved_surfaces
        )
        assert any(
            isinstance(surface, HarnessFileSurface)
            for surface in aggregate.uninstall.preserved_surfaces
        )

    purge = plan.purge
    assert isinstance(purge, PurgePlan)
    assert purge.preparations
    assert purge.output_surface.root is SurfaceRoot.PROJECT
    assert purge.output_surface.path == "graphify-out"
    assert any(
        fixture.location.path.startswith("graphify-out/") for fixture in purge.preparation.files
    )
    assert purge.output_surface in purge.purge.surfaces
    assert any(
        isinstance(surface, HarnessFileSurface) for surface in purge.purge.preserved_surfaces
    )
    assert purge.purge.command.argv == ("graphify", "uninstall", "--purge")


def test_phase_plan_rejects_open_or_incomplete_values() -> None:
    plan = _complete_plan()
    lifecycle = next(scenario for scenario in plan.scenarios if isinstance(scenario, LifecyclePlan))
    phase = lifecycle.phases[0]
    assert isinstance(phase, PhasePlan)

    invalid = (
        lambda: replace(phase, kind=cast(PhaseKind, object())),
        lambda: replace(phase, first_action_id=ActionId("", 0)),
        lambda: replace(phase, subject=AggregateSubject(("fictional",))),
        lambda: replace(phase, argv=()),
        lambda: replace(phase, surfaces=()),
    )
    for construct in invalid:
        with pytest.raises(ValueError):
            construct()
    with pytest.raises(ValueError, match="command-free"):
        NotApplicablePhasePlan(PhaseKind.INSTALL, "reason", Scope.USER)
    with pytest.raises(ValueError, match="target and reason"):
        UnsupportedPlan("", Scope.USER, "reason", ())


def test_lifecycle_plan_rejects_incoherent_phase_topology() -> None:
    plan = _complete_plan()
    lifecycles = tuple(
        scenario for scenario in plan.scenarios if isinstance(scenario, LifecyclePlan)
    )
    user = next(item for item in lifecycles if item.scope is Scope.USER)
    project = next(item for item in lifecycles if item.scope is Scope.PROJECT)
    first = project.phases[0]
    second = project.phases[1]
    assert isinstance(first, PhasePlan)
    assert isinstance(second, PhasePlan)
    user_cleanup = user.phases[-1]
    assert isinstance(user_cleanup, NotApplicablePhasePlan)

    invalid = (
        lambda: replace(project, scope=cast(Scope, object())),
        lambda: replace(project, phases=cast(tuple[PhasePlan, ...], (object(),))),
        lambda: replace(project, target=""),
        lambda: replace(project, scope=Scope.USER),
        lambda: replace(
            user,
            phases=(
                *user.phases[:-1],
                replace(user_cleanup, cleanup_scope=Scope.PROJECT),
            ),
        ),
        lambda: replace(
            project,
            phases=(replace(first, subject=TargetSubject("other")), *project.phases[1:]),
        ),
        lambda: replace(
            project,
            phases=(
                first,
                replace(
                    second,
                    first_action_id=ActionId(
                        second.first_action_id.plan_id,
                        second.first_action_id.ordinal + 2,
                    ),
                ),
                *project.phases[2:],
            ),
        ),
    )
    for construct in invalid:
        with pytest.raises(ValueError):
            construct()


def test_aggregate_isolation_and_purge_reject_incoherent_topology() -> None:
    plan = _complete_plan()
    aggregate = next(scenario for scenario in plan.scenarios if isinstance(scenario, AggregatePlan))
    isolation = next(
        scenario for scenario in plan.scenarios if isinstance(scenario, ScopeIsolationPlan)
    )
    purge = plan.purge
    aggregate_preparation = aggregate.preparations[0]
    preserved = isolation.preserved_preparations[0]
    selected = isolation.selected_preparations[0]
    purge_preparation = purge.preparations[0]

    invalid_aggregates = (
        lambda: replace(aggregate, preparations=()),
        lambda: replace(
            aggregate,
            preparations=(replace(aggregate_preparation, kind=PhaseKind.INSTALL),),
        ),
        lambda: replace(
            aggregate,
            uninstall=replace(
                aggregate.uninstall,
                subject=AggregateSubject(("other",)),
            ),
        ),
        lambda: replace(
            aggregate,
            uninstall=replace(
                aggregate.uninstall,
                first_action_id=ActionId(
                    aggregate.uninstall.first_action_id.plan_id,
                    aggregate.uninstall.first_action_id.ordinal + 2,
                ),
            ),
        ),
    )
    invalid_isolations = (
        lambda: replace(isolation, preserved_scope=isolation.selected_scope),
        lambda: replace(
            isolation,
            preserved_preparations=(replace(preserved, kind=PhaseKind.ISOLATION_PREPARE),),
        ),
        lambda: replace(
            isolation,
            selected_preparations=(replace(selected, kind=PhaseKind.ISOLATION_PRESERVE),),
        ),
        lambda: replace(
            isolation,
            uninstall=replace(isolation.uninstall, kind=PhaseKind.AGGREGATE_UNINSTALL),
        ),
        lambda: replace(
            isolation,
            selected_preparations=(
                replace(
                    selected,
                    first_action_id=ActionId(
                        selected.first_action_id.plan_id,
                        selected.first_action_id.ordinal + 2,
                    ),
                ),
            ),
        ),
    )
    duplicate_fixture = purge.preparation.files[0]
    invalid_purges = (
        lambda: replace(
            purge,
            preparations=(replace(purge_preparation, kind=PhaseKind.INSTALL),),
        ),
        lambda: replace(
            purge,
            preparation=replace(purge.preparation, files=()),
        ),
        lambda: replace(
            purge,
            preparation=replace(
                purge.preparation,
                files=(duplicate_fixture, duplicate_fixture),
            ),
        ),
        lambda: replace(
            purge,
            purge=replace(purge.purge, kind=PhaseKind.AGGREGATE_UNINSTALL),
        ),
        lambda: replace(
            purge,
            preparation=PreparationRequest(
                ActionId(
                    purge.preparation.action_id.plan_id,
                    purge.preparation.action_id.ordinal + 1,
                ),
                purge.preparation.files,
            ),
        ),
    )
    for construct in (*invalid_aggregates, *invalid_isolations, *invalid_purges):
        with pytest.raises(ValueError):
            construct()


def test_validation_plan_rejects_cross_scenario_identity_and_order() -> None:
    plan = _complete_plan()

    invalid = (
        lambda: replace(plan, plan_id=""),
        lambda: replace(plan, scenarios=()),
        lambda: replace(plan, plan_id="different-plan"),
        lambda: replace(plan, scenarios=tuple(reversed(plan.scenarios))),
        lambda: replace(plan, scenarios=cast(tuple[object, ...], (object(),))),
    )
    for construct in invalid:
        with pytest.raises(ValueError):
            construct()


def test_result_values_reject_open_or_incoherent_statuses() -> None:
    incomplete = PhaseResult(
        PhaseKind.INSTALL,
        PhaseStatus.INCOMPLETE,
        None,
        None,
        reason="fictional diagnostic failure",
    )

    with pytest.raises(ValueError, match="Finding"):
        ProductFinding("", "detail")
    with pytest.raises(ValueError, match="closed variants"):
        PhaseResult(cast(PhaseKind, object()), PhaseStatus.INCOMPLETE, None, None, reason="x")
    with pytest.raises(ValueError, match="target and closed scope"):
        LifecycleResult("", Scope.USER, ScenarioStatus.INCOMPLETE, (incomplete,), ())
    with pytest.raises(ValueError, match="closed scope"):
        AggregateResult(cast(Scope, object()), ScenarioStatus.INCOMPLETE, (incomplete,), ())
    with pytest.raises(ValueError, match="distinct scopes"):
        ScopeIsolationResult(
            Scope.USER,
            Scope.USER,
            ScenarioStatus.INCOMPLETE,
            (incomplete,),
            (),
        )
    with pytest.raises(ValueError, match="target, scope, and reason"):
        UnsupportedResult("", Scope.USER, ScenarioStatus.UNSUPPORTED, "reason", ())
    with pytest.raises(ValueError, match="closed status"):
        PurgeResult(cast(PurgeStatus, object()), (incomplete,), None, ())
    with pytest.raises(ValueError, match="purge status disagrees"):
        PurgeResult(PurgeStatus.PASS, (incomplete,), None, ())
    with pytest.raises(ValueError, match="closed executable"):
        LifecycleResult("fictional", Scope.USER, ScenarioStatus.UNSUPPORTED, (incomplete,), ())
    with pytest.raises(ValueError, match="closed phase results"):
        LifecycleResult(
            "fictional",
            Scope.USER,
            ScenarioStatus.PASS,
            cast(tuple[PhaseResult, ...], (object(),)),
            (),
        )
    with pytest.raises(ValueError, match="scenario status disagrees"):
        LifecycleResult("fictional", Scope.USER, ScenarioStatus.PASS, (incomplete,), ())
