from __future__ import annotations

from tools.install_sandbox import platform_specs
from tools.install_sandbox.spec_normalize import normalize_registry


def test_normalized_default_registry_is_deterministic() -> None:
    first = normalize_registry(platform_specs.DEFAULT_SCENARIO_REGISTRY)
    second = normalize_registry(platform_specs.DEFAULT_SCENARIO_REGISTRY)

    assert first == second


def test_normalized_registry_includes_platform_order() -> None:
    normalized = normalize_registry(platform_specs.DEFAULT_SCENARIO_REGISTRY)

    assert normalized["platform_order"] == platform_specs.ALL_PLATFORMS
    assert list(normalized["platforms"]) == platform_specs.ALL_PLATFORMS


def test_normalized_registry_includes_nested_expected_path_policies() -> None:
    normalized = normalize_registry(platform_specs.DEFAULT_SCENARIO_REGISTRY)
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
    normalized = normalize_registry(platform_specs.DEFAULT_SCENARIO_REGISTRY)

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
    assert windows["target_runtime_validation"][0]["section_title"] == "Windows Validation"


def test_normalized_registry_includes_synthetic_policies() -> None:
    normalized = normalize_registry(platform_specs.DEFAULT_SCENARIO_REGISTRY)

    assert normalized["universal_uninstall_specs"][0]["scenario_id"] == "universal-uninstall-user"
    assert normalized["universal_uninstall_specs"][1]["command"] == ["graphify", "uninstall", "--project"]
    assert normalized["disposable_artifact_specs"] == [
        {
            "scenario_id": "purge-disposable-graphify-out",
            "platform_label": "purge",
            "scope": "project",
            "command": ["graphify", "uninstall", "--purge"],
            "cwd_root": "project",
            "artifact_subdir": "uninstall-purge",
            "disposable_path_root": "project",
            "disposable_path_relative": "graphify-out",
            "seed_files": [{"relative": "graph.json", "content": '{"nodes": [], "edges": []}\n'}],
            "scope_eligibility": ["project", "both"],
            "risk_note": "purge verified only against disposable sandbox graphify-out state",
        }
    ]
