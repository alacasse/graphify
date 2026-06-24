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


def test_normalized_command_migrated_effects_match_expected_and_commands() -> None:
    normalized = normalize_default_registry()
    expected = {
        "copilot": {
            "user": {
                "install": ["graphify", "install", "--platform", "copilot"],
                "uninstall": ["graphify", "copilot", "uninstall"],
                "equivalent": ["graphify", "copilot", "install"],
                "surfaces": [("skill", "home", ".copilot/skills/graphify/SKILL.md")],
            },
            "project": {
                "install": ["graphify", "install", "--project", "--platform", "copilot"],
                "uninstall": ["graphify", "uninstall", "--project", "--platform", "copilot"],
                "equivalent": ["graphify", "copilot", "install", "--project"],
                "surfaces": [("skill", "project", ".copilot/skills/graphify/SKILL.md")],
            },
        },
        "cursor": {
            "project": {
                "install": ["graphify", "cursor", "install"],
                "uninstall": ["graphify", "cursor", "uninstall"],
                "equivalent": ["graphify", "install", "--project", "--platform", "cursor"],
                "surfaces": [("file", "project", ".cursor/rules/graphify.mdc")],
            },
        },
        "devin": {
            "user": {
                "install": ["graphify", "install", "--platform", "devin"],
                "uninstall": ["graphify", "devin", "uninstall"],
                "equivalent": ["graphify", "devin", "install"],
                "surfaces": [("skill", "home", ".config/devin/skills/graphify/SKILL.md")],
            },
            "project": {
                "install": ["graphify", "install", "--project", "--platform", "devin"],
                "uninstall": ["graphify", "uninstall", "--project", "--platform", "devin"],
                "equivalent": ["graphify", "devin", "install", "--project"],
                "surfaces": [
                    ("skill", "project", ".devin/skills/graphify/SKILL.md"),
                    ("file", "project", ".windsurf/rules/graphify.md"),
                ],
            },
        },
        "kiro": {
            "user": {
                "install": ["graphify", "install", "--platform", "kiro"],
                "uninstall": None,
                "equivalent": None,
                "surfaces": [("skill", "home", ".kiro/skills/graphify/SKILL.md")],
            },
            "project": {
                "install": ["graphify", "kiro", "install"],
                "uninstall": ["graphify", "kiro", "uninstall"],
                "equivalent": ["graphify", "install", "--project", "--platform", "kiro"],
                "surfaces": [
                    ("skill", "project", ".kiro/skills/graphify/SKILL.md"),
                    ("text_section", "project", ".kiro/steering/graphify.md"),
                ],
            },
        },
        "pi": {
            "user": {
                "install": ["graphify", "install", "--platform", "pi"],
                "uninstall": ["graphify", "pi", "uninstall"],
                "equivalent": ["graphify", "pi", "install"],
                "surfaces": [("skill", "home", ".pi/agent/skills/graphify/SKILL.md")],
            },
            "project": {
                "install": ["graphify", "install", "--project", "--platform", "pi"],
                "uninstall": ["graphify", "uninstall", "--project", "--platform", "pi"],
                "equivalent": ["graphify", "pi", "install", "--project"],
                "surfaces": [("skill", "project", ".pi/agent/skills/graphify/SKILL.md")],
            },
        },
    }

    for platform_name, scopes in expected.items():
        normalized_scopes = normalized["platforms"][platform_name]["scopes"]
        for scope_name, scope_expected in scopes.items():
            scope = normalized_scopes[scope_name]

            assert scope["effects"] == scope["expected"]
            assert scope["install_command"] == scope_expected["install"]
            assert scope["uninstall_command"] == scope_expected["uninstall"]
            assert scope["equivalent_install_command"] == scope_expected["equivalent"]
            assert [(entry["effect_type"], entry["root"], entry["relative"]) for entry in scope["effects"]] == scope_expected["surfaces"]

    assert normalized["platforms"]["cursor"]["unsupported_scopes"] == {
        "user": "cursor install writes a project-local .cursor rule in the current working directory; sandbox covers that file effect as project scope"
    }


def test_normalized_complex_migrated_effects_match_expected_for_claude_and_vscode() -> None:
    normalized = normalize_default_registry()
    claude_platform = normalized["platforms"]["claude"]
    claude = claude_platform["scopes"]
    vscode = normalized["platforms"]["vscode"]

    assert claude["user"]["effects"] == claude["user"]["expected"]
    assert claude["project"]["effects"] == claude["project"]["expected"]
    assert [(entry["effect_type"], entry["root"], entry["relative"]) for entry in claude["user"]["effects"]] == [
        ("skill", "home", ".claude/skills/graphify/SKILL.md"),
        ("text_section", "home", ".claude/CLAUDE.md"),
    ]
    assert [(entry["effect_type"], entry["root"], entry["relative"]) for entry in claude["project"]["effects"]] == [
        ("skill", "project", ".claude/skills/graphify/SKILL.md"),
        ("text_section", "project", ".claude/CLAUDE.md"),
        ("text_section", "project", "CLAUDE.md"),
        ("json_hooks", "project", ".claude/settings.json"),
    ]
    claude_hooks = next(entry for entry in claude["project"]["effects"] if entry["effect_type"] == "json_hooks")
    assert claude_hooks["json_expectation"]["schema_name"] == "claude_settings"
    assert claude_hooks["json_expectation"]["hooks"] == [
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
    ]
    assert claude_platform["universal_uninstall_scopes"] == ["project"]
    assert vscode["reference_bundles"] == [
        {"name": "vscode", "required_package_relative": "skill-vscode.md"},
        {"name": "copilot", "required_package_relative": None},
    ]
    assert vscode["uses_packaged_references"] is False
    assert vscode["scopes"]["user"]["effects"] == vscode["scopes"]["user"]["expected"]
    assert vscode["scopes"]["project"]["effects"] == vscode["scopes"]["project"]["expected"]


