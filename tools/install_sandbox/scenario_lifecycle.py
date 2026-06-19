from __future__ import annotations

import inspect
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

try:
    from . import validation_plan
    from .scenario_lifecycle_support import (
        CommandExecutor,
        DisposableArtifactOutcome,
        MatrixRunnerOverrides,
        SandboxPaths,
        ScenarioArtifacts,
        ScenarioFileEffects,
        ScenarioLifecycleHooks,
        ScenarioResultOutcome,
        ScenarioRunContext,
        StandardScenarioOutcome,
        StandardScenarioStages,
        UniversalUninstallOutcome,
        prepare_scenario_run,
        scenario_artifact_dir,
        scenario_duration_ms,
    )
    from .scenario_lifecycle_standard import (
        INITIAL_INSTALL_PHASE,
        REPEAT_INSTALL_PHASE,
        STALE_SIDECAR_REPAIR_PHASE,
        UNINSTALL_PHASE,
        StandardLifecycleMechanics,
        StandardLifecyclePhase,
        finalize_standard_scenario,
        run_equivalence_stage,
        run_initial_install,
        run_repeat_install,
        run_scenario,
        run_stale_sidecar_repair,
        run_uninstall_stage,
        standard_scenario_checks,
        standard_scenario_command_ok,
    )
    from .scenario_lifecycle_universal import (
        UniversalUninstallLifecycle,
        run_universal_uninstall_scenario,
        universal_uninstall_spec_for_scope,
    )
    from .platform_specs import DEFAULT_SCENARIO_REGISTRY, DisposableArtifactScenarioSpec, Scenario, ScenarioRegistry, SelectedUniversalUninstallScenario
except ImportError:
    import validation_plan  # type: ignore[no-redef]
    from scenario_lifecycle_support import (  # type: ignore[no-redef]
        CommandExecutor,
        DisposableArtifactOutcome,
        MatrixRunnerOverrides,
        SandboxPaths,
        ScenarioArtifacts,
        ScenarioFileEffects,
        ScenarioLifecycleHooks,
        ScenarioResultOutcome,
        ScenarioRunContext,
        StandardScenarioOutcome,
        StandardScenarioStages,
        UniversalUninstallOutcome,
        prepare_scenario_run,
        scenario_artifact_dir,
        scenario_duration_ms,
    )
    from scenario_lifecycle_standard import (  # type: ignore[no-redef]
        INITIAL_INSTALL_PHASE,
        REPEAT_INSTALL_PHASE,
        STALE_SIDECAR_REPAIR_PHASE,
        UNINSTALL_PHASE,
        StandardLifecycleMechanics,
        StandardLifecyclePhase,
        finalize_standard_scenario,
        run_equivalence_stage,
        run_initial_install,
        run_repeat_install,
        run_scenario,
        run_stale_sidecar_repair,
        run_uninstall_stage,
        standard_scenario_checks,
        standard_scenario_command_ok,
    )
    from scenario_lifecycle_universal import (  # type: ignore[no-redef]
        UniversalUninstallLifecycle,
        run_universal_uninstall_scenario,
        universal_uninstall_spec_for_scope,
    )
    from platform_specs import DEFAULT_SCENARIO_REGISTRY, DisposableArtifactScenarioSpec, Scenario, ScenarioRegistry, SelectedUniversalUninstallScenario


@dataclass(frozen=True)
class DisposableArtifactLifecycle:
    spec: DisposableArtifactScenarioSpec
    env: dict[str, str]
    hooks: ScenarioLifecycleHooks

    @property
    def scenario_name(self) -> str:
        return self.spec.scenario_id

    @property
    def command(self) -> tuple[str, ...]:
        return self.spec.command

    @property
    def disposable_path(self) -> Path:
        return self.hooks.paths.root_path(self.spec.disposable_path_root) / self.spec.disposable_path_relative

    def runner_scenario(self) -> Scenario:
        return Scenario(
            platform=self.spec.platform_label,
            scope=self.spec.scope,
            install_command=self.command,
            uninstall_command=None,
            cwd_root=self.spec.cwd_root,
            expected=(),
        )

    def prepare_context(self, runner_scenario: Scenario) -> ScenarioRunContext:
        return prepare_scenario_run(runner_scenario, self.env, hooks=self.hooks, scenario_name=self.scenario_name)

    def seed_disposable_artifact(self) -> None:
        self.disposable_path.mkdir(parents=True, exist_ok=True)
        for seed in self.spec.seed_files:
            path = self.disposable_path / seed.relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(seed.content, encoding="utf-8")

    def write_before_install_manifest(self, context: ScenarioRunContext) -> None:
        self.hooks.file_effects.write_manifest(context.artifact_dir / "before-install-files.json", self.hooks.paths.roots)

    def write_after_uninstall_manifest(self, context: ScenarioRunContext) -> None:
        self.hooks.file_effects.write_manifest(context.artifact_dir / "after-uninstall-files.json", self.hooks.paths.roots)

    def command_artifact_dir(self, context: ScenarioRunContext) -> Path:
        return context.artifact_dir / self.spec.artifact_subdir

    def run_disposable_command(self, context: ScenarioRunContext) -> subprocess.CompletedProcess[str]:
        return self.hooks.commands.capture(
            self.command,
            cwd=self.hooks.paths.root_path(self.spec.cwd_root),
            env=self.env,
            artifact_dir=self.command_artifact_dir(context),
            command_class="installer",
        )

    def removed(self) -> bool:
        return not self.disposable_path.exists()

    def checks(self, removed: bool) -> list[dict[str, object]]:
        return self.hooks.file_effects.disposable_artifact_checks(self.disposable_path, removed)

    def outcome(self, context: ScenarioRunContext) -> DisposableArtifactOutcome:
        self.seed_disposable_artifact()
        self.write_before_install_manifest(context)
        result = self.run_disposable_command(context)
        removed = self.removed()
        self.write_after_uninstall_manifest(context)
        return DisposableArtifactOutcome(
            scenario_name=self.scenario_name,
            platform_label=self.spec.platform_label,
            scope_name=self.spec.scope,
            command=self.command,
            result=result,
            checks=self.checks(removed),
            removed=removed,
            command_artifact_dir_path=self.command_artifact_dir(context),
            risk_note=self.spec.risk_note,
        )

    def run(self) -> dict[str, object]:
        runner_scenario = self.runner_scenario()
        context = self.prepare_context(runner_scenario)
        return self.hooks.artifacts.purge_result(context, self.outcome(context))


