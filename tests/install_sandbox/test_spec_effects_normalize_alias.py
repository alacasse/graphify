from __future__ import annotations

from tests.install_sandbox.install_target_test_support import normalize_default_registry


def test_normalized_registry_exposes_effects_alias_without_dropping_expected() -> None:
    # LR-B7 owns removal of normalized-output `expected`; LR-B6 keeps this
    # compatibility alias while banning `expected` as registry input.
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