def test_normalized_simulated_layout_migrated_effects_match_expected_and_policies() -> None:
    normalized = normalize_default_registry()
    expected = {
        "antigravity": {
            "simulated": False,
            "user": {
                "install": ["graphify", "antigravity", "install"],
                "uninstall": ["graphify", "antigravity", "uninstall"],
                "equivalent": None,
                "allowed_roots": ["home", "project", "user_cwd"],
                "risk_notes": ["mixed_scope_project_wiring"],
                "surfaces": [
                    ("skill", "home", ".gemini/config/skills/graphify/SKILL.md"),
                    ("text_section", "user_cwd", ".agents/rules/graphify.md"),
                    ("file", "user_cwd", ".agents/workflows/graphify.md"),
                ],
            },
            "project": {
                "install": ["graphify", "install", "--project", "--platform", "antigravity"],
                "uninstall": ["graphify", "uninstall", "--project", "--platform", "antigravity"],
                "equivalent": ["graphify", "antigravity", "install", "--project"],
                "allowed_roots": ["project"],
                "risk_notes": [],
                "surfaces": [
                    ("skill", "project", ".agents/skills/graphify/SKILL.md"),
                    ("text_section", "project", ".agents/rules/graphify.md"),
                    ("file", "project", ".agents/workflows/graphify.md"),
                ],
            },
        },
        "antigravity-windows": {
            "simulated": True,
            "user": {
                "install": ["graphify", "install", "--platform", "antigravity-windows"],
                "uninstall": None,
                "equivalent": None,
                "allowed_roots": ["home"],
                "risk_notes": ["public_cli_lacks_user_skill_uninstall", "simulated_linux_file_layout_only"],
                "surfaces": [("skill", "home", ".gemini/config/skills/graphify/SKILL.md")],
            },
            "project": {
                "install": ["graphify", "install", "--project", "--platform", "antigravity-windows"],
                "uninstall": ["graphify", "uninstall", "--project", "--platform", "antigravity-windows"],
                "equivalent": None,
                "allowed_roots": ["project"],
                "risk_notes": ["simulated_linux_file_layout_only"],
                "surfaces": [("skill", "project", ".agents/skills/graphify/SKILL.md")],
            },
        },
        "windows": {
            "simulated": True,
            "user": {
                "install": ["graphify", "install", "--platform", "windows"],
                "uninstall": None,
                "equivalent": None,
                "allowed_roots": ["home"],
                "risk_notes": ["public_cli_lacks_user_skill_uninstall", "simulated_linux_file_layout_only"],
                "surfaces": [
                    ("skill", "home", ".claude/skills/graphify/SKILL.md"),
                    ("text_section", "home", ".claude/CLAUDE.md"),
                ],
            },
            "project": {
                "install": ["graphify", "install", "--project", "--platform", "windows"],
                "uninstall": ["graphify", "uninstall", "--project", "--platform", "windows"],
                "equivalent": None,
                "allowed_roots": ["project"],
                "risk_notes": ["simulated_linux_file_layout_only"],
                "surfaces": [
                    ("skill", "project", ".claude/skills/graphify/SKILL.md"),
                    ("text_section", "project", ".claude/CLAUDE.md"),
                    ("text_section", "project", "CLAUDE.md"),
                    ("json_hooks", "project", ".claude/settings.json"),
                ],
            },
        },
    }

    for platform_name, platform_expected in expected.items():
        platform = normalized["platforms"][platform_name]
        assert platform["simulated_linux_layout"] is platform_expected["simulated"]
        assert platform["target_runtime_validation"] == []
        for scope_name in ("user", "project"):
            scope = platform["scopes"][scope_name]
            scope_expected = platform_expected[scope_name]

            assert scope["effects"] == scope["expected"]
            assert scope["install_command"] == scope_expected["install"]
            assert scope["uninstall_command"] == scope_expected["uninstall"]
            assert scope["equivalent_install_command"] == scope_expected["equivalent"]
            assert scope["allowed_roots"] == scope_expected["allowed_roots"]
            assert scope["risk_notes"] == scope_expected["risk_notes"]
            assert [(entry["effect_type"], entry["root"], entry["relative"]) for entry in scope["effects"]] == scope_expected["surfaces"]
