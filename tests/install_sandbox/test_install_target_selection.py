from __future__ import annotations

import pytest

from tools.install_sandbox.targets import install_target_models, install_target_selection

from install_target_test_support import REGISTRY, scenario_for


def test_scenario_id() -> None:
    assert install_target_selection.scenario_id("trae-cn", "project") == "trae-cn-project"
    assert install_target_selection.scenario_id("Bad Platform!", "User Scope") == "bad-platform-user-scope"
    assert install_target_selection.scenario_id("...", "___") == "scenario"


def test_catalog_accessors_preserve_target_and_platform_names() -> None:
    assert REGISTRY.target_names == REGISTRY.platform_names
    assert REGISTRY.target_spec("codex") is REGISTRY.platform_spec("codex")
    assert REGISTRY.selected_targets(all_platforms=True, target_name=None) == REGISTRY.selected_platforms(
        all_platforms=True,
        platform_name=None,
    )
    assert REGISTRY.selected_targets(all_platforms=False, target_name="codex") == REGISTRY.selected_platforms(
        all_platforms=False,
        platform_name="codex",
    )
    assert REGISTRY.target_scenarios("cursor", "both") == REGISTRY.platform_scenarios("cursor", "both")


def test_missing_install_target_and_legacy_platform_errors_keep_legacy_wording() -> None:
    with pytest.raises(RuntimeError, match=r"^unknown sandbox platform: missing-target$"):
        REGISTRY.target_spec("missing-target")
    with pytest.raises(RuntimeError, match=r"^unknown sandbox platform: missing-target$"):
        REGISTRY.platform_spec("missing-target")
    with pytest.raises(RuntimeError, match=r"^unknown sandbox platform\(s\): missing-target$"):
        REGISTRY.selected_targets(all_platforms=False, target_name="missing-target")
    with pytest.raises(RuntimeError, match=r"^unknown sandbox platform\(s\): missing-target$"):
        REGISTRY.selected_platforms(all_platforms=False, platform_name="missing-target")
    with pytest.raises(RuntimeError, match=r"^unknown sandbox platform: missing-target$"):
        REGISTRY.target_scenarios("missing-target", "both")
    with pytest.raises(RuntimeError, match=r"^unknown sandbox platform: missing-target$"):
        REGISTRY.platform_scenarios("missing-target", "both")


def test_every_catalog_scope_is_runnable_or_explained() -> None:
    for platform_name in REGISTRY.target_names:
        for scope in ("user", "project"):
            scenario = REGISTRY.make_scenario(platform_name, scope)
            reason = REGISTRY.unsupported_scope_reason(platform_name, scope)
            assert (scenario is not None) != (reason is not None), f"{platform_name}/{scope} should have exactly one scenario or unsupported reason"
            if scenario is not None:
                assert scenario.expected, f"{platform_name}/{scope} should assert at least one file effect"


def test_cursor_both_scope_selects_project_scenario() -> None:
    both = REGISTRY.target_scenarios("cursor", "both")

    assert [scenario.scope for scenario in both] == ["project"]


def test_agents_target_selection_includes_both_scopes_without_skills_alias_target() -> None:
    selected = REGISTRY.selected_targets(all_platforms=True, target_name=None)
    scenarios = REGISTRY.target_scenarios("agents", "both")

    assert "agents" in selected
    assert "skills" not in REGISTRY.specs
    assert [(scenario.platform, scenario.scope) for scenario in scenarios] == [
        ("agents", "user"),
        ("agents", "project"),
    ]
    assert [install_target_selection.scenario_id(scenario.platform, scenario.scope) for scenario in scenarios] == [
        "agents-user",
        "agents-project",
    ]


def test_agents_command_variants_and_equivalence_are_generic_target_facts() -> None:
    user = scenario_for("agents", "user")
    project = scenario_for("agents", "project")

    assert user.install_command == ("graphify", "install", "--platform", "agents")
    assert REGISTRY.install_variants(user) == (
        install_target_models.InstallCommandVariant("generic", ("graphify", "install", "--platform", "agents")),
    )
    assert REGISTRY.equivalent_install_command(user) is None
    assert project.install_command == ("graphify", "install", "--project", "--platform", "agents")
    assert REGISTRY.install_variants(project) == (
        install_target_models.InstallCommandVariant("generic", ("graphify", "install", "--project", "--platform", "agents")),
        install_target_models.InstallCommandVariant("direct", ("graphify", "agents", "install", "--project")),
    )
    assert REGISTRY.equivalent_install_command(project) == ("graphify", "agents", "install", "--project")


def test_make_scenario_projects_catalog_scope_specs() -> None:
    for platform_name in REGISTRY.target_names:
        spec = REGISTRY.platform_spec(platform_name)
        for scope, scope_spec in spec.scopes.items():
            scenario = REGISTRY.make_scenario(platform_name, scope)
            assert scenario is not None
            assert scenario.install_command == scope_spec.install_command
            assert scenario.uninstall_command == scope_spec.uninstall_command
            assert scenario.cwd_root == scope_spec.cwd_root
            assert scenario.expected == scope_spec.expected
            assert scenario.risk_notes == scope_spec.risk_notes


def test_direct_equivalence_uses_catalog_scope_specs() -> None:
    for platform_name in REGISTRY.target_names:
        spec = REGISTRY.platform_spec(platform_name)
        for scope, scope_spec in spec.scopes.items():
            scenario = REGISTRY.make_scenario(platform_name, scope)
            assert scenario is not None
            assert REGISTRY.equivalent_install_command(scenario) == scope_spec.equivalent_install_command


