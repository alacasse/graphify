from __future__ import annotations

from copy import deepcopy
from typing import Any

import yaml

from tools.install_sandbox.registry import spec_loader
from tools.install_sandbox.registry import spec_harness_policy_inputs
from tools.install_sandbox.registry import spec_install_surfaces
from tools.install_sandbox.registry import spec_schema_validation
from tools.install_sandbox.registry import spec_target_facts
from tools.install_sandbox.registry.spec_loader import load_registry_from_data, load_registry_from_dir
from tools.install_sandbox.registry.spec_normalize import normalize_registry

from tests.install_sandbox.install_target_test_support import legacy_platform_registry_data, valid_registry_data


FIELD_CLASS_DURABLE_TARGET_FACT = "durable_target_fact"
FIELD_CLASS_INSTALL_SURFACE = "install_surface"
FIELD_CLASS_TRANSITIONAL_SANDBOX_EXECUTION = "transitional_sandbox_execution_data"
FIELD_CLASS_TRANSITIONAL_SANDBOX_POLICY = "transitional_sandbox_policy_data"
FIELD_CLASS_DERIVED_DEFAULT = "derived_default"
FIELD_CLASS_HARNESS_POLICY = "harness_policy"
FIELD_CLASS_RUNTIME_LIMITATION = "runtime_limitation"
FIELD_CLASS_SYNTHETIC_OUTPUT_LABEL = "synthetic_output_label"
FIELD_CLASS_SELECTED_TARGET_ELIGIBILITY = "selected_target_eligibility"
FIELD_CLASS_YAML_INPUT_EDGE_VOCABULARY = "yaml_input_edge_vocabulary"
FIELD_CLASS_INTERNAL_STANDARD_SCENARIO_TARGET_IDENTITY = "internal_standard_scenario_target_identity"
FIELD_CLASS_SERIALIZED_ARTIFACT_VOCABULARY = "serialized_artifact_vocabulary"
FIELD_CLASS_PUBLIC_PRODUCT_EDGE_VOCABULARY = "public_product_edge_vocabulary"
FIELD_CLASS_LEGACY_INPUT_ONLY_READER = "legacy_input_only_reader"
FIELD_CLASS_HISTORICAL_EVIDENCE = "historical_evidence"
FIELD_CLASS_REPORTING_PROJECTION_EXEMPLAR = "reporting_projection_exemplar"
FIELD_CLASS_CURRENT_TARGET_NAMED_OUTPUT = "current_target_named_output"
FIELD_CLASS_CURRENT_TARGET_NAMED_INPUT = "current_target_named_input"
FIELD_CLASS_CURRENT_FIXTURE_INPUT = "current_fixture_input"


def _current_registry_data() -> dict[str, Any]:
    return deepcopy(valid_registry_data())


def _default_registry_yaml_data() -> dict[str, Any]:
    return {
        "schema_version": spec_loader.SCHEMA_VERSION,
        "targets": {
            path.stem: yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for path in sorted(spec_loader.DEFAULT_REGISTRY_PATH.glob("*.yaml"))
        },
    }


SPEC_WEIGHT_FIELD_CLASSIFICATION = {
    "install_command": FIELD_CLASS_TRANSITIONAL_SANDBOX_EXECUTION,
    "uninstall_command": FIELD_CLASS_TRANSITIONAL_SANDBOX_EXECUTION,
    "equivalent_install_command": FIELD_CLASS_TRANSITIONAL_SANDBOX_EXECUTION,
    "universal_uninstall_scopes": FIELD_CLASS_HARNESS_POLICY,
    "unsupported_scopes": FIELD_CLASS_RUNTIME_LIMITATION,
    "simulated_linux_layout": FIELD_CLASS_RUNTIME_LIMITATION,
    "reference_bundles": FIELD_CLASS_DURABLE_TARGET_FACT,
    "target_runtime_validation": FIELD_CLASS_RUNTIME_LIMITATION,
}

REGISTRY_FIELD_CLASSIFICATION = {
    "targets": FIELD_CLASS_CURRENT_TARGET_NAMED_INPUT,
    "platforms": FIELD_CLASS_LEGACY_INPUT_ONLY_READER,
    "universal_uninstall_specs": FIELD_CLASS_HARNESS_POLICY,
    "disposable_artifact_specs": FIELD_CLASS_TRANSITIONAL_SANDBOX_POLICY,
}

SPEC_WEIGHT_FIELD_EXAMPLES = {
    "install_command": "vscode.user",
    "uninstall_command": "codex.user",
    "equivalent_install_command": "cursor.project",
    "universal_uninstall_scopes": "codex",
    "unsupported_scopes": "cursor",
    "simulated_linux_layout": "windows",
    "reference_bundles": "vscode",
}

REGISTRY_FIELD_EXAMPLES = {
    "universal_uninstall_specs": {"<registry>"},
    "disposable_artifact_specs": {"<registry>"},
}

