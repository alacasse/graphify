from __future__ import annotations

import pytest

from tools.install_sandbox import validation_plan
from tools.install_sandbox.targets import install_target_catalog, install_target_models
from tests.install_sandbox.validation_plan_test_support import planner_registry, scope


def test_validation_plan_derives_universal_uninstall_from_policy_and_target_facts() -> None:
    registry = planner_registry()

    single = validation_plan.build_validation_plan(registry, all_targets=False, target_name="codex", scope="project")
    selected = validation_plan.build_validation_plan(
        registry,
        all_targets=False,
        target_name="codex",
        scope="project",
    )
    multi = validation_plan.build_validation_plan(
        registry,
        all_targets=False,
        target_name=None,
        selected_target_names=("codex", "claude", "gemini"),
        scope="project",
    )

    assert single.universal_uninstall == selected.universal_uninstall == ()
    assert len(multi.universal_uninstall) == 1
    assert multi.universal_uninstall[0].spec.scenario_id == "universal-uninstall-project"
    assert [scenario.target_name for scenario in multi.universal_uninstall[0].installed_scenarios] == [
        "codex",
        "claude",
        "gemini",
    ]


def test_validation_plan_derives_disposable_artifacts_by_scope() -> None:
    registry = planner_registry()

    user = validation_plan.build_validation_plan(registry, all_targets=False, target_name="codex", scope="user")
    project = validation_plan.build_validation_plan(registry, all_targets=False, target_name="codex", scope="project")

    assert user.disposable_artifacts == ()
    assert len(project.disposable_artifacts) == 1
    assert project.disposable_artifacts[0].scenario_id == "purge-disposable-graphify-out"
    assert project.disposable_artifacts[0].command == ("graphify", "uninstall", "--purge")


def test_validation_plan_derives_runtime_limitation_sections_from_policy() -> None:
    registry = planner_registry()

    plan = validation_plan.build_validation_plan(registry, all_targets=False, target_name="windows", scope="project")
    sections = plan.target_runtime_validation_sections

    assert [section["section_title"] for section in sections] == ["Windows Validation"]
    assert sections[0]["status"] == "payload_consistency_only"
    assert sections[0]["evidence_path"] is None
    assert "Windows runtime/path semantics" in sections[0]["strategy"]


def test_validation_plan_runtime_sections_are_limited_to_selected_targets() -> None:
    selected_runtime = install_target_models.TargetRuntimeValidationSpec(
        section_title="Selected Runtime",
        status="runtime_validated",
        evidence_path="runtime/selected-evidence.json",
        strategy="run the selected platform against its target runtime",
        targets=("selected target app", "selected cleanup behavior"),
        notes=("captures runtime-only integration behavior", "keeps report metadata explicit"),
    )
    unselected_runtime = install_target_models.TargetRuntimeValidationSpec(
        section_title="Unselected Runtime",
        status="declared",
        evidence_path="runtime/unselected-evidence.json",
        strategy="not selected",
        targets=("windows",),
        notes=("must not leak",),
    )
    registry = install_target_catalog.InstallTargetCatalog(
        {
            "codex": install_target_models.InstallTargetSpec(
                name="codex",
                scopes={"project": scope("codex.txt")},
                target_runtime_validation=(selected_runtime,),
            ),
            "windows": install_target_models.InstallTargetSpec(
                name="windows",
                scopes={"project": scope("windows.txt")},
                simulated_linux_layout=True,
                target_runtime_validation=(unselected_runtime,),
            ),
        }
    )

    selected = validation_plan.build_validation_plan(registry, all_targets=False, target_name="codex", scope="project")
    all_targets = validation_plan.build_validation_plan(registry, all_targets=True, target_name=None, scope="project")

    assert selected.target_runtime_validation_sections == (
        {
            "section_title": "Selected Runtime",
            "status": "runtime_validated",
            "evidence_path": "runtime/selected-evidence.json",
            "strategy": "run the selected platform against its target runtime",
            "targets": ["selected target app", "selected cleanup behavior"],
            "notes": ["captures runtime-only integration behavior", "keeps report metadata explicit"],
        },
    )
    assert all_targets.target_runtime_validation_sections == (
        {
            "section_title": "Selected Runtime",
            "status": "runtime_validated",
            "evidence_path": "runtime/selected-evidence.json",
            "strategy": "run the selected platform against its target runtime",
            "targets": ["selected target app", "selected cleanup behavior"],
            "notes": ["captures runtime-only integration behavior", "keeps report metadata explicit"],
        },
        {
            "section_title": "Unselected Runtime",
            "status": "declared",
            "evidence_path": "runtime/unselected-evidence.json",
            "strategy": "not selected",
            "targets": ["windows"],
            "notes": ["must not leak"],
        },
        validation_plan.DEFAULT_HARNESS_POLICY.runtime_limitation_sections[0].to_manifest(),
    )


def test_validation_plan_dedupes_explicit_and_policy_runtime_sections() -> None:
    validation = validation_plan.DEFAULT_HARNESS_POLICY.runtime_limitation_sections[0]
    registry = install_target_catalog.InstallTargetCatalog(
        {
            "one": install_target_models.InstallTargetSpec(
                name="one",
                simulated_linux_layout=True,
                target_runtime_validation=(validation,),
            ),
            "two": install_target_models.InstallTargetSpec(name="two", simulated_linux_layout=True),
        }
    )

    plan = validation_plan.build_validation_plan(registry, all_targets=True, target_name=None, scope="project")
    sections = plan.target_runtime_validation_sections

    assert len(sections) == 1
    assert sections[0]["section_title"] == "Windows Validation"


def test_validation_plan_coverage_records_unsupported_scopes() -> None:
    registry = planner_registry()
    plan = validation_plan.build_validation_plan(registry, all_targets=False, target_name="cursor", scope="both")
    records = plan.coverage_records
    user = next(record for record in records if record["scope"] == "user")
    project = next(record for record in records if record["scope"] == "project")

    assert user["status"] == "unsupported"
    assert "reason" in user
    assert project["status"] == "runnable"


def test_harness_policy_validates_owned_roots() -> None:
    validation_plan.DEFAULT_HARNESS_POLICY.validate_roots({"home", "project", "user_cwd"})
    policy = validation_plan.HarnessPolicy(
        universal_uninstall_specs=(
            install_target_models.UniversalUninstallScenarioSpec(
                scenario_id="bad",
                synthetic_result_label="bad",
                scope="project",
                command=("bad",),
                cwd_root="missing-cwd",
                eligible_target_scope="project",
            ),
        ),
        disposable_artifact_specs=(),
        runtime_limitation_sections=validation_plan.DEFAULT_HARNESS_POLICY.runtime_limitation_sections,
    )

    with pytest.raises(RuntimeError, match="missing-cwd"):
        policy.validate_roots({"project"})
