from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
import yaml

from tools.install_sandbox import platform_specs, spec_loader
from tools.install_sandbox.spec_loader import SpecLoaderError, load_default_registry, load_registry_from_data


def _skill(relative: str = ".mini/skills/graphify/SKILL.md") -> dict[str, object]:
    return {"root": "home", "relative": relative}


def _valid_data() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "platform_order": ["mini"],
        "platforms": {
            "mini": {
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
                            {"root": "project", "relative": ".mini/skills/graphify/SKILL.md"},
                            {"kind": "text_section", "root": "project", "relative": "AGENTS.md"},
                        ],
                        "equivalent_install_command": ["graphify", "mini", "install", "--project"],
                    },
                },
                "unsupported_scopes": {},
                "universal_uninstall_scopes": ["project"],
            }
        },
        "universal_uninstall_specs": ["project"],
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
    assert registry.universal_uninstall_specs[0].scenario_id == "universal-uninstall-project"


def _default_registry_yaml() -> dict[str, Any]:
    with spec_loader.DEFAULT_REGISTRY_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_default_registry_loads_and_returns_scenario_registry() -> None:
    registry = load_default_registry()

    assert isinstance(registry, platform_specs.ScenarioRegistry)
    assert registry.specs
    assert registry.universal_uninstall_specs
    assert registry.disposable_artifact_specs


def test_default_registry_declares_schema_version_one() -> None:
    assert _default_registry_yaml()["schema_version"] == spec_loader.SCHEMA_VERSION == 1


def test_default_registry_platform_order_matches_loaded_platform_keys() -> None:
    registry = load_default_registry()

    assert _default_registry_yaml()["platform_order"] == registry.platform_names


def test_default_registry_every_scope_is_runnable_or_explained() -> None:
    registry = load_default_registry()

    for platform_name in registry.platform_names:
        for scope in ("user", "project"):
            runnable = registry.make_scenario(platform_name, scope) is not None
            explained = registry.unsupported_scope_reason(platform_name, scope) is not None
            assert runnable != explained, f"{platform_name}/{scope} must be runnable xor explained"


def test_default_registry_skill_effects_declare_sidecar_expectation() -> None:
    registry = load_default_registry()

    for platform_name in registry.platform_names:
        for scope in ("user", "project"):
            scenario = registry.make_scenario(platform_name, scope)
            if scenario is None:
                continue
            for entry in scenario.expected:
                if entry.relative.endswith("SKILL.md"):
                    assert entry.skill_sidecar_expectation is not None, f"{platform_name}/{scope}/{entry.relative}"


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


def test_loader_derives_skill_sidecar_kind_and_rejects_explicit_wrong_kind() -> None:
    derived = load_registry_from_data(_valid_data()).make_scenario("mini", "user")
    assert derived is not None
    assert derived.expected[0].skill_sidecar_expectation == platform_specs.SkillSidecarExpectation()

    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["expected"][0]["kind"] = "file"

    _expect_invalid(data, "SKILL.md effects must use kind: skill or omit kind")


def test_loader_rejects_removed_plugin_file_kind() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["expected"][0] = {"kind": "plugin_file", "root": "home", "relative": ".mini/plugins/graphify.js"}

    _expect_invalid(data, "unknown effect kind")


def test_loader_rejects_unknown_effect_kind() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["expected"][0]["kind"] = "mystery"

    _expect_invalid(data, "unknown effect kind")


def test_loader_derives_json_hook_detail_names() -> None:
    single = _valid_data()
    single["platforms"]["mini"]["scopes"]["user"]["expected"] = [
        {"kind": "json_hooks", "root": "home", "relative": ".mini/settings.json", "schema_name": "mini_settings", "hooks": [{"event": "PreToolUse", "matcher": "Bash"}]}
    ]
    single_scenario = load_registry_from_data(single).make_scenario("mini", "user")
    assert single_scenario is not None
    single_json = single_scenario.expected[0].json_expectation
    assert single_json is not None
    assert single_json.hooks[0].detail_name == "graphify_hook_present"

    multiple = _valid_data()
    multiple["platforms"]["mini"]["scopes"]["user"]["expected"] = [
        {
            "kind": "json_hooks",
            "root": "home",
            "relative": ".mini/settings.json",
            "schema_name": "mini_settings",
            "hooks": [
                {"event": "PreToolUse", "matcher": "Bash"},
                {"event": "PreToolUse", "matcher": "Read|Glob"},
            ],
        }
    ]
    multiple_scenario = load_registry_from_data(multiple).make_scenario("mini", "user")
    assert multiple_scenario is not None
    multiple_json = multiple_scenario.expected[0].json_expectation
    assert multiple_json is not None
    assert [hook.detail_name for hook in multiple_json.hooks] == ["bash_hook_present", "read_glob_hook_present"]


