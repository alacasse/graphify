from __future__ import annotations

import ast
import importlib
import importlib.util
import types
from pathlib import Path


INSTALL_SANDBOX_ROOT = Path(__file__).parents[2] / "tools" / "install_sandbox"
INSTALL_SANDBOX_TESTS_ROOT = Path(__file__).parents[1] / "install_sandbox"

DELETED_PURE_ROOT_FACADE_MODULES = {
    "tools.install_sandbox.expected_effects",
    "tools.install_sandbox.spec_loader",
    "tools.install_sandbox.spec_normalize",
    "tools.install_sandbox.status",
}

DEFERRED_BROAD_COMPATIBILITY_FACADE_MODULES = {
    "tools.install_sandbox.install_surface_core",
    "tools.install_sandbox.platform_specs",
}

ROOT_WORTHY_COMPATIBILITY_ENTRYPOINTS = {
    "tools.install_sandbox.agent_summary",
}

PLATFORM_SPECS_DIRECT_TEST_IMPORT_SURFACE = {
    "tests/install_sandbox/test_platform_specs_facade.py": [
        "tools.install_sandbox.platform_specs",
    ],
    "tests/install_sandbox/test_spec_effect_derivation.py": [
        "tools.install_sandbox.platform_specs",
    ],
}


def _direct_test_import_surface(module_names: set[str]) -> dict[str, list[str]]:
    discovered_imports: dict[str, list[str]] = {}

    for path in sorted(INSTALL_SANDBOX_TESTS_ROOT.glob("test_*.py")):
        relative = path.relative_to(Path(__file__).parents[2]).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        direct_imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "tools.install_sandbox":
                for alias in node.names:
                    module_name = f"tools.install_sandbox.{alias.name}"
                    if module_name in module_names:
                        direct_imports.add(module_name)
            elif isinstance(node, ast.ImportFrom) and node.module in module_names:
                direct_imports.add(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in module_names:
                        direct_imports.add(alias.name)

        if direct_imports:
            discovered_imports[relative] = sorted(direct_imports)

    return discovered_imports


def test_root_topology_closeout_keeps_moved_implementation_packages_importable() -> None:
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
        "spec_loader",
        "spec_normalize",
        "status",
        "expected_effects",
    )
    for module_name in removed_root_implementation_modules:
        assert not (INSTALL_SANDBOX_ROOT / f"{module_name}.py").exists()
        assert importlib.util.find_spec(f"tools.install_sandbox.{module_name}") is None


def test_root_topology_closeout_keeps_deleted_pure_root_facades_absent() -> None:
    for module_name in DELETED_PURE_ROOT_FACADE_MODULES:
        root_file_name = module_name.rsplit(".", maxsplit=1)[-1]

        assert not (INSTALL_SANDBOX_ROOT / f"{root_file_name}.py").exists()
        assert importlib.util.find_spec(module_name) is None
        assert module_name not in DEFERRED_BROAD_COMPATIBILITY_FACADE_MODULES
        assert module_name not in ROOT_WORTHY_COMPATIBILITY_ENTRYPOINTS


def test_root_topology_closeout_characterizes_compatibility_facade_buckets() -> None:
    assert DELETED_PURE_ROOT_FACADE_MODULES == {
        "tools.install_sandbox.expected_effects",
        "tools.install_sandbox.spec_loader",
        "tools.install_sandbox.spec_normalize",
        "tools.install_sandbox.status",
    }
    assert DEFERRED_BROAD_COMPATIBILITY_FACADE_MODULES == {
        "tools.install_sandbox.install_surface_core",
        "tools.install_sandbox.platform_specs",
    }
    assert ROOT_WORTHY_COMPATIBILITY_ENTRYPOINTS == {
        "tools.install_sandbox.agent_summary",
    }
    assert DELETED_PURE_ROOT_FACADE_MODULES.isdisjoint(DEFERRED_BROAD_COMPATIBILITY_FACADE_MODULES)
    assert DELETED_PURE_ROOT_FACADE_MODULES.isdisjoint(ROOT_WORTHY_COMPATIBILITY_ENTRYPOINTS)


def test_root_topology_closeout_keeps_root_worthy_and_temporary_deferred_facades_importable() -> None:
    root_agent_summary = importlib.import_module("tools.install_sandbox.agent_summary")
    owner_agent_summary = importlib.import_module("tools.install_sandbox.reporting.agent_summary")
    root_install_surface_core = importlib.import_module("tools.install_sandbox.install_surface_core")
    owner_install_surface_statuses = importlib.import_module("tools.install_sandbox.surfaces.install_surface_statuses")
    root_platform_specs = importlib.import_module("tools.install_sandbox.platform_specs")
    owner_install_target_catalog = importlib.import_module("tools.install_sandbox.targets.install_target_catalog")

    assert (INSTALL_SANDBOX_ROOT / "agent_summary.py").exists()
    assert (INSTALL_SANDBOX_ROOT / "install_surface_core.py").exists()
    assert (INSTALL_SANDBOX_ROOT / "platform_specs.py").exists()
    assert root_agent_summary.summarize_output is owner_agent_summary.summarize_output
    assert root_install_surface_core.InstallSurfaceStatus is owner_install_surface_statuses.InstallSurfaceStatus
    assert root_platform_specs.InstallTargetCatalog is owner_install_target_catalog.InstallTargetCatalog


def test_root_topology_closeout_lists_deleted_pure_facade_direct_test_import_surface() -> None:
    expected_imports: dict[str, list[str]] = {}
    discovered_imports = _direct_test_import_surface(DELETED_PURE_ROOT_FACADE_MODULES)

    assert discovered_imports == expected_imports


