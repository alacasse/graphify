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
    from .platform_specs import DEFAULT_SCENARIO_REGISTRY, DisposableArtifactScenarioSpec, Scenario, ScenarioRegistry, SelectedUniversalUninstallScenario, UniversalUninstallScenarioSpec
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
    from platform_specs import DEFAULT_SCENARIO_REGISTRY, DisposableArtifactScenarioSpec, Scenario, ScenarioRegistry, SelectedUniversalUninstallScenario, UniversalUninstallScenarioSpec


@dataclass(frozen=True)
class StandardLifecyclePhase:
    check_phase: str
    artifact_subdir: str | None = None
    manifest_filename: str | None = None


INITIAL_INSTALL_PHASE = StandardLifecyclePhase("install", manifest_filename="after-install-files.json")
REPEAT_INSTALL_PHASE = StandardLifecyclePhase("repeat_install", artifact_subdir="repeat-install", manifest_filename="after-repeat-install-files.json")
STALE_SIDECAR_REPAIR_PHASE = StandardLifecyclePhase(
    "stale_sidecar_repair",
    artifact_subdir="stale-sidecar-repair",
    manifest_filename="after-stale-sidecar-repair-files.json",
)
UNINSTALL_PHASE = StandardLifecyclePhase("uninstall", artifact_subdir="uninstall", manifest_filename="after-uninstall-files.json")


@dataclass(frozen=True)
class StandardLifecycleMechanics:
    context: ScenarioRunContext
    hooks: ScenarioLifecycleHooks

    @property
    def scenario(self) -> Scenario:
        return self.context.scenario

    @property
    def artifact_dir(self) -> Path:
        return self.context.artifact_dir

    def command_artifact_dir(self, phase: StandardLifecyclePhase) -> Path:
        if phase.artifact_subdir is None:
            return self.artifact_dir
        return self.artifact_dir / phase.artifact_subdir

    def capture(self, command: tuple[str, ...], phase: StandardLifecyclePhase) -> subprocess.CompletedProcess[str]:
        return self.hooks.commands.capture(
            command,
            cwd=self.context.cwd,
            env=self.context.env,
            artifact_dir=self.command_artifact_dir(phase),
            command_class="installer",
        )

    def write_manifest(self, filename: str) -> None:
        self.hooks.file_effects.write_manifest(self.artifact_dir / filename, self.hooks.paths.roots, scenario=self.scenario)

    def write_phase_manifest(self, phase: StandardLifecyclePhase) -> None:
        if phase.manifest_filename is None:
            return
        self.write_manifest(phase.manifest_filename)

    def unexpected_checks(self, phase: StandardLifecyclePhase) -> list[dict[str, object]]:
        return self.hooks.file_effects.unexpected_checks(self.scenario, phase=phase.check_phase)

    def state(self) -> dict[str, dict[str, object]]:
        return self.hooks.file_effects.capture_state(self.scenario)

    def copy_generated_files(self) -> None:
        self.hooks.file_effects.archive_generated_files(self.scenario, self.artifact_dir)


def run_initial_install(context: ScenarioRunContext, *, hooks: ScenarioLifecycleHooks) -> StandardScenarioStages:
    scenario = context.scenario
    lifecycle = StandardLifecycleMechanics(context, hooks)
    hooks.file_effects.seed_scenario_inputs(scenario)
    lifecycle.write_manifest("before-install-files.json")

    install_1 = lifecycle.capture(scenario.install_command, INITIAL_INSTALL_PHASE)
    state_after_install = lifecycle.state()
    install_checks = hooks.file_effects.install_checks(scenario)
    scope_checks: list[dict[str, object]] = []
    unexpected_install_checks = lifecycle.unexpected_checks(INITIAL_INSTALL_PHASE)
    lifecycle.write_phase_manifest(INITIAL_INSTALL_PHASE)
    lifecycle.copy_generated_files()
    return StandardScenarioStages(
        install_1=install_1,
        state_after_install=state_after_install,
        install_checks=install_checks,
        scope_checks=scope_checks,
        unexpected_install_checks=unexpected_install_checks,
    )


def run_repeat_install(context: ScenarioRunContext, stages: StandardScenarioStages, *, hooks: ScenarioLifecycleHooks) -> None:
    scenario = context.scenario
    lifecycle = StandardLifecycleMechanics(context, hooks)
    stages.install_2 = lifecycle.capture(scenario.install_command, REPEAT_INSTALL_PHASE)
    stages.state_after_repeat = lifecycle.state()
    stages.idempotency_checks = hooks.file_effects.repeat_install_checks(
        scenario,
        stages.state_after_install,
        stages.state_after_repeat,
        phase=REPEAT_INSTALL_PHASE.check_phase,
    )
    lifecycle.write_phase_manifest(REPEAT_INSTALL_PHASE)


