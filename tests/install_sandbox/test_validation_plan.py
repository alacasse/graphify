from __future__ import annotations

import subprocess
import sys

import pytest

from tools.install_sandbox import platform_specs, validation_plan


def _scope(relative: str = "graphify.txt") -> platform_specs.ScopeSpec:
    return platform_specs.ScopeSpec(
        install_command=("graphify", "install"),
        uninstall_command=("graphify", "uninstall"),
        cwd_root="project",
        expected=(platform_specs.ExpectedPath("project", relative),),
    )


def _planner_registry() -> platform_specs.ScenarioRegistry:
    return platform_specs.ScenarioRegistry(
        {
            "claude": platform_specs.PlatformSpec(
                name="claude",
                scopes={"project": _scope("claude.txt")},
                universal_uninstall_scopes=("project",),
            ),
            "codex": platform_specs.PlatformSpec(
                name="codex",
                scopes={"project": _scope("codex.txt")},
                universal_uninstall_scopes=("project",),
            ),
            "cursor": platform_specs.PlatformSpec(
                name="cursor",
                scopes={"project": _scope("cursor.txt")},
                unsupported_scopes={"user": "user install is not supported"},
            ),
            "gemini": platform_specs.PlatformSpec(
                name="gemini",
                scopes={"project": _scope("gemini.txt")},
                universal_uninstall_scopes=("project",),
            ),
            "windows": platform_specs.PlatformSpec(
                name="windows",
                scopes={"project": _scope("windows.txt")},
                simulated_linux_layout=True,
            ),
        }
    )


def test_validation_plan_orders_all_platforms_and_standard_scenarios() -> None:
    registry = platform_specs.ScenarioRegistry(
        {
            "zeta": platform_specs.PlatformSpec(
                name="zeta",
                scopes={
                    "user": platform_specs.ScopeSpec(
                        install_command=("install", "zeta-user"),
                        uninstall_command=None,
                        cwd_root="user_cwd",
                        expected=(platform_specs.ExpectedPath("home", "zeta-user.txt"),),
                    ),
                    "project": platform_specs.ScopeSpec(
                        install_command=("install", "zeta-project"),
                        uninstall_command=None,
                        cwd_root="project",
                        expected=(platform_specs.ExpectedPath("project", "zeta-project.txt"),),
                    ),
                },
            ),
            "alpha": platform_specs.PlatformSpec(
                name="alpha",
                scopes={
                    "project": platform_specs.ScopeSpec(
                        install_command=("install", "alpha-project"),
                        uninstall_command=None,
                        cwd_root="project",
                        expected=(platform_specs.ExpectedPath("project", "alpha-project.txt"),),
                    )
                },
                unsupported_scopes={"user": "not supported"},
            ),
        }
    )

    plan = validation_plan.build_validation_plan(registry, all_platforms=True, platform_name=None, scope="both")

    assert plan.platforms == ("alpha", "zeta")
    assert [(scenario.platform, scenario.scope) for scenario in plan.standard_scenarios] == [
        ("alpha", "project"),
        ("zeta", "user"),
        ("zeta", "project"),
    ]


def test_validation_plan_rejects_unknown_platform() -> None:
    registry = platform_specs.ScenarioRegistry({"known": platform_specs.PlatformSpec(name="known")})

    with pytest.raises(RuntimeError, match="unknown sandbox platform"):
        validation_plan.build_validation_plan(registry, all_platforms=False, platform_name="missing", scope="project")


