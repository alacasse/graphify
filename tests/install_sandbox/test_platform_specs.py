from __future__ import annotations

from graphify import __main__ as graphify_main

from tools.install_sandbox import platform_specs


REGISTRY = platform_specs.DEFAULT_SCENARIO_REGISTRY


def test_scenario_id() -> None:
    assert REGISTRY.scenario_id("trae-cn", "project") == "trae-cn-project"
    assert REGISTRY.scenario_id("Bad Platform!", "User Scope") == "bad-platform-user-scope"
    assert REGISTRY.scenario_id("...", "___") == "scenario"
    assert REGISTRY.universal_uninstall_scenario_id("project") == "universal-uninstall-project"
    assert REGISTRY.purge_disposable_graphify_out_scenario_id() == "purge-disposable-graphify-out"


def test_expected_path_manifest_logic() -> None:
    user = REGISTRY.make_scenario("codex", "user")
    project = REGISTRY.make_scenario("codex", "project")
    assert user is not None
    assert project is not None
    assert any(entry.root == "home" and entry.relative == ".codex/skills/graphify/SKILL.md" for entry in user.expected)
    assert any(entry.root == "project" and entry.relative == ".codex/skills/graphify/SKILL.md" for entry in project.expected)
    assert any(entry.root == "project" and entry.relative == ".codex/hooks.json" for entry in project.expected)

    codebuddy = REGISTRY.make_scenario("codebuddy", "project")
    assert codebuddy is not None
    assert any(entry.relative == "CODEBUDDY.md" for entry in codebuddy.expected)
    assert any(entry.relative == ".codebuddy/settings.json" for entry in codebuddy.expected)

    both = REGISTRY.platform_scenarios("cursor", "both")
    assert [scenario.scope for scenario in both] == ["project"]


def test_json_expectations_are_declared_on_expected_paths() -> None:
    expectations = {
        ("claude", "project", ".claude/settings.json"): "claude_settings",
        ("codex", "project", ".codex/hooks.json"): "codex_hooks",
        ("codebuddy", "user", ".codebuddy/settings.json"): "codebuddy_settings",
        ("codebuddy", "project", ".codebuddy/settings.json"): "codebuddy_settings",
        ("gemini", "project", ".gemini/settings.json"): "gemini_settings",
        ("kilo", "project", ".kilo/kilo.json"): "kilo_config",
        ("opencode", "project", ".opencode/opencode.json"): "opencode_config",
    }

    for platform_name, scope, relative in expectations:
        scenario = REGISTRY.make_scenario(platform_name, scope)
        assert scenario is not None
        entry = next(item for item in scenario.expected if item.relative == relative)
        assert entry.json_expectation is not None
        assert entry.json_expectation.schema_name == expectations[(platform_name, scope, relative)]


def test_registry_mirrors_install_surface() -> None:
    cli_platforms = set(graphify_main._PLATFORM_CONFIG) | {"gemini", "cursor", "vscode"}

    assert set(platform_specs.ALL_PLATFORMS) == cli_platforms


def test_every_scope_is_runnable_or_explained() -> None:
    for platform_name in platform_specs.ALL_PLATFORMS:
        for scope in ("user", "project"):
            scenario = REGISTRY.make_scenario(platform_name, scope)
            reason = REGISTRY.unsupported_scope_reason(platform_name, scope)
            assert (scenario is not None) != (reason is not None), f"{platform_name}/{scope} should have exactly one scenario or unsupported reason"
            if scenario is not None:
                assert scenario.expected, f"{platform_name}/{scope} should assert at least one file effect"


def test_sandbox_registry_defines_all_platforms() -> None:
    specs = REGISTRY.specs

    assert list(specs) == platform_specs.ALL_PLATFORMS
    for platform_name, spec in specs.items():
        assert isinstance(spec, platform_specs.PlatformSpec)
        assert spec.name == platform_name
        assert bool(spec.scopes or spec.unsupported_scopes)


def test_vscode_reference_bundle_guard_is_declarative() -> None:
    spec = REGISTRY.platform_spec("vscode")

    assert spec.reference_bundles == (
        platform_specs.ReferenceBundle("vscode", required_package_relative="skill-vscode.md"),
        platform_specs.ReferenceBundle("copilot"),
    )


