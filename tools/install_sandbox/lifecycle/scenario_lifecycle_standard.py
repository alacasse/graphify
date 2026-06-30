from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..targets.install_target_models import Scenario
from .scenario_lifecycle_support import (
    ScenarioLifecycleHooks,
    ScenarioRunContext,
    StandardScenarioStages,
    prepare_scenario_run,
)


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

    def initial_install_effects(self, phase: StandardLifecyclePhase):
        return self.hooks.file_effects.initial_install_effects(self.scenario, self.artifact_dir, phase=phase.check_phase)

    def archive_initial_install_artifacts(self) -> None:
        self.hooks.file_effects.archive_initial_install_artifacts(self.scenario, self.artifact_dir)

    def repeat_install_effects(self, before: dict[str, dict[str, object]], phase: StandardLifecyclePhase):
        return self.hooks.file_effects.repeat_install_effects(self.scenario, before, phase=phase.check_phase)

    def stale_sidecar_repair_effects(self, phase: StandardLifecyclePhase):
        return self.hooks.file_effects.stale_sidecar_repair_effects(self.scenario, phase=phase.check_phase)

    def uninstall_effects(self, phase: StandardLifecyclePhase):
        return self.hooks.file_effects.uninstall_effects(self.scenario, phase=phase.check_phase)


def run_initial_install(context: ScenarioRunContext, *, hooks: ScenarioLifecycleHooks) -> StandardScenarioStages:
    scenario = context.scenario
    lifecycle = StandardLifecycleMechanics(context, hooks)
    hooks.file_effects.seed_scenario_inputs(scenario)
    lifecycle.write_manifest("before-install-files.json")

    install_1 = lifecycle.capture(scenario.install_command, INITIAL_INSTALL_PHASE)
    file_effects = lifecycle.initial_install_effects(INITIAL_INSTALL_PHASE)
    lifecycle.write_phase_manifest(INITIAL_INSTALL_PHASE)
    stages = StandardScenarioStages(
        install_1=install_1,
        state_after_install=file_effects.state_after_install,
        install_checks=file_effects.install_checks,
        scope_checks=file_effects.scope_checks,
        unexpected_install_checks=file_effects.unexpected_install_checks,
    )
    lifecycle.archive_initial_install_artifacts()
    return stages


def run_repeat_install(context: ScenarioRunContext, stages: StandardScenarioStages, *, hooks: ScenarioLifecycleHooks) -> None:
    scenario = context.scenario
    lifecycle = StandardLifecycleMechanics(context, hooks)
    stages.install_2 = lifecycle.capture(scenario.install_command, REPEAT_INSTALL_PHASE)
    file_effects = lifecycle.repeat_install_effects(stages.state_after_install, REPEAT_INSTALL_PHASE)
    stages.state_after_repeat = file_effects.state_after_repeat
    stages.idempotency_checks = file_effects.idempotency_checks
    lifecycle.write_phase_manifest(REPEAT_INSTALL_PHASE)


def run_stale_sidecar_repair(context: ScenarioRunContext, stages: StandardScenarioStages, *, hooks: ScenarioLifecycleHooks) -> None:
    scenario = context.scenario
    lifecycle = StandardLifecycleMechanics(context, hooks)
    stages.stale_sidecar_repair_seeded = hooks.file_effects.seed_stale_sidecar_repair(scenario)
    if not stages.stale_sidecar_repair_seeded:
        return
    stages.stale_sidecar_repair_result = lifecycle.capture(scenario.install_command, STALE_SIDECAR_REPAIR_PHASE)
    if stages.stale_sidecar_repair_result.returncode == 0:
        file_effects = lifecycle.stale_sidecar_repair_effects(STALE_SIDECAR_REPAIR_PHASE)
        stages.stale_sidecar_repair_checks = file_effects.stale_sidecar_repair_checks
    lifecycle.write_phase_manifest(STALE_SIDECAR_REPAIR_PHASE)


def run_uninstall_stage(context: ScenarioRunContext, stages: StandardScenarioStages, *, hooks: ScenarioLifecycleHooks) -> None:
    scenario = context.scenario
    if not scenario.uninstall_command:
        return
    lifecycle = StandardLifecycleMechanics(context, hooks)
    stages.uninstall_result = lifecycle.capture(scenario.uninstall_command, UNINSTALL_PHASE)
    file_effects = lifecycle.uninstall_effects(UNINSTALL_PHASE)
    stages.uninstall_checks = file_effects.uninstall_checks
    stages.unexpected_uninstall_checks = file_effects.unexpected_uninstall_checks
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
        command_ok=standard_scenario_command_ok(stages),
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
