from __future__ import annotations

import ast
import importlib
import importlib.util
import types
from pathlib import Path


INSTALL_SANDBOX_ROOT = Path(__file__).parents[2] / "tools" / "install_sandbox"
TESTS_ROOT = Path(__file__).parents[2] / "tests"
MODULE_UNDER_TEST = "tools.install_sandbox.platform_specs"
DELETED_FILE_WALK_MODULE = ".".join(("tools", "install_sandbox", "file_walk"))
DELETED_JSON_HELPER_MODULE = ".".join(("tools", "install_sandbox", "json_helpers"))

DELETED_PURE_ROOT_FACADE_MODULES = {
    "tools.install_sandbox.expected_effects",
    MODULE_UNDER_TEST,
    "tools.install_sandbox.spec_loader",
    "tools.install_sandbox.spec_normalize",
    "tools.install_sandbox.status",
}

DELETED_INSTALL_SURFACE_CORE_FACADE_MODULES = {
    "tools.install_sandbox.install_surface_core",
}

DELETED_ROOT_HELPER_MODULES = {
    DELETED_FILE_WALK_MODULE,
    DELETED_JSON_HELPER_MODULE,
}

ROOT_WORTHY_COMPATIBILITY_ENTRYPOINTS = {
    "tools.install_sandbox.agent_summary",
}

ROOT_HELPER_DELETION_CANDIDATES: set[str] = set()

ROOT_HELPER_DIRECT_SCRIPT_FALLBACKS = {
}

ROOT_WORTHY_ENTRYPOINTS_AND_DEEP_SEAMS = {
    "tools.install_sandbox.agent_summary",
    "tools.install_sandbox.harness_specs",
    "tools.install_sandbox.reference_resolution",
    "tools.install_sandbox.run",
    "tools.install_sandbox.sandbox_runner",
    "tools.install_sandbox.validation_plan",
}

SUPPORTED_SANDBOX_RUNNER_APIS = {
    "main": "tools.install_sandbox.sandbox_runner",
    "parse_args": "tools.install_sandbox.sandbox_runner",
}

SANDBOX_RUNNER_PRUNING_CANDIDATES = {
    "runtime_globals": {
        "ROOT_REGISTRY": "tools.install_sandbox.runtime.sandbox_run_environment.SandboxRunEnvironment.root_registry",
        "RUNTIME_ROOTS": "tools.install_sandbox.runtime.sandbox_run_environment.SandboxRunEnvironment.runtime_roots",
        "HOME": "tools.install_sandbox.runtime.sandbox_run_environment.SandboxRunEnvironment.home",
        "XDG_CONFIG_HOME": "tools.install_sandbox.runtime.sandbox_run_environment.SandboxRunEnvironment.xdg_config_home",
        "PROJECT": "tools.install_sandbox.runtime.sandbox_run_environment.SandboxRunEnvironment.project",
        "USER_CWD": "tools.install_sandbox.runtime.sandbox_run_environment.SandboxRunEnvironment.user_cwd",
        "REPO_MOUNT": "tools.install_sandbox.runtime.sandbox_run_environment.SandboxRunEnvironment.repo_mount",
        "SRC": "tools.install_sandbox.runtime.sandbox_run_environment.SandboxRunEnvironment.src",
        "OUTPUT": "tools.install_sandbox.runtime.sandbox_run_environment.SandboxRunEnvironment.output",
        "HARNESS_VERSION": "tools.install_sandbox.runtime.sandbox_run_environment.SandboxRunEnvironment.harness_version",
        "SCENARIO_REGISTRY": "tools.install_sandbox.runtime.sandbox_run_environment.SandboxRunEnvironment.scenario_registry",
    },
    "wrapper_functions": {
        "sandbox_env": "tools.install_sandbox.runtime.sandbox_run_environment.SandboxRunEnvironment.sandbox_env",
        "install_graphify": "tools.install_sandbox.runtime.sandbox_run_environment.SandboxRunEnvironment.install_graphify",
        "risk_report": "tools.install_sandbox.runtime.sandbox_run_environment.SandboxRunEnvironment.risk_report",
        "preflight": "tools.install_sandbox.runtime.sandbox_run_environment.SandboxRunEnvironment.preflight",
        "scenario_lifecycle_hooks": "tools.install_sandbox.runtime.sandbox_run_environment.SandboxRunEnvironment.scenario_lifecycle_hooks",
    },
    "sentinel_aliases": {
        "USER_SENTINEL": "tools.install_sandbox.effects.file_effect_state.USER_SENTINEL",
        "STALE_GRAPHIFY_SENTINEL": "tools.install_sandbox.effects.file_effect_state.STALE_GRAPHIFY_SENTINEL",
    },
    "lifecycle_aliases": {
        "ScenarioRunContext": "tools.install_sandbox.lifecycle.scenario_lifecycle_support.ScenarioRunContext",
        "StandardScenarioStages": "tools.install_sandbox.lifecycle.scenario_lifecycle_support.StandardScenarioStages",
    },
    "status_aliases": {
        "RISK_GRAPHIFY_FAILED": "tools.install_sandbox.reporting.status.RISK_GRAPHIFY_FAILED",
        "RISK_GRAPHIFY_VERIFIED": "tools.install_sandbox.reporting.status.RISK_GRAPHIFY_VERIFIED",
        "combined_status": "tools.install_sandbox.reporting.status.combined_status",
        "known_status_values": "tools.install_sandbox.reporting.status.known_status_values",
    },
}


