from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from tools.install_sandbox import platform_specs
from tools.install_sandbox.spec_loader import SpecLoaderError, load_default_registry, load_registry_from_data
from tools.install_sandbox.spec_normalize import normalize_registry


def _skill(relative: str = ".mini/skills/graphify/SKILL.md") -> dict[str, object]:
    return {"kind": "skill", "root": "home", "relative": relative}


def _valid_data() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "platform_order": ["mini"],
        "platforms": {
            "mini": {
                "name": "mini",
                "user_skill": ".mini/skills/graphify/SKILL.md",
                "project_skill": ".mini/skills/graphify/SKILL.md",
                "scopes": {
                    "user": {
                        "expected": [_skill()],
                        "uninstall_command": None,
                        "risk_notes": [platform_specs.PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE],
                    },
                    "project": {
                        "expected": [
                            {"kind": "skill", "root": "project", "relative": ".mini/skills/graphify/SKILL.md"},
                            {"kind": "text_section", "root": "project", "relative": "AGENTS.md", "preserve_user_content": True},
                        ],
                        "equivalent_install_command": ["graphify", "mini", "install", "--project"],
                    },
                },
                "unsupported_scopes": {},
                "universal_uninstall_scopes": ["project"],
            }
        },
        "universal_uninstall_specs": [
            {
                "scenario_id": "universal-uninstall-project",
                "platform_label": "multiple",
                "scope": "project",
                "command": ["graphify", "uninstall", "--project"],
                "cwd_root": "project",
                "eligible_platform_scope": "project",
            }
        ],
        "disposable_artifact_specs": [
            {
                "scenario_id": "purge-disposable-graphify-out",
                "platform_label": "purge",
                "scope": "project",
                "command": ["graphify", "uninstall", "--purge"],
                "cwd_root": "project",
                "artifact_subdir": "uninstall-purge",
                "disposable_path_root": "project",
                "disposable_path_relative": "graphify-out",
                "seed_files": [{"relative": "graph.json", "content": "{}\n"}],
                "scope_eligibility": ["project", "both"],
                "risk_note": "synthetic disposable artifact policy",
            }
        ],
    }


def test_loader_returns_existing_registry_dataclasses_with_defaults() -> None:
    registry = load_registry_from_data(_valid_data())
    user = registry.make_scenario("mini", "user")
    project = registry.make_scenario("mini", "project")

    assert isinstance(registry, platform_specs.ScenarioRegistry)
    assert isinstance(registry.platform_spec("mini"), platform_specs.PlatformSpec)
    assert user is not None
    assert user.install_command == ("graphify", "install", "--platform", "mini")
    assert user.uninstall_command is None
    assert user.cwd_root == "user_cwd"
    assert user.allowed_roots == ("home",)
    assert user.expected[0].skill_sidecar_expectation == platform_specs.SkillSidecarExpectation()
    assert project is not None
    assert registry.install_variants(project) == (
        platform_specs.InstallCommandVariant("generic", ("graphify", "install", "--project", "--platform", "mini")),
        platform_specs.InstallCommandVariant("direct", ("graphify", "mini", "install", "--project")),
    )
    agents = next(entry for entry in project.expected if entry.relative == "AGENTS.md")
    assert agents.text_expectation.preserve_user_content
    assert agents.text_expectation.require_user_content_on_uninstall


def test_default_yaml_registry_matches_python_baseline() -> None:
    yaml_registry = load_default_registry()

    assert normalize_registry(yaml_registry) == normalize_registry(platform_specs._python_default_scenario_registry())


def _expect_invalid(data: dict[str, Any], match: str) -> None:
    with pytest.raises(SpecLoaderError, match=match):
        load_registry_from_data(data)


def test_loader_rejects_unknown_expected_root() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["expected"][0]["root"] = "repo_mount"

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


def test_loader_rejects_skill_file_without_sidecar_kind() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["expected"][0]["kind"] = "file"

    _expect_invalid(data, "SKILL.md effects must declare skill sidecar policy")


def test_loader_rejects_unknown_effect_kind() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["expected"][0]["kind"] = "mystery"

    _expect_invalid(data, "unknown effect kind")


def test_loader_rejects_incomplete_json_expectations() -> None:
    missing_hook = _valid_data()
    missing_hook["platforms"]["mini"]["scopes"]["user"]["expected"] = [
        {"kind": "json_hooks", "root": "home", "relative": ".mini/settings.json", "schema_name": "mini_settings", "hooks": [{"event": "PreToolUse", "matcher": "Bash"}]}
    ]
    _expect_invalid(missing_hook, "detail_name")

    missing_plugin = _valid_data()
    missing_plugin["platforms"]["mini"]["scopes"]["user"]["expected"] = [
        {"kind": "json_plugin", "root": "home", "relative": ".mini/config.json", "schema_name": "mini_config"}
    ]
    _expect_invalid(missing_plugin, "plugin_relative")


def test_loader_rejects_unknown_structured_risk_note() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["risk_notes"] = ["unknown_structured_note"]

    _expect_invalid(data, "unknown structured risk note")


def test_loader_rejects_platform_order_mismatch() -> None:
    data = deepcopy(_valid_data())
    data["platform_order"] = ["other"]

    _expect_invalid(data, "declared platform order")
