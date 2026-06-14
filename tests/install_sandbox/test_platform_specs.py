from __future__ import annotations

import pytest

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
        assert entry.content_kind == "json"
        assert entry.json_expectation is not None
        assert entry.json_expectation.schema_name == expectations[(platform_name, scope, relative)]


def test_user_content_preservation_is_declared_on_registry_entries() -> None:
    preserving_entries = {
        (platform_name, scope, entry.root, entry.relative)
        for platform_name in platform_specs.ALL_PLATFORMS
        for scope in ("user", "project")
        if (scenario := REGISTRY.make_scenario(platform_name, scope)) is not None
        for entry in scenario.expected
        if entry.text_expectation.preserve_user_content
    }

    assert preserving_entries == {
        ("claude", "user", "home", ".claude/CLAUDE.md"),
        ("claude", "project", "project", ".claude/CLAUDE.md"),
        ("claude", "project", "project", "CLAUDE.md"),
        ("codex", "project", "project", "AGENTS.md"),
        ("opencode", "project", "project", "AGENTS.md"),
        ("kilo", "project", "project", "AGENTS.md"),
        ("gemini", "user", "user_cwd", "GEMINI.md"),
        ("gemini", "project", "project", "GEMINI.md"),
        ("aider", "project", "project", "AGENTS.md"),
        ("vscode", "user", "user_cwd", ".github/copilot-instructions.md"),
        ("vscode", "project", "project", ".github/copilot-instructions.md"),
        ("claw", "project", "project", "AGENTS.md"),
        ("droid", "project", "project", "AGENTS.md"),
        ("trae", "project", "project", "AGENTS.md"),
        ("trae-cn", "project", "project", "AGENTS.md"),
        ("hermes", "project", "project", "AGENTS.md"),
        ("windows", "user", "home", ".claude/CLAUDE.md"),
        ("windows", "project", "project", ".claude/CLAUDE.md"),
        ("windows", "project", "project", "CLAUDE.md"),
        ("amp", "project", "project", "AGENTS.md"),
    }


def test_text_section_repair_is_declared_on_expected_paths() -> None:
    nonstandard_marker_entries: set[tuple[str, str, str, str]] = set()
    for platform_name in platform_specs.ALL_PLATFORMS:
        for scope in ("user", "project"):
            scenario = REGISTRY.make_scenario(platform_name, scope)
            if scenario is None:
                continue
            for entry in scenario.expected:
                if entry.content_kind != "text":
                    continue
                if entry.marker == platform_specs.GRAPHIFY_MARKER:
                    assert entry.text_expectation.repair_stale_graphify_section, f"{platform_name}/{scope}/{entry.relative}"
                elif entry.marker is not None:
                    assert not entry.text_expectation.repair_stale_graphify_section, f"{platform_name}/{scope}/{entry.relative}"
                    nonstandard_marker_entries.add((platform_name, scope, entry.root, entry.relative))

    assert nonstandard_marker_entries == {
        ("claude", "user", "home", ".claude/CLAUDE.md"),
        ("claude", "project", "project", ".claude/CLAUDE.md"),
        ("kiro", "project", "project", ".kiro/steering/graphify.md"),
        ("windows", "user", "home", ".claude/CLAUDE.md"),
        ("windows", "project", "project", ".claude/CLAUDE.md"),
    }


def test_home_claude_instruction_docs_are_not_removed_on_uninstall() -> None:
    non_removable_entries = {
        (platform_name, scope, entry.root, entry.relative)
        for platform_name in platform_specs.ALL_PLATFORMS
        for scope in ("user", "project")
        if (scenario := REGISTRY.make_scenario(platform_name, scope)) is not None
        for entry in scenario.expected
        if not entry.remove_on_uninstall
    }

    assert non_removable_entries == {
        ("claude", "user", "home", ".claude/CLAUDE.md"),
        ("windows", "user", "home", ".claude/CLAUDE.md"),
    }


