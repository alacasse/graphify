from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
import types
from pathlib import Path

import pytest


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

ROOT_WORTHY_COMPATIBILITY_ENTRYPOINTS: set[str] = set()

ROOT_HELPER_DELETION_CANDIDATES: set[str] = set()

DELETED_AGENT_SUMMARY_SHIM_MODULES = {
    "tools.install_sandbox.agent_summary",
}

ROOT_HELPER_DIRECT_SCRIPT_FALLBACKS = {
}

ROOT_WORTHY_ENTRYPOINTS_AND_DEEP_SEAMS = {
    "tools.install_sandbox.harness_specs",
    "tools.install_sandbox.run",
    "tools.install_sandbox.sandbox_runner",
    "tools.install_sandbox.validation_plan",
}

ROOT_MODULE_RELOCATION_CANDIDATES = {
    "tools.install_sandbox.reference_resolution": "tools.install_sandbox.targets.reference_resolution",
}

SUPPORTED_EXTERNAL_REFERENCE_RESOLUTION_IMPORT_CONTRACTS: dict[str, tuple[str, ...]] = {}

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

DELETED_INSTALL_TARGET_MODEL_NAMES = {
    "Platform" "Spec",
}

ARTIFACT_VOCABULARY_DOCS = (
    INSTALL_SANDBOX_ROOT / "README.md",
    INSTALL_SANDBOX_ROOT / "specs" / "README.md",
)

PUBLIC_ARTIFACT_OUTPUT_PATHS = (
    INSTALL_SANDBOX_ROOT / "reporting",
    TESTS_ROOT / "install_sandbox" / "test_agent_summary.py",
    TESTS_ROOT / "install_sandbox" / "test_reports.py",
    TESTS_ROOT / "install_sandbox" / "test_sandbox_runner.py",
    TESTS_ROOT / "install_sandbox" / "test_validation_plan_compatibility.py",
)

ARTIFACT_OUTPUT_LEGACY_VOCABULARY = {
    "platform_coverage",
    "platform_coverage_summary",
    "Platform Coverage",
}

TARGET_NAMED_ARTIFACT_VOCABULARY = {
    "target_coverage",
    "target_coverage_summary",
    "Target Coverage",
}

REPORTING_PROJECTION_EXEMPLAR_ROLE_BUCKETS = {
    "current target-named generated output": {
        "manifest.target_coverage",
        "manifest.target_coverage_summary",
        "rendered Target Coverage",
        "agent_summary.failure.target",
    },
    "input-only legacy platform readers": {
        "legacy manifest.platform",
        "legacy manifest.platform_coverage",
        "legacy result.platform",
    },
    "serialized artifact input/output vocabulary": {
        "scenario.platform",
        "scenario.platforms",
        "result.platform",
    },
    "public command/YAML edge vocabulary": {
        "product --platform",
        "registry platforms",
    },
    "synthetic label vocabulary": {
        "platform_label",
    },
}

REPORTING_PROJECTION_INTERNAL_PLATFORM_VOCABULARY = {
    "platform_coverage",
    "platform_coverage_summary",
    "selected_platforms",
    "Scenario.platform",
    "PlatformSpec",
}

ALLOWED_ARTIFACT_LEGACY_VOCABULARY_LINES = {
    'coverage_source = manifest.get("target_coverage") if "target_coverage" in manifest else manifest.get("platform_coverage")',
    'def test_report_reads_legacy_platform_coverage_as_transitional_input_only() -> None:',
    '"platform_coverage": [',
    'assert "## Platform Coverage" not in markdown',
    'def test_report_prefers_explicit_empty_target_coverage_over_stale_legacy_rows() -> None:',
    '"platform_coverage" not in manifest',
    '"platform_coverage_summary" not in manifest',
    '"platform_coverage" not in projected',
    '"platform_coverage_summary" not in projected',
    '"platform_coverage",',
    '"platform_coverage_summary",',
    'platform_coverage = ({"platform": "legacy-alias", "status": "must-not-project"},)',
    'platform_coverage = ({"platform": "internal-alias", "status": "must-not-project"},)',
    'platform_coverage_summary = {"requested_scope": "legacy"}',
    'kwargs[alias_name] = () if alias_name != "platform_coverage" else ()',
}

