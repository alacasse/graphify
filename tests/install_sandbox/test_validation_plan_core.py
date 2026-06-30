from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from tools.install_sandbox import validation_plan
from tools.install_sandbox.targets import install_target_catalog, install_target_models
from tests.install_sandbox.validation_plan_test_support import planner_registry, scope


def test_validation_plan_orders_all_targets_and_standard_scenarios() -> None:
    registry = install_target_catalog.ScenarioRegistry(
        {
            "zeta": install_target_models.InstallTargetSpec(
                name="zeta",
                scopes={
                    "user": install_target_models.ScopeSpec(
                        install_command=("install", "zeta-user"),
                        uninstall_command=None,
                        cwd_root="user_cwd",
                        expected=(install_target_models.InstallSurface("home", "zeta-user.txt"),),
                    ),
                    "project": install_target_models.ScopeSpec(
                        install_command=("install", "zeta-project"),
                        uninstall_command=None,
                        cwd_root="project",
                        expected=(install_target_models.InstallSurface("project", "zeta-project.txt"),),
                    ),
                },
            ),
            "alpha": install_target_models.InstallTargetSpec(
                name="alpha",
                scopes={
                    "project": install_target_models.ScopeSpec(
                        install_command=("install", "alpha-project"),
                        uninstall_command=None,
                        cwd_root="project",
                        expected=(install_target_models.InstallSurface("project", "alpha-project.txt"),),
                    )
                },
                unsupported_scopes={"user": "not supported"},
            ),
        }
    )

    plan = validation_plan.build_validation_plan(registry, all_targets=True, target_name=None, scope="both")

    assert plan.selected_targets == ("alpha", "zeta")
    assert [(scenario.platform, scenario.scope) for scenario in plan.standard_scenarios] == [
        ("alpha", "project"),
        ("zeta", "user"),
        ("zeta", "project"),
    ]


def test_validation_plan_rejects_unknown_platform() -> None:
    registry = install_target_catalog.ScenarioRegistry({"known": install_target_models.InstallTargetSpec(name="known")})

    with pytest.raises(RuntimeError, match="unknown sandbox platform"):
        validation_plan.build_validation_plan(registry, all_targets=False, target_name="missing", scope="project")


@pytest.mark.xfail(
    reason="Temporary LR-B8 removal-driving xfail: Slice 2 must rename the public plan summary to target_coverage_summary; not permanent compatibility preservation.",
    strict=True,
)
def test_validation_plan_preserves_explicit_target_order_and_full_plan_contents() -> None:
    registry = planner_registry()

    plan = validation_plan.build_validation_plan(
        registry,
        all_targets=False,
        target_name=None,
        selected_target_names=("gemini", "claude", "codex"),
        scope="project",
    )

    assert plan.selected_targets == ("gemini", "claude", "codex")
    assert [(scenario.platform, scenario.scope) for scenario in plan.standard_scenarios] == [
        ("gemini", "project"),
        ("claude", "project"),
        ("codex", "project"),
    ]
    assert plan.synthetic_scenario_count == 2
    assert plan.scenario_count == 5
    assert len(plan.universal_uninstall) == 1
    assert plan.universal_uninstall[0].spec.scenario_id == "universal-uninstall-project"
    assert [scenario.platform for scenario in plan.universal_uninstall[0].installed_scenarios] == [
        "gemini",
        "claude",
        "codex",
    ]
    assert [scenario.scenario_id for scenario in plan.disposable_artifacts] == ["purge-disposable-graphify-out"]
    generic_direct_equivalence = {
        "status": "not_applicable",
        "reason": "generic and direct commands are unsupported or intentionally differ for this platform/scope",
    }
    assert plan.coverage_records == (
        {
            "platform": "gemini",
            "scope": "project",
            "status": "runnable",
            "scenario_id": "gemini-project",
            "install_command": ["graphify", "install"],
            "uninstall_command": ["graphify", "uninstall"],
            "generic_direct_equivalence": generic_direct_equivalence,
            "risk_notes": [],
        },
        {
            "platform": "claude",
            "scope": "project",
            "status": "runnable",
            "scenario_id": "claude-project",
            "install_command": ["graphify", "install"],
            "uninstall_command": ["graphify", "uninstall"],
            "generic_direct_equivalence": generic_direct_equivalence,
            "risk_notes": [],
        },
        {
            "platform": "codex",
            "scope": "project",
            "status": "runnable",
            "scenario_id": "codex-project",
            "install_command": ["graphify", "install"],
            "uninstall_command": ["graphify", "uninstall"],
            "generic_direct_equivalence": generic_direct_equivalence,
            "risk_notes": [],
        },
    )
    assert plan.target_runtime_validation_sections == ()
    assert plan.target_coverage_summary == {
        "registered_target_count": 3,
        "requested_scope": "project",
        "runnable_scope_count": 3,
        "universal_scenario_count": 2,
        "unsupported_scope_count": 0,
    }
    assert plan.target_runtime_verification == validation_plan.TARGET_RUNTIME_VERIFICATION_POLICY