def run_purge_scenario(env: dict[str, str], *, hooks: ScenarioLifecycleHooks) -> dict[str, object]:
    scenarios = disposable_artifact_scenarios("project", hooks=hooks)
    if not scenarios:
        raise RuntimeError("no disposable artifact scenario declaration for project scope")
    return DisposableArtifactLifecycle(scenarios[0], env, hooks).run()


def run_disposable_artifact_scenario(spec: DisposableArtifactScenarioSpec, env: dict[str, str], *, hooks: ScenarioLifecycleHooks) -> dict[str, object]:
    return DisposableArtifactLifecycle(spec, env, hooks).run()


def disposable_artifact_scenarios(scope: str, *, hooks: ScenarioLifecycleHooks) -> list[DisposableArtifactScenarioSpec]:
    specs = hooks.scenario_registry.disposable_artifact_specs or validation_plan.DEFAULT_HARNESS_POLICY.disposable_artifact_specs
    return [spec for spec in specs if scope in spec.scope_eligibility]


def _positional_parameter_count(callback: Callable[..., object]) -> int | None:
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        return None
    count = 0
    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_POSITIONAL:
            return None
        if parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
            count += 1
    return count


def _run_universal_override(
    callback: Callable[..., dict[str, object]],
    selected: SelectedUniversalUninstallScenario,
    env: dict[str, str],
) -> dict[str, object]:
    if _positional_parameter_count(callback) == 3:
        return callback(selected.spec.scope, list(selected.installed_scenarios), env)
    return callback(selected, env)


def _run_purge_override(
    callback: Callable[..., dict[str, object]],
    spec: DisposableArtifactScenarioSpec,
    env: dict[str, str],
) -> dict[str, object]:
    if _positional_parameter_count(callback) == 1:
        return callback(env)
    return callback(spec, env)


def run_validation_plan(plan: validation_plan.ValidationPlan, env: dict[str, str], hooks: ScenarioLifecycleHooks, fail_fast_scenarios: bool = False) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    overrides = hooks.matrix_overrides
    run_one = overrides.run_scenario or (lambda scenario, scenario_env: run_scenario(scenario, scenario_env, hooks=hooks))
    run_universal = overrides.run_universal_uninstall_scenario or (
        lambda selected, scenario_env: run_universal_uninstall_scenario(selected, env=scenario_env, hooks=hooks)
    )
    run_disposable = (
        overrides.run_purge_scenario
        or overrides.run_disposable_artifact_scenario
        or (lambda spec, scenario_env: run_disposable_artifact_scenario(spec, scenario_env, hooks=hooks))
    )
    for scenario in plan.standard_scenarios:
        result = run_one(scenario, env)
        results.append(result)
        if fail_fast_scenarios and result.get("passed") is not True:
            return results
    if any(result.get("passed") is not True for result in results):
        return results
    for selected in plan.universal_uninstall_scenarios:
        result = (
            _run_universal_override(run_universal, selected, env)
            if overrides.run_universal_uninstall_scenario is not None
            else run_universal(selected, env)
        )
        results.append(result)
    for disposable_spec in plan.disposable_artifact_scenarios:
        result = (
            _run_purge_override(run_disposable, disposable_spec, env)
            if overrides.run_purge_scenario is not None
            else run_disposable(disposable_spec, env)
        )
        results.append(result)
    return results


def run_matrix_scenarios(platforms: list[str], scope: str, env: dict[str, str], *, hooks: ScenarioLifecycleHooks, fail_fast_scenarios: bool = False) -> list[dict[str, object]]:
    plan = validation_plan.build_validation_plan(
        hooks.scenario_registry,
        all_platforms=False,
        selected_platform_names=platforms,
        scope=scope,
    )
    return run_validation_plan(plan, env, hooks, fail_fast_scenarios=fail_fast_scenarios)