FIXTURE_INPUT_ROLE_CLASSIFICATION = {
    "valid_registry_data.targets": {
        FIELD_CLASS_CURRENT_FIXTURE_INPUT,
        FIELD_CLASS_CURRENT_TARGET_NAMED_INPUT,
    },
    "legacy_platform_registry_data.platforms": {
        FIELD_CLASS_LEGACY_INPUT_ONLY_READER,
    },
}

HARNESS_POLICY_INPUT_EDGE_FIELD_CLASSIFICATION = {
    "universal_uninstall_specs[].platform_label": {
        FIELD_CLASS_YAML_INPUT_EDGE_VOCABULARY,
    },
    "universal_uninstall_specs[].eligible_target_scope": {
        FIELD_CLASS_SELECTED_TARGET_ELIGIBILITY,
        FIELD_CLASS_CURRENT_TARGET_NAMED_INPUT,
    },
    "universal_uninstall_specs[].eligible_platform_scope": {
        FIELD_CLASS_LEGACY_INPUT_ONLY_READER,
    },
    "disposable_artifact_specs[].platform_label": {
        FIELD_CLASS_YAML_INPUT_EDGE_VOCABULARY,
    },
}

SCENARIO_IDENTITY_EDGE_FIELD_CLASSIFICATION = {
    "Scenario.target_name": {
        FIELD_CLASS_INTERNAL_STANDARD_SCENARIO_TARGET_IDENTITY,
    },
    "standard_scenario_result.platform": {
        FIELD_CLASS_SERIALIZED_ARTIFACT_VOCABULARY,
    },
    "synthetic_scenario_result.platform": {
        FIELD_CLASS_SERIALIZED_ARTIFACT_VOCABULARY,
    },
    "synthetic_group_result.platforms": {
        FIELD_CLASS_SERIALIZED_ARTIFACT_VOCABULARY,
    },
    "UniversalUninstallScenarioSpec.synthetic_result_label": {
        FIELD_CLASS_SYNTHETIC_OUTPUT_LABEL,
    },
    "DisposableArtifactScenarioSpec.synthetic_result_label": {
        FIELD_CLASS_SYNTHETIC_OUTPUT_LABEL,
    },
    "product_command.--platform": {
        FIELD_CLASS_PUBLIC_PRODUCT_EDGE_VOCABULARY,
    },
    "registry_yaml.targets": {
        FIELD_CLASS_YAML_INPUT_EDGE_VOCABULARY,
        FIELD_CLASS_CURRENT_TARGET_NAMED_INPUT,
    },
    "legacy_registry_yaml.platforms": {
        FIELD_CLASS_LEGACY_INPUT_ONLY_READER,
    },
    "legacy_registry_yaml.eligible_platform_scope": {
        FIELD_CLASS_LEGACY_INPUT_ONLY_READER,
    },
    "historical_registry_yaml.platform_label": {
        FIELD_CLASS_HISTORICAL_EVIDENCE,
    },
    "normalized_registry_output.targets": {
        FIELD_CLASS_CURRENT_TARGET_NAMED_OUTPUT,
    },
    "legacy_manifest_input.platform": {
        FIELD_CLASS_LEGACY_INPUT_ONLY_READER,
    },
    "legacy_manifest_input.platform_coverage": {
        FIELD_CLASS_LEGACY_INPUT_ONLY_READER,
    },
}

REPORTING_PROJECTION_ROLE_CLASSIFICATION = {
    "manifest_projection.target_coverage": {
        FIELD_CLASS_REPORTING_PROJECTION_EXEMPLAR,
        FIELD_CLASS_CURRENT_TARGET_NAMED_OUTPUT,
    },
    "manifest_projection.target_coverage_summary": {
        FIELD_CLASS_REPORTING_PROJECTION_EXEMPLAR,
        FIELD_CLASS_CURRENT_TARGET_NAMED_OUTPUT,
    },
    "report_rendering.target_coverage": {
        FIELD_CLASS_REPORTING_PROJECTION_EXEMPLAR,
        FIELD_CLASS_CURRENT_TARGET_NAMED_OUTPUT,
    },
    "agent_summary.failure.target": {
        FIELD_CLASS_REPORTING_PROJECTION_EXEMPLAR,
        FIELD_CLASS_CURRENT_TARGET_NAMED_OUTPUT,
    },
    "legacy_manifest_input.platform": {
        FIELD_CLASS_REPORTING_PROJECTION_EXEMPLAR,
        FIELD_CLASS_LEGACY_INPUT_ONLY_READER,
    },
    "legacy_manifest_input.platform_coverage": {
        FIELD_CLASS_REPORTING_PROJECTION_EXEMPLAR,
        FIELD_CLASS_LEGACY_INPUT_ONLY_READER,
    },
    "legacy_result_input.platform": {
        FIELD_CLASS_REPORTING_PROJECTION_EXEMPLAR,
        FIELD_CLASS_LEGACY_INPUT_ONLY_READER,
    },
    "product_command.--platform": {
        FIELD_CLASS_PUBLIC_PRODUCT_EDGE_VOCABULARY,
    },
    "registry_yaml.targets": {
        FIELD_CLASS_YAML_INPUT_EDGE_VOCABULARY,
        FIELD_CLASS_CURRENT_TARGET_NAMED_INPUT,
    },
    "legacy_registry_yaml.platforms": {
        FIELD_CLASS_LEGACY_INPUT_ONLY_READER,
    },
    "legacy_registry_yaml.eligible_platform_scope": {
        FIELD_CLASS_LEGACY_INPUT_ONLY_READER,
    },
    "historical_registry_yaml.platform_label": {
        FIELD_CLASS_HISTORICAL_EVIDENCE,
    },
    "UniversalUninstallScenarioSpec.synthetic_result_label": {
        FIELD_CLASS_SYNTHETIC_OUTPUT_LABEL,
    },
    "DisposableArtifactScenarioSpec.synthetic_result_label": {
        FIELD_CLASS_SYNTHETIC_OUTPUT_LABEL,
    },
}