def test_scope_risk_notes_are_derived_from_locality_and_simulation() -> None:
    expected = {
        ("opencode", "user"): (
            platform_specs.MIXED_SCOPE_PROJECT_WIRING_NOTE,
            platform_specs.PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,
        ),
        ("kilo", "project"): (platform_specs.MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE,),
        ("antigravity-windows", "user"): (
            platform_specs.PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,
            platform_specs.SIMULATED_LINUX_LAYOUT_NOTE,
        ),
        ("windows", "project"): (platform_specs.SIMULATED_LINUX_LAYOUT_NOTE,),
    }

    for (platform_name, scope), risk_notes in expected.items():
        scenario = REGISTRY.make_scenario(platform_name, scope)
        assert scenario is not None
        assert scenario.risk_notes == risk_notes


def test_skill_sidecar_policy_is_declared_on_skill_entries() -> None:
    for platform_name in platform_specs.ALL_PLATFORMS:
        for scope in ("user", "project"):
            scenario = REGISTRY.make_scenario(platform_name, scope)
            if scenario is None:
                continue
            for entry in scenario.expected:
                if entry.relative.endswith("SKILL.md"):
                    assert entry.skill_sidecar_expectation is not None, f"{platform_name}/{scope}/{entry.relative}"


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


def test_install_variants_are_declared_and_preserve_arbitrary_labels() -> None:
    registry = platform_specs.ScenarioRegistry(
        {
            "strange-tool": platform_specs.PlatformSpec(
                name="strange-tool",
                scopes={
                    "project": platform_specs.ScopeSpec(
                        install_command=("tool", "apply", "alpha"),
                        uninstall_command=None,
                        cwd_root="project",
                        expected=(platform_specs.ExpectedPath("project", "tool.txt"),),
                        equivalent_install_command=("tool", "apply", "beta"),
                        install_variants=(
                            platform_specs.InstallCommandVariant("first declared", ("tool", "apply", "alpha")),
                            platform_specs.InstallCommandVariant("second declared", ("tool", "apply", "beta")),
                        ),
                    )
                },
            )
        }
    )
    scenario = registry.make_scenario("strange-tool", "project")

    assert scenario is not None
    assert registry.install_variants(scenario) == (
        platform_specs.InstallCommandVariant("first declared", ("tool", "apply", "alpha")),
        platform_specs.InstallCommandVariant("second declared", ("tool", "apply", "beta")),
    )
    assert registry.equivalent_install_variants(scenario) == (
        platform_specs.InstallCommandVariant("first declared", ("tool", "apply", "alpha")),
        platform_specs.InstallCommandVariant("second declared", ("tool", "apply", "beta")),
    )


def test_install_variant_fallback_uses_neutral_labels_for_unrecognized_commands() -> None:
    registry = platform_specs.ScenarioRegistry(
        {
            "neutral": platform_specs.PlatformSpec(
                name="neutral",
                scopes={
                    "project": platform_specs.ScopeSpec(
                        install_command=("tool", "primary"),
                        uninstall_command=None,
                        cwd_root="project",
                        expected=(platform_specs.ExpectedPath("project", "neutral.txt"),),
                        equivalent_install_command=("tool", "alternate"),
                    )
                },
            )
        }
    )

    assert registry.install_variants_for_scope("neutral", "project") == (
        platform_specs.InstallCommandVariant("primary", ("tool", "primary")),
        platform_specs.InstallCommandVariant("alternate", ("tool", "alternate")),
    )


def test_target_runtime_validation_sections_are_declared_and_deduped() -> None:
    validation = platform_specs.TargetRuntimeValidationSpec(
        section_title="Synthetic Runtime Validation",
        status="declared-only",
        strategy="inspect generated payloads",
        targets=("runtime-a", "runtime-b"),
        notes=("separate runtime smoke tests required",),
        evidence_path="evidence/synthetic.md",
    )
    registry = platform_specs.ScenarioRegistry(
        {
            "runtime-one": platform_specs.PlatformSpec(name="runtime-one", target_runtime_validation=(validation,)),
            "runtime-two": platform_specs.PlatformSpec(name="runtime-two", target_runtime_validation=(validation,)),
        }
    )

    assert registry.target_runtime_validation_sections() == [
        {
            "section_title": "Synthetic Runtime Validation",
            "status": "declared-only",
            "evidence_path": "evidence/synthetic.md",
            "strategy": "inspect generated payloads",
            "targets": ["runtime-a", "runtime-b"],
            "notes": ["separate runtime smoke tests required"],
        }
    ]
    assert platform_specs.ScenarioRegistry({"plain": platform_specs.PlatformSpec(name="plain")}).target_runtime_validation_sections() == []
    assert platform_specs.target_runtime_validation_sections()