def test_validation_plan_preserves_explicit_platform_order_and_full_plan_contents() -> None:
    registry = _planner_registry()

    plan = validation_plan.build_validation_plan(
        registry,
        all_platforms=False,
        platform_name=None,
        selected_platform_names=("gemini", "claude", "codex"),
        scope="project",
    )

    assert plan.platforms == ("gemini", "claude", "codex")
    assert [(scenario.platform, scenario.scope) for scenario in plan.standard_scenarios] == [
        ("gemini", "project"),
        ("claude", "project"),
        ("codex", "project"),
    ]
    assert plan.synthetic_scenario_count == 2
    assert plan.scenario_count == 5
    assert len(plan.universal_uninstall) == 1
    assert plan.universal_uninstall[0].spec.scenario_id == "universal-uninstall-project"
    assert [scenario.platform for scenario in plan.universal_uninstall[0].installed_scenarios] == [
        "gemini",
        "claude",
        "codex",
    ]
    assert [scenario.scenario_id for scenario in plan.disposable_artifacts] == ["purge-disposable-graphify-out"]
    generic_direct_equivalence = {
        "status": "not_applicable",
        "reason": "generic and direct commands are unsupported or intentionally differ for this platform/scope",
    }
    assert plan.coverage_records == (
        {
            "platform": "gemini",
            "scope": "project",
            "status": "runnable",
            "scenario_id": "gemini-project",
            "install_command": ["graphify", "install"],
            "uninstall_command": ["graphify", "uninstall"],
            "generic_direct_equivalence": generic_direct_equivalence,
            "risk_notes": [],
        },
        {
            "platform": "claude",
            "scope": "project",
            "status": "runnable",
            "scenario_id": "claude-project",
            "install_command": ["graphify", "install"],
            "uninstall_command": ["graphify", "uninstall"],
            "generic_direct_equivalence": generic_direct_equivalence,
            "risk_notes": [],
        },
        {
            "platform": "codex",
            "scope": "project",
            "status": "runnable",
            "scenario_id": "codex-project",
            "install_command": ["graphify", "install"],
            "uninstall_command": ["graphify", "uninstall"],
            "generic_direct_equivalence": generic_direct_equivalence,
            "risk_notes": [],
        },
    )
    assert plan.target_runtime_validation_sections == ()
    assert plan.platform_coverage_summary == {
        "registered_platform_count": 3,
        "requested_scope": "project",
        "runnable_scope_count": 3,
        "universal_scenario_count": 2,
        "unsupported_scope_count": 0,
    }
    assert plan.target_runtime_verification == validation_plan.TARGET_RUNTIME_VERIFICATION_POLICY


def test_validation_plan_builds_full_ordered_plan_for_both_scope() -> None:
    registry = platform_specs.ScenarioRegistry(
        {
            "alpha": platform_specs.PlatformSpec(
                name="alpha",
                scopes={
                    "user": _scope("alpha-user.txt"),
                    "project": _scope("alpha-project.txt"),
                },
                universal_uninstall_scopes=("user", "project"),
            ),
            "beta": platform_specs.PlatformSpec(
                name="beta",
                scopes={
                    "user": _scope("beta-user.txt"),
                    "project": _scope("beta-project.txt"),
                },
                universal_uninstall_scopes=("user", "project"),
            ),
        }
    )

    plan = validation_plan.build_validation_plan(
        registry,
        all_platforms=False,
        selected_platform_names=("beta", "alpha"),
        scope="both",
    )

    assert plan.platforms == ("beta", "alpha")
    assert [(scenario.platform, scenario.scope) for scenario in plan.standard_scenarios] == [
        ("beta", "user"),
        ("beta", "project"),
        ("alpha", "user"),
        ("alpha", "project"),
    ]
    assert [selected.spec.scenario_id for selected in plan.universal_uninstall] == [
        "universal-uninstall-user",
        "universal-uninstall-project",
    ]
    assert [
        [(scenario.platform, scenario.scope) for scenario in selected.installed_scenarios]
        for selected in plan.universal_uninstall
    ] == [
        [("beta", "user"), ("alpha", "user")],
        [("beta", "project"), ("alpha", "project")],
    ]
    assert [scenario.scenario_id for scenario in plan.disposable_artifacts] == ["purge-disposable-graphify-out"]
    assert plan.synthetic_scenario_count == 3
    assert plan.scenario_count == 7
    assert plan.platform_coverage_summary == {
        "registered_platform_count": 2,
        "requested_scope": "both",
        "runnable_scope_count": 4,
        "universal_scenario_count": 3,
        "unsupported_scope_count": 0,
    }


def test_validation_plan_rejects_unknown_explicit_platform_names() -> None:
    registry = _planner_registry()

    with pytest.raises(RuntimeError, match="unknown sandbox platform\\(s\\): missing, absent"):
        validation_plan.build_validation_plan(
            registry,
            all_platforms=False,
            platform_name=None,
            selected_platform_names=("gemini", "missing", "absent"),
            scope="project",
        )


