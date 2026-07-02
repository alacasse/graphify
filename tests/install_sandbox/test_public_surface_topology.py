from __future__ import annotations

import importlib
import importlib.util
import inspect
import types
from pathlib import Path


INSTALL_SANDBOX_ROOT = Path(__file__).parents[2] / "tools" / "install_sandbox"

DELETED_PURE_ROOT_FACADE_MODULES = {
    "tools.install_sandbox.expected_effects",
    "tools.install_sandbox.platform_specs",
    "tools.install_sandbox.spec_loader",
    "tools.install_sandbox.spec_normalize",
    "tools.install_sandbox.status",
}

DELETED_INSTALL_SURFACE_CORE_FACADE_MODULES = {
    "tools.install_sandbox.install_surface_core",
}

DELETED_ROOT_HELPER_MODULES = {
    "tools.install_sandbox.file_walk",
    "tools.install_sandbox.json_helpers",
}

DELETED_AGENT_SUMMARY_SHIM_MODULES = {
    "tools.install_sandbox.agent_summary",
}

SUPPORTED_ROOT_ENTRYPOINT_MODULES = {
    "tools.install_sandbox.run",
    "tools.install_sandbox.sandbox_runner",
    "tools.install_sandbox.sandbox_roots",
    "tools.install_sandbox.validation_plan",
}

SUPPORTED_SANDBOX_RUNNER_APIS = {
    "main": "tools.install_sandbox.sandbox_runner",
    "parse_args": "tools.install_sandbox.sandbox_runner",
}

VALIDATION_PLAN_ROOT_SEAM_APIS = {
    "build_validation_plan",
    "selected_targets",
    "ValidationPlan",
    "ValidationWorkItem",
    "HarnessPolicy",
    "validate_policy_owned_roots",
}

VALIDATION_PLAN_ALIAS_PRUNING_CANDIDATES = {
    "constructor_aliases": {
        "platforms",
        "selected_platforms",
        "universal_uninstall_scenarios",
        "disposable_artifact_scenarios",
        "platform_coverage",
        "platform_coverage_summary",
        "runtime_limitation_sections",
    },
    "property_aliases": {
        "platforms",
        "selected_platforms",
        "universal_uninstall_scenarios",
        "disposable_artifact_scenarios",
        "platform_coverage",
        "platform_coverage_summary",
        "runtime_limitation_sections",
    },
    "helper_aliases": {
        "selected_platforms",
    },
}

VALIDATION_PLAN_PUBLIC_OUTPUT_FIELDS = {
    "target_coverage",
    "target_coverage_summary",
    "target_runtime_validation_sections",
    "target_runtime_verification",
}

SANDBOX_RUNNER_PRUNED_ALIASES = {
    "ROOT_REGISTRY",
    "RUNTIME_ROOTS",
    "HOME",
    "XDG_CONFIG_HOME",
    "PROJECT",
    "USER_CWD",
    "REPO_MOUNT",
    "SRC",
    "OUTPUT",
    "HARNESS_VERSION",
    "SCENARIO_REGISTRY",
    "USER_SENTINEL",
    "STALE_GRAPHIFY_SENTINEL",
    "ScenarioRunContext",
    "StandardScenarioStages",
    "RISK_GRAPHIFY_FAILED",
    "RISK_GRAPHIFY_VERIFIED",
    "combined_status",
    "known_status_values",
    "sandbox_env",
    "install_graphify",
    "risk_report",
    "preflight",
    "scenario_lifecycle_hooks",
}


def test_supported_package_imports_remain_importable() -> None:
    for module_name in (
        "tools.install_sandbox.registry.spec_loader",
        "tools.install_sandbox.registry.spec_normalize",
        "tools.install_sandbox.reporting.harness_run",
        "tools.install_sandbox.reporting.reports",
        "tools.install_sandbox.reporting.agent_summary",
        "tools.install_sandbox.runtime.command_runner",
        "tools.install_sandbox.runtime.container_runtime",
        "tools.install_sandbox.runtime.harness_orchestration",
        "tools.install_sandbox.runtime.source_snapshot",
    ):
        assert importlib.import_module(module_name).__name__ == module_name


def test_public_root_command_and_package_entrypoints_remain_importable() -> None:
    for module_name in SUPPORTED_ROOT_ENTRYPOINT_MODULES:
        assert importlib.import_module(module_name).__name__ == module_name

    sandbox_runner = importlib.import_module("tools.install_sandbox.sandbox_runner")
    for public_name, owner_module_name in SUPPORTED_SANDBOX_RUNNER_APIS.items():
        public_api = getattr(sandbox_runner, public_name)
        assert callable(public_api)
        assert public_api.__module__ == owner_module_name


def test_deleted_root_facades_stay_absent() -> None:
    for module_name in (
        *DELETED_PURE_ROOT_FACADE_MODULES,
        *DELETED_INSTALL_SURFACE_CORE_FACADE_MODULES,
        *DELETED_ROOT_HELPER_MODULES,
        *DELETED_AGENT_SUMMARY_SHIM_MODULES,
        "tools.install_sandbox.harness_specs",
        "tools.install_sandbox.reference_resolution",
    ):
        root_file_name = module_name.rsplit(".", maxsplit=1)[-1]

        assert not (INSTALL_SANDBOX_ROOT / f"{root_file_name}.py").exists()
        assert importlib.util.find_spec(module_name) is None