def _direct_test_import_surface(module_names: set[str]) -> dict[str, list[str]]:
    discovered_imports: dict[str, list[str]] = {}

    for path in sorted(TESTS_ROOT.rglob("*.py")):
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


def _module_name_for(path: Path) -> str:
    relative = path.relative_to(Path(__file__).parents[2]).with_suffix("")
    return ".".join(relative.parts)


def _resolve_import_from_module(importing_module: str, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module

    package_parts = importing_module.split(".")[:-1]
    parent_parts = package_parts[: len(package_parts) - node.level + 1]
    if node.module:
        parent_parts.extend(node.module.split("."))
    return ".".join(parent_parts)


def _direct_repo_import_surface(module_names: set[str], fallback_names: dict[str, str]) -> dict[str, list[str]]:
    discovered_imports: dict[str, list[str]] = {}

    for root in (INSTALL_SANDBOX_ROOT, TESTS_ROOT / "install_sandbox"):
        for path in sorted(root.rglob("*.py")):
            relative = path.relative_to(Path(__file__).parents[2]).as_posix()
            importing_module = _module_name_for(path)
            tree = ast.parse(path.read_text(encoding="utf-8"))
            direct_imports: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    resolved_module = _resolve_import_from_module(importing_module, node)
                    if resolved_module == "tools.install_sandbox":
                        for alias in node.names:
                            module_name = f"tools.install_sandbox.{alias.name}"
                            if module_name in module_names:
                                direct_imports.add(module_name)
                    elif resolved_module in module_names:
                        direct_imports.add(resolved_module)
                    elif resolved_module in fallback_names:
                        direct_imports.add(fallback_names[resolved_module])
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in module_names:
                            direct_imports.add(alias.name)
                        elif alias.name in fallback_names:
                            direct_imports.add(fallback_names[alias.name])

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
        assert module_name not in DELETED_INSTALL_SURFACE_CORE_FACADE_MODULES
        assert module_name not in ROOT_WORTHY_COMPATIBILITY_ENTRYPOINTS


def test_root_topology_closeout_characterizes_compatibility_facade_buckets() -> None:
    assert DELETED_PURE_ROOT_FACADE_MODULES == {
        "tools.install_sandbox.expected_effects",
        MODULE_UNDER_TEST,
        "tools.install_sandbox.spec_loader",
        "tools.install_sandbox.spec_normalize",
        "tools.install_sandbox.status",
    }
    assert DELETED_INSTALL_SURFACE_CORE_FACADE_MODULES == {
        "tools.install_sandbox.install_surface_core",
    }
    assert ROOT_WORTHY_COMPATIBILITY_ENTRYPOINTS == {
        "tools.install_sandbox.agent_summary",
    }
    assert DELETED_PURE_ROOT_FACADE_MODULES.isdisjoint(DELETED_INSTALL_SURFACE_CORE_FACADE_MODULES)
    assert DELETED_PURE_ROOT_FACADE_MODULES.isdisjoint(ROOT_WORTHY_COMPATIBILITY_ENTRYPOINTS)
    assert DELETED_INSTALL_SURFACE_CORE_FACADE_MODULES.isdisjoint(ROOT_WORTHY_COMPATIBILITY_ENTRYPOINTS)


def test_root_topology_closeout_characterizes_root_helper_relocation_buckets() -> None:
    assert DELETED_ROOT_HELPER_MODULES == {
        DELETED_FILE_WALK_MODULE,
        DELETED_JSON_HELPER_MODULE,
    }
    assert ROOT_HELPER_DELETION_CANDIDATES == set()
    assert ROOT_HELPER_DIRECT_SCRIPT_FALLBACKS == {}
    assert ROOT_WORTHY_ENTRYPOINTS_AND_DEEP_SEAMS == {
        "tools.install_sandbox.agent_summary",
        "tools.install_sandbox.harness_specs",
        "tools.install_sandbox.reference_resolution",
        "tools.install_sandbox.run",
        "tools.install_sandbox.sandbox_runner",
        "tools.install_sandbox.validation_plan",
    }
    assert ROOT_HELPER_DELETION_CANDIDATES.isdisjoint(ROOT_WORTHY_ENTRYPOINTS_AND_DEEP_SEAMS)
    assert ROOT_HELPER_DELETION_CANDIDATES.isdisjoint(DELETED_PURE_ROOT_FACADE_MODULES)
    assert ROOT_HELPER_DELETION_CANDIDATES.isdisjoint(DELETED_INSTALL_SURFACE_CORE_FACADE_MODULES)
    assert DELETED_ROOT_HELPER_MODULES.isdisjoint(ROOT_HELPER_DELETION_CANDIDATES)
    assert DELETED_ROOT_HELPER_MODULES.isdisjoint(ROOT_WORTHY_ENTRYPOINTS_AND_DEEP_SEAMS)


def test_root_topology_closeout_keeps_deleted_root_helpers_absent() -> None:
    for module_name in DELETED_ROOT_HELPER_MODULES:
        root_file_name = module_name.rsplit(".", maxsplit=1)[-1]

        assert not (INSTALL_SANDBOX_ROOT / f"{root_file_name}.py").exists()
        assert importlib.util.find_spec(module_name) is None


def test_root_topology_closeout_keeps_root_worthy_facades_importable() -> None:
    root_agent_summary = importlib.import_module("tools.install_sandbox.agent_summary")
    owner_agent_summary = importlib.import_module("tools.install_sandbox.reporting.agent_summary")

    assert (INSTALL_SANDBOX_ROOT / "agent_summary.py").exists()
    assert root_agent_summary.summarize_output is owner_agent_summary.summarize_output


def test_root_topology_closeout_keeps_deleted_install_surface_core_facade_absent() -> None:
    for module_name in DELETED_INSTALL_SURFACE_CORE_FACADE_MODULES:
        root_file_name = module_name.rsplit(".", maxsplit=1)[-1]

        assert not (INSTALL_SANDBOX_ROOT / f"{root_file_name}.py").exists()
        assert importlib.util.find_spec(module_name) is None


def test_root_topology_closeout_lists_deleted_pure_facade_direct_test_import_surface() -> None:
    expected_imports: dict[str, list[str]] = {}
    discovered_imports = _direct_test_import_surface(DELETED_PURE_ROOT_FACADE_MODULES)

    assert discovered_imports == expected_imports


def test_root_topology_closeout_lists_deleted_platform_specs_direct_test_import_surface() -> None:
    discovered_imports = _direct_test_import_surface({MODULE_UNDER_TEST})

    assert discovered_imports == {}


def test_root_topology_closeout_lists_deleted_install_surface_core_direct_test_import_surface() -> None:
    discovered_imports = _direct_test_import_surface(DELETED_INSTALL_SURFACE_CORE_FACADE_MODULES)

    assert discovered_imports == {}


def test_root_topology_closeout_lists_root_helper_deletion_candidate_import_surface() -> None:
    discovered_imports = _direct_repo_import_surface(
        ROOT_HELPER_DELETION_CANDIDATES,
        ROOT_HELPER_DIRECT_SCRIPT_FALLBACKS,
    )

    assert discovered_imports == {}


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
    for public_name, owner_module_name in SUPPORTED_SANDBOX_RUNNER_APIS.items():
        assert getattr(sandbox_runner, public_name).__module__ == owner_module_name
        assert callable(getattr(sandbox_runner, public_name))
    assert root_agent_summary.summarize_output is agent_summary.summarize_output


def test_root_topology_closeout_characterizes_runner_compatibility_tail_as_pruning_candidates() -> None:
    sandbox_runner = importlib.import_module("tools.install_sandbox.sandbox_runner")
    run_environment = sandbox_runner.RUN_ENVIRONMENT
    file_effect_state = importlib.import_module("tools.install_sandbox.effects.file_effect_state")
    scenario_lifecycle_support = importlib.import_module("tools.install_sandbox.lifecycle.scenario_lifecycle_support")
    reporting_status = importlib.import_module("tools.install_sandbox.reporting.status")

    runtime_global_names = {
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
    assert set(SANDBOX_RUNNER_PRUNING_CANDIDATES["runtime_globals"]) == set(runtime_global_names)
    for public_name, environment_name in runtime_global_names.items():
        assert getattr(sandbox_runner, public_name) is getattr(run_environment, environment_name)

    sentinel_aliases = {
        "USER_SENTINEL": file_effect_state.USER_SENTINEL,
        "STALE_GRAPHIFY_SENTINEL": file_effect_state.STALE_GRAPHIFY_SENTINEL,
    }
    assert set(SANDBOX_RUNNER_PRUNING_CANDIDATES["sentinel_aliases"]) == set(sentinel_aliases)
    for public_name, owner_value in sentinel_aliases.items():
        assert getattr(sandbox_runner, public_name) is owner_value

    lifecycle_aliases = {
        "ScenarioRunContext": scenario_lifecycle_support.ScenarioRunContext,
        "StandardScenarioStages": scenario_lifecycle_support.StandardScenarioStages,
    }
    assert set(SANDBOX_RUNNER_PRUNING_CANDIDATES["lifecycle_aliases"]) == set(lifecycle_aliases)
    for public_name, owner_value in lifecycle_aliases.items():
        assert getattr(sandbox_runner, public_name) is owner_value

    assert set(SANDBOX_RUNNER_PRUNING_CANDIDATES["wrapper_functions"]) == {
        "sandbox_env",
        "install_graphify",
        "risk_report",
        "preflight",
        "scenario_lifecycle_hooks",
    }
    for public_name in SANDBOX_RUNNER_PRUNING_CANDIDATES["wrapper_functions"]:
        assert not hasattr(sandbox_runner, public_name)

    status_aliases = {
        "RISK_GRAPHIFY_FAILED": reporting_status.RISK_GRAPHIFY_FAILED,
        "RISK_GRAPHIFY_VERIFIED": reporting_status.RISK_GRAPHIFY_VERIFIED,
        "combined_status": reporting_status.combined_status,
        "known_status_values": reporting_status.known_status_values,
    }
    assert set(SANDBOX_RUNNER_PRUNING_CANDIDATES["status_aliases"]) == set(status_aliases)
    for public_name, owner_value in status_aliases.items():
        assert getattr(sandbox_runner, public_name) is owner_value

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
