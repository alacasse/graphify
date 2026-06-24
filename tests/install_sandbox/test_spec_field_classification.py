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


def test_default_registry_spec_weight_fields_are_classified() -> None:
    candidate_fields = {
        "install_command",
        "uninstall_command",
        "equivalent_install_command",
        "universal_uninstall_scopes",
        "unsupported_scopes",
        "simulated_linux_layout",
        "reference_bundles",
        "target_runtime_validation",
    }
    expected_classification = {
        "install_command": FIELD_CLASS_TRANSITIONAL_SANDBOX_EXECUTION,
        "uninstall_command": FIELD_CLASS_TRANSITIONAL_SANDBOX_EXECUTION,
        "equivalent_install_command": FIELD_CLASS_TRANSITIONAL_SANDBOX_EXECUTION,
        "universal_uninstall_scopes": FIELD_CLASS_HARNESS_POLICY,
        "unsupported_scopes": FIELD_CLASS_RUNTIME_LIMITATION,
        "simulated_linux_layout": FIELD_CLASS_RUNTIME_LIMITATION,
        "reference_bundles": FIELD_CLASS_DURABLE_TARGET_FACT,
        "target_runtime_validation": FIELD_CLASS_RUNTIME_LIMITATION,
    }
    expected_inventory = {
        "install_command": {
            "antigravity.user",
            "cursor.project",
            "kilo.project",
            "kiro.project",
            "vscode.project",
            "vscode.user",
        },
        "uninstall_command": {
            "agents.user",
            "aider.user",
            "amp.user",
            "antigravity-windows.user",
            "antigravity.user",
            "claude.user",
            "claw.user",
            "codebuddy.user",
            "codex.user",
            "copilot.user",
            "cursor.project",
            "devin.user",
            "droid.user",
            "gemini.user",
            "hermes.user",
            "kilo.project",
            "kilo.user",
            "kimi.user",
            "kiro.project",
            "kiro.user",
            "opencode.user",
            "pi.user",
            "trae-cn.user",
            "trae.user",
            "vscode.project",
            "vscode.user",
            "windows.user",
        },
        "equivalent_install_command": {
            "antigravity-windows.project",
            "antigravity.project",
            "codebuddy.project",
            "copilot.user",
            "cursor.project",
            "devin.project",
            "devin.user",
            "gemini.user",
            "kimi.project",
            "kiro.project",
            "pi.project",
            "pi.user",
            "windows.project",
        },
        "universal_uninstall_scopes": {
            "antigravity",
            "claude",
            "codebuddy",
            "codex",
            "cursor",
            "devin",
            "gemini",
            "vscode",
        },
        "unsupported_scopes": {"cursor"},
        "simulated_linux_layout": {"antigravity-windows", "windows"},
        "reference_bundles": {"vscode"},
        "target_runtime_validation": set(),
    }
    actual_inventory = {field: set() for field in candidate_fields}

    for path in spec_loader.DEFAULT_REGISTRY_PATH.glob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for field in candidate_fields & data.keys():
            actual_inventory[field].add(path.stem)
        for scope_name, scope_data in data.get("scopes", {}).items():
            for field in candidate_fields & scope_data.keys():
                actual_inventory[field].add(f"{path.stem}.{scope_name}")

    assert actual_inventory == expected_inventory
    assert set(expected_classification) == candidate_fields
    assert expected_classification["universal_uninstall_scopes"] == FIELD_CLASS_HARNESS_POLICY


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