def test_deleted_implementation_modules_stay_absent_from_root_package() -> None:
    removed_root_implementation_modules = (
        "reports",
        "command_runner",
        "container_runtime",
        "source_snapshot",
        "install_surface_generated",
        "install_surface_sidecars",
        "install_surface_state",
        "install_surface_statuses",
        "install_target_catalog",
        "install_target_defaults",
        "install_target_harness_policy",
        "install_target_models",
        "install_target_scenarios",
        "install_target_selection",
        "spec_loader",
        "spec_normalize",
        "status",
        "expected_effects",
    )
    for module_name in removed_root_implementation_modules:
        assert not (INSTALL_SANDBOX_ROOT / f"{module_name}.py").exists()
        assert importlib.util.find_spec(f"tools.install_sandbox.{module_name}") is None


def test_sandbox_roots_is_supported_root_package_owner() -> None:
    sandbox_roots = importlib.import_module("tools.install_sandbox.sandbox_roots")

    assert hasattr(sandbox_roots, "SandboxRootRegistry")
    assert hasattr(sandbox_roots, "SandboxRootSpec")
    assert hasattr(sandbox_roots, "DEFAULT_SANDBOX_ROOT_REGISTRY")


def test_validation_reporting_and_runner_public_apis_remain_owned() -> None:
    validation_plan = importlib.import_module("tools.install_sandbox.validation_plan")
    manifest_projection = importlib.import_module("tools.install_sandbox.reporting.manifest_projection")
    harness_run = importlib.import_module("tools.install_sandbox.reporting.harness_run")
    reports = importlib.import_module("tools.install_sandbox.reporting.reports")
    agent_summary = importlib.import_module("tools.install_sandbox.reporting.agent_summary")
    harness_orchestration = importlib.import_module("tools.install_sandbox.runtime.harness_orchestration")
    sandbox_runner = importlib.import_module("tools.install_sandbox.sandbox_runner")

    assert callable(validation_plan.build_validation_plan)
    assert validation_plan.HarnessPolicy
    assert validation_plan.DEFAULT_HARNESS_POLICY.target_runtime_verification
    assert callable(manifest_projection.validation_plan_manifest_projection)
    assert callable(reports.render_report_md)
    assert callable(reports.write_report_md)
    assert callable(agent_summary.summarize_output)
    assert callable(agent_summary.write_summary)
    assert callable(harness_run.harness_run_result)
    assert callable(harness_run.write_harness_run_outputs)
    assert callable(harness_orchestration.run_harness)
    assert not hasattr(harness_orchestration, "run_harness_and_write_outputs")
    for public_name, owner_module_name in SUPPORTED_SANDBOX_RUNNER_APIS.items():
        assert getattr(sandbox_runner, public_name).__module__ == owner_module_name
        assert callable(getattr(sandbox_runner, public_name))


def test_validation_plan_public_surface_excludes_pruned_aliases() -> None:
    validation_plan = importlib.import_module("tools.install_sandbox.validation_plan")
    plan_signature = inspect.signature(validation_plan.ValidationPlan)
    target_selector_signature = inspect.signature(validation_plan.selected_targets)

    for public_name in VALIDATION_PLAN_ROOT_SEAM_APIS:
        assert hasattr(validation_plan, public_name)

    assert VALIDATION_PLAN_ROOT_SEAM_APIS.isdisjoint(
        VALIDATION_PLAN_ALIAS_PRUNING_CANDIDATES["constructor_aliases"]
        | VALIDATION_PLAN_ALIAS_PRUNING_CANDIDATES["property_aliases"]
        | VALIDATION_PLAN_ALIAS_PRUNING_CANDIDATES["helper_aliases"]
    )
    assert not set(plan_signature.parameters) & VALIDATION_PLAN_ALIAS_PRUNING_CANDIDATES["constructor_aliases"]
    assert not any(
        hasattr(validation_plan.ValidationPlan, public_name)
        for public_name in VALIDATION_PLAN_ALIAS_PRUNING_CANDIDATES["property_aliases"]
    )
    assert not any(
        hasattr(validation_plan, public_name)
        for public_name in VALIDATION_PLAN_ALIAS_PRUNING_CANDIDATES["helper_aliases"]
    )
    assert set(target_selector_signature.parameters) >= {"all_targets", "target_name", "selected_target_names"}
    assert VALIDATION_PLAN_PUBLIC_OUTPUT_FIELDS == {
        "target_coverage",
        "target_coverage_summary",
        "target_runtime_validation_sections",
        "target_runtime_verification",
    }
    assert "selected_targets" not in VALIDATION_PLAN_PUBLIC_OUTPUT_FIELDS
    assert "coverage_records" not in VALIDATION_PLAN_PUBLIC_OUTPUT_FIELDS
    assert "runtime_limitation_sections" not in VALIDATION_PLAN_PUBLIC_OUTPUT_FIELDS


def test_sandbox_runner_public_surface_excludes_pruned_runtime_aliases() -> None:
    sandbox_runner = importlib.import_module("tools.install_sandbox.sandbox_runner")

    for public_name in SANDBOX_RUNNER_PRUNED_ALIASES:
        assert not hasattr(sandbox_runner, public_name)

    ordinary_imported_dependencies = {
        "harness_run": "tools.install_sandbox.reporting.harness_run",
        "harness_orchestration": "tools.install_sandbox.runtime.harness_orchestration",
        "validation_plan": "tools.install_sandbox.validation_plan",
    }
    for dependency_name, owner_module_name in ordinary_imported_dependencies.items():
        dependency = getattr(sandbox_runner, dependency_name)
        assert isinstance(dependency, types.ModuleType)
        assert dependency.__name__ == owner_module_name
        assert dependency is importlib.import_module(owner_module_name)