def test_loader_derives_json_plugin_relative_from_paired_payload() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["expected"] = [
        _skill(),
        {"root": "home", "relative": ".mini/plugins/graphify.js"},
        {"kind": "json_plugin", "root": "home", "relative": ".mini/config.json", "schema_name": "mini_config"},
    ]

    scenario = load_registry_from_data(data).make_scenario("mini", "user")

    assert scenario is not None
    config = next(entry for entry in scenario.expected if entry.relative == ".mini/config.json")
    assert config.json_expectation is not None
    assert config.json_expectation.plugin is not None
    assert config.json_expectation.plugin.expected_entry == ".mini/plugins/graphify.js"


def test_loader_rejects_unpaired_or_ambiguous_json_plugin_payloads() -> None:
    missing_plugin = _valid_data()
    missing_plugin["platforms"]["mini"]["scopes"]["user"]["expected"] = [
        _skill(),
        {"kind": "json_plugin", "root": "home", "relative": ".mini/config.json", "schema_name": "mini_config"},
    ]
    _expect_invalid(missing_plugin, "one paired JavaScript plugin payload")

    ambiguous_plugin = _valid_data()
    ambiguous_plugin["platforms"]["mini"]["scopes"]["user"]["expected"] = [
        _skill(),
        {"root": "home", "relative": ".mini/plugins/graphify.js"},
        {"root": "home", "relative": ".mini/plugins/extra.js"},
        {"kind": "json_plugin", "root": "home", "relative": ".mini/config.json", "schema_name": "mini_config"},
    ]
    _expect_invalid(ambiguous_plugin, "ambiguous paired JavaScript plugin payloads")


def test_loader_derives_text_section_policies() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["expected"] = [
        _skill(),
        {"kind": "text_section", "root": "home", "relative": ".claude/CLAUDE.md", "marker": "# graphify"},
    ]

    user = load_registry_from_data(data).make_scenario("mini", "user")

    assert user is not None
    instruction = next(entry for entry in user.expected if entry.relative == ".claude/CLAUDE.md")
    assert instruction.text_expectation.preserve_user_content
    assert not instruction.text_expectation.repair_stale_graphify_section
    assert not instruction.remove_on_uninstall


def test_loader_derives_scope_locality_and_simulated_notes() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["simulated_linux_layout"] = True
    data["platforms"]["mini"]["scopes"]["user"]["expected"].append({"root": "user_cwd", "relative": "GEMINI.md", "kind": "text_section"})

    user = load_registry_from_data(data).make_scenario("mini", "user")

    assert user is not None
    assert user.allowed_roots == ("home", "project", "user_cwd")
    assert user.risk_notes == (
        platform_specs.MIXED_SCOPE_PROJECT_WIRING_NOTE,
        platform_specs.PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,
        platform_specs.SIMULATED_LINUX_LAYOUT_NOTE,
    )


def test_loader_attaches_shared_runtime_validation_to_simulated_platforms() -> None:
    data = _valid_data()
    data["target_runtime_validation_policies"] = {
        "simulated_linux_layout": {
            "section_title": "Windows Validation",
            "status": "payload_consistency_only",
            "strategy": "payload check only",
            "targets": ["windows payload"],
            "notes": ["runtime validation is external"],
        }
    }
    data["platforms"]["mini"]["simulated_linux_layout"] = True

    spec = load_registry_from_data(data).platform_spec("mini")

    assert spec.target_runtime_validation == (
        platform_specs.TargetRuntimeValidationSpec(
            section_title="Windows Validation",
            status="payload_consistency_only",
            strategy="payload check only",
            targets=("windows payload",),
            notes=("runtime validation is external",),
        ),
    )


def test_loader_rejects_unknown_runtime_validation_policy() -> None:
    data = _valid_data()
    data["target_runtime_validation_policies"] = {"typo": {}}

    _expect_invalid(data, "unknown runtime validation policy")


def test_loader_rejects_unknown_structured_risk_note() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["risk_notes"] = ["unknown_structured_note"]

    _expect_invalid(data, "unknown structured risk note")


def test_loader_rejects_platform_order_mismatch() -> None:
    data = deepcopy(_valid_data())
    data["platform_order"] = ["other"]

    _expect_invalid(data, "declared platform order")