SCENARIO_PLATFORM_CONTRACT_DECISION = "migratable_internal_identity"

DEFAULT_YAML_STRUCTURAL_TARGET_FIELDS = {
    "display_name",
    "project_skill",
    "scopes",
    "target_kind",
    "user_skill",
    "uses_packaged_references",
}
DEFAULT_YAML_STRUCTURAL_SCOPE_FIELDS = {
    "effects",
    "expected",
}


def _schema_class_to_field_class(field: str, schema_class: str) -> str:
    if field in {"simulated_linux_layout", "target_runtime_validation", "unsupported_scopes"}:
        return FIELD_CLASS_RUNTIME_LIMITATION
    if field == "universal_uninstall_scopes":
        return FIELD_CLASS_HARNESS_POLICY
    if schema_class == spec_schema_validation.SCHEMA_CLASS_TARGET_FACT:
        return FIELD_CLASS_DURABLE_TARGET_FACT
    if schema_class == spec_schema_validation.SCHEMA_CLASS_TRANSITIONAL_EXECUTION:
        return FIELD_CLASS_TRANSITIONAL_SANDBOX_EXECUTION
    if schema_class == spec_schema_validation.SCHEMA_CLASS_TRANSITIONAL_PLANNING:
        return FIELD_CLASS_TRANSITIONAL_SANDBOX_POLICY
    if schema_class == spec_schema_validation.SCHEMA_CLASS_HARNESS_POLICY_INPUT:
        return FIELD_CLASS_HARNESS_POLICY
    if schema_class == spec_schema_validation.SCHEMA_CLASS_PUBLIC_SCHEMA_COMPATIBILITY:
        return FIELD_CLASS_LEGACY_INPUT_ONLY_READER
    raise AssertionError(f"unknown schema class for {field}: {schema_class}")


def _default_yaml_field_path_examples() -> dict[str, set[str]]:
    examples: dict[str, set[str]] = {}

    def add(path: str, example: str) -> None:
        examples.setdefault(path, set()).add(example)

    def walk(value: object, prefix: str, example: str) -> None:
        add(prefix, example)
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{prefix}.{key}", example)
            return
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    walk(item, f"{prefix}[]", example)

    for spec_path in sorted(spec_loader.DEFAULT_REGISTRY_PATH.glob("*.yaml")):
        data = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
        for field, value in data.items():
            if field == "scopes" and isinstance(value, dict):
                add("scopes", spec_path.stem)
                for scope_name, scope_data in value.items():
                    add(f"scopes.{scope_name}", spec_path.stem)
                    if isinstance(scope_data, dict):
                        for scope_field, scope_field_value in scope_data.items():
                            walk(scope_field_value, f"scopes.*.{scope_field}", f"{spec_path.stem}.{scope_name}")
                continue
            walk(value, field, spec_path.stem)

    return examples


def _classify_default_yaml_field_path(path: str) -> str | None:
    if path in {"scopes.project", "scopes.user"}:
        return FIELD_CLASS_DURABLE_TARGET_FACT
    if path.startswith("unsupported_scopes."):
        return FIELD_CLASS_RUNTIME_LIMITATION
    if path == "reference_bundles[]":
        return FIELD_CLASS_DURABLE_TARGET_FACT
    if path.startswith("reference_bundles[]."):
        field = path.removeprefix("reference_bundles[].")
        if field in spec_target_facts._REFERENCE_BUNDLE_FIELDS:
            return _schema_class_to_field_class(field, spec_schema_validation.SCHEMA_CLASS_TARGET_FACT)
        return None
    if path.startswith("target_runtime_validation[]."):
        field = path.removeprefix("target_runtime_validation[].")
        if field in spec_target_facts._TARGET_RUNTIME_VALIDATION_FIELDS:
            return FIELD_CLASS_RUNTIME_LIMITATION
        return None
    if path == "scopes.*.effects[].hooks[]":
        return FIELD_CLASS_INSTALL_SURFACE
    if path.startswith("scopes.*.effects[].hooks[]."):
        field = path.removeprefix("scopes.*.effects[].hooks[].")
        if field in spec_install_surfaces._JSON_HOOK_FIELDS:
            return FIELD_CLASS_INSTALL_SURFACE
        return None
    if path == "scopes.*.effects[]":
        return FIELD_CLASS_INSTALL_SURFACE
    if path.startswith("scopes.*.effects[]."):
        field = path.removeprefix("scopes.*.effects[].")
        if field in set().union(*spec_install_surfaces._EFFECT_FIELDS_BY_KIND.values()):
            return FIELD_CLASS_INSTALL_SURFACE
        return None
    if path.startswith("scopes.*."):
        field = path.removeprefix("scopes.*.")
        schema_class = spec_target_facts.SCOPE_FIELD_CLASSIFICATIONS.get(field)
        if schema_class is None:
            return None
        if field == "effects":
            return FIELD_CLASS_INSTALL_SURFACE
        if field == "expected":
            return FIELD_CLASS_LEGACY_INPUT_ONLY_READER
        return _schema_class_to_field_class(field, schema_class)

    schema_class = spec_target_facts.TARGET_FIELD_CLASSIFICATIONS.get(path)
    if schema_class is None:
        return None
    return _schema_class_to_field_class(path, schema_class)


