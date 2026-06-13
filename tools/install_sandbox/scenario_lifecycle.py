from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Protocol

try:
    from .platform_specs import DEFAULT_SCENARIO_REGISTRY, DisposableArtifactScenarioSpec, Scenario, ScenarioRegistry, SelectedUniversalUninstallScenario, UniversalUninstallScenarioSpec
except ImportError:
    from platform_specs import DEFAULT_SCENARIO_REGISTRY, DisposableArtifactScenarioSpec, Scenario, ScenarioRegistry, SelectedUniversalUninstallScenario, UniversalUninstallScenarioSpec


@dataclass(frozen=True)
class ScenarioRunContext:
    scenario: Scenario
    env: dict[str, str]
    artifact_dir: Path
    cwd: Path
    started_at: str
    started_monotonic: float


@dataclass
class StandardScenarioStages:
    install_1: subprocess.CompletedProcess[str]
    state_after_install: dict[str, dict[str, object]]
    install_checks: list[dict[str, object]]
    scope_checks: list[dict[str, object]]
    unexpected_install_checks: list[dict[str, object]]
    install_2: subprocess.CompletedProcess[str] | None = None
    idempotency_checks: list[dict[str, object]] = field(default_factory=list)
    stale_sidecar_repair_seeded: list[dict[str, object]] = field(default_factory=list)
    stale_sidecar_repair_result: subprocess.CompletedProcess[str] | None = None
    stale_sidecar_repair_checks: list[dict[str, object]] = field(default_factory=list)
    uninstall_result: subprocess.CompletedProcess[str] | None = None
    uninstall_checks: list[dict[str, object]] = field(default_factory=list)
    unexpected_uninstall_checks: list[dict[str, object]] = field(default_factory=list)
    equivalence_checks: list[dict[str, object]] = field(default_factory=list)
    state_after_repeat: dict[str, dict[str, object]] = field(default_factory=dict)


class ScenarioResultOutcome(Protocol):
    @property
    def scenario_name(self) -> str: ...

    @property
    def passed(self) -> bool: ...

    def platform_name(self, context: ScenarioRunContext) -> str: ...

    def scope(self, context: ScenarioRunContext) -> str: ...

    def reproduction_command(self, context: ScenarioRunContext) -> tuple[str, ...]: ...

    def command_artifact_dir(self, context: ScenarioRunContext) -> Path: ...

    def assertions(self, context: ScenarioRunContext) -> dict[str, object]: ...

    def risks(self, context: ScenarioRunContext, artifacts: ScenarioArtifacts) -> dict[str, object]: ...


@dataclass(frozen=True)
class StandardScenarioOutcome:
    scenario_name: str
    stages: StandardScenarioStages
    checks: list[dict[str, object]]
    generic_direct_equivalence: dict[str, object]

    @property
    def passed(self) -> bool:
        return standard_scenario_command_ok(self.stages) and all(check["ok"] for check in self.checks)

    def platform_name(self, context: ScenarioRunContext) -> str:
        return context.scenario.platform

    def scope(self, context: ScenarioRunContext) -> str:
        return context.scenario.scope

    def reproduction_command(self, context: ScenarioRunContext) -> tuple[str, ...]:
        return context.scenario.install_command

    def command_artifact_dir(self, context: ScenarioRunContext) -> Path:
        return context.artifact_dir

    def assertions(self, context: ScenarioRunContext) -> dict[str, object]:
        scenario = context.scenario
        return {
            "scenario": {"platform": scenario.platform, "scope": scenario.scope, "id": self.scenario_name},
            "passed": self.passed,
            "install_exit_code": self.stages.install_1.returncode,
            "repeat_install_exit_code": None if self.stages.install_2 is None else self.stages.install_2.returncode,
            "stale_sidecar_repair_exit_code": None if self.stages.stale_sidecar_repair_result is None else self.stages.stale_sidecar_repair_result.returncode,
            "stale_sidecar_repair_seeded": self.stages.stale_sidecar_repair_seeded,
            "stale_sidecar_repair_checks": self.stages.stale_sidecar_repair_checks,
            "uninstall_exit_code": None if self.stages.uninstall_result is None else self.stages.uninstall_result.returncode,
            "state_after_install": self.stages.state_after_install,
            "state_after_repeat_install": self.stages.state_after_repeat,
            "generic_direct_equivalence": self.generic_direct_equivalence,
            "checks": self.checks,
        }

    def risks(self, context: ScenarioRunContext, artifacts: ScenarioArtifacts) -> dict[str, object]:
        return artifacts.risk_report(context.scenario, self.passed)