def test_validation_plan_builds_ordered_typed_work_items_from_existing_buckets() -> None:
    registry = planner_registry()

    plan = validation_plan.build_validation_plan(
        registry,
        all_targets=False,
        target_name=None,
        selected_target_names=("gemini", "claude", "codex"),
        scope="project",
    )

    assert [work_item.kind for work_item in plan.validation_work_items] == [
        "standard_scenario",
        "standard_scenario",
        "standard_scenario",
        "universal_uninstall",
        "disposable_artifact",
    ]
    assert [work_item.payload for work_item in plan.validation_work_items] == [
        *plan.standard_scenarios,
        *plan.universal_uninstall,
        *plan.disposable_artifacts,
    ]
    assert plan.standard_validation_count == 3
    assert plan.synthetic_scenario_count == 2
    assert plan.scenario_count == 5


def test_validation_work_item_is_frozen_plan_owned_model() -> None:
    scenario = install_target_models.Scenario(
        platform="codex",
        scope="project",
        install_command=("graphify", "install"),
        uninstall_command=("graphify", "uninstall"),
        cwd_root="project",
        expected=(),
    )
    work_item = validation_plan.ValidationWorkItem("standard_scenario", scenario)

    assert work_item.kind == "standard_scenario"
    assert work_item.payload == scenario
    with pytest.raises(FrozenInstanceError):
        work_item.kind = "disposable_artifact"  # type: ignore[misc]


@pytest.mark.xfail(
    reason="Temporary LR-B8 removal-driving xfail: Slice 2 must rename the public plan summary to target_coverage_summary; not permanent compatibility preservation.",
    strict=True,
)
def test_validation_plan_builds_full_ordered_plan_for_both_scope() -> None:
    registry = install_target_catalog.ScenarioRegistry(
        {
            "alpha": install_target_models.InstallTargetSpec(
                name="alpha",
                scopes={
                    "user": scope("alpha-user.txt"),
                    "project": scope("alpha-project.txt"),
                },
                universal_uninstall_scopes=("user", "project"),
            ),
            "beta": install_target_models.InstallTargetSpec(
                name="beta",
                scopes={
                    "user": scope("beta-user.txt"),
                    "project": scope("beta-project.txt"),
                },
                universal_uninstall_scopes=("user", "project"),
            ),
        }
    )

    plan = validation_plan.build_validation_plan(
        registry,
        all_targets=False,
        selected_target_names=("beta", "alpha"),
        scope="both",
    )

    assert plan.selected_targets == ("beta", "alpha")
    assert [(scenario.platform, scenario.scope) for scenario in plan.standard_scenarios] == [
        ("beta", "user"),
        ("beta", "project"),
        ("alpha", "user"),
        ("alpha", "project"),
    ]
    assert [selected.spec.scenario_id for selected in plan.universal_uninstall] == [
        "universal-uninstall-user",
        "universal-uninstall-project",
    ]
    assert [
        [(scenario.platform, scenario.scope) for scenario in selected.installed_scenarios]
        for selected in plan.universal_uninstall
    ] == [
        [("beta", "user"), ("alpha", "user")],
        [("beta", "project"), ("alpha", "project")],
    ]
    assert [scenario.scenario_id for scenario in plan.disposable_artifacts] == ["purge-disposable-graphify-out"]
    assert plan.synthetic_scenario_count == 3
    assert plan.scenario_count == 7
    assert plan.target_coverage_summary == {
        "registered_target_count": 2,
        "requested_scope": "both",
        "runnable_scope_count": 4,
        "universal_scenario_count": 3,
        "unsupported_scope_count": 0,
    }
    assert [work_item.kind for work_item in plan.validation_work_items] == [
        "standard_scenario",
        "standard_scenario",
        "standard_scenario",
        "standard_scenario",
        "universal_uninstall",
        "universal_uninstall",
        "disposable_artifact",
    ]


def test_validation_plan_rejects_unknown_explicit_target_names() -> None:
    registry = planner_registry()

    with pytest.raises(RuntimeError, match="unknown sandbox platform\\(s\\): missing, absent"):
        validation_plan.build_validation_plan(
            registry,
            all_targets=False,
            target_name=None,
            selected_target_names=("gemini", "missing", "absent"),
            scope="project",
        )


@pytest.mark.xfail(
    reason="Temporary LR-B8 removal-driving xfail: Slice 2 must accept target_coverage_summary constructor input; not permanent compatibility preservation.",
    strict=True,
)
def test_validation_plan_accepts_owner_named_selected_targets_constructor_input() -> None:
    plan = validation_plan.ValidationPlan(
        selected_targets=("codex",),
        requested_scope="project",
        standard_scenarios=(),
        universal_uninstall=(),
        disposable_artifacts=(),
        coverage_records=(),
        target_runtime_validation_sections=(),
        target_coverage_summary={"requested_scope": "project"},
    )

    assert plan.selected_targets == ("codex",)