def test_loader_derives_conventional_product_yaml_equivalent_to_explicit_fixture() -> None:
    explicit = _current_registry_data()
    conventional = _current_registry_data()
    mini = conventional["targets"]["mini"]
    mini.pop("user_skill")
    mini.pop("project_skill")
    mini["scopes"]["user"].pop("risk_notes")
    mini["scopes"]["project"].pop("equivalent_install_command")

    assert FIELD_CLASS_DERIVED_DEFAULT == "derived_default"
    assert normalize_registry(load_registry_from_data(conventional)) == normalize_registry(load_registry_from_data(explicit))


def test_default_registry_derives_removed_checked_in_boilerplate() -> None:
    minimal = _default_registry_yaml_data()
    explicit = deepcopy(minimal)
    explicit["targets"]["agents"]["user_skill"] = ".agents/skills/graphify/SKILL.md"
    explicit["targets"]["agents"]["project_skill"] = ".agents/skills/graphify/SKILL.md"
    explicit["targets"]["antigravity"]["scopes"]["project"]["equivalent_install_command"] = [
        "graphify",
        "antigravity",
        "install",
        "--project",
    ]
    explicit["targets"]["devin"]["scopes"]["project"]["equivalent_install_command"] = [
        "graphify",
        "devin",
        "install",
        "--project",
    ]
    explicit["targets"]["pi"]["scopes"]["project"]["equivalent_install_command"] = [
        "graphify",
        "pi",
        "install",
        "--project",
    ]

    assert normalize_registry(load_registry_from_data(minimal)) == normalize_registry(load_registry_from_data(explicit))


def _default_yaml_spec_weight_field_inventory() -> dict[str, set[str]]:
    actual_inventory: dict[str, set[str]] = {}

    for path in spec_loader.DEFAULT_REGISTRY_PATH.glob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for field in data.keys() - DEFAULT_YAML_STRUCTURAL_TARGET_FIELDS:
            actual_inventory.setdefault(field, set()).add(path.stem)
        for scope_name, scope_data in data.get("scopes", {}).items():
            for field in scope_data.keys() - DEFAULT_YAML_STRUCTURAL_SCOPE_FIELDS:
                actual_inventory.setdefault(field, set()).add(f"{path.stem}.{scope_name}")

    return actual_inventory


def test_spec_weight_field_classification_vocabulary_is_explicit() -> None:
    assert SPEC_WEIGHT_FIELD_CLASSIFICATION == {
        "install_command": FIELD_CLASS_TRANSITIONAL_SANDBOX_EXECUTION,
        "uninstall_command": FIELD_CLASS_TRANSITIONAL_SANDBOX_EXECUTION,
        "equivalent_install_command": FIELD_CLASS_TRANSITIONAL_SANDBOX_EXECUTION,
        "universal_uninstall_scopes": FIELD_CLASS_HARNESS_POLICY,
        "unsupported_scopes": FIELD_CLASS_RUNTIME_LIMITATION,
        "simulated_linux_layout": FIELD_CLASS_RUNTIME_LIMITATION,
        "reference_bundles": FIELD_CLASS_DURABLE_TARGET_FACT,
        "target_runtime_validation": FIELD_CLASS_RUNTIME_LIMITATION,
    }


def test_registry_field_classification_vocabulary_is_explicit() -> None:
    assert REGISTRY_FIELD_CLASSIFICATION == {
        "targets": FIELD_CLASS_CURRENT_TARGET_NAMED_INPUT,
        "platforms": FIELD_CLASS_LEGACY_INPUT_ONLY_READER,
        "universal_uninstall_specs": FIELD_CLASS_HARNESS_POLICY,
        "disposable_artifact_specs": FIELD_CLASS_TRANSITIONAL_SANDBOX_POLICY,
    }