def test_validation_plan_derives_universal_uninstall_from_policy_and_target_facts() -> None:
    registry = _planner_registry()

    single = validation_plan.build_validation_plan(registry, all_platforms=False, platform_name="codex", scope="project")
    selected = validation_plan.build_validation_plan(
        registry,
        all_platforms=False,
        platform_name="codex",
        scope="project",
    )
    multi = validation_plan.universal_uninstall_scenarios(registry, ("codex", "claude", "gemini"), "project")

    assert single.universal_uninstall == selected.universal_uninstall == ()
    assert len(multi) == 1
    assert multi[0].spec.scenario_id == "universal-uninstall-project"
    assert [scenario.platform for scenario in multi[0].installed_scenarios] == ["codex", "claude", "gemini"]


def test_validation_plan_derives_disposable_artifacts_by_scope() -> None:
    registry = _planner_registry()

    assert validation_plan.disposable_artifact_scenarios(registry, "user") == ()
    project = validation_plan.disposable_artifact_scenarios(registry, "project")

    assert len(project) == 1
    assert project[0].scenario_id == "purge-disposable-graphify-out"
    assert project[0].command == ("graphify", "uninstall", "--purge")


def test_validation_plan_derives_runtime_limitation_sections_from_policy() -> None:
    registry = _planner_registry()

    sections = validation_plan.target_runtime_validation_sections(registry)

    assert [section["section_title"] for section in sections] == ["Windows Validation"]
    assert sections[0]["status"] == "payload_consistency_only"
    assert sections[0]["evidence_path"] is None
    assert "Windows runtime/path semantics" in sections[0]["strategy"]


def test_validation_plan_runtime_sections_are_limited_to_selected_platforms() -> None:
    registry = platform_specs.ScenarioRegistry(
        {
            "codex": platform_specs.PlatformSpec(name="codex", scopes={"project": _scope("codex.txt")}),
            "windows": platform_specs.PlatformSpec(
                name="windows",
                scopes={"project": _scope("windows.txt")},
                simulated_linux_layout=True,
                target_runtime_validation=(
                    platform_specs.TargetRuntimeValidationSpec(
                        section_title="Unselected Runtime",
                        status="declared",
                        strategy="not selected",
                        targets=("windows",),
                        notes=("must not leak",),
                    ),
                ),
            ),
        }
    )

    selected = validation_plan.build_validation_plan(registry, all_platforms=False, platform_name="codex", scope="project")
    all_platforms = validation_plan.build_validation_plan(registry, all_platforms=True, platform_name=None, scope="project")

    assert selected.target_runtime_validation_sections == ()
    assert [section["section_title"] for section in all_platforms.target_runtime_validation_sections] == [
        "Unselected Runtime",
        "Windows Validation",
    ]


def test_validation_plan_dedupes_explicit_and_policy_runtime_sections() -> None:
    validation = validation_plan.DEFAULT_HARNESS_POLICY.runtime_limitation_sections[0]
    registry = platform_specs.ScenarioRegistry(
        {
            "one": platform_specs.PlatformSpec(
                name="one",
                simulated_linux_layout=True,
                target_runtime_validation=(validation,),
            ),
            "two": platform_specs.PlatformSpec(name="two", simulated_linux_layout=True),
        }
    )

    sections = validation_plan.target_runtime_validation_sections(registry)

    assert len(sections) == 1
    assert sections[0]["section_title"] == "Windows Validation"


def test_validation_plan_coverage_records_unsupported_scopes() -> None:
    registry = _planner_registry()
    records = validation_plan.coverage_records(registry, ("cursor",), "both")
    user = next(record for record in records if record["scope"] == "user")
    project = next(record for record in records if record["scope"] == "project")

    assert user["status"] == "unsupported"
    assert "reason" in user
    assert project["status"] == "runnable"


def test_harness_policy_validates_owned_roots() -> None:
    validation_plan.DEFAULT_HARNESS_POLICY.validate_roots({"home", "project", "user_cwd"})
    policy = validation_plan.HarnessPolicy(
        universal_uninstall_specs=(
            platform_specs.UniversalUninstallScenarioSpec(
                scenario_id="bad",
                platform_label="bad",
                scope="project",
                command=("bad",),
                cwd_root="missing-cwd",
                eligible_platform_scope="project",
            ),
        ),
        disposable_artifact_specs=(),
        runtime_limitation_sections=validation_plan.DEFAULT_HARNESS_POLICY.runtime_limitation_sections,
    )

    with pytest.raises(RuntimeError, match="missing-cwd"):
        policy.validate_roots({"project"})


def test_validation_plan_supports_direct_script_import_fallback() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, 'tools/install_sandbox'); from validation_plan import build_validation_plan; print(build_validation_plan.__name__)",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "build_validation_plan"
