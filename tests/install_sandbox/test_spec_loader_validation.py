from __future__ import annotations

import pytest

from tests.install_sandbox.install_target_test_support import (
    expect_invalid_registry as _expect_invalid,
    valid_registry_data as _valid_data,
)
from tools.install_sandbox import validation_plan
from tools.install_sandbox.sandbox_roots import DEFAULT_SANDBOX_ROOT_REGISTRY
from tools.install_sandbox.registry import spec_harness_policy_inputs, spec_loader, spec_target_facts
from tools.install_sandbox.registry.spec_loader import SpecLoaderError, load_registry_from_data


def test_loader_root_validation_uses_install_surface_root_vocabulary() -> None:
    assert DEFAULT_SANDBOX_ROOT_REGISTRY.install_surface_root_names() == {"home", "project", "user_cwd"}


def test_loader_root_validation_also_uses_all_sandbox_roots_for_harness_policy() -> None:
    all_root_names = DEFAULT_SANDBOX_ROOT_REGISTRY.root_names()

    assert "repo_mount" in all_root_names - DEFAULT_SANDBOX_ROOT_REGISTRY.install_surface_root_names()
    assert DEFAULT_SANDBOX_ROOT_REGISTRY.policy_cwd_root_names() == all_root_names


def test_loader_parse_path_consumes_root_name_role_apis(monkeypatch) -> None:
    class RoleOnlyRegistry:
        def __init__(self) -> None:
            self.root_name_calls = 0
            self.policy_cwd_root_name_calls = 0

        def root_names(self) -> set[str]:
            self.root_name_calls += 1
            return {"home", "project", "user_cwd", "repo_mount"}

        def policy_cwd_root_names(self) -> set[str]:
            self.policy_cwd_root_name_calls += 1
            return {"home", "project", "user_cwd", "repo_mount"}

    root_registry = RoleOnlyRegistry()
    monkeypatch.setattr(spec_loader, "DEFAULT_SANDBOX_ROOT_REGISTRY", root_registry)
    monkeypatch.setattr(spec_target_facts, "DEFAULT_SANDBOX_ROOT_REGISTRY", root_registry)
    monkeypatch.setattr(spec_harness_policy_inputs, "DEFAULT_SANDBOX_ROOT_REGISTRY", root_registry)

    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["project"]["cwd_root"] = "repo_mount"
    data["universal_uninstall_specs"] = [
        {
            "scenario_id": "repo-mount-uninstall",
            "platform_label": "repo-mounted",
            "scope": "project",
            "command": ["graphify", "uninstall", "--project"],
            "cwd_root": "repo_mount",
            "eligible_platform_scope": "project",
        }
    ]
    data["disposable_artifact_specs"][0]["cwd_root"] = "repo_mount"

    registry = load_registry_from_data(data)

    assert registry.target_names == ["mini"]
    assert registry.make_scenario("mini", "project").cwd_root == "repo_mount"
    assert registry.universal_uninstall_specs[0].eligible_target_scope == "project"
    assert root_registry.root_name_calls == 1
    assert root_registry.policy_cwd_root_name_calls == 3


def test_loader_accepts_non_surface_root_for_policy_cwd_root() -> None:
    data = _valid_data()
    data["universal_uninstall_specs"] = [
        {
            "scenario_id": "repo-mount-uninstall",
            "platform_label": "repo-mounted",
            "scope": "project",
            "command": ["graphify", "uninstall", "--project"],
            "cwd_root": "repo_mount",
            "eligible_platform_scope": "project",
        }
    ]
    data["disposable_artifact_specs"][0]["cwd_root"] = "repo_mount"

    registry = load_registry_from_data(data)

    assert registry.universal_uninstall_specs[0].cwd_root == "repo_mount"
    assert registry.universal_uninstall_specs[0].eligible_target_scope == "project"
    assert registry.disposable_artifact_specs[0].cwd_root == "repo_mount"


