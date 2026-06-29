from __future__ import annotations

import subprocess
import sys

import pytest

from tools.install_sandbox import validation_plan
from tools.install_sandbox.harness_specs import DEFAULT_SANDBOX_ROOT_REGISTRY, SandboxRootRegistry, SandboxRootSpec
from tools.install_sandbox.targets import install_target_catalog, install_target_models
from tests.install_sandbox.validation_plan_test_support import planner_registry, scope


def test_validation_plan_derives_universal_uninstall_from_policy_and_target_facts() -> None:
    registry = planner_registry()

    single = validation_plan.build_validation_plan(registry, all_platforms=False, platform_name="codex", scope="project")
    selected = validation_plan.build_validation_plan(
        registry,
        all_platforms=False,
        platform_name="codex",
        scope="project",
    )
    multi = validation_plan.build_validation_plan(
        registry,
        all_platforms=False,
        platform_name=None,
        selected_platform_names=("codex", "claude", "gemini"),
        scope="project",
    )

    assert single.universal_uninstall == selected.universal_uninstall == ()
    assert len(multi.universal_uninstall) == 1
    assert multi.universal_uninstall[0].spec.scenario_id == "universal-uninstall-project"
    assert [scenario.platform for scenario in multi.universal_uninstall[0].installed_scenarios] == [
        "codex",
        "claude",
        "gemini",
    ]


def test_validation_plan_derives_disposable_artifacts_by_scope() -> None:
    registry = planner_registry()

    user = validation_plan.build_validation_plan(registry, all_platforms=False, platform_name="codex", scope="user")
    project = validation_plan.build_validation_plan(registry, all_platforms=False, platform_name="codex", scope="project")

    assert user.disposable_artifacts == ()
    assert len(project.disposable_artifacts) == 1
    assert project.disposable_artifacts[0].scenario_id == "purge-disposable-graphify-out"
    assert project.disposable_artifacts[0].command == ("graphify", "uninstall", "--purge")


def test_validation_plan_derives_runtime_limitation_sections_from_policy() -> None:
    registry = planner_registry()

    plan = validation_plan.build_validation_plan(registry, all_platforms=False, platform_name="windows", scope="project")
    sections = plan.target_runtime_validation_sections

    assert [section["section_title"] for section in sections] == ["Windows Validation"]
    assert sections[0]["status"] == "payload_consistency_only"
    assert sections[0]["evidence_path"] is None
    assert "Windows runtime/path semantics" in sections[0]["strategy"]


