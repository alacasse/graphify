from __future__ import annotations

from tools.install_sandbox.spec_loader import load_default_registry
from tools.install_sandbox.spec_normalize import normalize_registry


FORBIDDEN_TARGET_ALIAS_KEYS = {
    "install_target_catalog",
    "install_targets",
    "selected_targets",
    "target_catalog",
    "target_specs",
}


def normalize_default_registry() -> dict[str, object]:
    return normalize_registry(load_default_registry())


def test_normalized_default_registry_is_deterministic() -> None:
    first = normalize_default_registry()
    second = normalize_default_registry()

    assert first == second


def test_normalized_registry_includes_platforms_in_registry_order() -> None:
    registry = load_default_registry()
    normalized = normalize_registry(registry)

    assert list(normalized["platforms"]) == registry.platform_names


def test_normalized_registry_top_level_key_set_is_stable() -> None:
    normalized = normalize_default_registry()

    assert set(normalized) == {"platforms"}


def test_normalized_platform_and_scope_key_sets_are_stable() -> None:
    normalized = normalize_default_registry()
    codex_platform = normalized["platforms"]["codex"]
    codex_project = codex_platform["scopes"]["project"]
    hooks = next(entry for entry in codex_project["expected"] if entry["relative"] == ".codex/hooks.json")

    assert set(codex_platform) == {
        "name",
        "display_name",
        "target_kind",
        "user_skill",
        "project_skill",
        "uses_packaged_references",
        "simulated_linux_layout",
        "scopes",
        "unsupported_scopes",
        "reference_bundles",
        "universal_uninstall_scopes",
        "target_runtime_validation",
    }
    assert set(codex_project) == {
        "install_command",
        "uninstall_command",
        "cwd_root",
        "expected",
        "effects",
        "risk_notes",
        "equivalent_install_command",
        "install_variants",
        "allowed_roots",
        "generated_file_expectation",
    }
    assert set(hooks) == {
        "effect_type",
        "root",
        "relative",
        "kind",
        "content_kind",
        "marker",
        "remove_on_uninstall",
        "text_expectation",
        "json_expectation",
        "skill_sidecar_expectation",
    }


def test_normalized_registry_does_not_emit_install_target_alias_keys() -> None:
    def walk(value: object) -> None:
        if isinstance(value, dict):
            assert FORBIDDEN_TARGET_ALIAS_KEYS.isdisjoint(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(normalize_default_registry())


def test_normalized_registry_includes_target_metadata() -> None:
    normalized = normalize_default_registry()

    assert normalized["platforms"]["agents"]["display_name"] == "Agent Skills"
    assert normalized["platforms"]["agents"]["target_kind"] == "generic_standard"
    assert normalized["platforms"]["codex"]["display_name"] is None
    assert normalized["platforms"]["codex"]["target_kind"] == "product"


def test_normalized_registry_includes_nested_expected_path_policies() -> None:
    normalized = normalize_default_registry()
    codex_project = normalized["platforms"]["codex"]["scopes"]["project"]
    hooks = next(entry for entry in codex_project["expected"] if entry["relative"] == ".codex/hooks.json")
    skill = next(entry for entry in codex_project["expected"] if entry["relative"].endswith("SKILL.md"))

    assert codex_project["install_variants"] == [
        {"label": "generic", "command": ["graphify", "install", "--project", "--platform", "codex"]},
        {"label": "direct", "command": ["graphify", "codex", "install", "--project"]},
    ]
    assert codex_project["allowed_roots"] == ["project"]
    assert hooks["effect_type"] == "json_hooks"
    assert hooks["content_kind"] == "json"
    assert hooks["json_expectation"]["schema_name"] == "codex_hooks"
    assert hooks["json_expectation"]["hooks"][0]["required_fragments"] == ["graphify", "hook-check"]
    assert skill["effect_type"] == "skill"
    assert skill["skill_sidecar_expectation"]["references_dir"] == "references"


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


def test_normalized_registry_includes_high_risk_platform_policies() -> None:
    normalized = normalize_default_registry()

    kilo_project = normalized["platforms"]["kilo"]["scopes"]["project"]
    gemini_user = normalized["platforms"]["gemini"]["scopes"]["user"]
    vscode = normalized["platforms"]["vscode"]
    antigravity_windows = normalized["platforms"]["antigravity-windows"]
    windows = normalized["platforms"]["windows"]

    assert kilo_project["allowed_roots"] == ["home", "project", "user_cwd"]
    assert any(entry["root"] == "home" for entry in kilo_project["expected"])
    assert gemini_user["allowed_roots"] == ["home", "project", "user_cwd"]
    assert vscode["uses_packaged_references"] is False
    assert vscode["reference_bundles"] == [
        {"name": "vscode", "required_package_relative": "skill-vscode.md"},
        {"name": "copilot", "required_package_relative": None},
    ]
    assert antigravity_windows["simulated_linux_layout"] is True
    assert windows["target_runtime_validation"] == []


def test_normalized_registry_omits_harness_policies() -> None:
    normalized = normalize_default_registry()

    assert "platform_order" not in normalized
    assert "universal_uninstall_specs" not in normalized
    assert "disposable_artifact_specs" not in normalized
