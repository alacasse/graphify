from __future__ import annotations

import subprocess
import sys

import pytest

from tools.install_sandbox import validation_plan
from tools.install_sandbox.harness_specs import DEFAULT_SANDBOX_ROOT_REGISTRY, SandboxRootRegistry, SandboxRootSpec
from tools.install_sandbox.targets import install_target_catalog, install_target_models
from tests.install_sandbox.validation_plan_test_support import planner_registry, scope


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
