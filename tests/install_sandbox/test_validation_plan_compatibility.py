from __future__ import annotations

import inspect

import pytest

from tools.install_sandbox import validation_plan
from tools.install_sandbox.reporting import manifest_projection
from tools.install_sandbox.targets import install_target_models


PUBLIC_COMPATIBILITY_OUTPUT_KEYS = {
    "platform_coverage",
    "platform_coverage_summary",
    "target_runtime_validation_sections",
    "target_runtime_verification",
}

VALIDATION_PLAN_INTERNAL_ALIAS_CANDIDATES = {
    "constructor": {
        "selected_platforms",
        "universal_uninstall_scenarios",
        "disposable_artifact_scenarios",
        "platform_coverage",
        "runtime_limitation_sections",
    },
    "properties": {
        "selected_platforms",
        "selected_targets",
        "universal_uninstall_scenarios",
        "disposable_artifact_scenarios",
        "platform_coverage",
        "runtime_limitation_sections",
    },
    "helpers": {
        "selected_platforms",
        "selected_platform_names",
    },
}


def test_validation_plan_does_not_accept_selected_targets_constructor_input() -> None:
    with pytest.raises(TypeError, match="selected_targets"):
        validation_plan.ValidationPlan(  # type: ignore[call-arg]
            selected_targets=("codex",),
            requested_scope="project",
            standard_scenarios=(),
            universal_uninstall=(),
            disposable_artifacts=(),
            coverage_records=(),
            target_runtime_validation_sections=(),
            platform_coverage_summary={},
        )


def test_validation_plan_alias_inventory_separates_output_shape_from_pruning_candidates() -> None:
    plan_signature = inspect.signature(validation_plan.ValidationPlan)
    selector_signature = inspect.signature(validation_plan.selected_platforms)

    assert set(plan_signature.parameters) & VALIDATION_PLAN_INTERNAL_ALIAS_CANDIDATES["constructor"] == {
        "selected_platforms",
        "universal_uninstall_scenarios",
        "disposable_artifact_scenarios",
        "platform_coverage",
        "runtime_limitation_sections",
    }
    assert not (PUBLIC_COMPATIBILITY_OUTPUT_KEYS & VALIDATION_PLAN_INTERNAL_ALIAS_CANDIDATES["constructor"]) - {
        "platform_coverage"
    }
    assert {
        name for name in VALIDATION_PLAN_INTERNAL_ALIAS_CANDIDATES["properties"] if isinstance(getattr(validation_plan.ValidationPlan, name), property)
    } == VALIDATION_PLAN_INTERNAL_ALIAS_CANDIDATES["properties"]
    assert set(selector_signature.parameters) & VALIDATION_PLAN_INTERNAL_ALIAS_CANDIDATES["helpers"] == {
        "selected_platform_names",
    }
    assert callable(validation_plan.selected_platforms)
    assert "selected_targets" not in plan_signature.parameters


def test_validation_plan_manifest_projection_preserves_public_output_names_not_internal_aliases() -> None:
    class Plan:
        standard_validation_count = 1
        coverage_records = ({"platform": "codex", "scope": "project", "status": "runnable"},)
        target_runtime_validation_sections = ({"section_title": "Target Runtime", "status": "declared"},)
        platform_coverage_summary = {"requested_scope": "project", "universal_scenario_count": 0}
        target_runtime_verification = {"performed": False}

        selected_platforms = ("legacy-platform-property",)
        selected_targets = ("future-target-property",)
        platform_coverage = ({"platform": "internal-alias", "status": "must-not-project"},)
        runtime_limitation_sections = ({"section_title": "Internal Alias", "status": "must-not-project"},)

    projected = manifest_projection.validation_plan_manifest_projection(
        Plan(),
        [{"id": "codex-project", "passed": True}, {"id": "universal-cleanup", "passed": True}],
    )

    assert set(projected) == PUBLIC_COMPATIBILITY_OUTPUT_KEYS | {"scenario_count"}
    assert projected["platform_coverage"] == [{"platform": "codex", "scope": "project", "status": "runnable"}]
    assert projected["target_runtime_validation_sections"] == [{"section_title": "Target Runtime", "status": "declared"}]
    assert "selected_platforms" not in projected
    assert "selected_targets" not in projected
    assert "coverage_records" not in projected
    assert "runtime_limitation_sections" not in projected


