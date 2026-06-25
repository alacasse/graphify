from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path


INSTALL_SANDBOX_ROOT = Path(__file__).parents[2] / "tools" / "install_sandbox"


def test_root_topology_closeout_keeps_moved_implementation_packages_importable() -> None:
    for module_name in (
        "tools.install_sandbox.registry.spec_loader",
        "tools.install_sandbox.registry.spec_normalize",
        "tools.install_sandbox.reporting.harness_run",
        "tools.install_sandbox.reporting.reports",
        "tools.install_sandbox.reporting.agent_summary",
        "tools.install_sandbox.runtime.command_runner",
        "tools.install_sandbox.runtime.container_runtime",
        "tools.install_sandbox.runtime.source_snapshot",
    ):
        assert importlib.import_module(module_name).__name__ == module_name


def test_root_topology_closeout_keeps_old_implementation_modules_absent() -> None:
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
    )
    for module_name in removed_root_implementation_modules:
        assert not (INSTALL_SANDBOX_ROOT / f"{module_name}.py").exists()
        assert importlib.util.find_spec(f"tools.install_sandbox.{module_name}") is None


def test_root_topology_closeout_keeps_batch_compatibility_facades_importable() -> None:
    root_agent_summary = importlib.import_module("tools.install_sandbox.agent_summary")
    owner_agent_summary = importlib.import_module("tools.install_sandbox.reporting.agent_summary")
    root_spec_loader = importlib.import_module("tools.install_sandbox.spec_loader")
    owner_spec_loader = importlib.import_module("tools.install_sandbox.registry.spec_loader")
    root_spec_normalize = importlib.import_module("tools.install_sandbox.spec_normalize")
    owner_spec_normalize = importlib.import_module("tools.install_sandbox.registry.spec_normalize")
    root_install_surface_core = importlib.import_module("tools.install_sandbox.install_surface_core")
    owner_install_surface_statuses = importlib.import_module("tools.install_sandbox.surfaces.install_surface_statuses")
    root_expected_effects = importlib.import_module("tools.install_sandbox.expected_effects")
    owner_install_surface_models = importlib.import_module("tools.install_sandbox.surfaces.install_surface_models")
    root_platform_specs = importlib.import_module("tools.install_sandbox.platform_specs")
    owner_install_target_catalog = importlib.import_module("tools.install_sandbox.targets.install_target_catalog")
    root_status = importlib.import_module("tools.install_sandbox.status")
    owner_status = importlib.import_module("tools.install_sandbox.reporting.status")

    assert (INSTALL_SANDBOX_ROOT / "agent_summary.py").exists()
    assert (INSTALL_SANDBOX_ROOT / "spec_loader.py").exists()
    assert (INSTALL_SANDBOX_ROOT / "spec_normalize.py").exists()
    assert (INSTALL_SANDBOX_ROOT / "install_surface_core.py").exists()
    assert (INSTALL_SANDBOX_ROOT / "expected_effects.py").exists()
    assert (INSTALL_SANDBOX_ROOT / "platform_specs.py").exists()
    assert (INSTALL_SANDBOX_ROOT / "status.py").exists()
    assert root_agent_summary.summarize_output is owner_agent_summary.summarize_output
    assert root_spec_loader.load_default_registry is owner_spec_loader.load_default_registry
    assert set(root_spec_loader.__all__) == {
        "DEFAULT_REGISTRY_PATH",
        "SCHEMA_VERSION",
        "InstallTargetCatalog",
        "ScenarioRegistry",
        "SpecLoaderError",
        "load_default_registry",
        "load_registry_from_data",
        "load_registry_from_dir",
        "load_registry_from_yaml",
    }
    assert root_spec_normalize.normalize_registry is owner_spec_normalize.normalize_registry
    assert root_spec_normalize.__all__ == ["normalize_registry"]
    assert root_install_surface_core.InstallSurfaceStatus is owner_install_surface_statuses.InstallSurfaceStatus
    assert root_expected_effects.InstallSurface is owner_install_surface_models.InstallSurface
    assert root_platform_specs.InstallTargetCatalog is owner_install_target_catalog.InstallTargetCatalog
    assert root_status.known_status_values is owner_status.known_status_values


def test_root_topology_closeout_names_validation_reporting_and_runner_public_apis() -> None:
    validation_plan = importlib.import_module("tools.install_sandbox.validation_plan")
    manifest_projection = importlib.import_module("tools.install_sandbox.reporting.manifest_projection")
    harness_run = importlib.import_module("tools.install_sandbox.reporting.harness_run")
    reports = importlib.import_module("tools.install_sandbox.reporting.reports")
    agent_summary = importlib.import_module("tools.install_sandbox.reporting.agent_summary")
    sandbox_runner = importlib.import_module("tools.install_sandbox.sandbox_runner")
    root_agent_summary = importlib.import_module("tools.install_sandbox.agent_summary")

    assert callable(validation_plan.build_validation_plan)
    assert validation_plan.HarnessPolicy
    assert validation_plan.DEFAULT_HARNESS_POLICY.target_runtime_verification
    assert callable(manifest_projection.validation_plan_manifest_projection)
    assert callable(reports.render_report_md)
    assert callable(reports.write_report_md)
    assert callable(agent_summary.summarize_output)
    assert callable(agent_summary.write_summary)
    assert callable(harness_run.harness_run_result)
    assert callable(sandbox_runner.main)
    assert callable(sandbox_runner.parse_args)
    assert root_agent_summary.summarize_output is agent_summary.summarize_output


def test_root_topology_closeout_harness_run_projects_validation_plan_manifest_fields() -> None:
    harness_run = importlib.import_module("tools.install_sandbox.reporting.harness_run")

    class Plan:
        standard_scenarios = ("codex-project",)
        coverage_records = ({"platform": "codex", "scope": "project", "status": "runnable"},)
        target_runtime_validation_sections = ({"section_title": "Runtime Boundary", "status": "declared"},)
        platform_coverage_summary = {"requested_scope": "project", "universal_scenario_count": 0}
        target_runtime_verification = {"performed": False}

    manifest = harness_run.harness_run_result(
        harness_version="test",
        python_version="3.12",
        os_release={},
        architecture="x86_64",
        package_install={"version": "9.9.9"},
        source_snapshot={},
        preflight={},
        plan=Plan(),
        results=[{"id": "codex-project", "passed": True}, {"id": "universal-cleanup", "passed": True}],
    ).manifest()

    assert manifest["target_runtime_verification"] == {"performed": False}
    assert manifest["target_runtime_validation_sections"] == [{"section_title": "Runtime Boundary", "status": "declared"}]
    assert manifest["platform_coverage"] == [{"platform": "codex", "scope": "project", "status": "runnable"}]
    assert manifest["platform_coverage_summary"]["universal_scenario_count"] == 1
    assert manifest["scenario_count"] == 2
