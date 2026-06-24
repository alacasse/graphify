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