def test_validation_plan_runtime_sections_are_limited_to_selected_platforms() -> None:
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
    registry = install_target_catalog.ScenarioRegistry(
        {
            "codex": install_target_models.PlatformSpec(
                name="codex",
                scopes={"project": scope("codex.txt")},
                target_runtime_validation=(selected_runtime,),
            ),
            "windows": install_target_models.PlatformSpec(
                name="windows",
                scopes={"project": scope("windows.txt")},
                simulated_linux_layout=True,
                target_runtime_validation=(unselected_runtime,),
            ),
        }
    )

    selected = validation_plan.build_validation_plan(registry, all_platforms=False, platform_name="codex", scope="project")
    all_platforms = validation_plan.build_validation_plan(registry, all_platforms=True, platform_name=None, scope="project")

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
    assert all_platforms.target_runtime_validation_sections == (
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
    registry = install_target_catalog.ScenarioRegistry(
        {
            "one": install_target_models.PlatformSpec(
                name="one",
                simulated_linux_layout=True,
                target_runtime_validation=(validation,),
            ),
            "two": install_target_models.PlatformSpec(name="two", simulated_linux_layout=True),
        }
    )

    plan = validation_plan.build_validation_plan(registry, all_platforms=True, platform_name=None, scope="project")
    sections = plan.target_runtime_validation_sections

    assert len(sections) == 1
    assert sections[0]["section_title"] == "Windows Validation"


def test_validation_plan_coverage_records_unsupported_scopes() -> None:
    registry = planner_registry()
    plan = validation_plan.build_validation_plan(registry, all_platforms=False, platform_name="cursor", scope="both")
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


def test_build_validation_plan_validates_target_roots_before_selected_policy_roots() -> None:
    calls: list[tuple[str, set[str]]] = []

    class Registry:
        specs = {"codex": install_target_models.PlatformSpec(name="codex")}
        universal_uninstall_specs = ()
        disposable_artifact_specs = ()

        def validate_target_roots(self, declared_roots: set[str]) -> None:
            calls.append(("target", declared_roots))

        def validate_roots(self, declared_roots: set[str]) -> None:
            raise AssertionError("build_validation_plan should use the target-root owner when available")

        def platform_spec(self, platform_name: str) -> install_target_models.PlatformSpec:
            return self.specs[platform_name]

        def make_scenario(self, platform_name: str, scope: str):
            return None

        def coverage_records(self, platforms: list[str], scope: str) -> list[dict[str, object]]:
            return []

    policy = validation_plan.HarnessPolicy(
        universal_uninstall_specs=(
            install_target_models.UniversalUninstallScenarioSpec(
                scenario_id="repo-mounted-uninstall",
                platform_label="repo-mounted",
                scope="project",
                command=("graphify", "uninstall", "--project"),
                cwd_root="repo_mount",
                eligible_platform_scope="project",
            ),
        ),
        disposable_artifact_specs=(),
        runtime_limitation_sections=validation_plan.DEFAULT_HARNESS_POLICY.runtime_limitation_sections,
    )

    with pytest.raises(RuntimeError, match="repo_mount"):
        validation_plan.build_validation_plan(
            Registry(),
            all_platforms=False,
            platform_name="codex",
            scope="project",
            policy=policy,
            root_registry=DEFAULT_SANDBOX_ROOT_REGISTRY,
        )

    assert calls == [("target", {"home", "project", "user_cwd"})]


def test_build_validation_plan_consumes_install_surface_root_role_for_validation() -> None:
    class RootRegistry:
        def __init__(self) -> None:
            self.calls = 0

        def install_surface_root_names(self) -> set[str]:
            self.calls += 1
            return {"home", "project", "user_cwd"}

    root_registry = RootRegistry()

    plan = validation_plan.build_validation_plan(
        planner_registry(),
        all_platforms=False,
        platform_name="codex",
        scope="project",
        root_registry=root_registry,  # type: ignore[arg-type]
    )

    assert plan.platforms == ("codex",)
    assert root_registry.calls == 2


def test_build_validation_plan_keeps_target_roots_limited_to_install_surface_roots() -> None:
    registry = install_target_catalog.ScenarioRegistry(
        {
            "repo-mounted": install_target_models.PlatformSpec(
                name="repo-mounted",
                scopes={
                    "project": install_target_models.ScopeSpec(
                        install_command=("tool", "install"),
                        uninstall_command=None,
                        cwd_root="repo_mount",
                        expected=(),
                    )
                },
            )
        }
    )

    with pytest.raises(RuntimeError, match="repo_mount"):
        validation_plan.build_validation_plan(registry, all_platforms=True, platform_name=None, scope="project")


def test_build_validation_plan_policy_validation_uses_install_surface_roots_not_all_runtime_roots() -> None:
    root_registry = SandboxRootRegistry(
        (
            SandboxRootSpec("home", "/tmp/graphify-home"),
            SandboxRootSpec("project", "/tmp/graphify-project"),
            SandboxRootSpec("user_cwd", "/tmp/graphify-user-cwd"),
            SandboxRootSpec("policy_cwd", "/tmp/policy-cwd"),
        )
    )
    policy = validation_plan.HarnessPolicy(
        universal_uninstall_specs=(
            install_target_models.UniversalUninstallScenarioSpec(
                scenario_id="policy-cwd-uninstall",
                platform_label="policy-cwd",
                scope="project",
                command=("graphify", "uninstall", "--project"),
                cwd_root="policy_cwd",
                eligible_platform_scope="project",
            ),
        ),
        disposable_artifact_specs=(),
        runtime_limitation_sections=validation_plan.DEFAULT_HARNESS_POLICY.runtime_limitation_sections,
    )

    with pytest.raises(RuntimeError, match="policy_cwd"):
        validation_plan.build_validation_plan(
            planner_registry(),
            all_platforms=False,
            platform_name="codex",
            scope="project",
            policy=policy,
            root_registry=root_registry,
        )


def test_build_validation_plan_validates_registry_specific_synthetic_policy_roots() -> None:
    registry = install_target_catalog.ScenarioRegistry(
        {
            "alpha": install_target_models.PlatformSpec(
                name="alpha",
                scopes={"project": scope("alpha.txt")},
                universal_uninstall_scopes=("project",),
            ),
        },
        universal_uninstall_specs=(
            install_target_models.UniversalUninstallScenarioSpec(
                scenario_id="custom-uninstall",
                platform_label="custom",
                scope="project",
                command=("tool", "uninstall"),
                cwd_root="missing-universal-root",
                eligible_platform_scope="project",
            ),
        ),
        disposable_artifact_specs=(
            install_target_models.DisposableArtifactScenarioSpec(
                scenario_id="custom-disposable",
                platform_label="custom",
                scope="project",
                command=("tool", "purge"),
                cwd_root="project",
                artifact_subdir="custom-disposable",
                disposable_path_root="missing-disposable-root",
                disposable_path_relative="cache",
                seed_files=(),
                scope_eligibility=("project",),
                risk_note="custom disposable artifact policy",
            ),
        ),
    )

    with pytest.raises(RuntimeError) as excinfo:
        validation_plan.build_validation_plan(registry, all_platforms=True, platform_name=None, scope="project")

    message = str(excinfo.value)
    assert "unknown harness policy root declaration" in message
    assert "missing-universal-root" in message
    assert "missing-disposable-root" in message


def test_validation_plan_supports_direct_script_import_fallback() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, 'tools/install_sandbox'); "
            "from validation_plan import ValidationWorkItem, build_validation_plan; "
            "print(build_validation_plan.__name__, ValidationWorkItem.__name__)",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "build_validation_plan ValidationWorkItem"