def test_loader_splits_catalog_target_root_and_policy_root_validation(monkeypatch) -> None:
    calls: list[tuple[str, set[str]]] = []
    original_validate_target_roots = spec_loader.ScenarioRegistry.validate_target_roots
    original_validate_policy_owned_roots = validation_plan.validate_policy_owned_roots

    def validate_target_roots(self, declared_roots):
        calls.append(("target", set(declared_roots)))
        original_validate_target_roots(self, declared_roots)

    def validate_policy_owned_roots(registry, policy, declared_roots):
        calls.append(("policy", set(declared_roots)))
        original_validate_policy_owned_roots(registry, policy, declared_roots)

    monkeypatch.setattr(spec_loader.ScenarioRegistry, "validate_target_roots", validate_target_roots)
    monkeypatch.setattr(validation_plan, "validate_policy_owned_roots", validate_policy_owned_roots)

    registry = load_registry_from_data(_valid_data())

    assert registry.target_names == ["mini"]
    assert calls == [
        ("target", DEFAULT_SANDBOX_ROOT_REGISTRY.root_names()),
        ("policy", DEFAULT_SANDBOX_ROOT_REGISTRY.root_names()),
    ]


def test_loader_rejects_unknown_policy_cwd_root_before_catalog_validation() -> None:
    data = _valid_data()
    data["universal_uninstall_specs"] = [
        {
            "scenario_id": "unknown-root-uninstall",
            "platform_label": "unknown-root",
            "scope": "project",
            "command": ["graphify", "uninstall", "--project"],
            "cwd_root": "missing_root",
            "eligible_platform_scope": "project",
        }
    ]

    _expect_invalid(data, "unknown cwd root: missing_root")


def test_loader_rejects_unknown_expected_root() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["effects"][0]["root"] = "repo_mount"

    _expect_invalid(data, "unknown expected root")


def test_loader_rejects_non_surface_root_for_disposable_path_root() -> None:
    data = _valid_data()
    data["disposable_artifact_specs"][0]["disposable_path_root"] = "repo_mount"

    _expect_invalid(data, "unknown expected root")


def test_loader_rejects_platform_key_name_mismatch() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["name"] = "other"

    _expect_invalid(data, "platform key/name mismatch")


def test_loader_rejects_missing_or_conflicting_scope_declarations() -> None:
    missing = _valid_data()
    missing["platforms"]["mini"]["scopes"].pop("project")
    _expect_invalid(missing, "exactly one runnable scope")

    conflicting = _valid_data()
    conflicting["platforms"]["mini"]["unsupported_scopes"]["project"] = "unsupported"
    _expect_invalid(conflicting, "exactly one runnable scope")


def test_loader_rejects_invalid_commands() -> None:
    empty = _valid_data()
    empty["platforms"]["mini"]["scopes"]["user"]["install_command"] = []
    _expect_invalid(empty, "expected non-empty list")

    non_string = _valid_data()
    non_string["platforms"]["mini"]["scopes"]["user"]["install_command"] = ["tool", 3]
    _expect_invalid(non_string, "expected non-empty string")


def test_loader_rejects_invalid_relative_paths() -> None:
    absolute = _valid_data()
    absolute["platforms"]["mini"]["scopes"]["user"]["effects"][0]["relative"] = "/tmp/SKILL.md"
    _expect_invalid(absolute, "must not be absolute")

    escaping = _valid_data()
    escaping["platforms"]["mini"]["scopes"]["user"]["effects"][0]["relative"] = "../SKILL.md"
    _expect_invalid(escaping, "must not escape")


def test_loader_rejects_duplicate_install_variant_labels() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["project"]["install_variants"] = [
        {"label": "same", "command": ["tool", "a"]},
        {"label": "same", "command": ["tool", "b"]},
    ]

    _expect_invalid(data, "duplicate install variant label")


def test_loader_rejects_invalid_scope_names() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["both"] = data["platforms"]["mini"]["scopes"].pop("project")

    _expect_invalid(data, "invalid platform scope: both")


def test_loader_rejects_unknown_structured_risk_note() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["risk_notes"] = ["unknown_structured_note"]

    _expect_invalid(data, "unknown structured risk note")


