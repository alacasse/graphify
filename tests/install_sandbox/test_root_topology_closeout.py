from __future__ import annotations

import ast
import importlib
import inspect
import types
from pathlib import Path


INSTALL_SANDBOX_ROOT = Path(__file__).parents[2] / "tools" / "install_sandbox"

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

SCENARIO_PLATFORM_CONTRACT_DECISION = "migrated_internal_artifact_identity"

LEGACY_PLATFORM_INPUT_ONLY_READERS = {
    "tools/install_sandbox/reporting/artifacts.py": 1,
    "tools/install_sandbox/reporting/manifest_projection.py": 1,
}

RUNNER_INTAKE_FRONTIER_MODULES = (
    "tools.install_sandbox.run",
    "tools.install_sandbox.sandbox_runner",
    "tools.install_sandbox.runtime.harness_orchestration",
)


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


def _class_method_node(module: types.ModuleType, class_name: str, method_name: str) -> ast.FunctionDef:
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return next(
        node
        for node in class_node.body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )


def _constant_values(node: ast.AST) -> set[object]:
    return {
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant)
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
    spec_loader = importlib.import_module("tools.install_sandbox.registry.spec_loader")
    spec_inputs = importlib.import_module("tools.install_sandbox.registry.spec_harness_policy_inputs")
    schema_validation = importlib.import_module("tools.install_sandbox.registry.spec_schema_validation")

    assert spec_loader.CURRENT_REGISTRY_CONTAINER_FIELD == "targets"
    assert spec_loader.LEGACY_REGISTRY_CONTAINER_FIELD == "platforms"
    assert spec_loader.CURRENT_REGISTRY_CONTAINER_FIELD == schema_validation.CURRENT_REGISTRY_CONTAINER_FIELD
    assert spec_loader.LEGACY_REGISTRY_CONTAINER_FIELD == schema_validation.LEGACY_REGISTRY_CONTAINER_FIELD
    assert schema_validation.CURRENT_HARNESS_POLICY_ELIGIBILITY_FIELD == "eligible_target_scope"
    assert schema_validation.LEGACY_HARNESS_POLICY_ELIGIBILITY_FIELD == "eligible_platform_scope"
    assert spec_inputs.UNIVERSAL_UNINSTALL_FIELD_CLASSIFICATIONS["eligible_target_scope"] == (
        schema_validation.SCHEMA_CLASS_HARNESS_POLICY_INPUT
    )
    assert spec_inputs.UNIVERSAL_UNINSTALL_FIELD_CLASSIFICATIONS["eligible_platform_scope"] == (
        schema_validation.SCHEMA_CLASS_PUBLIC_SCHEMA_COMPATIBILITY
    )
    assert spec_inputs.UNIVERSAL_UNINSTALL_FIELD_CLASSIFICATIONS["platform_label"] == (
        schema_validation.SCHEMA_CLASS_TRANSITIONAL_EXECUTION
    )
    assert spec_inputs.DISPOSABLE_ARTIFACT_FIELD_CLASSIFICATIONS["platform_label"] == (
        schema_validation.SCHEMA_CLASS_TRANSITIONAL_EXECUTION
    )
    assert schema_validation.PUBLIC_SCHEMA_COMPATIBILITY_FIELDS >= {"platforms", "eligible_platform_scope"}
    assert schema_validation.PUBLIC_PRODUCT_CONTRACT_FIELDS == {"--platform"}

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
    eligibility_resolver_source = inspect.getsource(spec_inputs._universal_uninstall_eligible_target_scope)
    assert "eligible_target_scope=" in loader_source
    assert "CURRENT_HARNESS_POLICY_ELIGIBILITY_FIELD" in eligibility_resolver_source
    assert "LEGACY_HARNESS_POLICY_ELIGIBILITY_FIELD" in eligibility_resolver_source


def test_root_topology_closeout_classifies_scenario_platform_as_internal_identity() -> None:
    models = importlib.import_module("tools.install_sandbox.targets.install_target_models")

    assert SCENARIO_PLATFORM_CONTRACT_DECISION == "migrated_internal_artifact_identity"
    assert "target_name" in models.Scenario.__dataclass_fields__
    assert "platform" not in models.Scenario.__dataclass_fields__
    assert not hasattr(models.Scenario, "platform")
    assert not isinstance(getattr(models.Scenario, "platform", None), property)

    attribute_references = _source_occurrence_counts(
        lambda node: isinstance(node, ast.Attribute)
        and node.attr == "platform"
        and not (isinstance(node.value, ast.Name) and node.value.id == "args")
    )

    assert attribute_references == {}


def test_root_topology_closeout_classifies_generated_artifact_vocabulary_separately_from_legacy_input() -> None:
    assert LEGACY_PLATFORM_INPUT_ONLY_READERS == {
        "tools/install_sandbox/reporting/artifacts.py": 1,
        "tools/install_sandbox/reporting/manifest_projection.py": 1,
    }

    lifecycle_support = importlib.import_module("tools.install_sandbox.lifecycle.scenario_lifecycle_support")
    result_record_constants = _constant_values(_class_method_node(lifecycle_support, "ScenarioArtifacts", "result_record"))
    standard_assertion_constants = _constant_values(_class_method_node(lifecycle_support, "StandardScenarioOutcome", "assertions"))
    universal_assertion_constants = _constant_values(_class_method_node(lifecycle_support, "UniversalUninstallOutcome", "assertions"))
    disposable_assertion_constants = _constant_values(_class_method_node(lifecycle_support, "DisposableArtifactOutcome", "assertions"))

    assert "target" in result_record_constants
    assert "target" in standard_assertion_constants
    assert "targets" in universal_assertion_constants
    assert "target" in disposable_assertion_constants
    assert "platform" not in (
        result_record_constants
        | standard_assertion_constants
        | universal_assertion_constants
        | disposable_assertion_constants
    )

    literal_platform_keys = _source_occurrence_counts(
        lambda node: isinstance(node, ast.Constant) and node.value == "platform"
    )

    assert literal_platform_keys == LEGACY_PLATFORM_INPUT_ONLY_READERS


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
