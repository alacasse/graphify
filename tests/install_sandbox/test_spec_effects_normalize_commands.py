from __future__ import annotations

from tests.install_sandbox.install_target_test_support import normalize_default_registry


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
            assert [
                (entry["effect_type"], entry["root"], entry["relative"]) for entry in scope["effects"]
            ] == scope_expected["surfaces"]

    assert normalized["platforms"]["cursor"]["unsupported_scopes"] == {
        "user": (
            "cursor install writes a project-local .cursor rule in the current working directory; "
            "sandbox covers that file effect as project scope"
        )
    }