def run_stale_sidecar_repair(context: ScenarioRunContext, stages: StandardScenarioStages, *, hooks: ScenarioLifecycleHooks) -> None:
    scenario = context.scenario
    lifecycle = StandardLifecycleMechanics(context, hooks)
    stages.stale_sidecar_repair_seeded = hooks.file_effects.seed_stale_sidecar_repair(scenario)
    if not stages.stale_sidecar_repair_seeded:
        return
    stages.stale_sidecar_repair_result = lifecycle.capture(scenario.install_command, STALE_SIDECAR_REPAIR_PHASE)
    if stages.stale_sidecar_repair_result.returncode == 0:
        stages.stale_sidecar_repair_checks = hooks.file_effects.stale_sidecar_repair_checks(
            scenario,
            phase=STALE_SIDECAR_REPAIR_PHASE.check_phase,
        )
    lifecycle.write_phase_manifest(STALE_SIDECAR_REPAIR_PHASE)


def run_uninstall_stage(context: ScenarioRunContext, stages: StandardScenarioStages, *, hooks: ScenarioLifecycleHooks) -> None:
    scenario = context.scenario
    if not scenario.uninstall_command:
        return
    lifecycle = StandardLifecycleMechanics(context, hooks)
    stages.uninstall_result = lifecycle.capture(scenario.uninstall_command, UNINSTALL_PHASE)
    stages.uninstall_checks = hooks.file_effects.uninstall_checks(scenario, phase=UNINSTALL_PHASE.check_phase)
    stages.unexpected_uninstall_checks = []
    lifecycle.write_phase_manifest(UNINSTALL_PHASE)


def run_equivalence_stage(context: ScenarioRunContext, stages: StandardScenarioStages, *, hooks: ScenarioLifecycleHooks) -> None:
    stages.equivalence_checks = hooks.file_effects.equivalence_checks(context.scenario, context.env, context.artifact_dir)


def standard_scenario_checks(stages: StandardScenarioStages) -> list[dict[str, object]]:
    return (
        stages.install_checks
        + stages.scope_checks
        + stages.unexpected_install_checks
        + stages.idempotency_checks
        + stages.stale_sidecar_repair_checks
        + stages.uninstall_checks
        + stages.unexpected_uninstall_checks
        + stages.equivalence_checks
    )


def standard_scenario_command_ok(stages: StandardScenarioStages) -> bool:
    return (
        stages.install_1.returncode == 0
        and stages.install_2 is not None
        and stages.install_2.returncode == 0
        and (stages.stale_sidecar_repair_result is None or stages.stale_sidecar_repair_result.returncode == 0)
        and (stages.uninstall_result is None or stages.uninstall_result.returncode == 0)
    )


def finalize_standard_scenario(context: ScenarioRunContext, stages: StandardScenarioStages, *, hooks: ScenarioLifecycleHooks) -> dict[str, object]:
    scenario = context.scenario
    scenario_name = hooks.scenario_registry.scenario_id(scenario.platform, scenario.scope)
    checks = standard_scenario_checks(stages)
    return hooks.artifacts.standard_result(
        context,
        scenario_name=scenario_name,
        stages=stages,
        checks=checks,
        generic_direct_equivalence=hooks.scenario_registry.equivalence_status(scenario),
    )


def run_scenario(scenario: Scenario, env: dict[str, str], *, hooks: ScenarioLifecycleHooks) -> dict[str, object]:
    context = prepare_scenario_run(scenario, env, hooks=hooks)
    stages = run_initial_install(context, hooks=hooks)
    if stages.install_1.returncode == 0:
        run_repeat_install(context, stages, hooks=hooks)
        if stages.install_2 is not None and stages.install_2.returncode == 0:
            run_stale_sidecar_repair(context, stages, hooks=hooks)
        run_uninstall_stage(context, stages, hooks=hooks)
        run_equivalence_stage(context, stages, hooks=hooks)
    return finalize_standard_scenario(context, stages, hooks=hooks)