def test_fixture_input_roles_keep_current_and_legacy_inputs_separate() -> None:
    current_fixture = valid_registry_data()
    legacy_fixture = legacy_platform_registry_data()

    assert FIXTURE_INPUT_ROLE_CLASSIFICATION == {
        "valid_registry_data.targets": {
            FIELD_CLASS_CURRENT_FIXTURE_INPUT,
            FIELD_CLASS_CURRENT_TARGET_NAMED_INPUT,
        },
        "legacy_platform_registry_data.platforms": {
            FIELD_CLASS_LEGACY_INPUT_ONLY_READER,
        },
    }
    assert "targets" in current_fixture
    assert "platforms" not in current_fixture
    assert "platforms" in legacy_fixture
    assert "targets" not in legacy_fixture


def test_harness_policy_input_edge_platform_field_roles_are_explicit() -> None:
    assert HARNESS_POLICY_INPUT_EDGE_FIELD_CLASSIFICATION == {
        "universal_uninstall_specs[].platform_label": {
            FIELD_CLASS_YAML_INPUT_EDGE_VOCABULARY,
        },
        "universal_uninstall_specs[].eligible_target_scope": {
            FIELD_CLASS_SELECTED_TARGET_ELIGIBILITY,
            FIELD_CLASS_CURRENT_TARGET_NAMED_INPUT,
        },
        "universal_uninstall_specs[].eligible_platform_scope": {
            FIELD_CLASS_LEGACY_INPUT_ONLY_READER,
        },
        "disposable_artifact_specs[].platform_label": {
            FIELD_CLASS_YAML_INPUT_EDGE_VOCABULARY,
        },
    }


def test_scenario_identity_edge_platform_field_roles_are_explicit() -> None:
    assert SCENARIO_PLATFORM_CONTRACT_DECISION == "migratable_internal_identity"
    assert SCENARIO_IDENTITY_EDGE_FIELD_CLASSIFICATION == {
        "Scenario.target_name": {
            FIELD_CLASS_INTERNAL_STANDARD_SCENARIO_TARGET_IDENTITY,
        },
        "standard_scenario_result.platform": {
            FIELD_CLASS_SERIALIZED_ARTIFACT_VOCABULARY,
        },
        "synthetic_scenario_result.platform": {
            FIELD_CLASS_SERIALIZED_ARTIFACT_VOCABULARY,
        },
        "synthetic_group_result.platforms": {
            FIELD_CLASS_SERIALIZED_ARTIFACT_VOCABULARY,
        },
        "UniversalUninstallScenarioSpec.synthetic_result_label": {
            FIELD_CLASS_SYNTHETIC_OUTPUT_LABEL,
        },
        "DisposableArtifactScenarioSpec.synthetic_result_label": {
            FIELD_CLASS_SYNTHETIC_OUTPUT_LABEL,
        },
        "product_command.--platform": {
            FIELD_CLASS_PUBLIC_PRODUCT_EDGE_VOCABULARY,
        },
        "registry_yaml.targets": {
            FIELD_CLASS_YAML_INPUT_EDGE_VOCABULARY,
            FIELD_CLASS_CURRENT_TARGET_NAMED_INPUT,
        },
        "legacy_registry_yaml.platforms": {
            FIELD_CLASS_LEGACY_INPUT_ONLY_READER,
        },
        "legacy_registry_yaml.eligible_platform_scope": {
            FIELD_CLASS_LEGACY_INPUT_ONLY_READER,
        },
        "historical_registry_yaml.platform_label": {
            FIELD_CLASS_HISTORICAL_EVIDENCE,
        },
        "normalized_registry_output.targets": {
            FIELD_CLASS_CURRENT_TARGET_NAMED_OUTPUT,
        },
        "legacy_manifest_input.platform": {
            FIELD_CLASS_LEGACY_INPUT_ONLY_READER,
        },
        "legacy_manifest_input.platform_coverage": {
            FIELD_CLASS_LEGACY_INPUT_ONLY_READER,
        },
    }