DEFERRED_PRODUCT_PLATFORM_VOCABULARY = {
    "--platform": "LR-B9 product CLI flag",
    "platforms": "YAML",
}

TARGET_OWNER_API_PARAMETER_GUARDS = {
    "tools.install_sandbox.targets.install_target_selection": {
        "coverage_records": {"target_names"},
        "direct_install_command": {"target_name"},
        "direct_uninstall_command": {"target_name"},
        "generic_install_command": {"target_name"},
        "install_variants_for_scope": {"target_name"},
        "make_scenario": {"target_name"},
        "project_skill": {"target_name"},
        "scenario_id": {"target_name"},
        "selected_targets": {"target_name"},
        "target_scenarios": {"target_name"},
        "target_spec": {"target_name"},
        "unsupported_scope_reason": {"target_name"},
        "user_skill": {"target_name"},
    },
    "tools.install_sandbox.targets.install_target_catalog.ScenarioRegistry": {
        "coverage_records": {"target_names"},
        "direct_install_command": {"target_name"},
        "direct_uninstall_command": {"target_name"},
        "generic_install_command": {"target_name"},
        "install_variants_for_scope": {"target_name"},
        "make_scenario": {"target_name"},
        "project_skill": {"target_name"},
        "scenario_id": {"target_name"},
        "selected_targets": {"target_name"},
        "target_scenarios": {"target_name"},
        "target_spec": {"target_name"},
        "unsupported_scope_reason": {"target_name"},
        "user_skill": {"target_name"},
    },
    "tools.install_sandbox.targets.install_target_defaults": {
        "direct_install_command": {"target_name"},
        "direct_uninstall_command": {"target_name"},
        "generic_install_command": {"target_name"},
        "install_target_scenarios": {"target_name"},
        "install_target_spec": {"target_name"},
        "make_scenario": {"target_name"},
        "project_skill": {"target_name"},
        "risk_notes": {"target_name"},
        "unsupported_scope_reason": {"target_name"},
        "user_skill": {"target_name"},
    },
}

DEFERRED_TARGET_OWNER_PLATFORM_PARAMETERS = {
    "tools.install_sandbox.targets.install_target_defaults.universal_uninstall_scenarios": {"platforms"},
}

HARNESS_POLICY_TARGET_ELIGIBILITY_PARAMETER_GUARDS = {
    "tools.install_sandbox.targets.install_target_harness_policy": {
        "universal_uninstall_scenarios": {"target_names"},
        "universal_uninstall_groups": {"target_names"},
        "selected_universal_uninstall_scenarios": {"target_names"},
        "_select_universal_uninstall_scenarios": {"target_names"},
        "risk_notes": {"target_name"},
    },
}

HARNESS_POLICY_FRONTIER_EDGE_VOCABULARY = {
    "UniversalUninstallScenarioSpec.platform_label": "synthetic output label",
    "DisposableArtifactScenarioSpec.platform_label": "synthetic output label",
    "registry.universal_uninstall_specs[].eligible_platform_scope": "YAML input edge",
    "Scenario.target_name": "standard scenario target identity",
    "--platform": "public product command edge",
    "platforms": "public YAML edge",
}

SCENARIO_PLATFORM_CONTRACT_DECISION = "migratable_internal_identity"

SCENARIO_PLATFORM_INTERNAL_IDENTITY_REFERENCES: dict[str, int] = {}

SCENARIO_PLATFORM_ALLOWED_VOCABULARY_BUCKETS = {
    "product/public CLI": {"--platform", "args.platform", "build_container_command(platform=...)"},
    "YAML input edge": {"platforms", "eligible_platform_scope"},
    "serialized artifact output keys": {"scenario.platform", "scenario.platforms", "result.platform"},
    "legacy input-only readers": {"manifest.platform", "manifest.platform_coverage"},
    "synthetic label vocabulary": {"platform_label"},
}

SCENARIO_PLATFORM_SERIALIZED_ARTIFACT_KEYS = {
    "tools/install_sandbox/lifecycle/scenario_lifecycle_support.py": 3,
}

LEGACY_PLATFORM_INPUT_ONLY_READERS = {
    "tools/install_sandbox/reporting/artifacts.py": 1,
    "tools/install_sandbox/reporting/manifest_projection.py": 1,
    "tools/install_sandbox/reporting/reports.py": 2,
}