def test_reference_bundle_eligibility_uses_required_package_file(tmp_path) -> None:
    bundle = platform_specs.ReferenceBundle("not-vscode", required_package_relative="skill-not-vscode.md")

    assert not bundle.is_eligible(tmp_path)

    (tmp_path / "skill-not-vscode.md").write_text("skill")

    assert bundle.is_eligible(tmp_path)
    assert platform_specs.ReferenceBundle("not-vscode").is_eligible(tmp_path)


def test_make_scenario_projects_registry_scope_specs() -> None:
    for platform_name in ("claude", "codex", "codebuddy", "kilo", "vscode", "antigravity", "windows"):
        spec = REGISTRY.platform_spec(platform_name)
        for scope, scope_spec in spec.scopes.items():
            scenario = REGISTRY.make_scenario(platform_name, scope)
            assert scenario is not None
            assert scenario.install_command == scope_spec.install_command
            assert scenario.uninstall_command == scope_spec.uninstall_command
            assert scenario.cwd_root == scope_spec.cwd_root
            assert scenario.expected == scope_spec.expected
            assert scenario.risk_notes == scope_spec.risk_notes


def test_direct_equivalence_uses_registry_scope_specs() -> None:
    for platform_name in platform_specs.ALL_PLATFORMS:
        spec = REGISTRY.platform_spec(platform_name)
        for scope, scope_spec in spec.scopes.items():
            scenario = REGISTRY.make_scenario(platform_name, scope)
            assert scenario is not None
            assert REGISTRY.equivalent_install_command(scenario) == scope_spec.equivalent_install_command


def test_platform_coverage_records_unsupported_scopes() -> None:
    records = REGISTRY.coverage_records(["cursor"], "both")
    user = next(record for record in records if record["scope"] == "user")
    project = next(record for record in records if record["scope"] == "project")

    assert user["status"] == "unsupported"
    assert "reason" in user
    assert project["status"] == "runnable"


def test_codebuddy_scopes_are_runnable() -> None:
    for scope in ("user", "project"):
        scenario = REGISTRY.make_scenario("codebuddy", scope)
        assert scenario is not None
        assert any(entry.relative.endswith("SKILL.md") for entry in scenario.expected)
        assert any(entry.relative.endswith("CODEBUDDY.md") for entry in scenario.expected)
        assert any(entry.relative == ".codebuddy/settings.json" for entry in scenario.expected)


def test_generic_direct_equivalence_applicability() -> None:
    gemini_user = REGISTRY.make_scenario("gemini", "user")
    codex_user = REGISTRY.make_scenario("codex", "user")
    codex_project = REGISTRY.make_scenario("codex", "project")
    codebuddy_user = REGISTRY.make_scenario("codebuddy", "user")
    codebuddy_project = REGISTRY.make_scenario("codebuddy", "project")
    cursor_project = REGISTRY.make_scenario("cursor", "project")

    assert gemini_user is not None
    assert codex_user is not None
    assert codex_project is not None
    assert codebuddy_user is not None
    assert codebuddy_project is not None
    assert cursor_project is not None
    assert REGISTRY.equivalent_install_command(gemini_user) == ("graphify", "gemini", "install")
    assert REGISTRY.equivalent_install_command(codex_user) is None
    assert REGISTRY.equivalent_install_command(codex_project) == ("graphify", "codex", "install", "--project")
    assert REGISTRY.equivalent_install_command(codebuddy_user) is None
    assert REGISTRY.equivalent_install_command(codebuddy_project) == ("graphify", "codebuddy", "install")
    assert REGISTRY.equivalent_install_command(cursor_project) == ("graphify", "install", "--project", "--platform", "cursor")


def test_universal_scenario_selection_requires_multiple_platforms() -> None:
    assert REGISTRY.universal_uninstall_groups(["codex"], "project") == []

    groups = REGISTRY.universal_uninstall_groups(["codex", "claude", "gemini"], "project")
    assert len(groups) == 1
    assert groups[0][0] == "project"