@dataclass(frozen=True)
class UniversalUninstallOutcome:
    scenario_name: str
    platform_label: str
    scope_name: str
    scenarios: list[Scenario]
    install_results: list[dict[str, object]]
    uninstall_command: tuple[str, ...]
    uninstall_result: subprocess.CompletedProcess[str]
    checks: list[dict[str, object]]
    uninstall_artifact_dir: Path
    risk_note: str

    @property
    def passed(self) -> bool:
        return all(result["exit_code"] == 0 for result in self.install_results) and self.uninstall_result.returncode == 0 and all(check["ok"] for check in self.checks)

    def reproduction_command(self, context: ScenarioRunContext) -> tuple[str, ...]:
        return self.uninstall_command

    def platform_name(self, context: ScenarioRunContext) -> str:
        return self.platform_label

    def scope(self, context: ScenarioRunContext) -> str:
        return self.scope_name

    def command_artifact_dir(self, context: ScenarioRunContext) -> Path:
        return self.uninstall_artifact_dir

    def assertions(self, context: ScenarioRunContext) -> dict[str, object]:
        return {
            "scenario": {"id": self.scenario_name, "scope": self.scope_name, "platforms": [scenario.platform for scenario in self.scenarios]},
            "passed": self.passed,
            "install_results": self.install_results,
            "uninstall_command": list(self.uninstall_command),
            "uninstall_exit_code": self.uninstall_result.returncode,
            "checks": self.checks,
        }

    def risks(self, context: ScenarioRunContext, artifacts: ScenarioArtifacts) -> dict[str, object]:
        return artifacts.synthetic_risk_payload(
            self.passed,
            note=self.risk_note,
        )