RUNNER_INTAKE_FRONTIER_MODULES = (
    "tools.install_sandbox.run",
    "tools.install_sandbox.sandbox_runner",
    "tools.install_sandbox.runtime.harness_orchestration",
)


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


def _install_target_model_name_surface(model_names: set[str]) -> dict[str, list[str]]:
    discovered_names: dict[str, list[str]] = {}

    for root in (INSTALL_SANDBOX_ROOT, TESTS_ROOT / "install_sandbox"):
        for path in sorted(root.rglob("*.py")):
            relative = path.relative_to(Path(__file__).parents[2]).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    names.update(alias.name for alias in node.names if alias.name in model_names)
                elif isinstance(node, ast.Import):
                    names.update(alias.name for alias in node.names if alias.name in model_names)
                elif isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                    if node.name in model_names:
                        names.add(node.name)
                elif isinstance(node, ast.Name) and node.id in model_names:
                    names.add(node.id)
                elif isinstance(node, ast.Attribute) and node.attr in model_names:
                    names.add(node.attr)

            if names:
                discovered_names[relative] = sorted(names)

    return discovered_names


def _text_files(paths: tuple[Path, ...]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(child for child in path.rglob("*") if child.suffix in {".py", ".md"}))
        else:
            files.append(path)
    return files


def _documented_reference_resolution_contracts() -> dict[str, list[str]]:
    repo_root = Path(__file__).parents[2]
    documented_imports: dict[str, list[str]] = {}
    documentation_paths = (
        repo_root / "README.md",
        repo_root / "AGENTS.md",
        repo_root / "docs",
        INSTALL_SANDBOX_ROOT / "README.md",
        INSTALL_SANDBOX_ROOT / "specs" / "README.md",
    )
    patterns = (
        "tools.install_sandbox.reference_resolution",
        "tools/install_sandbox/reference_resolution.py",
        "from tools.install_sandbox import reference_resolution",
        "from tools.install_sandbox.reference_resolution import",
        "import tools.install_sandbox.reference_resolution",
    )

    for path in _text_files(documentation_paths):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        matches = sorted(pattern for pattern in patterns if pattern in text)
        if matches:
            documented_imports[path.relative_to(repo_root).as_posix()] = matches
    return documented_imports


def _source_occurrence_counts(predicate) -> dict[str, int]:
    occurrences: dict[str, int] = {}
    for path in sorted(INSTALL_SANDBOX_ROOT.rglob("*.py")):
        relative = path.relative_to(Path(__file__).parents[2]).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        count = sum(1 for node in ast.walk(tree) if predicate(node))
        if count:
            occurrences[relative] = count
    return occurrences


def _function_node(module: types.ModuleType, function_name: str) -> ast.FunctionDef:
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )


def _resolve_dotted_owner(dotted_name: str) -> object:
    module_name, separator, _ = dotted_name.partition(".ScenarioRegistry")
    owner = importlib.import_module(module_name)
    if separator:
        owner = getattr(owner, "ScenarioRegistry")
    return owner


def test_root_topology_closeout_guards_target_owner_parameter_vocabulary() -> None:
    legacy_parameter_names = {"platform_name", "platforms"}
    for owner_name, api_parameters in TARGET_OWNER_API_PARAMETER_GUARDS.items():
        owner = _resolve_dotted_owner(owner_name)
        for api_name, target_parameters in api_parameters.items():
            signature = inspect.signature(getattr(owner, api_name))

            assert set(signature.parameters) >= target_parameters
            assert not (set(signature.parameters) & legacy_parameter_names)

    for owner_api_name, deferred_parameters in DEFERRED_TARGET_OWNER_PLATFORM_PARAMETERS.items():
        module_name, api_name = owner_api_name.rsplit(".", maxsplit=1)
        owner = importlib.import_module(module_name)
        signature = inspect.signature(getattr(owner, api_name))

        assert set(signature.parameters) >= deferred_parameters


