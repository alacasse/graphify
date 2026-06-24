from __future__ import annotations

import pytest

from tools.install_sandbox import platform_specs
from tools.install_sandbox.targets import (
    install_target_catalog,
    install_target_defaults,
    install_target_harness_policy,
    install_target_models,
)

from install_target_test_support import REGISTRY


def test_synthetic_policy_scenario_ids() -> None:
    assert (
        install_target_harness_policy.universal_uninstall_scenario_id(
            REGISTRY.universal_uninstall_specs,
            "project",
        )
        == "universal-uninstall-project"
    )
    assert (
        install_target_harness_policy.purge_disposable_graphify_out_scenario_id(
            REGISTRY.disposable_artifact_specs,
        )
        == "purge-disposable-graphify-out"
    )
    assert REGISTRY.universal_uninstall_scenario_id("project") == "universal-uninstall-project"
    assert REGISTRY.purge_disposable_graphify_out_scenario_id() == "purge-disposable-graphify-out"


def test_target_runtime_validation_sections_are_declared_and_deduped() -> None:
    validation = install_target_models.TargetRuntimeValidationSpec(
        section_title="Synthetic Runtime Validation",
        status="declared-only",
        strategy="inspect generated payloads",
        targets=("runtime-a", "runtime-b"),
        notes=("separate runtime smoke tests required",),
        evidence_path="evidence/synthetic.md",
    )
    specs = {
        "runtime-one": install_target_models.PlatformSpec(name="runtime-one", target_runtime_validation=(validation,)),
        "runtime-two": install_target_models.PlatformSpec(name="runtime-two", target_runtime_validation=(validation,)),
    }
    registry = install_target_catalog.ScenarioRegistry(specs)
    expected_sections = [
        {
            "section_title": "Synthetic Runtime Validation",
            "status": "declared-only",
            "evidence_path": "evidence/synthetic.md",
            "strategy": "inspect generated payloads",
            "targets": ["runtime-a", "runtime-b"],
            "notes": ["separate runtime smoke tests required"],
        }
    ]

    assert install_target_harness_policy.target_runtime_validation_sections(specs) == expected_sections
    assert registry.target_runtime_validation_sections() == expected_sections
    assert (
        install_target_harness_policy.target_runtime_validation_sections(
            {"plain": install_target_models.PlatformSpec(name="plain")},
        )
        == []
    )
    assert install_target_catalog.ScenarioRegistry(
        {"plain": install_target_models.PlatformSpec(name="plain")},
    ).target_runtime_validation_sections() == []
    assert install_target_defaults.target_runtime_validation_sections() == REGISTRY.target_runtime_validation_sections()
    assert platform_specs.target_runtime_validation_sections() == REGISTRY.target_runtime_validation_sections()


def test_disposable_artifact_scenarios_are_declared_by_scope() -> None:
    spec = install_target_models.DisposableArtifactScenarioSpec(
        scenario_id="discard-cache",
        platform_label="cache-cleaner",
        scope="project",
        command=("tool", "discard"),
        cwd_root="project",
        artifact_subdir="discard-artifacts",
        disposable_path_root="project",
        disposable_path_relative="tmp-cache",
        seed_files=(install_target_models.DisposableSeedFile("seed.txt", "seed\n"),),
        scope_eligibility=("project",),
        risk_note="synthetic disposable artifact policy",
    )

    assert install_target_harness_policy.disposable_artifact_scenarios((spec,), "project") == [spec]
    assert install_target_harness_policy.disposable_artifact_scenarios((spec,), "user") == []


def test_universal_uninstall_scenarios_return_declared_policy() -> None:
    installable_scope = install_target_models.ScopeSpec(
        install_command=("tool", "install"),
        uninstall_command=None,
        cwd_root="project",
        expected=(install_target_models.ExpectedPath("project", "installed.txt"),),
    )
    universal = install_target_models.UniversalUninstallScenarioSpec(
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
    specs = {
        "alpha": install_target_models.PlatformSpec(
            name="alpha",
            scopes={"project": installable_scope},
            universal_uninstall_scopes=("project",),
        ),
        "beta": install_target_models.PlatformSpec(name="beta", scopes={"project": installable_scope}),
    }

    selected = install_target_harness_policy.universal_uninstall_scenarios(
        specs,
        (universal,),
        ["alpha", "beta"],
        "workspace",
    )

    assert len(selected) == 1
    assert selected[0].spec is universal
    assert selected[0].spec.command == ("tool", "remove", "all")
    assert selected[0].spec.cwd_root == "user_cwd"
    assert [scenario.platform for scenario in selected[0].installed_scenarios] == ["alpha"]


def test_catalog_facade_boundary_preserves_selection_and_synthetic_behavior() -> None:
    installable_scope = install_target_models.ScopeSpec(
        install_command=("tool", "install"),
        uninstall_command=("tool", "uninstall"),
        cwd_root="project",
        expected=(install_target_models.InstallSurface("project", "installed.txt"),),
    )
    universal = install_target_models.UniversalUninstallScenarioSpec(
        scenario_id="uninstall-combo",
        platform_label="declared-combo",
        scope="project",
        command=("tool", "remove", "all"),
        cwd_root="project",
        eligible_platform_scope="project",
        minimum_installed_scenarios=2,
    )
    disposable = install_target_models.DisposableArtifactScenarioSpec(
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
    registry = install_target_catalog.InstallTargetCatalog(
        {
            "alpha": install_target_models.InstallTargetSpec(
                name="alpha",
                scopes={"project": installable_scope},
                universal_uninstall_scopes=("project",),
            ),
            "beta": install_target_models.InstallTargetSpec(
                name="beta",
                scopes={"project": installable_scope},
                universal_uninstall_scopes=("project",),
            ),
            "unsupported": install_target_models.InstallTargetSpec(
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
    specs = {
        "rooted": install_target_models.PlatformSpec(
            name="rooted",
            scopes={
                "project": install_target_models.ScopeSpec(
                    install_command=("tool", "install"),
                    uninstall_command=None,
                    cwd_root="declared-cwd",
                    expected=(install_target_models.ExpectedPath("declared-output", "artifact.txt"),),
                )
            },
        )
    }
    universal_specs = (
        install_target_models.UniversalUninstallScenarioSpec(
            scenario_id="universal",
            platform_label="combo",
            scope="project",
            command=("tool", "uninstall"),
            cwd_root="declared-cwd",
            eligible_platform_scope="project",
        ),
    )
    disposable_specs = (
        install_target_models.DisposableArtifactScenarioSpec(
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
    )

    install_target_harness_policy.validate_roots(
        specs,
        universal_specs,
        disposable_specs,
        {"declared-cwd", "declared-output"},
    )
    install_target_defaults.validate_roots({"home", "project", "user_cwd"})
    with pytest.raises(RuntimeError, match="declared-output"):
        install_target_harness_policy.validate_roots(specs, universal_specs, disposable_specs, {"declared-cwd"})


def test_default_registry_does_not_own_universal_uninstall_selection() -> None:
    assert REGISTRY.universal_uninstall_groups(["codex", "claude", "gemini"], "project") == []
