from __future__ import annotations

from tests.install_sandbox.install_target_test_support import (
    expect_invalid_registry as _expect_invalid,
    valid_registry_data as _valid_data,
)
from tools.install_sandbox.harness_specs import DEFAULT_SANDBOX_ROOT_REGISTRY
from tools.install_sandbox.registry.spec_loader import load_registry_from_data


def test_loader_root_validation_uses_install_surface_root_vocabulary() -> None:
    assert DEFAULT_SANDBOX_ROOT_REGISTRY.install_surface_root_names() == {"home", "project", "user_cwd"}
    assert DEFAULT_SANDBOX_ROOT_REGISTRY.declared_expected_root_names() == DEFAULT_SANDBOX_ROOT_REGISTRY.install_surface_root_names()


def test_loader_root_validation_also_uses_all_sandbox_roots_for_harness_policy() -> None:
    all_root_names = {root.name for root in DEFAULT_SANDBOX_ROOT_REGISTRY.roots}

    assert "repo_mount" in all_root_names - DEFAULT_SANDBOX_ROOT_REGISTRY.install_surface_root_names()


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
    assert registry.disposable_artifact_specs[0].cwd_root == "repo_mount"


def test_loader_rejects_unknown_expected_root() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["expected"][0]["root"] = "repo_mount"

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
    absolute["platforms"]["mini"]["scopes"]["user"]["expected"][0]["relative"] = "/tmp/SKILL.md"
    _expect_invalid(absolute, "must not be absolute")

    escaping = _valid_data()
    escaping["platforms"]["mini"]["scopes"]["user"]["expected"][0]["relative"] = "../SKILL.md"
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