def test_root_topology_closeout_guards_harness_policy_frontier_vocabulary() -> None:
    models = importlib.import_module("tools.install_sandbox.targets.install_target_models")
    harness_policy = importlib.import_module("tools.install_sandbox.targets.install_target_harness_policy")
    spec_inputs = importlib.import_module("tools.install_sandbox.registry.spec_harness_policy_inputs")

    assert HARNESS_POLICY_FRONTIER_EDGE_VOCABULARY == {
        "UniversalUninstallScenarioSpec.platform_label": "synthetic output label",
        "DisposableArtifactScenarioSpec.platform_label": "synthetic output label",
        "registry.universal_uninstall_specs[].eligible_platform_scope": "YAML input edge",
        "Scenario.target_name": "standard scenario target identity",
        "--platform": "public product command edge",
        "platforms": "public YAML edge",
    }

    legacy_eligibility_names = {"platform_name", "platforms", "eligible_platform_scope"}
    for owner_name, api_parameters in HARNESS_POLICY_TARGET_ELIGIBILITY_PARAMETER_GUARDS.items():
        owner = importlib.import_module(owner_name)
        for api_name, target_parameters in api_parameters.items():
            signature = inspect.signature(getattr(owner, api_name))

            assert set(signature.parameters) >= target_parameters
            assert not (set(signature.parameters) & legacy_eligibility_names)

    universal_fields = models.UniversalUninstallScenarioSpec.__dataclass_fields__
    disposable_fields = models.DisposableArtifactScenarioSpec.__dataclass_fields__
    assert "platform_label" in universal_fields
    assert "platform_label" in disposable_fields
    assert "eligible_target_scope" in universal_fields
    assert "eligible_platform_scope" not in universal_fields
    assert "target_name" in models.Scenario.__dataclass_fields__
    assert "platform" not in models.Scenario.__dataclass_fields__
    assert not isinstance(getattr(models.Scenario, "platform", None), property)

    selection_source = inspect.getsource(harness_policy._select_universal_uninstall_scenarios)
    assert "eligible_target_scope" in selection_source
    assert "eligible_platform_scope" not in selection_source
    assert "platform_label" not in selection_source

    loader_source = inspect.getsource(spec_inputs._universal_uninstall)
    assert 'data.get("eligible_platform_scope")' in loader_source
    assert "eligible_target_scope=" in loader_source


def test_root_topology_closeout_classifies_scenario_platform_as_internal_identity() -> None:
    models = importlib.import_module("tools.install_sandbox.targets.install_target_models")

    assert SCENARIO_PLATFORM_CONTRACT_DECISION == "migratable_internal_identity"
    assert "target_name" in models.Scenario.__dataclass_fields__
    assert "platform" not in models.Scenario.__dataclass_fields__
    assert not hasattr(models.Scenario, "platform")
    assert not isinstance(getattr(models.Scenario, "platform", None), property)
    assert SCENARIO_PLATFORM_INTERNAL_IDENTITY_REFERENCES == {}

    attribute_references = _source_occurrence_counts(
        lambda node: isinstance(node, ast.Attribute)
        and node.attr == "platform"
        and not (isinstance(node.value, ast.Name) and node.value.id == "args")
    )

    assert attribute_references == SCENARIO_PLATFORM_INTERNAL_IDENTITY_REFERENCES


def test_root_topology_closeout_documents_exact_platform_vocabulary_buckets() -> None:
    assert SCENARIO_PLATFORM_ALLOWED_VOCABULARY_BUCKETS == {
        "product/public CLI": {"--platform", "args.platform", "build_container_command(platform=...)"},
        "YAML input edge": {"platforms", "eligible_platform_scope"},
        "serialized artifact output keys": {"scenario.platform", "scenario.platforms", "result.platform"},
        "legacy input-only readers": {"manifest.platform", "manifest.platform_coverage"},
        "synthetic label vocabulary": {"platform_label"},
    }

    bucketed_terms = set().union(*SCENARIO_PLATFORM_ALLOWED_VOCABULARY_BUCKETS.values())
    assert "Scenario.platform" not in bucketed_terms
    assert "scenario.platform" in SCENARIO_PLATFORM_ALLOWED_VOCABULARY_BUCKETS["serialized artifact output keys"]
    assert "platform_label" in SCENARIO_PLATFORM_ALLOWED_VOCABULARY_BUCKETS["synthetic label vocabulary"]


