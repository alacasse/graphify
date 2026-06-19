from __future__ import annotations

import pytest

from tools.install_sandbox import install_target_catalog, install_target_defaults, platform_specs

from install_target_test_support import REGISTRY


def test_scenario_id() -> None:
    assert REGISTRY.scenario_id("trae-cn", "project") == "trae-cn-project"
    assert REGISTRY.scenario_id("Bad Platform!", "User Scope") == "bad-platform-user-scope"
    assert REGISTRY.scenario_id("...", "___") == "scenario"
    assert REGISTRY.universal_uninstall_scenario_id("project") == "universal-uninstall-project"
    assert REGISTRY.purge_disposable_graphify_out_scenario_id() == "purge-disposable-graphify-out"


def test_scenario_construction_helper_keeps_scope_spec_contract() -> None:
    scope = install_target_catalog._scenario(
        "owner-target",
        "project",
        (
            platform_specs.InstallSurface("project", "owner-target.txt"),
            platform_specs.InstallSurface("home", ".owner/skills/graphify/SKILL.md"),
        ),
        risk_notes=(platform_specs.MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE,),
        equivalent_install_command=("graphify", "owner-target", "install", "--project"),
    )

    assert isinstance(scope, platform_specs.ScopeSpec)
    assert scope.install_command == ("graphify", "install", "--project", "--platform", "owner-target")
    assert scope.uninstall_command == ("graphify", "uninstall", "--project", "--platform", "owner-target")
    assert scope.cwd_root == "project"
    assert scope.allowed_roots == ("home", "project", "user_cwd")
    assert [entry.relative for entry in scope.expected] == [
        "owner-target.txt",
        ".owner/skills/graphify/SKILL.md",
    ]
    assert scope.install_variants == (
        platform_specs.InstallCommandVariant(
            "generic",
            ("graphify", "install", "--project", "--platform", "owner-target"),
        ),
        platform_specs.InstallCommandVariant(
            "direct",
            ("graphify", "owner-target", "install", "--project"),
        ),
    )


def test_default_catalog_helpers_live_in_install_target_defaults() -> None:
    helper_names = (
        "default_install_target_catalog",
        "install_target_specs",
        "install_target_spec",
        "install_target_scenarios",
        "platform_spec",
        "platform_scenarios",
        "make_scenario",
        "risk_notes",
        "validate_roots",
    )

    for name in helper_names:
        assert getattr(platform_specs, name) is getattr(install_target_defaults, name)
    assert platform_specs._LAZY_DEFAULT_NAMES is install_target_defaults._LAZY_DEFAULT_NAMES


def test_install_target_accessors_match_legacy_platform_accessors() -> None:
    assert REGISTRY.target_names == REGISTRY.platform_names == platform_specs.ALL_PLATFORMS
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


def test_install_target_module_helpers_match_default_registry() -> None:
    assert platform_specs.default_install_target_catalog() is REGISTRY
    assert platform_specs.install_target_specs() is REGISTRY.specs
    assert platform_specs.install_target_spec("codex") is REGISTRY.target_spec("codex")
    assert platform_specs.install_target_scenarios("cursor", "both") == REGISTRY.target_scenarios("cursor", "both")
    with pytest.raises(RuntimeError, match=r"^unknown sandbox platform: missing-target$"):
        platform_specs.install_target_spec("missing-target")
    with pytest.raises(RuntimeError, match=r"^unknown sandbox platform: missing-target$"):
        platform_specs.install_target_scenarios("missing-target", "both")


def test_install_target_helpers_use_existing_default_registry_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = platform_specs.ScenarioRegistry(
        {
            "cached-target": platform_specs.PlatformSpec(
                name="cached-target",
                scopes={
                    "project": platform_specs.ScopeSpec(
                        install_command=("tool", "install"),
                        uninstall_command=None,
                        cwd_root="project",
                        expected=(platform_specs.ExpectedPath("project", "cached.txt"),),
                    )
                },
            )
        }
    )
    monkeypatch.setattr(install_target_defaults, "_DEFAULT_SCENARIO_REGISTRY", registry)

    assert platform_specs.default_install_target_catalog() is registry
    assert platform_specs.install_target_specs() is registry.specs
    assert platform_specs.install_target_spec("cached-target") is registry.target_spec("cached-target")
    assert platform_specs.install_target_scenarios("cached-target", "project") == registry.target_scenarios(
        "cached-target",
        "project",
    )
    assert "DEFAULT_INSTALL_TARGET_CATALOG" not in platform_specs._LAZY_DEFAULT_NAMES
    assert "DEFAULT_INSTALL_TARGET_CATALOG" not in install_target_defaults._LAZY_DEFAULT_NAMES