def test_disposable_artifact_scenarios_are_declared_by_scope() -> None:
    spec = platform_specs.DisposableArtifactScenarioSpec(
        scenario_id="discard-cache",
        platform_label="cache-cleaner",
        scope="project",
        command=("tool", "discard"),
        cwd_root="project",
        artifact_subdir="discard-artifacts",
        disposable_path_root="project",
        disposable_path_relative="tmp-cache",
        seed_files=(platform_specs.DisposableSeedFile("seed.txt", "seed\n"),),
        scope_eligibility=("project",),
        risk_note="synthetic disposable artifact policy",
    )
    registry = platform_specs.ScenarioRegistry({}, disposable_artifact_specs=(spec,))

    assert registry.disposable_artifact_scenarios("project") == [spec]
    assert registry.disposable_artifact_scenarios("user") == []
    assert platform_specs.disposable_artifact_scenarios("project") == list(
        REGISTRY.disposable_artifact_scenarios("project")
    )
    assert REGISTRY.purge_disposable_graphify_out_scenario_id() == REGISTRY.disposable_artifact_scenarios("project")[0].scenario_id


def test_universal_uninstall_scenarios_return_declared_policy() -> None:
    installable_scope = platform_specs.ScopeSpec(
        install_command=("tool", "install"),
        uninstall_command=None,
        cwd_root="project",
        expected=(platform_specs.ExpectedPath("project", "installed.txt"),),
    )
    universal = platform_specs.UniversalUninstallScenarioSpec(
        scenario_id="uninstall-everything",
        platform_label="declared-combo",
        scope="workspace",
        command=("tool", "remove", "all"),
        cwd_root="user_cwd",
        eligible_platform_scope="project",
        minimum_installed_scenarios=1,
        artifact_subdir="declared-uninstall",
        risk_note="synthetic universal uninstall policy",
    )
    registry = platform_specs.ScenarioRegistry(
        {
            "alpha": platform_specs.PlatformSpec(
                name="alpha",
                scopes={"project": installable_scope},
                universal_uninstall_scopes=("project",),
            ),
            "beta": platform_specs.PlatformSpec(name="beta", scopes={"project": installable_scope}),
        },
        universal_uninstall_specs=(universal,),
    )

    selected = registry.universal_uninstall_scenarios(["alpha", "beta"], "workspace")

    assert len(selected) == 1
    assert selected[0].spec is universal
    assert selected[0].spec.command == ("tool", "remove", "all")
    assert selected[0].spec.cwd_root == "user_cwd"
    assert [scenario.platform for scenario in selected[0].installed_scenarios] == ["alpha"]
    assert platform_specs.universal_uninstall_scenarios(["codex", "claude", "gemini"], "project")


def test_validate_roots_covers_scenarios_and_synthetic_policies() -> None:
    registry = platform_specs.ScenarioRegistry(
        {
            "rooted": platform_specs.PlatformSpec(
                name="rooted",
                scopes={
                    "project": platform_specs.ScopeSpec(
                        install_command=("tool", "install"),
                        uninstall_command=None,
                        cwd_root="declared-cwd",
                        expected=(platform_specs.ExpectedPath("declared-output", "artifact.txt"),),
                    )
                },
            )
        },
        universal_uninstall_specs=(
            platform_specs.UniversalUninstallScenarioSpec(
                scenario_id="universal",
                platform_label="combo",
                scope="project",
                command=("tool", "uninstall"),
                cwd_root="declared-cwd",
                eligible_platform_scope="project",
            ),
        ),
        disposable_artifact_specs=(
            platform_specs.DisposableArtifactScenarioSpec(
                scenario_id="disposable",
                platform_label="cleanup",
                scope="project",
                command=("tool", "purge"),
                cwd_root="declared-cwd",
                artifact_subdir="purge",
                disposable_path_root="declared-output",
                disposable_path_relative="cache",
                seed_files=(),
                scope_eligibility=("project",),
                risk_note="synthetic disposable policy",
            ),
        ),
    )

    registry.validate_roots({"declared-cwd", "declared-output"})
    platform_specs.validate_roots({"home", "project", "user_cwd"})
    with pytest.raises(RuntimeError, match="declared-output"):
        registry.validate_roots({"declared-cwd"})


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