def test_root_topology_closeout_names_reporting_projection_as_exemplar_frontier() -> None:
    assert REPORTING_PROJECTION_EXEMPLAR_ROLE_BUCKETS == {
        "current target-named generated output": {
            "manifest.target_coverage",
            "manifest.target_coverage_summary",
            "rendered Target Coverage",
            "agent_summary.failure.target",
        },
        "input-only legacy platform readers": {
            "legacy manifest.platform",
            "legacy manifest.platform_coverage",
            "legacy result.platform",
        },
        "serialized artifact input/output vocabulary": {
            "scenario.platform",
            "scenario.platforms",
            "result.platform",
        },
        "public command/YAML edge vocabulary": {
            "product --platform",
            "registry platforms",
        },
        "synthetic label vocabulary": {
            "platform_label",
        },
    }

    current_output = REPORTING_PROJECTION_EXEMPLAR_ROLE_BUCKETS["current target-named generated output"]
    legacy_readers = REPORTING_PROJECTION_EXEMPLAR_ROLE_BUCKETS["input-only legacy platform readers"]
    serialized_artifacts = REPORTING_PROJECTION_EXEMPLAR_ROLE_BUCKETS["serialized artifact input/output vocabulary"]
    edge_vocabulary = REPORTING_PROJECTION_EXEMPLAR_ROLE_BUCKETS["public command/YAML edge vocabulary"]
    synthetic_labels = REPORTING_PROJECTION_EXEMPLAR_ROLE_BUCKETS["synthetic label vocabulary"]

    assert current_output.isdisjoint(legacy_readers)
    assert current_output.isdisjoint(serialized_artifacts)
    assert current_output.isdisjoint(edge_vocabulary)
    assert current_output.isdisjoint(synthetic_labels)
    assert all("target" in field or "Target" in field for field in current_output)
    assert all("legacy " in field for field in legacy_readers)
    assert {"scenario.platform", "scenario.platforms", "result.platform"} == serialized_artifacts
    assert "platform_coverage" not in " ".join(current_output)
    assert "Scenario.platform" not in set().union(*REPORTING_PROJECTION_EXEMPLAR_ROLE_BUCKETS.values())


def test_root_topology_closeout_does_not_preserve_internal_platform_reporting_vocabulary() -> None:
    current_output = REPORTING_PROJECTION_EXEMPLAR_ROLE_BUCKETS["current target-named generated output"]
    legacy_readers = REPORTING_PROJECTION_EXEMPLAR_ROLE_BUCKETS["input-only legacy platform readers"]
    public_edge_vocabulary = REPORTING_PROJECTION_EXEMPLAR_ROLE_BUCKETS["public command/YAML edge vocabulary"]

    assert REPORTING_PROJECTION_INTERNAL_PLATFORM_VOCABULARY == {
        "platform_coverage",
        "platform_coverage_summary",
        "selected_platforms",
        "Scenario.platform",
        "PlatformSpec",
    }
    assert REPORTING_PROJECTION_INTERNAL_PLATFORM_VOCABULARY.isdisjoint(current_output)
    assert REPORTING_PROJECTION_INTERNAL_PLATFORM_VOCABULARY.isdisjoint(public_edge_vocabulary)
    assert "legacy manifest.platform_coverage" in legacy_readers
    assert "platform_coverage" not in legacy_readers
    assert "platform_coverage_summary" not in legacy_readers
    assert "selected_platforms" not in legacy_readers


