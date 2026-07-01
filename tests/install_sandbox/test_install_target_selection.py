from __future__ import annotations

import inspect

import pytest

from tools.install_sandbox.targets import install_target_models, install_target_selection

from install_target_test_support import REGISTRY, scenario_for


TARGET_SELECTION_PLATFORM_NAMED_PARAMETER_DEBT = {
    "coverage_records": {"platforms"},
    "direct_install_command": {"platform_name"},
    "direct_uninstall_command": {"platform_name"},
    "generic_install_command": {"platform_name"},
    "install_variants_for_scope": {"platform_name"},
    "make_scenario": {"platform_name"},
    "scenario_id": {"platform_name"},
    "unsupported_scope_reason": {"platform_name"},
    "user_skill": {"platform_name"},
    "project_skill": {"platform_name"},
}

DEFERRED_SELECTION_EDGE_VOCABULARY = {
    "Scenario.platform",
    "--platform command argument",
    "YAML platforms registry key",
}


def test_scenario_id() -> None:
    assert install_target_selection.scenario_id("trae-cn", "project") == "trae-cn-project"
    assert install_target_selection.scenario_id("Bad Platform!", "User Scope") == "bad-platform-user-scope"
    assert install_target_selection.scenario_id("...", "___") == "scenario"


def test_catalog_preferred_target_accessors_select_target_facts() -> None:
    assert REGISTRY.target_names == list(REGISTRY.specs)
    assert REGISTRY.target_spec("codex") is REGISTRY.specs["codex"]
    assert REGISTRY.selected_targets(all_platforms=True, target_name=None) == REGISTRY.target_names
    assert REGISTRY.selected_targets(all_platforms=False, target_name="codex") == ["codex"]
    assert [(scenario.platform, scenario.scope) for scenario in REGISTRY.target_scenarios("cursor", "both")] == [
        ("cursor", "project")
    ]


def test_catalog_platform_aliases_are_not_supported_accessors() -> None:
    for name in (
        "platform_names",
        "platform_spec",
        "selected_platforms",
        "platform_scenarios",
    ):
        assert not hasattr(REGISTRY, name)


def test_target_selection_classifies_remaining_platform_parameters_as_internal_debt() -> None:
    assert DEFERRED_SELECTION_EDGE_VOCABULARY == {
        "Scenario.platform",
        "--platform command argument",
        "YAML platforms registry key",
    }
    for helper_name, debt_parameters in TARGET_SELECTION_PLATFORM_NAMED_PARAMETER_DEBT.items():
        signature = inspect.signature(getattr(install_target_selection, helper_name))

        assert set(signature.parameters) >= debt_parameters

    assert "platform" in install_target_models.Scenario.__dataclass_fields__


def test_missing_install_target_and_legacy_platform_errors_keep_legacy_wording() -> None:
    # Error wording is user-visible today and intentionally remains separate
    # from the internal accessor migration.
    with pytest.raises(RuntimeError, match=r"^unknown sandbox platform: missing-target$"):
        REGISTRY.target_spec("missing-target")
    with pytest.raises(RuntimeError, match=r"^unknown sandbox platform\(s\): missing-target$"):
        REGISTRY.selected_targets(all_platforms=False, target_name="missing-target")
    with pytest.raises(RuntimeError, match=r"^unknown sandbox platform: missing-target$"):
        REGISTRY.target_scenarios("missing-target", "both")


def test_every_catalog_scope_is_runnable_or_explained() -> None:
    for target_name in REGISTRY.target_names:
        for scope in ("user", "project"):
            scenario = REGISTRY.make_scenario(target_name, scope)
            reason = REGISTRY.unsupported_scope_reason(target_name, scope)
            assert (scenario is not None) != (reason is not None), f"{target_name}/{scope} should have exactly one scenario or unsupported reason"
            if scenario is not None:
                assert scenario.expected, f"{target_name}/{scope} should assert at least one file effect"


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
    for target_name in REGISTRY.target_names:
        spec = REGISTRY.target_spec(target_name)
        for scope, scope_spec in spec.scopes.items():
            scenario = REGISTRY.make_scenario(target_name, scope)
            assert scenario is not None
            assert scenario.install_command == scope_spec.install_command
            assert scenario.uninstall_command == scope_spec.uninstall_command
            assert scenario.cwd_root == scope_spec.cwd_root
            assert scenario.expected == scope_spec.expected
            assert scenario.risk_notes == scope_spec.risk_notes


def test_direct_equivalence_uses_catalog_scope_specs() -> None:
    for target_name in REGISTRY.target_names:
        spec = REGISTRY.target_spec(target_name)
        for scope, scope_spec in spec.scopes.items():
            scenario = REGISTRY.make_scenario(target_name, scope)
            assert scenario is not None
            assert REGISTRY.equivalent_install_command(scenario) == scope_spec.equivalent_install_command


def test_install_variants_are_declared_and_preserve_arbitrary_labels() -> None:
    specs = {
        "strange-tool": install_target_models.InstallTargetSpec(
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
        "neutral": install_target_models.InstallTargetSpec(
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


def test_target_coverage_records_unsupported_scopes() -> None:
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
            "target": "cursor",
            "scope": "user",
            "status": "unsupported",
            "reason": "cursor install writes a project-local .cursor rule in the current working directory; sandbox covers that file effect as project scope",
        },
        {
            "target": "cursor",
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
