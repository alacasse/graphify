from __future__ import annotations

from tools.install_sandbox.spec_loader import load_default_registry
from tools.install_sandbox.spec_normalize import normalize_registry


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