def test_root_topology_closeout_classifies_remaining_platform_vocabulary_for_ptt_b5() -> None:
    allowed_closeout_buckets = {
        "public product CLI": {"product --platform"},
        "YAML input": {"registry platforms"},
        "serialized artifact input/output where current": {
            "scenario.platform",
            "scenario.platforms",
            "result.platform",
        },
        "legacy input-only reader": {
            "legacy manifest.platform",
            "legacy manifest.platform_coverage",
            "legacy result.platform",
        },
        "synthetic label vocabulary": {"platform_label"},
    }

    actual_closeout_buckets = {
        "public product CLI": REPORTING_PROJECTION_EXEMPLAR_ROLE_BUCKETS["public command/YAML edge vocabulary"]
        & {"product --platform"},
        "YAML input": REPORTING_PROJECTION_EXEMPLAR_ROLE_BUCKETS["public command/YAML edge vocabulary"]
        & {"registry platforms"},
        "serialized artifact input/output where current": REPORTING_PROJECTION_EXEMPLAR_ROLE_BUCKETS[
            "serialized artifact input/output vocabulary"
        ],
        "legacy input-only reader": REPORTING_PROJECTION_EXEMPLAR_ROLE_BUCKETS[
            "input-only legacy platform readers"
        ],
        "synthetic label vocabulary": REPORTING_PROJECTION_EXEMPLAR_ROLE_BUCKETS["synthetic label vocabulary"],
    }

    assert actual_closeout_buckets == allowed_closeout_buckets

    allowed_terms = set().union(*actual_closeout_buckets.values())
    internal_terms = REPORTING_PROJECTION_INTERNAL_PLATFORM_VOCABULARY - {
        "platform_coverage",
    }
    assert internal_terms.isdisjoint(allowed_terms)
    assert "legacy manifest.platform_coverage" in actual_closeout_buckets["legacy input-only reader"]
    assert "platform_coverage" not in allowed_terms


def test_root_topology_closeout_keeps_scenario_result_platform_keys_at_artifact_edges() -> None:
    assert SCENARIO_PLATFORM_SERIALIZED_ARTIFACT_KEYS == {
        "tools/install_sandbox/lifecycle/scenario_lifecycle_support.py": 3,
    }
    assert LEGACY_PLATFORM_INPUT_ONLY_READERS == {
        "tools/install_sandbox/reporting/artifacts.py": 1,
        "tools/install_sandbox/reporting/manifest_projection.py": 1,
        "tools/install_sandbox/reporting/reports.py": 2,
    }

    literal_platform_keys = _source_occurrence_counts(
        lambda node: isinstance(node, ast.Constant) and node.value == "platform"
    )

    assert literal_platform_keys == {
        **SCENARIO_PLATFORM_SERIALIZED_ARTIFACT_KEYS,
        **LEGACY_PLATFORM_INPUT_ONLY_READERS,
    }


def test_root_topology_closeout_documents_target_named_artifact_vocabulary() -> None:
    for path in ARTIFACT_VOCABULARY_DOCS:
        text = path.read_text(encoding="utf-8")
        assert "target_coverage" in text
        assert "target_coverage_summary" in text
        assert "Target Coverage" in text or path.name == "README.md" and path.parent.name == "specs"
        assert "Platform Coverage" not in text


def test_root_topology_closeout_keeps_legacy_platform_coverage_out_of_current_artifact_outputs() -> None:
    offenders: list[str] = []

    for path in _text_files(PUBLIC_ARTIFACT_OUTPUT_PATHS):
        relative = path.relative_to(Path(__file__).parents[2]).as_posix()
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not any(term in line for term in ARTIFACT_OUTPUT_LEGACY_VOCABULARY):
                continue
            stripped = line.strip()
            if stripped in ALLOWED_ARTIFACT_LEGACY_VOCABULARY_LINES:
                continue
            if "transitional input" in stripped or "must-not-project" in stripped:
                continue
            if "not in" in stripped:
                continue
            offenders.append(f"{relative}:{lineno}: {stripped}")

    assert offenders == []


def test_root_topology_closeout_classifies_deferred_platform_vocabulary_as_product_contract() -> None:
    docs_text = "\n".join(path.read_text(encoding="utf-8") for path in ARTIFACT_VOCABULARY_DOCS)

    for vocabulary, classification in DEFERRED_PRODUCT_PLATFORM_VOCABULARY.items():
        assert vocabulary in docs_text
        assert classification in docs_text