def test_loader_rejects_unknown_top_level_registry_fields() -> None:
    data = _valid_data()
    data["target_runtime_validation_policies"] = {"typo": {}}

    with pytest.raises(SpecLoaderError, match=r"<data>: unknown field: target_runtime_validation_policies"):
        load_registry_from_data(data)


@pytest.mark.parametrize(
    ("mutate", "field_name"),
    [
        (
            lambda data: data["platforms"]["mini"].update({"unknown_target_fact": True}),
            "unknown_target_fact",
        ),
        (
            lambda data: data["platforms"]["mini"]["scopes"]["user"].update({"unknown_scope_fact": True}),
            "unknown_scope_fact",
        ),
        (
            lambda data: data["platforms"]["mini"]["scopes"]["user"]["effects"][0].update({"unknown_effect_fact": True}),
            "unknown_effect_fact",
        ),
        (
            lambda data: data["platforms"]["mini"]["scopes"]["user"].update(
                {
                    "generated_file_expectation": {
                        "relative_substrings": ["graphify"],
                        "unknown_generated_fact": True,
                    }
                }
            ),
            "unknown_generated_fact",
        ),
        (
            lambda data: data["platforms"]["mini"].update(
                {"reference_bundles": [{"name": "mini", "unknown_reference_fact": True}]}
            ),
            "unknown_reference_fact",
        ),
        (
            lambda data: data["platforms"]["mini"].update(
                {
                    "target_runtime_validation": [
                        {
                            "section_title": "Runtime",
                            "status": "declared",
                            "strategy": "manual",
                            "targets": ["runtime"],
                            "notes": ["external"],
                            "unknown_runtime_fact": True,
                        }
                    ]
                }
            ),
            "unknown_runtime_fact",
        ),
    ],
)
def test_loader_rejects_unknown_target_fact_fields(mutate, field_name: str) -> None:
    data = _valid_data()
    mutate(data)

    with pytest.raises(SpecLoaderError, match=rf"unknown field: {field_name}"):
        load_registry_from_data(data)


def test_loader_rejects_unknown_json_hook_fields() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["effects"] = [
        {
            "kind": "json_hooks",
            "root": "home",
            "relative": ".mini/settings.json",
            "schema_name": "mini_settings",
            "hooks": [
                {
                    "event": "PreToolUse",
                    "matcher": "Bash",
                    "required_fragments": ["graphify"],
                    "unknown_hook_fact": True,
                }
            ],
        }
    ]

    with pytest.raises(SpecLoaderError, match=r"unknown field: unknown_hook_fact"):
        load_registry_from_data(data)


def test_loader_rejects_unknown_json_plugin_fields() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["effects"] = [
        {
            "kind": "file",
            "root": "home",
            "relative": ".mini/plugins/graphify.js",
        },
        {
            "kind": "json_plugin",
            "root": "home",
            "relative": ".mini/config.json",
            "schema_name": "mini_config",
            "unknown_plugin_fact": True,
        },
    ]

    with pytest.raises(SpecLoaderError, match=r"unknown field: unknown_plugin_fact"):
        load_registry_from_data(data)


@pytest.mark.parametrize(
    ("mutate", "field_name"),
    [
        (
            lambda data: data["universal_uninstall_specs"].append(
                {
                    "scenario_id": "repo-mount-uninstall",
                    "platform_label": "repo-mounted",
                    "scope": "project",
                    "command": ["graphify", "uninstall", "--project"],
                    "cwd_root": "repo_mount",
                    "eligible_platform_scope": "project",
                    "unknown_universal_policy": True,
                }
            ),
            "unknown_universal_policy",
        ),
        (
            lambda data: data["disposable_artifact_specs"][0].update({"unknown_disposable_policy": True}),
            "unknown_disposable_policy",
        ),
        (
            lambda data: data["disposable_artifact_specs"][0]["seed_files"][0].update({"unknown_seed_policy": True}),
            "unknown_seed_policy",
        ),
    ],
)
def test_loader_rejects_unknown_harness_policy_input_fields(mutate, field_name: str) -> None:
    data = _valid_data()
    mutate(data)

    with pytest.raises(SpecLoaderError, match=rf"unknown field: {field_name}"):
        load_registry_from_data(data)
