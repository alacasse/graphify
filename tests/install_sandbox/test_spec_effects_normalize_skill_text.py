from __future__ import annotations

from tests.install_sandbox.install_target_test_support import normalize_default_registry


def test_normalized_simple_effects_for_both_scopes() -> None:
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
        normalized_scopes = normalized["targets"][platform_name]["scopes"]
        for scope_name, surfaces in scopes.items():
            scope = normalized_scopes[scope_name]
            assert [(entry["effect_type"], entry["root"], entry["relative"]) for entry in scope["effects"]] == surfaces
