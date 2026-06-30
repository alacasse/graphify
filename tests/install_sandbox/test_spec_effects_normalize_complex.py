from __future__ import annotations

from tests.install_sandbox.install_target_test_support import normalize_default_registry


def test_normalized_complex_effects_for_claude_and_vscode() -> None:
    normalized = normalize_default_registry()
    claude_platform = normalized["platforms"]["claude"]
    claude = claude_platform["scopes"]
    vscode = normalized["platforms"]["vscode"]

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
    assert [
        (entry["effect_type"], entry["root"], entry["relative"])
        for entry in vscode["scopes"]["user"]["effects"]
    ] == [
        ("skill", "home", ".copilot/skills/graphify/SKILL.md"),
        ("text_section", "user_cwd", ".github/copilot-instructions.md"),
    ]
    assert [
        (entry["effect_type"], entry["root"], entry["relative"])
        for entry in vscode["scopes"]["project"]["effects"]
    ] == [
        ("skill", "home", ".copilot/skills/graphify/SKILL.md"),
        ("text_section", "project", ".github/copilot-instructions.md"),
    ]


def test_normalized_simulated_layout_effects_and_policies() -> None:
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

            assert scope["install_command"] == scope_expected["install"]
            assert scope["uninstall_command"] == scope_expected["uninstall"]
            assert scope["equivalent_install_command"] == scope_expected["equivalent"]
            assert scope["allowed_roots"] == scope_expected["allowed_roots"]
            assert scope["risk_notes"] == scope_expected["risk_notes"]
            assert [(entry["effect_type"], entry["root"], entry["relative"]) for entry in scope["effects"]] == scope_expected["surfaces"]