@dataclass(frozen=True)
class UniversalUninstallLifecycle:
    spec: UniversalUninstallScenarioSpec
    scenarios: list[Scenario]
    env: dict[str, str]
    hooks: ScenarioLifecycleHooks

    @property
    def scenario_name(self) -> str:
        return self.spec.scenario_id

    @property
    def uninstall_command(self) -> tuple[str, ...]:
        return self.spec.command

    @property
    def uninstall_cwd(self) -> Path:
        return self.hooks.paths.root_path(self.spec.cwd_root)

    def runner_scenario(self) -> Scenario:
        return Scenario(
            platform=self.spec.platform_label,
            scope=self.spec.scope,
            install_command=self.uninstall_command,
            uninstall_command=None,
            cwd_root=self.spec.cwd_root,
            expected=tuple(entry for scenario in self.scenarios for entry in scenario.expected),
        )

    def prepare_context(self, runner_scenario: Scenario) -> ScenarioRunContext:
        return prepare_scenario_run(runner_scenario, self.env, hooks=self.hooks, scenario_name=self.scenario_name)

    def seed_installed_scenarios(self) -> None:
        for scenario in self.scenarios:
            self.hooks.file_effects.seed_scenario_inputs(scenario)

    def write_before_install_manifest(self, context: ScenarioRunContext) -> None:
        self.hooks.file_effects.write_manifest(context.artifact_dir / "before-install-files.json", self.hooks.paths.roots)

    def write_after_install_manifest(self, context: ScenarioRunContext) -> None:
        self.hooks.file_effects.write_manifest(context.artifact_dir / "after-install-files.json", self.hooks.paths.roots, debug_full=True)

    def write_after_uninstall_manifest(self, context: ScenarioRunContext) -> None:
        self.hooks.file_effects.write_manifest(context.artifact_dir / "after-uninstall-files.json", self.hooks.paths.roots, debug_full=True)

    def install_artifact_dir(self, context: ScenarioRunContext, scenario: Scenario) -> Path:
        install_scenario_id = self.hooks.scenario_registry.scenario_id(scenario.platform, scenario.scope)
        return context.artifact_dir / "installs" / install_scenario_id

    def run_installs(self, context: ScenarioRunContext) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        install_results: list[dict[str, object]] = []
        install_checks: list[dict[str, object]] = []
        for scenario in self.scenarios:
            install_scenario_id = self.hooks.scenario_registry.scenario_id(scenario.platform, scenario.scope)
            result = self.hooks.commands.capture(
                scenario.install_command,
                cwd=self.hooks.paths.root_path(scenario.cwd_root),
                env=self.env,
                artifact_dir=self.install_artifact_dir(context, scenario),
                command_class="installer",
            )
            scenario_install_checks = self.hooks.file_effects.install_checks(scenario)
            install_checks.extend(scenario_install_checks)
            install_results.append(
                {
                    "scenario_id": install_scenario_id,
                    "command": list(scenario.install_command),
                    "exit_code": result.returncode,
                    "checks": scenario_install_checks,
                }
            )
        return install_results, install_checks

    def run_uninstall(self, context: ScenarioRunContext) -> subprocess.CompletedProcess[str]:
        return self.hooks.commands.capture(
            self.uninstall_command,
            cwd=self.uninstall_cwd,
            env=self.env,
            artifact_dir=context.artifact_dir / self.spec.artifact_subdir,
            command_class="installer",
        )

    def universal_checks(
        self,
        runner_scenario: Scenario,
        install_checks: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        return self.hooks.file_effects.universal_uninstall_checks(runner_scenario, self.scenarios, install_checks)

    def outcome(self, context: ScenarioRunContext, runner_scenario: Scenario) -> UniversalUninstallOutcome:
        self.seed_installed_scenarios()
        self.write_before_install_manifest(context)
        install_results, install_checks = self.run_installs(context)
        self.write_after_install_manifest(context)
        uninstall_result = self.run_uninstall(context)
        checks = self.universal_checks(runner_scenario, install_checks)
        self.write_after_uninstall_manifest(context)
        return UniversalUninstallOutcome(
            scenario_name=self.scenario_name,
            platform_label=self.spec.platform_label,
            scope_name=self.spec.scope,
            scenarios=self.scenarios,
            install_results=install_results,
            uninstall_command=self.uninstall_command,
            uninstall_result=uninstall_result,
            checks=checks,
            uninstall_artifact_dir=context.artifact_dir / self.spec.artifact_subdir,
            risk_note=self.spec.risk_note,
        )

    def run(self) -> dict[str, object]:
        runner_scenario = self.runner_scenario()
        context = self.prepare_context(runner_scenario)
        return self.hooks.artifacts.universal_uninstall_result(context, self.outcome(context, runner_scenario))


def universal_uninstall_spec_for_scope(scope: str, *, hooks: ScenarioLifecycleHooks) -> UniversalUninstallScenarioSpec:
    spec = hooks.scenario_registry.universal_uninstall_spec_for_scope(scope)
    if spec is None:
        spec = next((policy_spec for policy_spec in validation_plan.DEFAULT_HARNESS_POLICY.universal_uninstall_specs if policy_spec.scope == scope), None)
    if spec is None:
        raise RuntimeError(f"no universal uninstall scenario declaration for scope: {scope}")
    return spec


def run_universal_uninstall_scenario(selected_or_scope: SelectedUniversalUninstallScenario | str, scenarios: list[Scenario] | None = None, env: dict[str, str] | None = None, *, hooks: ScenarioLifecycleHooks) -> dict[str, object]:
    if isinstance(selected_or_scope, SelectedUniversalUninstallScenario):
        selected = selected_or_scope
        scenario_env = env or {}
    else:
        if scenarios is None:
            raise TypeError("scenarios are required when running a universal uninstall by scope")
        selected = SelectedUniversalUninstallScenario(universal_uninstall_spec_for_scope(selected_or_scope, hooks=hooks), tuple(scenarios))
        scenario_env = env or {}
    return UniversalUninstallLifecycle(selected.spec, list(selected.installed_scenarios), scenario_env, hooks).run()


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
