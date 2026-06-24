from __future__ import annotations

from tools.install_sandbox.targets import install_target_models, install_target_scenarios


def test_scenario_construction_helper_keeps_scope_spec_contract() -> None:
    scope = install_target_scenarios._scenario(
        "owner-target",
        "project",
        (
            install_target_models.InstallSurface("project", "owner-target.txt"),
            install_target_models.InstallSurface("home", ".owner/skills/graphify/SKILL.md"),
        ),
        risk_notes=(install_target_models.MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE,),
        equivalent_install_command=("graphify", "owner-target", "install", "--project"),
    )

    assert isinstance(scope, install_target_models.ScopeSpec)
    assert scope.install_command == ("graphify", "install", "--project", "--platform", "owner-target")
    assert scope.uninstall_command == ("graphify", "uninstall", "--project", "--platform", "owner-target")
    assert scope.cwd_root == "project"
    assert scope.allowed_roots == ("home", "project", "user_cwd")
    assert [entry.relative for entry in scope.expected] == [
        "owner-target.txt",
        ".owner/skills/graphify/SKILL.md",
    ]
    assert scope.install_variants == (
        install_target_models.InstallCommandVariant(
            "generic",
            ("graphify", "install", "--project", "--platform", "owner-target"),
        ),
        install_target_models.InstallCommandVariant(
            "direct",
            ("graphify", "owner-target", "install", "--project"),
        ),
    )


def test_scenario_construction_helper_labels_agents_project_alias_as_direct_variant() -> None:
    scope = install_target_scenarios._scenario(
        "agents",
        "project",
        (install_target_models.InstallSurface("project", ".agents/skills/graphify/SKILL.md"),),
        equivalent_install_command=("graphify", "agents", "install", "--project"),
    )

    assert scope.install_command == ("graphify", "install", "--project", "--platform", "agents")
    assert scope.install_variants == (
        install_target_models.InstallCommandVariant(
            "generic",
            ("graphify", "install", "--project", "--platform", "agents"),
        ),
        install_target_models.InstallCommandVariant(
            "direct",
            ("graphify", "agents", "install", "--project"),
        ),
    )
