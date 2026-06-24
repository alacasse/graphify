from __future__ import annotations

from copy import deepcopy
from typing import Any

import yaml

from tools.install_sandbox import spec_loader
from tools.install_sandbox.spec_loader import load_registry_from_data, load_registry_from_dir
from tools.install_sandbox.spec_normalize import normalize_registry

from tests.install_sandbox.install_target_test_support import valid_registry_data, write_registry_dir


FIELD_CLASS_DURABLE_TARGET_FACT = "durable_target_fact"
FIELD_CLASS_TRANSITIONAL_SANDBOX_EXECUTION = "transitional_sandbox_execution_data"
FIELD_CLASS_DERIVED_DEFAULT = "derived_default"
FIELD_CLASS_HARNESS_POLICY = "harness_policy"
FIELD_CLASS_RUNTIME_LIMITATION = "runtime_limitation"

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

SPEC_WEIGHT_FIELD_EXAMPLES = {
    "install_command": "vscode.user",
    "uninstall_command": "codex.user",
    "equivalent_install_command": "cursor.project",
    "universal_uninstall_scopes": "codex",
    "unsupported_scopes": "cursor",
    "simulated_linux_layout": "windows",
    "reference_bundles": "vscode",
}

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


def test_loader_derives_conventional_product_yaml_equivalent_to_explicit_fixture() -> None:
    explicit = valid_registry_data()
    conventional = deepcopy(valid_registry_data())
    mini = conventional["platforms"]["mini"]
    mini.pop("user_skill")
    mini.pop("project_skill")
    mini["scopes"]["user"].pop("risk_notes")
    mini["scopes"]["project"].pop("equivalent_install_command")

    assert FIELD_CLASS_DERIVED_DEFAULT == "derived_default"
    assert normalize_registry(load_registry_from_data(conventional)) == normalize_registry(load_registry_from_data(explicit))


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


def test_default_yaml_uses_only_classified_spec_weight_fields() -> None:
    actual_inventory = _default_yaml_spec_weight_field_inventory()
    unclassified_fields = set(actual_inventory) - set(SPEC_WEIGHT_FIELD_CLASSIFICATION)

    assert unclassified_fields == set()


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
            write_registry_dir(registry_dir, {"platforms": {path.stem: data}})
            explicit = load_registry_from_dir(registry_dir)
            explicit_project = explicit.platform_spec(path.stem).scopes["project"]

            project_scope.pop("equivalent_install_command")
            write_registry_dir(registry_dir, {"platforms": {path.stem: data}})
            derived = load_registry_from_dir(registry_dir)
            derived_project = derived.platform_spec(path.stem).scopes["project"]

            assert explicit_project.equivalent_install_command is None
            assert derived_project.equivalent_install_command == ("graphify", path.stem, "install", "--project")
            assert normalize_registry(explicit) != normalize_registry(derived)
