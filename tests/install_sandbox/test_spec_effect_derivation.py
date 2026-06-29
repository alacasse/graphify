from __future__ import annotations

from tools.install_sandbox.registry.spec_loader import load_registry_from_data
from tools.install_sandbox.surfaces import install_surface_models

from tests.install_sandbox.install_target_test_support import (
    expect_invalid_registry as _expect_invalid,
    skill_effect_data as _skill,
    valid_registry_data as _valid_data,
)


def test_loader_derives_skill_sidecar_kind_and_rejects_explicit_wrong_kind() -> None:
    derived = load_registry_from_data(_valid_data()).make_scenario("mini", "user")
    assert derived is not None
    assert isinstance(derived.expected[0], install_surface_models.SkillEffect)
    assert derived.expected[0].skill_sidecar_expectation == install_surface_models.SkillSidecarExpectation()

    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["expected"][0]["kind"] = "file"

    _expect_invalid(data, "SKILL.md effects must use kind: skill or omit kind")


def test_loader_derives_plain_file_effect_from_non_skill_relative_path() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["expected"] = [
        {"root": "home", "relative": ".mini/config.toml", "remove_on_uninstall": False}
    ]

    user = load_registry_from_data(data).make_scenario("mini", "user")

    assert user is not None
    effect = user.expected[0]
    assert isinstance(effect, install_surface_models.FileEffect)
    assert not isinstance(effect, install_surface_models.SkillEffect)
    assert effect.root == "home"
    assert effect.relative == ".mini/config.toml"
    assert effect.content_kind == "text"
    assert effect.marker is None
    assert effect.remove_on_uninstall is False


def test_loader_rejects_removed_plugin_file_kind() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["expected"][0] = {
        "kind": "plugin_file",
        "root": "home",
        "relative": ".mini/plugins/graphify.js",
    }

    _expect_invalid(data, "unknown effect kind")


def test_loader_rejects_unknown_effect_kind() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["scopes"]["user"]["expected"][0]["kind"] = "mystery"

    _expect_invalid(data, "unknown effect kind")


def test_loader_derives_json_hook_detail_names() -> None:
    single = _valid_data()
    single["platforms"]["mini"]["scopes"]["user"]["expected"] = [
        {
            "kind": "json_hooks",
            "root": "home",
            "relative": ".mini/settings.json",
            "schema_name": "mini_settings",
            "hooks": [{"event": "PreToolUse", "matcher": "Bash"}],
        }
    ]
    single_scenario = load_registry_from_data(single).make_scenario("mini", "user")
    assert single_scenario is not None
    assert isinstance(single_scenario.expected[0], install_surface_models.JsonHooksEffect)
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
    assert isinstance(
        next(entry for entry in scenario.expected if entry.relative == ".mini/plugins/graphify.js"),
        install_surface_models.FileEffect,
    )
    config = next(entry for entry in scenario.expected if entry.relative == ".mini/config.json")
    assert isinstance(config, install_surface_models.JsonPluginEffect)
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