def test_validation_plan_keeps_target_and_report_aliases_as_compatibility_paths() -> None:
    plan = validation_plan.ValidationPlan(
        selected_platforms=("codex",),
        requested_scope="project",
        standard_scenarios=(),
        universal_uninstall_scenarios=(),
        disposable_artifact_scenarios=(),
        platform_coverage=({"platform": "codex", "scope": "project", "status": "runnable"},),
        runtime_limitation_sections=({"section_title": "Compatibility Runtime", "status": "declared"},),
        platform_coverage_summary={"requested_scope": "project"},
    )

    assert plan.platforms == ("codex",)
    assert plan.selected_platforms == plan.platforms
    assert plan.selected_targets == plan.platforms
    assert plan.universal_uninstall == plan.universal_uninstall_scenarios == ()
    assert plan.disposable_artifacts == plan.disposable_artifact_scenarios == ()
    assert plan.validation_work_items == ()
    assert plan.coverage_records == plan.platform_coverage == ({"platform": "codex", "scope": "project", "status": "runnable"},)
    assert plan.target_runtime_validation_sections == plan.runtime_limitation_sections == (
        {"section_title": "Compatibility Runtime", "status": "declared"},
    )


def test_validation_plan_constructor_aliases_are_limited_to_supported_compatibility_names() -> None:
    required = {
        "requested_scope": "project",
        "standard_scenarios": (),
        "platform_coverage_summary": {"requested_scope": "project"},
    }

    alias_constructed = validation_plan.ValidationPlan(
        selected_platforms=("codex",),
        universal_uninstall_scenarios=(),
        disposable_artifact_scenarios=(),
        platform_coverage=(),
        runtime_limitation_sections=(),
        **required,
    )
    owner_constructed = validation_plan.ValidationPlan(
        platforms=("codex",),
        universal_uninstall=(),
        disposable_artifacts=(),
        coverage_records=(),
        target_runtime_validation_sections=(),
        **required,
    )

    assert alias_constructed == owner_constructed
    assert alias_constructed.selected_targets == ("codex",)
    with pytest.raises(TypeError, match="selected_targets"):
        validation_plan.ValidationPlan(  # type: ignore[call-arg]
            selected_targets=("codex",),
            universal_uninstall=(),
            disposable_artifacts=(),
            coverage_records=(),
            target_runtime_validation_sections=(),
            **required,
        )
    with pytest.raises(TypeError, match="scenario_count"):
        validation_plan.ValidationPlan(  # type: ignore[call-arg]
            platforms=("codex",),
            universal_uninstall=(),
            disposable_artifacts=(),
            coverage_records=(),
            target_runtime_validation_sections=(),
            scenario_count=1,
            **required,
        )
    with pytest.raises(TypeError, match="validation_work_items"):
        validation_plan.ValidationPlan(  # type: ignore[call-arg]
            platforms=("codex",),
            universal_uninstall=(),
            disposable_artifacts=(),
            coverage_records=(),
            target_runtime_validation_sections=(),
            validation_work_items=(),
            **required,
        )


def test_validation_plan_constructor_derives_work_items_without_changing_alias_paths() -> None:
    scenario = install_target_models.Scenario(
        platform="codex",
        scope="project",
        install_command=("graphify", "install"),
        uninstall_command=("graphify", "uninstall"),
        cwd_root="project",
        expected=(),
    )
    disposable = install_target_models.DisposableArtifactScenarioSpec(
        scenario_id="purge-disposable-graphify-out",
        platform_label="purge",
        scope="project",
        command=("graphify", "uninstall", "--purge"),
        cwd_root="project",
        artifact_subdir="uninstall-purge",
        disposable_path_root="project",
        disposable_path_relative="graphify-out",
        seed_files=(),
        scope_eligibility=("project",),
        risk_note="purge verified only against disposable sandbox graphify-out state",
    )

    plan = validation_plan.ValidationPlan(
        selected_platforms=("codex",),
        requested_scope="project",
        standard_scenarios=(scenario,),
        universal_uninstall_scenarios=(),
        disposable_artifact_scenarios=(disposable,),
        platform_coverage=(),
        runtime_limitation_sections=(),
        platform_coverage_summary={"requested_scope": "project"},
    )

    assert plan.validation_work_items == (
        validation_plan.ValidationWorkItem("standard_scenario", scenario),
        validation_plan.ValidationWorkItem("disposable_artifact", disposable),
    )
    assert plan.standard_scenarios == (scenario,)
    assert plan.disposable_artifacts == plan.disposable_artifact_scenarios == (disposable,)
    assert plan.standard_validation_count == 1
    assert plan.synthetic_scenario_count == 1
    assert plan.scenario_count == 2