def test_install_variants_are_declared_and_preserve_arbitrary_labels() -> None:
    specs = {
        "strange-tool": install_target_models.PlatformSpec(
            name="strange-tool",
            scopes={
                "project": install_target_models.ScopeSpec(
                    install_command=("tool", "apply", "alpha"),
                    uninstall_command=None,
                    cwd_root="project",
                    expected=(install_target_models.ExpectedPath("project", "tool.txt"),),
                    equivalent_install_command=("tool", "apply", "beta"),
                    install_variants=(
                        install_target_models.InstallCommandVariant("first declared", ("tool", "apply", "alpha")),
                        install_target_models.InstallCommandVariant("second declared", ("tool", "apply", "beta")),
                    ),
                )
            },
        )
    }
    scenario = install_target_selection.make_scenario(specs, "strange-tool", "project")

    assert scenario is not None
    assert install_target_selection.install_variants(specs, scenario) == (
        install_target_models.InstallCommandVariant("first declared", ("tool", "apply", "alpha")),
        install_target_models.InstallCommandVariant("second declared", ("tool", "apply", "beta")),
    )
    assert install_target_selection.equivalent_install_variants(specs, scenario) == (
        install_target_models.InstallCommandVariant("first declared", ("tool", "apply", "alpha")),
        install_target_models.InstallCommandVariant("second declared", ("tool", "apply", "beta")),
    )


def test_install_variant_fallback_uses_neutral_labels_for_unrecognized_commands() -> None:
    specs = {
        "neutral": install_target_models.PlatformSpec(
            name="neutral",
            scopes={
                "project": install_target_models.ScopeSpec(
                    install_command=("tool", "primary"),
                    uninstall_command=None,
                    cwd_root="project",
                    expected=(install_target_models.ExpectedPath("project", "neutral.txt"),),
                    equivalent_install_command=("tool", "alternate"),
                )
            },
        )
    }

    assert install_target_selection.install_variants_for_scope(specs, "neutral", "project") == (
        install_target_models.InstallCommandVariant("primary", ("tool", "primary")),
        install_target_models.InstallCommandVariant("alternate", ("tool", "alternate")),
    )


def test_platform_coverage_records_unsupported_scopes() -> None:
    records = REGISTRY.coverage_records(["cursor"], "both")
    user = next(record for record in records if record["scope"] == "user")
    project = next(record for record in records if record["scope"] == "project")

    assert user["status"] == "unsupported"
    assert "reason" in user
    assert project["status"] == "runnable"


def test_generic_direct_equivalence_applicability() -> None:
    gemini_user = REGISTRY.make_scenario("gemini", "user")
    gemini_project = REGISTRY.make_scenario("gemini", "project")
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
    assert gemini_project is not None
    assert REGISTRY.equivalent_install_command(gemini_user) == ("graphify", "gemini", "install")
    assert gemini_project.install_command == (
        "graphify",
        "install",
        "--project",
        "--platform",
        "gemini",
    )
    assert REGISTRY.install_variants(gemini_project) == (
        install_target_models.InstallCommandVariant(
            "generic",
            ("graphify", "install", "--project", "--platform", "gemini"),
        ),
        install_target_models.InstallCommandVariant(
            "direct",
            ("graphify", "gemini", "install", "--project"),
        ),
    )
    assert REGISTRY.equivalent_install_command(codex_user) is None
    assert REGISTRY.equivalent_install_command(codex_project) == ("graphify", "codex", "install", "--project")
    assert REGISTRY.equivalent_install_command(codebuddy_user) is None
    assert REGISTRY.equivalent_install_command(codebuddy_project) == ("graphify", "codebuddy", "install")
    assert REGISTRY.equivalent_install_command(cursor_project) == ("graphify", "install", "--project", "--platform", "cursor")


def test_catalog_accessors_return_selection_behavior() -> None:
    scenario = REGISTRY.make_scenario("codex", "project")

    assert REGISTRY.scenario_id("codex", "project") == "codex-project"
    assert REGISTRY.coverage_records(["cursor"], "both") == [
        {
            "platform": "cursor",
            "scope": "user",
            "status": "unsupported",
            "reason": "cursor install writes a project-local .cursor rule in the current working directory; sandbox covers that file effect as project scope",
        },
        {
            "platform": "cursor",
            "scope": "project",
            "status": "runnable",
            "scenario_id": "cursor-project",
            "install_command": ["graphify", "cursor", "install"],
            "uninstall_command": ["graphify", "cursor", "uninstall"],
            "generic_direct_equivalence": {
                "status": "runnable",
                "command": ["graphify", "install", "--project", "--platform", "cursor"],
            },
            "risk_notes": [],
        },
    ]
    assert scenario is not None
    assert REGISTRY.install_variants_for_scope("codex", "project") == (
        install_target_models.InstallCommandVariant("generic", ("graphify", "install", "--project", "--platform", "codex")),
        install_target_models.InstallCommandVariant("direct", ("graphify", "codex", "install", "--project")),
    )
    assert REGISTRY.install_variants(scenario) == REGISTRY.install_variants_for_scope("codex", "project")
    assert REGISTRY.equivalent_install_command(scenario) == ("graphify", "codex", "install", "--project")
    assert REGISTRY.equivalent_install_variants(scenario) == (
        install_target_models.InstallCommandVariant("generic", ("graphify", "install", "--project", "--platform", "codex")),
        install_target_models.InstallCommandVariant("direct", ("graphify", "codex", "install", "--project")),
    )
