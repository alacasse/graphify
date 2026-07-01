from __future__ import annotations

import inspect

import pytest

from tools.install_sandbox import validation_plan
from tools.install_sandbox.reporting import manifest_projection
from tests.install_sandbox.validation_plan_test_support import planner_registry


PUBLIC_COMPATIBILITY_OUTPUT_KEYS = {
    "target_coverage",
    "target_coverage_summary",
    "target_runtime_validation_sections",
    "target_runtime_verification",
}

VALIDATION_PLAN_PRUNED_COMPATIBILITY_ALIASES = {
    "constructor": {
        "platforms",
        "selected_platforms",
        "universal_uninstall_scenarios",
        "disposable_artifact_scenarios",
        "platform_coverage",
        "platform_coverage_summary",
        "runtime_limitation_sections",
    },
    "properties": {
        "platforms",
        "selected_platforms",
        "universal_uninstall_scenarios",
        "disposable_artifact_scenarios",
        "platform_coverage",
        "platform_coverage_summary",
        "runtime_limitation_sections",
    },
    "helpers": {
        "selected_platforms",
        "selected_platform_names",
    },
}


def test_validation_plan_alias_inventory_keeps_only_owner_names_and_output_shape() -> None:
    plan_signature = inspect.signature(validation_plan.ValidationPlan)
    target_selector_signature = inspect.signature(validation_plan.selected_targets)

    assert set(plan_signature.parameters) == {
        "selected_targets",
        "requested_scope",
        "standard_scenarios",
        "universal_uninstall",
        "disposable_artifacts",
        "coverage_records",
        "target_runtime_validation_sections",
        "target_coverage_summary",
        "target_runtime_verification",
    }
    assert not set(plan_signature.parameters) & VALIDATION_PLAN_PRUNED_COMPATIBILITY_ALIASES["constructor"]
    assert not any(hasattr(validation_plan.ValidationPlan, name) for name in VALIDATION_PLAN_PRUNED_COMPATIBILITY_ALIASES["properties"])
    assert not any(hasattr(validation_plan, name) for name in VALIDATION_PLAN_PRUNED_COMPATIBILITY_ALIASES["helpers"])
    assert set(target_selector_signature.parameters) >= {"all_targets", "target_name", "selected_target_names"}
    assert callable(validation_plan.selected_targets)
    assert PUBLIC_COMPATIBILITY_OUTPUT_KEYS == {
        "target_coverage",
        "target_coverage_summary",
        "target_runtime_validation_sections",
        "target_runtime_verification",
    }


def test_validation_plan_manifest_projection_preserves_public_output_names_not_internal_aliases() -> None:
    class Plan:
        standard_validation_count = 1
        coverage_records = ({"target": "codex", "scope": "project", "status": "runnable"},)
        target_runtime_validation_sections = ({"section_title": "Target Runtime", "status": "declared"},)
        target_coverage_summary = {"requested_scope": "project", "universal_scenario_count": 0}
        target_runtime_verification = {"performed": False}

        selected_platforms = ("legacy-platform-property",)
        selected_targets = ("future-target-property",)
        platform_coverage = ({"platform": "internal-alias", "status": "must-not-project"},)
        platform_coverage_summary = {"requested_scope": "legacy"}
        runtime_limitation_sections = ({"section_title": "Internal Alias", "status": "must-not-project"},)

    projected = manifest_projection.validation_plan_manifest_projection(
        Plan(),
        [{"id": "codex-project", "passed": True}, {"id": "universal-cleanup", "passed": True}],
    )

    assert set(projected) == PUBLIC_COMPATIBILITY_OUTPUT_KEYS | {"scenario_count"}
    assert projected["target_coverage"] == [{"target": "codex", "scope": "project", "status": "runnable"}]
    assert projected["target_coverage_summary"] == {"requested_scope": "project", "universal_scenario_count": 1}
    assert projected["target_runtime_validation_sections"] == [{"section_title": "Target Runtime", "status": "declared"}]
    assert "platform_coverage" not in projected
    assert "platform_coverage_summary" not in projected
    assert "selected_platforms" not in projected
    assert "selected_targets" not in projected
    assert "coverage_records" not in projected
    assert "runtime_limitation_sections" not in projected


def test_validation_plan_constructor_rejects_pruned_compatibility_aliases() -> None:
    required = {
        "selected_targets": ("codex",),
        "requested_scope": "project",
        "standard_scenarios": (),
        "universal_uninstall": (),
        "disposable_artifacts": (),
        "coverage_records": (),
        "target_runtime_validation_sections": (),
        "target_coverage_summary": {"requested_scope": "project"},
    }

    for alias_name in VALIDATION_PLAN_PRUNED_COMPATIBILITY_ALIASES["constructor"] | {
        "scenario_count",
        "validation_work_items",
    }:
        kwargs = dict(required)
        kwargs[alias_name] = () if alias_name != "platform_coverage" else ()
        with pytest.raises(TypeError, match=alias_name):
            validation_plan.ValidationPlan(  # type: ignore[call-arg]
                **kwargs,
            )


def test_validation_plan_target_named_build_selection_is_owner_path() -> None:
    registry = planner_registry()

    selected = validation_plan.selected_targets(
        registry,
        all_targets=False,
        target_name=None,
        selected_target_names=("gemini", "codex"),
    )
    plan = validation_plan.build_validation_plan(
        registry,
        all_targets=False,
        target_name=None,
        selected_target_names=("gemini", "codex"),
        scope="project",
    )

    assert selected == ("gemini", "codex")
    assert plan.selected_targets == ("gemini", "codex")
    assert [(scenario.target_name, scenario.scope) for scenario in plan.standard_scenarios] == [
        ("gemini", "project"),
        ("codex", "project"),
    ]