def test_root_topology_closeout_lists_temporary_platform_specs_direct_test_import_surface() -> None:
    discovered_imports = _direct_test_import_surface({"tools.install_sandbox.platform_specs"})

    assert discovered_imports == PLATFORM_SPECS_DIRECT_TEST_IMPORT_SURFACE


def test_root_topology_closeout_names_validation_reporting_and_runner_public_apis() -> None:
    validation_plan = importlib.import_module("tools.install_sandbox.validation_plan")
    manifest_projection = importlib.import_module("tools.install_sandbox.reporting.manifest_projection")
    harness_run = importlib.import_module("tools.install_sandbox.reporting.harness_run")
    reports = importlib.import_module("tools.install_sandbox.reporting.reports")
    agent_summary = importlib.import_module("tools.install_sandbox.reporting.agent_summary")
    harness_orchestration = importlib.import_module("tools.install_sandbox.runtime.harness_orchestration")
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
    assert callable(harness_run.write_harness_run_outputs)
    assert callable(harness_orchestration.run_harness)
    assert not hasattr(harness_orchestration, "run_harness_and_write_outputs")
    assert callable(sandbox_runner.main)
    assert callable(sandbox_runner.parse_args)
    assert root_agent_summary.summarize_output is agent_summary.summarize_output


def test_root_topology_closeout_characterizes_supported_runner_compatibility_surface() -> None:
    sandbox_runner = importlib.import_module("tools.install_sandbox.sandbox_runner")
    run_environment = sandbox_runner.RUN_ENVIRONMENT

    supported_runtime_globals = {
        "ROOT_REGISTRY": "root_registry",
        "RUNTIME_ROOTS": "runtime_roots",
        "HOME": "home",
        "XDG_CONFIG_HOME": "xdg_config_home",
        "PROJECT": "project",
        "USER_CWD": "user_cwd",
        "REPO_MOUNT": "repo_mount",
        "SRC": "src",
        "OUTPUT": "output",
        "HARNESS_VERSION": "harness_version",
        "SCENARIO_REGISTRY": "scenario_registry",
    }
    for public_name, environment_name in supported_runtime_globals.items():
        assert getattr(sandbox_runner, public_name) is getattr(run_environment, environment_name)

    supported_wrappers_and_aliases = {
        "USER_SENTINEL": sandbox_runner.file_effect_state.USER_SENTINEL,
        "STALE_GRAPHIFY_SENTINEL": sandbox_runner.file_effect_state.STALE_GRAPHIFY_SENTINEL,
        "ScenarioRunContext": sandbox_runner.scenario_lifecycle_support.ScenarioRunContext,
        "StandardScenarioStages": sandbox_runner.scenario_lifecycle_support.StandardScenarioStages,
    }
    for public_name, owner_value in supported_wrappers_and_aliases.items():
        assert getattr(sandbox_runner, public_name) is owner_value

    assert sandbox_runner.USER_SENTINEL == sandbox_runner.file_effect_state.USER_SENTINEL
    assert sandbox_runner.STALE_GRAPHIFY_SENTINEL == sandbox_runner.file_effect_state.STALE_GRAPHIFY_SENTINEL
    assert sandbox_runner.ScenarioRunContext is sandbox_runner.scenario_lifecycle_support.ScenarioRunContext
    assert sandbox_runner.StandardScenarioStages is sandbox_runner.scenario_lifecycle_support.StandardScenarioStages
    assert callable(sandbox_runner.sandbox_env)
    assert callable(sandbox_runner.install_graphify)
    assert callable(sandbox_runner.risk_report)
    assert callable(sandbox_runner.preflight)
    assert callable(sandbox_runner.scenario_lifecycle_hooks)

    ordinary_imported_dependencies = {
        "file_effect_state": "tools.install_sandbox.effects.file_effect_state",
        "harness_run": "tools.install_sandbox.reporting.harness_run",
        "harness_orchestration": "tools.install_sandbox.runtime.harness_orchestration",
        "scenario_lifecycle_support": "tools.install_sandbox.lifecycle.scenario_lifecycle_support",
        "validation_plan": "tools.install_sandbox.validation_plan",
    }
    for dependency_name, owner_module_name in ordinary_imported_dependencies.items():
        dependency = getattr(sandbox_runner, dependency_name)
        assert isinstance(dependency, types.ModuleType)
        assert dependency.__name__ == owner_module_name
        assert dependency is importlib.import_module(owner_module_name)


def test_root_topology_closeout_keeps_runtime_root_roles_on_registry_apis() -> None:
    runtime_module = importlib.import_module("tools.install_sandbox.runtime.sandbox_run_environment")
    tree = ast.parse(Path(runtime_module.__file__).read_text(encoding="utf-8"))

    root_registry_roots_reads = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr == "roots"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "root_registry"
    ]

    assert root_registry_roots_reads == []


def test_root_topology_closeout_names_slice2_runtime_orchestration_owner() -> None:
    slice2_owner_module = "tools.install_sandbox.runtime.harness_orchestration"

    assert importlib.util.find_spec("tools.install_sandbox.runtime") is not None
    assert importlib.util.find_spec("tools.install_sandbox.runtime.sandbox_run_environment") is not None
    assert slice2_owner_module.rsplit(".", 1)[0] == "tools.install_sandbox.runtime"


def test_root_topology_closeout_harness_run_projects_validation_plan_manifest_fields() -> None:
    harness_run = importlib.import_module("tools.install_sandbox.reporting.harness_run")

    class Plan:
        standard_validation_count = 1
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
