from __future__ import annotations

from tests.install_sandbox.install_target_test_support import normalize_default_registry


def test_normalized_hook_migrated_effects_match_expected_for_runnable_scopes() -> None:
    normalized = normalize_default_registry()
    expected_hooks = {
        "codex": {
            "project": [
                {
                    "event": "PreToolUse",
                    "matcher": "Bash",
                    "detail_name": "graphify_hook_present",
                    "required_fragments": ["graphify", "hook-check"],
                },
            ],
        },
        "codebuddy": {
            "user": [
                {
                    "event": "PreToolUse",
                    "matcher": "Bash",
                    "detail_name": "bash_hook_present",
                    "required_fragments": ["graphify"],
                },
                {
                    "event": "PreToolUse",
                    "matcher": "Read|Glob",
                    "detail_name": "read_glob_hook_present",
                    "required_fragments": ["graphify"],
                },
            ],
            "project": [
                {
                    "event": "PreToolUse",
                    "matcher": "Bash",
                    "detail_name": "bash_hook_present",
                    "required_fragments": ["graphify"],
                },
                {
                    "event": "PreToolUse",
                    "matcher": "Read|Glob",
                    "detail_name": "read_glob_hook_present",
                    "required_fragments": ["graphify"],
                },
            ],
        },
    }

    for platform_name, scopes in expected_hooks.items():
        normalized_scopes = normalized["platforms"][platform_name]["scopes"]
        for scope_name, hooks in scopes.items():
            scope = normalized_scopes[scope_name]
            json_effect = next(entry for entry in scope["effects"] if entry["effect_type"] == "json_hooks")
            assert scope["effects"] == scope["expected"]
            assert json_effect["json_expectation"]["hooks"] == hooks


def test_normalized_plugin_migrated_effects_match_expected_entries() -> None:
    normalized = normalize_default_registry()
    expected_plugins = {
        "kilo": {
            "project": {
                "config": ".kilo/kilo.json",
                "entry": ".kilo/plugins/graphify.js",
                "schema": "kilo_config",
                "allow_file_uri": True,
            },
        },
        "opencode": {
            "user": {
                "config": ".opencode/opencode.json",
                "entry": ".opencode/plugins/graphify.js",
                "schema": "opencode_config",
                "allow_file_uri": False,
            },
            "project": {
                "config": ".opencode/opencode.json",
                "entry": ".opencode/plugins/graphify.js",
                "schema": "opencode_config",
                "allow_file_uri": False,
            },
        },
    }

    for platform_name, scopes in expected_plugins.items():
        normalized_scopes = normalized["platforms"][platform_name]["scopes"]
        for scope_name, plugin in scopes.items():
            scope = normalized_scopes[scope_name]
            json_effect = next(
                entry
                for entry in scope["effects"]
                if entry["effect_type"] == "json_plugin" and entry["relative"] == plugin["config"]
            )

            assert scope["effects"] == scope["expected"]
            assert json_effect["json_expectation"]["schema_name"] == plugin["schema"]
            assert json_effect["json_expectation"]["plugin"]["expected_entry"] == plugin["entry"]
            assert json_effect["json_expectation"]["plugin"]["allow_file_uri"] is plugin["allow_file_uri"]