def test_reporting_projection_role_classification_names_exemplar_boundary() -> None:
    assert REPORTING_PROJECTION_ROLE_CLASSIFICATION == {
        "manifest_projection.target_coverage": {
            FIELD_CLASS_REPORTING_PROJECTION_EXEMPLAR,
            FIELD_CLASS_CURRENT_TARGET_NAMED_OUTPUT,
        },
        "manifest_projection.target_coverage_summary": {
            FIELD_CLASS_REPORTING_PROJECTION_EXEMPLAR,
            FIELD_CLASS_CURRENT_TARGET_NAMED_OUTPUT,
        },
        "report_rendering.target_coverage": {
            FIELD_CLASS_REPORTING_PROJECTION_EXEMPLAR,
            FIELD_CLASS_CURRENT_TARGET_NAMED_OUTPUT,
        },
        "agent_summary.failure.target": {
            FIELD_CLASS_REPORTING_PROJECTION_EXEMPLAR,
            FIELD_CLASS_CURRENT_TARGET_NAMED_OUTPUT,
        },
        "legacy_manifest_input.platform": {
            FIELD_CLASS_REPORTING_PROJECTION_EXEMPLAR,
            FIELD_CLASS_LEGACY_INPUT_ONLY_READER,
        },
        "legacy_manifest_input.platform_coverage": {
            FIELD_CLASS_REPORTING_PROJECTION_EXEMPLAR,
            FIELD_CLASS_LEGACY_INPUT_ONLY_READER,
        },
        "legacy_result_input.platform": {
            FIELD_CLASS_REPORTING_PROJECTION_EXEMPLAR,
            FIELD_CLASS_LEGACY_INPUT_ONLY_READER,
        },
        "product_command.--platform": {
            FIELD_CLASS_PUBLIC_PRODUCT_EDGE_VOCABULARY,
        },
        "registry_yaml.targets": {
            FIELD_CLASS_YAML_INPUT_EDGE_VOCABULARY,
            FIELD_CLASS_CURRENT_TARGET_NAMED_INPUT,
        },
        "legacy_registry_yaml.platforms": {
            FIELD_CLASS_LEGACY_INPUT_ONLY_READER,
        },
        "legacy_registry_yaml.eligible_platform_scope": {
            FIELD_CLASS_LEGACY_INPUT_ONLY_READER,
        },
        "historical_registry_yaml.platform_label": {
            FIELD_CLASS_HISTORICAL_EVIDENCE,
        },
        "UniversalUninstallScenarioSpec.synthetic_result_label": {
            FIELD_CLASS_SYNTHETIC_OUTPUT_LABEL,
        },
        "DisposableArtifactScenarioSpec.synthetic_result_label": {
            FIELD_CLASS_SYNTHETIC_OUTPUT_LABEL,
        },
    }


def test_reporting_projection_classification_keeps_legacy_platform_vocabulary_input_only() -> None:
    current_output_fields = {
        field
        for field, classes in REPORTING_PROJECTION_ROLE_CLASSIFICATION.items()
        if FIELD_CLASS_CURRENT_TARGET_NAMED_OUTPUT in classes
    }
    legacy_reader_fields = {
        field
        for field, classes in REPORTING_PROJECTION_ROLE_CLASSIFICATION.items()
        if FIELD_CLASS_LEGACY_INPUT_ONLY_READER in classes
    }

    assert current_output_fields == {
        "manifest_projection.target_coverage",
        "manifest_projection.target_coverage_summary",
        "report_rendering.target_coverage",
        "agent_summary.failure.target",
    }
    assert legacy_reader_fields == {
        "legacy_manifest_input.platform",
        "legacy_manifest_input.platform_coverage",
        "legacy_result_input.platform",
        "legacy_registry_yaml.platforms",
        "legacy_registry_yaml.eligible_platform_scope",
    }
    assert current_output_fields.isdisjoint(legacy_reader_fields)
    assert all("platform_coverage" not in field for field in current_output_fields)