@dataclass(frozen=True)
class DisposableArtifactOutcome:
    scenario_name: str
    platform_label: str
    scope_name: str
    command: tuple[str, ...]
    result: subprocess.CompletedProcess[str]
    checks: list[dict[str, object]]
    removed: bool
    command_artifact_dir_path: Path
    risk_note: str

    @property
    def passed(self) -> bool:
        return self.result.returncode == 0 and self.removed

    def reproduction_command(self, context: ScenarioRunContext) -> tuple[str, ...]:
        return self.command

    def platform_name(self, context: ScenarioRunContext) -> str:
        return self.platform_label

    def scope(self, context: ScenarioRunContext) -> str:
        return self.scope_name

    def command_artifact_dir(self, context: ScenarioRunContext) -> Path:
        return self.command_artifact_dir_path

    def assertions(self, context: ScenarioRunContext) -> dict[str, object]:
        return {
            "scenario": {"id": self.scenario_name, "scope": self.scope_name, "platform": self.platform_label},
            "passed": self.passed,
            "uninstall_exit_code": self.result.returncode,
            "checks": self.checks,
        }

    def risks(self, context: ScenarioRunContext, artifacts: ScenarioArtifacts) -> dict[str, object]:
        return artifacts.synthetic_risk_payload(
            self.passed,
            note=self.risk_note,
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
class SandboxPaths:
    output: Path
    roots: dict[str, Path]
    project: Path
    user_cwd: Path
    utc_timestamp: Callable[[], str]
    root_path: Callable[[str], Path]
    reset_sandbox_dirs: Callable[[], None]

    def scenario_artifact_dir(self, scenario_name: str) -> Path:
        return self.output / "scenarios" / scenario_name

    def prepare_run(self, scenario: Scenario, env: dict[str, str], *, registry: ScenarioRegistry, scenario_name: str | None = None) -> ScenarioRunContext:
        started_at = self.utc_timestamp()
        started_monotonic = time.monotonic()
        self.reset_sandbox_dirs()
        artifact_dir = self.scenario_artifact_dir(scenario_name or registry.scenario_id(scenario.platform, scenario.scope))
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        return ScenarioRunContext(
            scenario=scenario,
            env=env,
            artifact_dir=artifact_dir,
            cwd=self.root_path(scenario.cwd_root),
            started_at=started_at,
            started_monotonic=started_monotonic,
        )


class ScenarioFileEffects(Protocol):
    def seed_scenario_inputs(self, scenario: Scenario) -> None: ...

    def write_manifest(self, path: Path, roots: dict[str, Path], **kwargs: object) -> None: ...

    def capture_state(self, scenario: Scenario) -> dict[str, dict[str, object]]: ...

    def install_checks(self, scenario: Scenario) -> list[dict[str, object]]: ...

    def unexpected_checks(self, scenario: Scenario, *, phase: str) -> list[dict[str, object]]: ...

    def archive_generated_files(self, scenario: Scenario, artifact_dir: Path) -> None: ...

    def repeat_install_checks(
        self,
        scenario: Scenario,
        before: dict[str, dict[str, object]],
        after: dict[str, dict[str, object]],
        *,
        phase: str,
    ) -> list[dict[str, object]]: ...

    def seed_stale_sidecar_repair(self, scenario: Scenario) -> list[dict[str, object]]: ...

    def stale_sidecar_repair_checks(self, scenario: Scenario, *, phase: str) -> list[dict[str, object]]: ...

    def uninstall_checks(self, scenario: Scenario, *, phase: str) -> list[dict[str, object]]: ...

    def equivalence_checks(self, scenario: Scenario, env: dict[str, str], artifact_dir: Path) -> list[dict[str, object]]: ...

    def universal_uninstall_checks(
        self,
        runner_scenario: Scenario,
        installed_scenarios: Iterable[Scenario],
        install_checks: list[dict[str, object]],
    ) -> list[dict[str, object]]: ...

    def disposable_artifact_checks(self, disposable_path: Path, removed: bool) -> list[dict[str, object]]: ...


@dataclass(frozen=True)
class CommandExecutor:
    run_capture: Callable[..., subprocess.CompletedProcess[str]]

    def capture(
        self,
        command: tuple[str, ...],
        *,
        cwd: Path,
        env: dict[str, str],
        artifact_dir: Path | None = None,
        command_class: str = "installer",
        timeout_seconds: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        kwargs: dict[str, object] = {"cwd": cwd, "env": env, "artifact_dir": artifact_dir, "command_class": command_class}
        if timeout_seconds is not None:
            kwargs["timeout_seconds"] = timeout_seconds
        return self.run_capture(command, **kwargs)


@dataclass(frozen=True)
class ScenarioArtifacts:
    risk_report: Callable[[Scenario, bool], dict[str, object]]
    command_artifact_summary: Callable[[Path], dict[str, object]]
    combined_status: Callable[[bool], str]
    known_status_values: Callable[[], list[str]]

    def write_json_artifact(self, artifact_dir: Path, filename: str, payload: dict[str, object]) -> None:
        (artifact_dir / filename).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def write_scenario_artifacts(self, artifact_dir: Path, assertions: dict[str, object], risks: dict[str, object]) -> None:
        self.write_json_artifact(artifact_dir, "assertions.json", assertions)
        self.write_json_artifact(artifact_dir, "risk.json", risks)

    def synthetic_risk_payload(self, passed: bool, *, note: str) -> dict[str, object]:
        return {
            "statuses": [self.combined_status(passed)],
            "notes": [note],
            "known_status_values": self.known_status_values(),
        }

    def result_record(
        self,
        context: ScenarioRunContext,
        outcome: ScenarioResultOutcome,
        risks: dict[str, object] | None = None,
    ) -> dict[str, object]:
        risk_payload = outcome.risks(context, self) if risks is None else risks
        return {
            "id": outcome.scenario_name,
            "platform": outcome.platform_name(context),
            "scope": outcome.scope(context),
            "started_at": context.started_at,
            "duration_ms": scenario_duration_ms(context),
            "reproduction_command": shlex.join(outcome.reproduction_command(context)),
            "command_artifact": self.command_artifact_summary(outcome.command_artifact_dir(context)),
            "overall_status": self.combined_status(outcome.passed),
            "graphify_file_effects_passed": outcome.passed,
            "passed": outcome.passed,
            "risks": risk_payload["statuses"],
        }

    def recorded_result(
        self,
        context: ScenarioRunContext,
        outcome: ScenarioResultOutcome,
    ) -> dict[str, object]:
        assertions = outcome.assertions(context)
        risks = outcome.risks(context, self)
        self.write_scenario_artifacts(context.artifact_dir, assertions, risks)
        return self.result_record(context, outcome, risks)

    def standard_result(
        self,
        context: ScenarioRunContext,
        *,
        scenario_name: str,
        stages: StandardScenarioStages,
        checks: list[dict[str, object]],
        generic_direct_equivalence: dict[str, object],
    ) -> dict[str, object]:
        return self.recorded_result(context, StandardScenarioOutcome(scenario_name, stages, checks, generic_direct_equivalence))

    def universal_uninstall_result(
        self,
        context: ScenarioRunContext,
        outcome: UniversalUninstallOutcome,
    ) -> dict[str, object]:
        return self.recorded_result(context, outcome)

    def purge_result(
        self,
        context: ScenarioRunContext,
        outcome: DisposableArtifactOutcome,
    ) -> dict[str, object]:
        return self.recorded_result(context, outcome)


@dataclass(frozen=True)
class MatrixRunnerOverrides:
    platform_scenarios: Callable[[str, str], Iterable[Scenario]] | None = None
    run_scenario: Callable[[Scenario, dict[str, str]], dict[str, object]] | None = None
    universal_uninstall_scenarios: Callable[[list[str], str], list[SelectedUniversalUninstallScenario | tuple[str, list[Scenario]]]] | None = None
    run_universal_uninstall_scenario: Callable[..., dict[str, object]] | None = None
    run_purge_scenario: Callable[[dict[str, str]], dict[str, object]] | None = None
    disposable_artifact_scenarios: Callable[[str], list[DisposableArtifactScenarioSpec]] | None = None
    run_disposable_artifact_scenario: Callable[[DisposableArtifactScenarioSpec, dict[str, str]], dict[str, object]] | None = None


@dataclass(frozen=True)
class ScenarioLifecycleHooks:
    paths: SandboxPaths
    file_effects: ScenarioFileEffects
    commands: CommandExecutor
    artifacts: ScenarioArtifacts
    scenario_registry: ScenarioRegistry = DEFAULT_SCENARIO_REGISTRY
    matrix_overrides: MatrixRunnerOverrides = field(default_factory=MatrixRunnerOverrides)


def scenario_artifact_dir(scenario_name: str, *, hooks: ScenarioLifecycleHooks) -> Path:
    return hooks.paths.scenario_artifact_dir(scenario_name)


def prepare_scenario_run(scenario: Scenario, env: dict[str, str], *, hooks: ScenarioLifecycleHooks, scenario_name: str | None = None) -> ScenarioRunContext:
    return hooks.paths.prepare_run(scenario, env, registry=hooks.scenario_registry, scenario_name=scenario_name)


def scenario_duration_ms(context: ScenarioRunContext) -> int:
    return int((time.monotonic() - context.started_monotonic) * 1000)


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
        raise RuntimeError(f"no universal uninstall scenario declaration for scope: {scope}")
    return spec


def selected_universal_uninstall(selected: SelectedUniversalUninstallScenario | tuple[str, list[Scenario]], *, hooks: ScenarioLifecycleHooks) -> SelectedUniversalUninstallScenario:
    if isinstance(selected, SelectedUniversalUninstallScenario):
        return selected
    scope, scenarios = selected
    return SelectedUniversalUninstallScenario(universal_uninstall_spec_for_scope(scope, hooks=hooks), tuple(scenarios))


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
    scenarios = hooks.scenario_registry.disposable_artifact_scenarios("project")
    if not scenarios:
        raise RuntimeError("no disposable artifact scenario declaration for project scope")
    return DisposableArtifactLifecycle(scenarios[0], env, hooks).run()


def run_disposable_artifact_scenario(spec: DisposableArtifactScenarioSpec, env: dict[str, str], *, hooks: ScenarioLifecycleHooks) -> dict[str, object]:
    return DisposableArtifactLifecycle(spec, env, hooks).run()


def disposable_artifact_scenarios(scope: str, *, hooks: ScenarioLifecycleHooks) -> list[DisposableArtifactScenarioSpec]:
    return hooks.scenario_registry.disposable_artifact_scenarios(scope)


def universal_uninstall_scenarios(platforms: list[str], scope: str, *, hooks: ScenarioLifecycleHooks) -> list[SelectedUniversalUninstallScenario]:
    return hooks.scenario_registry.universal_uninstall_scenarios(platforms, scope)


def run_matrix_scenarios(platforms: list[str], scope: str, env: dict[str, str], *, hooks: ScenarioLifecycleHooks, fail_fast_scenarios: bool = False) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    overrides = hooks.matrix_overrides
    run_one = overrides.run_scenario or (lambda scenario, scenario_env: run_scenario(scenario, scenario_env, hooks=hooks))
    universal_groups = overrides.universal_uninstall_scenarios or (lambda selected_platforms, selected_scope: universal_uninstall_scenarios(selected_platforms, selected_scope, hooks=hooks))
    run_universal_override = overrides.run_universal_uninstall_scenario
    disposable_specs = overrides.disposable_artifact_scenarios or (lambda selected_scope: disposable_artifact_scenarios(selected_scope, hooks=hooks))
    run_disposable = overrides.run_disposable_artifact_scenario or (lambda spec, scenario_env: run_disposable_artifact_scenario(spec, scenario_env, hooks=hooks))
    run_purge = overrides.run_purge_scenario
    platform_scenarios = overrides.platform_scenarios or hooks.scenario_registry.platform_scenarios
    for scenario in [scenario for platform_name in platforms for scenario in platform_scenarios(platform_name, scope)]:
        result = run_one(scenario, env)
        results.append(result)
        if fail_fast_scenarios and result.get("passed") is not True:
            return results
    if any(result.get("passed") is not True for result in results):
        return results
    for universal_group in universal_groups(platforms, scope):
        selected = selected_universal_uninstall(universal_group, hooks=hooks)
        if run_universal_override is None:
            result = run_universal_uninstall_scenario(selected, env=env, hooks=hooks)
        else:
            result = run_universal_override(selected.spec.scope, list(selected.installed_scenarios), env)
        results.append(result)
    for disposable_spec in disposable_specs(scope):
        result = run_purge(env) if run_purge is not None else run_disposable(disposable_spec, env)
        results.append(result)
    return results
