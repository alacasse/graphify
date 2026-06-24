from __future__ import annotations

from tools.install_sandbox import platform_specs
from tools.install_sandbox.spec_loader import load_default_registry, load_registry_from_data

from tests.install_sandbox.install_target_test_support import valid_registry_data as _valid_data


def test_default_registry_every_scope_is_runnable_or_explained() -> None:
    registry = load_default_registry()

    for platform_name in registry.platform_names:
        for scope in ("user", "project"):
            runnable = registry.make_scenario(platform_name, scope) is not None
            explained = registry.unsupported_scope_reason(platform_name, scope) is not None
            assert runnable != explained, f"{platform_name}/{scope} must be runnable xor explained"


def test_default_registry_skill_effects_declare_sidecar_expectation() -> None:
    registry = load_default_registry()

    for platform_name in registry.platform_names:
        for scope in ("user", "project"):
            scenario = registry.make_scenario(platform_name, scope)
            if scenario is None:
                continue
            for entry in scenario.expected:
                if entry.relative.endswith("SKILL.md"):
                    assert entry.skill_sidecar_expectation is not None, f"{platform_name}/{scope}/{entry.relative}"


def test_loader_derives_scope_locality_and_simulated_notes() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["simulated_linux_layout"] = True
    data["platforms"]["mini"]["scopes"]["user"]["expected"].append(
        {"root": "user_cwd", "relative": "GEMINI.md", "kind": "text_section"}
    )

    user = load_registry_from_data(data).make_scenario("mini", "user")

    assert user is not None
    assert user.allowed_roots == ("home", "project", "user_cwd")
    assert user.risk_notes == (
        platform_specs.MIXED_SCOPE_PROJECT_WIRING_NOTE,
        platform_specs.PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,
        platform_specs.SIMULATED_LINUX_LAYOUT_NOTE,
    )


def test_loader_preserves_explicit_target_runtime_validation() -> None:
    data = _valid_data()
    data["platforms"]["mini"]["target_runtime_validation"] = [
        {
            "section_title": "Windows Validation",
            "status": "payload_consistency_only",
            "strategy": "payload check only",
            "targets": ["windows payload"],
            "notes": ["runtime validation is external"],
        }
    ]
    data["platforms"]["mini"]["simulated_linux_layout"] = True

    spec = load_registry_from_data(data).platform_spec("mini")

    assert spec.target_runtime_validation == (
        platform_specs.TargetRuntimeValidationSpec(
            section_title="Windows Validation",
            status="payload_consistency_only",
            strategy="payload check only",
            targets=("windows payload",),
            notes=("runtime validation is external",),
        ),
    )


def test_loader_ignores_top_level_runtime_validation_policies() -> None:
    data = _valid_data()
    data["target_runtime_validation_policies"] = {"typo": {}}

    assert load_registry_from_data(data).platform_spec("mini").target_runtime_validation == ()
