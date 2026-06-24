from __future__ import annotations

from tools.install_sandbox.spec_loader import load_default_registry
from tools.install_sandbox.spec_normalize import normalize_registry


def normalize_default_registry() -> dict[str, object]:
    return normalize_registry(load_default_registry())


def test_normalized_registry_exposes_effects_alias_without_dropping_expected() -> None:
    normalized = normalize_default_registry()
    codex_project = normalized["platforms"]["codex"]["scopes"]["project"]

    assert codex_project["effects"] == codex_project["expected"]


def test_normalized_gemini_effects_match_expected_for_both_scopes() -> None:
    normalized = normalize_default_registry()
    gemini = normalized["platforms"]["gemini"]["scopes"]

    assert gemini["user"]["effects"] == gemini["user"]["expected"]
    assert gemini["project"]["effects"] == gemini["project"]["expected"]
    assert [(entry["effect_type"], entry["root"], entry["relative"]) for entry in gemini["user"]["effects"]] == [
        ("skill", "home", ".gemini/skills/graphify/SKILL.md"),
        ("text_section", "user_cwd", "GEMINI.md"),
        ("json_hooks", "user_cwd", ".gemini/settings.json"),
    ]
    assert [(entry["effect_type"], entry["root"], entry["relative"]) for entry in gemini["project"]["effects"]] == [
        ("skill", "project", ".gemini/skills/graphify/SKILL.md"),
        ("text_section", "project", "GEMINI.md"),
        ("json_hooks", "project", ".gemini/settings.json"),
    ]


def test_normalized_simple_migrated_effects_match_expected_for_both_scopes() -> None:
    normalized = normalize_default_registry()
    expected_surfaces = {
        "aider": {
            "user": [("skill", "home", ".aider/graphify/SKILL.md")],
            "project": [
                ("skill", "project", ".aider/graphify/SKILL.md"),
                ("text_section", "project", "AGENTS.md"),
            ],
        },
        "amp": {
            "user": [("skill", "home", ".config/agents/skills/graphify/SKILL.md")],
            "project": [
                ("skill", "project", ".agents/skills/graphify/SKILL.md"),
                ("text_section", "project", "AGENTS.md"),
            ],
        },
        "hermes": {
            "user": [("skill", "home", ".hermes/skills/graphify/SKILL.md")],
            "project": [
                ("skill", "project", ".hermes/skills/graphify/SKILL.md"),
                ("text_section", "project", "AGENTS.md"),
            ],
        },
        "agents": {
            "user": [("skill", "home", ".agents/skills/graphify/SKILL.md")],
            "project": [("skill", "project", ".agents/skills/graphify/SKILL.md")],
        },
        "claw": {
            "user": [("skill", "home", ".openclaw/skills/graphify/SKILL.md")],
            "project": [
                ("skill", "project", ".openclaw/skills/graphify/SKILL.md"),
                ("text_section", "project", "AGENTS.md"),
            ],
        },
        "droid": {
            "user": [("skill", "home", ".factory/skills/graphify/SKILL.md")],
            "project": [
                ("skill", "project", ".factory/skills/graphify/SKILL.md"),
                ("text_section", "project", "AGENTS.md"),
            ],
        },
        "kimi": {
            "user": [("skill", "home", ".kimi/skills/graphify/SKILL.md")],
            "project": [("skill", "project", ".kimi/skills/graphify/SKILL.md")],
        },
        "trae": {
            "user": [("skill", "home", ".trae/skills/graphify/SKILL.md")],
            "project": [
                ("skill", "project", ".trae/skills/graphify/SKILL.md"),
                ("text_section", "project", "AGENTS.md"),
            ],
        },
        "trae-cn": {
            "user": [("skill", "home", ".trae-cn/skills/graphify/SKILL.md")],
            "project": [
                ("skill", "project", ".trae-cn/skills/graphify/SKILL.md"),
                ("text_section", "project", "AGENTS.md"),
            ],
        },
    }

    for platform_name, scopes in expected_surfaces.items():
        normalized_scopes = normalized["platforms"][platform_name]["scopes"]
        for scope_name, surfaces in scopes.items():
            scope = normalized_scopes[scope_name]
            assert scope["effects"] == scope["expected"]
            assert [(entry["effect_type"], entry["root"], entry["relative"]) for entry in scope["effects"]] == surfaces


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
