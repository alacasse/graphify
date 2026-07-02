from __future__ import annotations

import ast
import importlib
import inspect
import types
from pathlib import Path


INSTALL_SANDBOX_ROOT = Path(__file__).parents[2] / "tools" / "install_sandbox"
TESTS_ROOT = Path(__file__).parents[2] / "tests"

VALIDATION_PLAN_INTERNAL_TARGET_HELPER_VOCABULARY = {
    "tools.install_sandbox.validation_plan._standard_scenarios": {"target_names"},
    "tools.install_sandbox.validation_plan.coverage_records": {"target_names"},
    "tools.install_sandbox.validation_plan.universal_uninstall_scenarios": {"target_names"},
    "tools.install_sandbox.validation_plan.target_runtime_validation_sections": {"target_names"},
    "tools.install_sandbox.validation_plan._coverage_summary": {"target_names"},
}

VALIDATION_PLAN_EDGE_PLATFORM_VOCABULARY_BUCKETS = {
    "public product CLI": {"--platform"},
    "YAML input": {"registry platforms"},
    "serialized artifact input/output": {"scenario.platform", "scenario.platforms", "result.platform"},
    "legacy input-only reader": {
        "legacy manifest.platform",
        "legacy manifest.platform_coverage",
        "legacy result.platform",
    },
}

DELETED_INSTALL_TARGET_MODEL_NAMES = {
    "Platform" "Spec",
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


def test_root_topology_closeout_characterizes_validation_plan_internal_target_vocabulary() -> None:
    validation_plan = importlib.import_module("tools.install_sandbox.validation_plan")

    assert VALIDATION_PLAN_INTERNAL_TARGET_HELPER_VOCABULARY == {
        "tools.install_sandbox.validation_plan._standard_scenarios": {"target_names"},
        "tools.install_sandbox.validation_plan.coverage_records": {"target_names"},
        "tools.install_sandbox.validation_plan.universal_uninstall_scenarios": {"target_names"},
        "tools.install_sandbox.validation_plan.target_runtime_validation_sections": {"target_names"},
        "tools.install_sandbox.validation_plan._coverage_summary": {"target_names"},
    }
    assert VALIDATION_PLAN_EDGE_PLATFORM_VOCABULARY_BUCKETS == {
        "public product CLI": {"--platform"},
        "YAML input": {"registry platforms"},
        "serialized artifact input/output": {"scenario.platform", "scenario.platforms", "result.platform"},
        "legacy input-only reader": {
            "legacy manifest.platform",
            "legacy manifest.platform_coverage",
            "legacy result.platform",
        },
    }

    public_plan_parameters = set(inspect.signature(validation_plan.ValidationPlan).parameters)
    public_selector_parameters = set(inspect.signature(validation_plan.selected_targets).parameters)
    assert "platforms" not in public_plan_parameters
    assert {"target_name", "selected_target_names"} <= public_selector_parameters

    for dotted_name, expected_parameters in VALIDATION_PLAN_INTERNAL_TARGET_HELPER_VOCABULARY.items():
        _, helper_name = dotted_name.rsplit(".", maxsplit=1)
        signature = inspect.signature(getattr(validation_plan, helper_name))
        helper_node = _function_node(validation_plan, helper_name)
        helper_parameters = {arg.arg for arg in helper_node.args.args + helper_node.args.kwonlyargs}

        assert set(signature.parameters) >= expected_parameters
        assert helper_parameters >= expected_parameters
        assert "platforms" not in helper_parameters

    build_node = _function_node(validation_plan, "build_validation_plan")
    coverage_summary_keywords = _call_keyword_names(build_node, "_coverage_summary")
    assert coverage_summary_keywords >= {"target_names"}
    assert "platforms" not in coverage_summary_keywords

    internal_terms = set().union(*VALIDATION_PLAN_INTERNAL_TARGET_HELPER_VOCABULARY.values())
    edge_terms = set().union(*VALIDATION_PLAN_EDGE_PLATFORM_VOCABULARY_BUCKETS.values())
    assert internal_terms == {"target_names"}
    assert "registry platforms" in edge_terms
    assert "platforms" not in edge_terms
    assert internal_terms.isdisjoint(edge_terms)


def test_root_topology_closeout_keeps_deleted_install_target_model_names_absent() -> None:
    install_target_models = importlib.import_module("tools.install_sandbox.targets.install_target_models")

    for model_name in DELETED_INSTALL_TARGET_MODEL_NAMES:
        assert not hasattr(install_target_models, model_name)

    assert _install_target_model_name_surface(DELETED_INSTALL_TARGET_MODEL_NAMES) == {}


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

    assert importlib.import_module("tools.install_sandbox.runtime")
    assert importlib.import_module("tools.install_sandbox.runtime.sandbox_run_environment")
    assert slice2_owner_module.rsplit(".", 1)[0] == "tools.install_sandbox.runtime"