def test_platform_to_target_closeout_classifies_remaining_platform_vocabulary_edges() -> None:
    classified_edges = {
        "current fixture input": {
            field
            for field, classes in FIXTURE_INPUT_ROLE_CLASSIFICATION.items()
            if FIELD_CLASS_CURRENT_FIXTURE_INPUT in classes
        },
        "public product CLI": {
            field
            for field, classes in REPORTING_PROJECTION_ROLE_CLASSIFICATION.items()
            if FIELD_CLASS_PUBLIC_PRODUCT_EDGE_VOCABULARY in classes
        },
        "current YAML input": {
            field
            for field, classes in REPORTING_PROJECTION_ROLE_CLASSIFICATION.items()
            if FIELD_CLASS_YAML_INPUT_EDGE_VOCABULARY in classes
        },
        "generated output vocabulary": {
            field
            for field, classes in SCENARIO_IDENTITY_EDGE_FIELD_CLASSIFICATION.items()
            if FIELD_CLASS_SERIALIZED_ARTIFACT_VOCABULARY in classes
        },
        "legacy input-only reader": {
            field
            for field, classes in REPORTING_PROJECTION_ROLE_CLASSIFICATION.items()
            if FIELD_CLASS_LEGACY_INPUT_ONLY_READER in classes
        }
        | {
            field
            for field, classes in FIXTURE_INPUT_ROLE_CLASSIFICATION.items()
            if FIELD_CLASS_LEGACY_INPUT_ONLY_READER in classes
        },
        "historical evidence": {
            field
            for classification in (
                REPORTING_PROJECTION_ROLE_CLASSIFICATION,
                SCENARIO_IDENTITY_EDGE_FIELD_CLASSIFICATION,
            )
            for field, classes in classification.items()
            if FIELD_CLASS_HISTORICAL_EVIDENCE in classes
        },
        "current target-named output": {
            field
            for classification in (
                REPORTING_PROJECTION_ROLE_CLASSIFICATION,
                SCENARIO_IDENTITY_EDGE_FIELD_CLASSIFICATION,
            )
            for field, classes in classification.items()
            if FIELD_CLASS_CURRENT_TARGET_NAMED_OUTPUT in classes
        },
        "synthetic label vocabulary": {
            field
            for field, classes in REPORTING_PROJECTION_ROLE_CLASSIFICATION.items()
            if FIELD_CLASS_SYNTHETIC_OUTPUT_LABEL in classes
        },
    }

    assert classified_edges == {
        "current fixture input": {"valid_registry_data.targets"},
        "public product CLI": {"product_command.--platform"},
        "current YAML input": {"registry_yaml.targets"},
        "generated output vocabulary": {
            "standard_scenario_result.platform",
            "synthetic_scenario_result.platform",
            "synthetic_group_result.platforms",
        },
        "legacy input-only reader": {
            "legacy_platform_registry_data.platforms",
            "legacy_manifest_input.platform",
            "legacy_manifest_input.platform_coverage",
            "legacy_result_input.platform",
            "legacy_registry_yaml.platforms",
            "legacy_registry_yaml.eligible_platform_scope",
        },
        "historical evidence": {
            "historical_registry_yaml.platform_label",
        },
        "current target-named output": {
            "manifest_projection.target_coverage",
            "manifest_projection.target_coverage_summary",
            "report_rendering.target_coverage",
            "agent_summary.failure.target",
            "normalized_registry_output.targets",
        },
        "synthetic label vocabulary": {
            "UniversalUninstallScenarioSpec.synthetic_result_label",
            "DisposableArtifactScenarioSpec.synthetic_result_label",
        },
    }

    assert all(
        FIELD_CLASS_CURRENT_TARGET_NAMED_OUTPUT not in classes
        for field, classes in REPORTING_PROJECTION_ROLE_CLASSIFICATION.items()
        if "platform" in field
    )
    assert {
        field
        for field, classes in HARNESS_POLICY_INPUT_EDGE_FIELD_CLASSIFICATION.items()
        if "platform_label" in field and FIELD_CLASS_SYNTHETIC_OUTPUT_LABEL in classes
    } == set()
    assert {
        field
        for field, classes in REPORTING_PROJECTION_ROLE_CLASSIFICATION.items()
        if FIELD_CLASS_SYNTHETIC_OUTPUT_LABEL in classes
    } == {
        "UniversalUninstallScenarioSpec.synthetic_result_label",
        "DisposableArtifactScenarioSpec.synthetic_result_label",
    }


def test_public_yaml_schema_closeout_keeps_current_legacy_and_product_buckets_separate() -> None:
    current_schema_inputs = {
        "registry_yaml.targets",
        "universal_uninstall_specs[].eligible_target_scope",
    }
    legacy_input_only = {
        "legacy_registry_yaml.platforms",
        "legacy_registry_yaml.eligible_platform_scope",
    }
    product_command_contracts = {"product_command.--platform"}
    current_output_fields = {
        "manifest_projection.target_coverage",
        "manifest_projection.target_coverage_summary",
        "report_rendering.target_coverage",
        "agent_summary.failure.target",
        "normalized_registry_output.targets",
    }

    assert spec_schema_validation.CURRENT_REGISTRY_CONTAINER_FIELD == "targets"
    assert spec_schema_validation.CURRENT_HARNESS_POLICY_ELIGIBILITY_FIELD == "eligible_target_scope"
    assert spec_schema_validation.PUBLIC_SCHEMA_COMPATIBILITY_FIELDS == {
        "platforms",
        "eligible_platform_scope",
    }
    assert spec_schema_validation.PUBLIC_PRODUCT_CONTRACT_FIELDS == {"--platform"}

    assert current_schema_inputs.isdisjoint(legacy_input_only)
    assert current_schema_inputs.isdisjoint(product_command_contracts)
    assert legacy_input_only.isdisjoint(product_command_contracts)
    assert current_output_fields.isdisjoint(legacy_input_only)

    assert {
        field
        for field, classes in SCENARIO_IDENTITY_EDGE_FIELD_CLASSIFICATION.items()
        if FIELD_CLASS_CURRENT_TARGET_NAMED_INPUT in classes
    } == {
        "registry_yaml.targets",
    }
    assert {
        field
        for field, classes in HARNESS_POLICY_INPUT_EDGE_FIELD_CLASSIFICATION.items()
        if FIELD_CLASS_CURRENT_TARGET_NAMED_INPUT in classes
    } == {"universal_uninstall_specs[].eligible_target_scope"}
    assert {
        field
        for field, classes in SCENARIO_IDENTITY_EDGE_FIELD_CLASSIFICATION.items()
        if FIELD_CLASS_CURRENT_TARGET_NAMED_OUTPUT in classes
    } == {"normalized_registry_output.targets"}
    assert {
        field
        for field, classes in REPORTING_PROJECTION_ROLE_CLASSIFICATION.items()
        if FIELD_CLASS_LEGACY_INPUT_ONLY_READER in classes and field.startswith("legacy_registry_yaml.")
    } == legacy_input_only
    assert set(normalize_registry(load_registry_from_data(_current_registry_data()))) == {"targets"}