def test_root_topology_closeout_guards_runner_intake_frontier_target_naming() -> None:
    run_module = importlib.import_module("tools.install_sandbox.run")
    sandbox_runner = importlib.import_module("tools.install_sandbox.sandbox_runner")
    harness_orchestration = importlib.import_module("tools.install_sandbox.runtime.harness_orchestration")

    assert RUNNER_INTAKE_FRONTIER_MODULES == (
        "tools.install_sandbox.run",
        "tools.install_sandbox.sandbox_runner",
        "tools.install_sandbox.runtime.harness_orchestration",
    )

    run_main = _function_node(run_module, "main")
    build_container_call = next(
        node
        for node in ast.walk(run_main)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "build_container_command"
    )
    host_public_platform_kwarg = next(
        keyword for keyword in build_container_call.keywords if keyword.arg == "platform"
    )
    assert isinstance(host_public_platform_kwarg.value, ast.Name)
    assert host_public_platform_kwarg.value.id == "selected_install_target_input"

    runner_main = _function_node(sandbox_runner, "main")
    run_harness_call = next(
        node
        for node in ast.walk(runner_main)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run_harness"
    )
    selected_target_kwarg = next(
        keyword for keyword in run_harness_call.keywords if keyword.arg == "selected_target_name"
    )
    assert isinstance(selected_target_kwarg.value, ast.Name)
    assert selected_target_kwarg.value.id == "selected_target_name"

    orchestration_run_harness = _function_node(harness_orchestration, "run_harness")
    build_plan_call = next(
        node
        for node in ast.walk(orchestration_run_harness)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "build_validation_plan"
    )
    target_name_kwarg = next(
        keyword for keyword in build_plan_call.keywords if keyword.arg == "target_name"
    )
    assert isinstance(target_name_kwarg.value, ast.Name)
    assert target_name_kwarg.value.id == "selected_target_name"


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


def test_root_topology_closeout_keeps_deleted_install_target_model_names_absent() -> None:
    install_target_models = importlib.import_module("tools.install_sandbox.targets.install_target_models")

    for model_name in DELETED_INSTALL_TARGET_MODEL_NAMES:
        assert not hasattr(install_target_models, model_name)

    assert _install_target_model_name_surface(DELETED_INSTALL_TARGET_MODEL_NAMES) == {}


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
    assert ROOT_WORTHY_COMPATIBILITY_ENTRYPOINTS == set()
    assert DELETED_AGENT_SUMMARY_SHIM_MODULES == {
        "tools.install_sandbox.agent_summary",
    }
    assert DELETED_PURE_ROOT_FACADE_MODULES.isdisjoint(DELETED_INSTALL_SURFACE_CORE_FACADE_MODULES)
    assert DELETED_PURE_ROOT_FACADE_MODULES.isdisjoint(ROOT_WORTHY_COMPATIBILITY_ENTRYPOINTS)
    assert DELETED_INSTALL_SURFACE_CORE_FACADE_MODULES.isdisjoint(ROOT_WORTHY_COMPATIBILITY_ENTRYPOINTS)
    assert DELETED_AGENT_SUMMARY_SHIM_MODULES.isdisjoint(ROOT_WORTHY_COMPATIBILITY_ENTRYPOINTS)


def test_root_topology_closeout_characterizes_root_helper_relocation_buckets() -> None:
    assert DELETED_ROOT_HELPER_MODULES == {
        DELETED_FILE_WALK_MODULE,
        DELETED_JSON_HELPER_MODULE,
    }
    assert ROOT_HELPER_DELETION_CANDIDATES == set()
    assert ROOT_HELPER_DIRECT_SCRIPT_FALLBACKS == {}
    assert ROOT_WORTHY_ENTRYPOINTS_AND_DEEP_SEAMS == {
        "tools.install_sandbox.harness_specs",
        "tools.install_sandbox.run",
        "tools.install_sandbox.sandbox_runner",
        "tools.install_sandbox.validation_plan",
    }
    assert ROOT_MODULE_RELOCATION_CANDIDATES == {
        "tools.install_sandbox.reference_resolution": "tools.install_sandbox.targets.reference_resolution",
    }
    assert ROOT_HELPER_DELETION_CANDIDATES.isdisjoint(ROOT_WORTHY_ENTRYPOINTS_AND_DEEP_SEAMS)
    assert set(ROOT_MODULE_RELOCATION_CANDIDATES).isdisjoint(ROOT_WORTHY_ENTRYPOINTS_AND_DEEP_SEAMS)
    assert ROOT_HELPER_DELETION_CANDIDATES.isdisjoint(DELETED_PURE_ROOT_FACADE_MODULES)
    assert ROOT_HELPER_DELETION_CANDIDATES.isdisjoint(DELETED_INSTALL_SURFACE_CORE_FACADE_MODULES)
    assert DELETED_ROOT_HELPER_MODULES.isdisjoint(ROOT_HELPER_DELETION_CANDIDATES)
    assert DELETED_ROOT_HELPER_MODULES.isdisjoint(ROOT_WORTHY_ENTRYPOINTS_AND_DEEP_SEAMS)
    assert DELETED_AGENT_SUMMARY_SHIM_MODULES.isdisjoint(ROOT_WORTHY_ENTRYPOINTS_AND_DEEP_SEAMS)


