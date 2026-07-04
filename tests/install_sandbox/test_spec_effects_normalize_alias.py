from __future__ import annotations

from tests.install_sandbox.install_target_test_support import normalize_default_registry


def test_normalized_registry_exposes_codex_project_effects() -> None:
    normalized = normalize_default_registry()
    codex_project = normalized["targets"]["codex"]["scopes"]["project"]

    assert [
        (entry["effect_type"], entry["root"], entry["relative"]) for entry in codex_project["effects"]
    ] == [
        ("skill", "project", ".codex/skills/graphify/SKILL.md"),
        ("text_section", "project", "AGENTS.md"),
        ("json_hooks", "project", ".codex/hooks.json"),
    ]


def test_normalized_gemini_effects_for_both_scopes() -> None:
    normalized = normalize_default_registry()
    gemini = normalized["targets"]["gemini"]["scopes"]

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