def test_default_yaml_uses_only_classified_spec_weight_fields() -> None:
    actual_inventory = _default_yaml_spec_weight_field_inventory()
    unclassified_fields = set(actual_inventory) - set(SPEC_WEIGHT_FIELD_CLASSIFICATION)

    assert unclassified_fields == set()


def test_default_yaml_field_paths_are_covered_by_classification_contract() -> None:
    actual_field_examples = _default_yaml_field_path_examples()
    actual_classification = {
        field_path: _classify_default_yaml_field_path(field_path)
        for field_path in actual_field_examples
    }
    unclassified_fields = {
        field_path: sorted(actual_field_examples[field_path])
        for field_path, classification in actual_classification.items()
        if classification is None
    }

    assert unclassified_fields == {}


def test_default_yaml_classification_contract_keeps_owner_categories_distinct() -> None:
    actual_classification = {
        field_path: _classify_default_yaml_field_path(field_path)
        for field_path in _default_yaml_field_path_examples()
    }
    fields_by_class = {
        field_class: {
            field_path
            for field_path, actual_class in actual_classification.items()
            if actual_class == field_class
        }
        for field_class in {
            FIELD_CLASS_DURABLE_TARGET_FACT,
            FIELD_CLASS_INSTALL_SURFACE,
            FIELD_CLASS_TRANSITIONAL_SANDBOX_EXECUTION,
            FIELD_CLASS_HARNESS_POLICY,
            FIELD_CLASS_RUNTIME_LIMITATION,
        }
    }

    assert fields_by_class[FIELD_CLASS_TRANSITIONAL_SANDBOX_EXECUTION] == {
        "scopes.*.equivalent_install_command",
        "scopes.*.install_command",
        "scopes.*.uninstall_command",
    }
    assert fields_by_class[FIELD_CLASS_TRANSITIONAL_SANDBOX_EXECUTION].isdisjoint(
        fields_by_class[FIELD_CLASS_DURABLE_TARGET_FACT]
    )
    assert fields_by_class[FIELD_CLASS_HARNESS_POLICY] == {
        "universal_uninstall_scopes",
    }
    assert fields_by_class[FIELD_CLASS_RUNTIME_LIMITATION] == {
        "simulated_linux_layout",
        "unsupported_scopes",
        "unsupported_scopes.user",
    }
    assert "scopes.*.effects" in fields_by_class[FIELD_CLASS_INSTALL_SURFACE]
    assert "targets" in REGISTRY_FIELD_CLASSIFICATION
    assert REGISTRY_FIELD_CLASSIFICATION["targets"] == FIELD_CLASS_CURRENT_TARGET_NAMED_INPUT
    assert REGISTRY_FIELD_CLASSIFICATION["platforms"] == FIELD_CLASS_LEGACY_INPUT_ONLY_READER
    assert FIELD_CLASS_DERIVED_DEFAULT == "derived_default"


def test_top_level_registry_policy_inputs_are_not_target_facts() -> None:
    registry_data = _current_registry_data()
    actual_inventory = {
        field: {"<registry>"}
        for field in registry_data.keys() - {"schema_version", "targets"}
    }
    registry_policy_fields = set(REGISTRY_FIELD_CLASSIFICATION) - {"targets", "platforms"}
    unclassified_fields = set(actual_inventory) - registry_policy_fields

    assert unclassified_fields == set()
    assert actual_inventory == REGISTRY_FIELD_EXAMPLES
    assert (
        spec_harness_policy_inputs.TOP_LEVEL_TRANSITIONAL_POLICY_INPUT_FIELDS
        == registry_policy_fields
    )


def test_default_yaml_has_targeted_examples_for_spec_weight_field_categories() -> None:
    actual_inventory = _default_yaml_spec_weight_field_inventory()

    for field, example in SPEC_WEIGHT_FIELD_EXAMPLES.items():
        assert example in actual_inventory[field]


def test_default_registry_explicit_project_equivalent_nulls_are_meaningful_runtime_limitations(tmp_path: Any) -> None:
    for path in spec_loader.DEFAULT_REGISTRY_PATH.glob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        project_scope = data.get("scopes", {}).get("project")
        if isinstance(project_scope, dict) and project_scope.get("equivalent_install_command", "missing") is None:
            registry_dir = tmp_path / path.stem
            registry_dir.mkdir()
            (registry_dir / f"{path.stem}.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            explicit = load_registry_from_dir(registry_dir)
            explicit_project = explicit.target_spec(path.stem).scopes["project"]

            project_scope.pop("equivalent_install_command")
            (registry_dir / f"{path.stem}.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            derived = load_registry_from_dir(registry_dir)
            derived_project = derived.target_spec(path.stem).scopes["project"]

            assert explicit_project.equivalent_install_command is None
            assert derived_project.equivalent_install_command == ("graphify", path.stem, "install", "--project")
            assert normalize_registry(explicit) != normalize_registry(derived)