def test_root_topology_closeout_finds_no_supported_reference_resolution_root_import_contract() -> None:
    assert SUPPORTED_EXTERNAL_REFERENCE_RESOLUTION_IMPORT_CONTRACTS == {}
    assert _documented_reference_resolution_contracts() == SUPPORTED_EXTERNAL_REFERENCE_RESOLUTION_IMPORT_CONTRACTS


def test_root_topology_closeout_keeps_deleted_root_helpers_absent() -> None:
    for module_name in DELETED_ROOT_HELPER_MODULES:
        root_file_name = module_name.rsplit(".", maxsplit=1)[-1]

        assert not (INSTALL_SANDBOX_ROOT / f"{root_file_name}.py").exists()
        assert importlib.util.find_spec(module_name) is None


def test_root_topology_closeout_keeps_agent_summary_shim_absent() -> None:
    owner_agent_summary = importlib.import_module("tools.install_sandbox.reporting.agent_summary")

    for module_name in DELETED_AGENT_SUMMARY_SHIM_MODULES:
        root_file_name = module_name.rsplit(".", maxsplit=1)[-1]

        assert not (INSTALL_SANDBOX_ROOT / f"{root_file_name}.py").exists()
        assert importlib.util.find_spec(module_name) is None
    assert callable(owner_agent_summary.summarize_output)
    assert callable(owner_agent_summary.write_summary)


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


def test_root_topology_closeout_characterizes_validation_plan_alias_surface() -> None:
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
    assert not any(hasattr(validation_plan.ValidationPlan, public_name) for public_name in VALIDATION_PLAN_ALIAS_PRUNING_CANDIDATES["property_aliases"])
    assert not any(hasattr(validation_plan, public_name) for public_name in VALIDATION_PLAN_ALIAS_PRUNING_CANDIDATES["helper_aliases"])
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


def test_root_topology_closeout_keeps_runner_runtime_and_lifecycle_aliases_pruned() -> None:
    sandbox_runner = importlib.import_module("tools.install_sandbox.sandbox_runner")

    pruned_alias_names = {
        *SANDBOX_RUNNER_PRUNING_CANDIDATES["runtime_globals"],
        *SANDBOX_RUNNER_PRUNING_CANDIDATES["sentinel_aliases"],
        *SANDBOX_RUNNER_PRUNING_CANDIDATES["lifecycle_aliases"],
        *SANDBOX_RUNNER_PRUNING_CANDIDATES["status_aliases"],
    }
    for public_name in pruned_alias_names:
        assert not hasattr(sandbox_runner, public_name)

    assert set(SANDBOX_RUNNER_PRUNING_CANDIDATES["wrapper_functions"]) == {
        "sandbox_env",
        "install_graphify",
        "risk_report",
        "preflight",
        "scenario_lifecycle_hooks",
    }
    for public_name in SANDBOX_RUNNER_PRUNING_CANDIDATES["wrapper_functions"]:
        assert not hasattr(sandbox_runner, public_name)

    assert set(SANDBOX_RUNNER_PRUNING_CANDIDATES["status_aliases"]) == {
        "RISK_GRAPHIFY_FAILED",
        "RISK_GRAPHIFY_VERIFIED",
        "combined_status",
        "known_status_values",
    }

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
        coverage_records = ({"target": "codex", "scope": "project", "status": "runnable"},)
        target_runtime_validation_sections = ({"section_title": "Runtime Boundary", "status": "declared"},)
        target_coverage_summary = {"requested_scope": "project", "universal_scenario_count": 0}
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
    assert manifest["target_coverage"] == [{"target": "codex", "scope": "project", "status": "runnable"}]
    assert manifest["target_coverage_summary"]["universal_scenario_count"] == 1
    assert manifest["scenario_count"] == 2
