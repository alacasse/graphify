from __future__ import annotations

import ast
import inspect
from pathlib import Path

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

VALIDATION_PLAN_INTERNAL_TARGET_HELPER_PARAMETERS = {
    "_standard_scenarios": {"target_names"},
    "coverage_records": {"target_names"},
    "universal_uninstall_scenarios": {"target_names"},
    "target_runtime_validation_sections": {"target_names"},
    "_coverage_summary": {"target_names"},
}

VALIDATION_PLAN_INTERNAL_TARGET_CALLSITE_KEYWORDS = {
    "build_validation_plan": {"_coverage_summary.target_names"},
}


def _validation_plan_tree() -> ast.Module:
    return ast.parse(Path(validation_plan.__file__).read_text(encoding="utf-8"))


def _top_level_function(tree: ast.Module, function_name: str) -> ast.FunctionDef:
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )


def _call_keyword_names(function_node: ast.FunctionDef, called_function_name: str) -> set[str]:
    return {
        keyword.arg
        for node in ast.walk(function_node)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == called_function_name
        for keyword in node.keywords
        if keyword.arg is not None
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


def test_validation_plan_uses_target_vocabulary_for_internal_helper_names() -> None:
    plan_signature = inspect.signature(validation_plan.ValidationPlan)
    target_selector_signature = inspect.signature(validation_plan.selected_targets)

    assert "platforms" not in plan_signature.parameters
    assert {"target_name", "selected_target_names"} <= set(target_selector_signature.parameters)
    assert "platform_name" not in target_selector_signature.parameters
    assert "selected_platform_names" not in target_selector_signature.parameters

    for helper_name, expected_parameters in VALIDATION_PLAN_INTERNAL_TARGET_HELPER_PARAMETERS.items():
        helper_signature = inspect.signature(getattr(validation_plan, helper_name))

        assert set(helper_signature.parameters) >= expected_parameters
        assert "platforms" not in helper_signature.parameters

    build_source = inspect.getsource(validation_plan.build_validation_plan)
    assert "platforms=selected_target_names_tuple" not in build_source
    assert "target_names=selected_target_names_tuple" in build_source
    assert VALIDATION_PLAN_INTERNAL_TARGET_CALLSITE_KEYWORDS == {
        "build_validation_plan": {"_coverage_summary.target_names"},
    }
    assert not any(hasattr(validation_plan.ValidationPlan, name) for name in {"platforms", "selected_platforms"})


def test_validation_plan_source_has_no_internal_platform_helper_parameters_or_call_keywords() -> None:
    tree = _validation_plan_tree()

    for helper_name, expected_parameters in VALIDATION_PLAN_INTERNAL_TARGET_HELPER_PARAMETERS.items():
        helper_node = _top_level_function(tree, helper_name)
        parameter_names = {arg.arg for arg in helper_node.args.args + helper_node.args.kwonlyargs}

        assert parameter_names >= expected_parameters
        assert "platforms" not in parameter_names

    build_node = _top_level_function(tree, "build_validation_plan")
    coverage_summary_keywords = _call_keyword_names(build_node, "_coverage_summary")
    assert coverage_summary_keywords >= {"target_names"}
    assert "platforms" not in coverage_summary_keywords


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