def test_lazy_default_catalog_exports_share_one_registry_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    registry = platform_specs.ScenarioRegistry(
        {
            "cached-target": platform_specs.PlatformSpec(
                name="cached-target",
                scopes={
                    "project": platform_specs.ScopeSpec(
                        install_command=("tool", "install"),
                        uninstall_command=None,
                        cwd_root="project",
                        expected=(platform_specs.InstallSurface("project", "cached.txt"),),
                    )
                },
            )
        }
    )

    def load_default_registry():
        nonlocal calls
        calls += 1
        return registry

    monkeypatch.setattr(install_target_defaults, "_DEFAULT_SCENARIO_REGISTRY", None)
    monkeypatch.setitem(install_target_defaults.__dict__, "_import_load_default_registry", lambda: load_default_registry)
    for name in install_target_defaults._LAZY_DEFAULT_NAMES:
        monkeypatch.delitem(platform_specs.__dict__, name, raising=False)
        monkeypatch.delitem(install_target_defaults.__dict__, name, raising=False)

    assert platform_specs.default_install_target_catalog() is registry
    assert platform_specs.install_target_specs() is registry.specs
    assert platform_specs.install_target_spec("cached-target") is registry.target_spec("cached-target")
    assert platform_specs.__getattr__("DEFAULT_SCENARIO_REGISTRY") is registry
    assert platform_specs.__getattr__("SANDBOX_PLATFORM_SPECS") is registry.specs
    assert platform_specs.__getattr__("ALL_PLATFORMS") == ["cached-target"]
    assert install_target_defaults.__getattr__("DEFAULT_SCENARIO_REGISTRY") is registry
    assert calls == 1
    for name in install_target_defaults._LAZY_DEFAULT_NAMES:
        platform_specs.__dict__.pop(name, None)
        install_target_defaults.__dict__.pop(name, None)


def test_every_scope_is_runnable_or_explained() -> None:
    for platform_name in platform_specs.ALL_PLATFORMS:
        for scope in ("user", "project"):
            scenario = REGISTRY.make_scenario(platform_name, scope)
            reason = REGISTRY.unsupported_scope_reason(platform_name, scope)
            assert (scenario is not None) != (reason is not None), f"{platform_name}/{scope} should have exactly one scenario or unsupported reason"
            if scenario is not None:
                assert scenario.expected, f"{platform_name}/{scope} should assert at least one file effect"


def test_cursor_both_scope_selects_project_scenario() -> None:
    both = REGISTRY.platform_scenarios("cursor", "both")

    assert [scenario.scope for scenario in both] == ["project"]


def test_make_scenario_projects_registry_scope_specs() -> None:
    for platform_name in platform_specs.ALL_PLATFORMS:
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


def test_catalog_facade_boundary_preserves_selection_and_synthetic_behavior() -> None:
    installable_scope = platform_specs.ScopeSpec(
        install_command=("tool", "install"),
        uninstall_command=("tool", "uninstall"),
        cwd_root="project",
        expected=(platform_specs.InstallSurface("project", "installed.txt"),),
    )
    universal = platform_specs.UniversalUninstallScenarioSpec(
        scenario_id="uninstall-combo",
        platform_label="declared-combo",
        scope="project",
        command=("tool", "remove", "all"),
        cwd_root="project",
        eligible_platform_scope="project",
        minimum_installed_scenarios=2,
    )
    disposable = platform_specs.DisposableArtifactScenarioSpec(
        scenario_id="purge-cache",
        platform_label="cleanup",
        scope="project",
        command=("tool", "purge"),
        cwd_root="project",
        artifact_subdir="purge",
        disposable_path_root="project",
        disposable_path_relative="cache",
        seed_files=(),
        scope_eligibility=("project",),
        risk_note="synthetic disposable policy",
    )
    registry = platform_specs.InstallTargetCatalog(
        {
            "alpha": platform_specs.InstallTargetSpec(
                name="alpha",
                scopes={"project": installable_scope},
                universal_uninstall_scopes=("project",),
            ),
            "beta": platform_specs.InstallTargetSpec(
                name="beta",
                scopes={"project": installable_scope},
                universal_uninstall_scopes=("project",),
            ),
            "unsupported": platform_specs.InstallTargetSpec(
                name="unsupported",
                unsupported_scopes={"project": "project install is not supported"},
            ),
        },
        universal_uninstall_specs=(universal,),
        disposable_artifact_specs=(disposable,),
    )

    assert registry.selected_targets(all_platforms=True, target_name=None) == ["alpha", "beta", "unsupported"]
    assert registry.selected_platforms(all_platforms=False, platform_name="alpha") == ["alpha"]
    assert [(scenario.platform, scenario.scope) for scenario in registry.target_scenarios("alpha", "project")] == [
        ("alpha", "project")
    ]
    assert registry.platform_scenarios("alpha", "project") == registry.target_scenarios("alpha", "project")
    assert registry.coverage_records(["alpha", "unsupported"], "project") == [
        {
            "platform": "alpha",
            "scope": "project",
            "status": "runnable",
            "scenario_id": "alpha-project",
            "install_command": ["tool", "install"],
            "uninstall_command": ["tool", "uninstall"],
            "generic_direct_equivalence": {
                "status": "not_applicable",
                "reason": "generic and direct commands are unsupported or intentionally differ for this platform/scope",
            },
            "risk_notes": [],
        },
        {
            "platform": "unsupported",
            "scope": "project",
            "status": "unsupported",
            "reason": "project install is not supported",
        },
    ]
    selected = registry.universal_uninstall_scenarios(["alpha", "beta", "unsupported"], "project")
    assert len(selected) == 1
    assert selected[0].spec is universal
    assert [scenario.platform for scenario in selected[0].installed_scenarios] == ["alpha", "beta"]
    assert registry.disposable_artifact_scenarios("project") == [disposable]
    registry.validate_roots({"project"})
    with pytest.raises(RuntimeError, match=r"unknown sandbox root declaration\(s\): project"):
        registry.validate_roots({"home"})


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


def test_default_registry_does_not_own_universal_uninstall_selection() -> None:
    assert REGISTRY.universal_uninstall_groups(["codex", "claude", "gemini"], "project") == []
