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
    from .platform_specs import DEFAULT_SCENARIO_REGISTRY, Scenario, ScenarioRegistry
except ImportError:
    from platform_specs import DEFAULT_SCENARIO_REGISTRY, Scenario, ScenarioRegistry


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

    def purge_checks(self, graphify_out: Path, purged: bool) -> list[dict[str, object]]: ...


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

    def result_record(
        self,
        context: ScenarioRunContext,
        *,
        scenario_name: str,
        platform_name: str,
        scope: str,
        passed: bool,
        risks: dict[str, object],
        reproduction_command: tuple[str, ...],
        command_artifact_dir: Path,
    ) -> dict[str, object]:
        return {
            "id": scenario_name,
            "platform": platform_name,
            "scope": scope,
            "started_at": context.started_at,
            "duration_ms": scenario_duration_ms(context),
            "reproduction_command": shlex.join(reproduction_command),
            "command_artifact": self.command_artifact_summary(command_artifact_dir),
            "overall_status": self.combined_status(passed),
            "graphify_file_effects_passed": passed,
            "passed": passed,
            "risks": risks["statuses"],
        }

    def recorded_result(
        self,
        context: ScenarioRunContext,
        *,
        scenario_name: str,
        platform_name: str,
        scope: str,
        passed: bool,
        assertions: dict[str, object],
        risks: dict[str, object],
        reproduction_command: tuple[str, ...],
        command_artifact_dir: Path,
    ) -> dict[str, object]:
        self.write_scenario_artifacts(context.artifact_dir, assertions, risks)
        return self.result_record(
            context,
            scenario_name=scenario_name,
            platform_name=platform_name,
            scope=scope,
            passed=passed,
            risks=risks,
            reproduction_command=reproduction_command,
            command_artifact_dir=command_artifact_dir,
        )

    def standard_result(
        self,
        context: ScenarioRunContext,
        *,
        scenario_name: str,
        stages: StandardScenarioStages,
        checks: list[dict[str, object]],
        passed: bool,
        generic_direct_equivalence: str,
    ) -> dict[str, object]:
        scenario = context.scenario
        assertions = {
            "scenario": {"platform": scenario.platform, "scope": scenario.scope, "id": scenario_name},
            "passed": passed,
            "install_exit_code": stages.install_1.returncode,
            "repeat_install_exit_code": None if stages.install_2 is None else stages.install_2.returncode,
            "stale_sidecar_repair_exit_code": None if stages.stale_sidecar_repair_result is None else stages.stale_sidecar_repair_result.returncode,
            "stale_sidecar_repair_seeded": stages.stale_sidecar_repair_seeded,
            "stale_sidecar_repair_checks": stages.stale_sidecar_repair_checks,
            "uninstall_exit_code": None if stages.uninstall_result is None else stages.uninstall_result.returncode,
            "state_after_install": stages.state_after_install,
            "state_after_repeat_install": stages.state_after_repeat,
            "generic_direct_equivalence": generic_direct_equivalence,
            "checks": checks,
        }
        risks = self.risk_report(scenario, passed)
        return self.recorded_result(
            context,
            scenario_name=scenario_name,
            platform_name=scenario.platform,
            scope=scenario.scope,
            passed=passed,
            assertions=assertions,
            risks=risks,
            reproduction_command=scenario.install_command,
            command_artifact_dir=context.artifact_dir,
        )

    def universal_uninstall_result(
        self,
        context: ScenarioRunContext,
        *,
        scenario_name: str,
        scope: str,
        platforms: list[str],
        install_results: list[dict[str, object]],
        uninstall_command: tuple[str, ...],
        uninstall_exit_code: int,
        checks: list[dict[str, object]],
        passed: bool,
        command_artifact_dir: Path,
    ) -> dict[str, object]:
        assertions = {
            "scenario": {"id": scenario_name, "scope": scope, "platforms": platforms},
            "passed": passed,
            "install_results": install_results,
            "uninstall_command": list(uninstall_command),
            "uninstall_exit_code": uninstall_exit_code,
            "checks": checks,
        }
        risks = {
            "statuses": [self.combined_status(passed)],
            "notes": ["universal uninstall covers Graphify-owned file effects after multiple installs"],
            "known_status_values": self.known_status_values(),
        }
        return self.recorded_result(
            context,
            scenario_name=scenario_name,
            platform_name="multiple",
            scope=scope,
            passed=passed,
            assertions=assertions,
            risks=risks,
            reproduction_command=uninstall_command,
            command_artifact_dir=command_artifact_dir,
        )

    def purge_result(
        self,
        context: ScenarioRunContext,
        *,
        scenario_name: str,
        command: tuple[str, ...],
        uninstall_exit_code: int,
        checks: list[dict[str, object]],
        passed: bool,
        command_artifact_dir: Path,
    ) -> dict[str, object]:
        assertions = {
            "scenario": {"id": scenario_name, "scope": "project", "platform": "purge"},
            "passed": passed,
            "uninstall_exit_code": uninstall_exit_code,
            "checks": checks,
        }
        risks = {
            "statuses": [self.combined_status(passed)],
            "notes": ["purge verified only against disposable sandbox graphify-out state"],
            "known_status_values": self.known_status_values(),
        }
        return self.recorded_result(
            context,
            scenario_name=scenario_name,
            platform_name="purge",
            scope="project",
            passed=passed,
            assertions=assertions,
            risks=risks,
            reproduction_command=command,
            command_artifact_dir=command_artifact_dir,
        )


@dataclass(frozen=True)
class MatrixRunnerOverrides:
    platform_scenarios: Callable[[str, str], Iterable[Scenario]] | None = None
    run_scenario: Callable[[Scenario, dict[str, str]], dict[str, object]] | None = None
    universal_uninstall_scenarios: Callable[[list[str], str], list[tuple[str, list[Scenario]]]] | None = None
    run_universal_uninstall_scenario: Callable[[str, list[Scenario], dict[str, str]], dict[str, object]] | None = None
    run_purge_scenario: Callable[[dict[str, str]], dict[str, object]] | None = None


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
    passed = standard_scenario_command_ok(stages) and all(check["ok"] for check in checks)
    return hooks.artifacts.standard_result(
        context,
        scenario_name=scenario_name,
        stages=stages,
        checks=checks,
        passed=passed,
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


def run_universal_uninstall_scenario(scope: str, scenarios: list[Scenario], env: dict[str, str], *, hooks: ScenarioLifecycleHooks) -> dict[str, object]:
    scenario_name = hooks.scenario_registry.universal_uninstall_scenario_id(scope)
    runner_scenario = Scenario(
        platform="multiple",
        scope=scope,
        install_command=("graphify", "uninstall", "--project") if scope == "project" else ("graphify", "uninstall"),
        uninstall_command=None,
        cwd_root="project" if scope == "project" else "user_cwd",
        expected=tuple(entry for scenario in scenarios for entry in scenario.expected),
    )
    context = prepare_scenario_run(runner_scenario, env, hooks=hooks, scenario_name=scenario_name)
    artifact_dir = context.artifact_dir

    for scenario in scenarios:
        hooks.file_effects.seed_scenario_inputs(scenario)
    hooks.file_effects.write_manifest(artifact_dir / "before-install-files.json", hooks.paths.roots)

    install_results = []
    install_checks: list[dict[str, object]] = []
    for scenario in scenarios:
        install_scenario_id = hooks.scenario_registry.scenario_id(scenario.platform, scenario.scope)
        install_dir = artifact_dir / "installs" / install_scenario_id
        result = hooks.commands.capture(scenario.install_command, cwd=hooks.paths.root_path(scenario.cwd_root), env=env, artifact_dir=install_dir, command_class="installer")
        scenario_install_checks = hooks.file_effects.install_checks(scenario)
        install_checks.extend(scenario_install_checks)
        install_results.append(
            {
                "scenario_id": install_scenario_id,
                "command": list(scenario.install_command),
                "exit_code": result.returncode,
                "checks": scenario_install_checks,
            }
        )
    hooks.file_effects.write_manifest(artifact_dir / "after-install-files.json", hooks.paths.roots, debug_full=True)

    if scope == "project":
        uninstall_command = ("graphify", "uninstall", "--project")
        cwd = hooks.paths.project
    else:
        uninstall_command = ("graphify", "uninstall")
        cwd = hooks.paths.user_cwd
    uninstall_result = hooks.commands.capture(uninstall_command, cwd=cwd, env=env, artifact_dir=artifact_dir / "uninstall", command_class="installer")
    checks = hooks.file_effects.universal_uninstall_checks(runner_scenario, scenarios, install_checks)
    hooks.file_effects.write_manifest(artifact_dir / "after-uninstall-files.json", hooks.paths.roots, debug_full=True)
    passed = all(result["exit_code"] == 0 for result in install_results) and uninstall_result.returncode == 0 and all(check["ok"] for check in checks)
    return hooks.artifacts.universal_uninstall_result(
        context,
        scenario_name=scenario_name,
        scope=scope,
        platforms=[scenario.platform for scenario in scenarios],
        install_results=install_results,
        uninstall_command=uninstall_command,
        uninstall_exit_code=uninstall_result.returncode,
        checks=checks,
        passed=passed,
        command_artifact_dir=artifact_dir / "uninstall",
    )


def run_purge_scenario(env: dict[str, str], *, hooks: ScenarioLifecycleHooks) -> dict[str, object]:
    scenario_name = hooks.scenario_registry.purge_disposable_graphify_out_scenario_id()
    command = ("graphify", "uninstall", "--purge")
    runner_scenario = Scenario(
        platform="purge",
        scope="project",
        install_command=command,
        uninstall_command=None,
        cwd_root="project",
        expected=(),
    )
    context = prepare_scenario_run(runner_scenario, env, hooks=hooks, scenario_name=scenario_name)
    artifact_dir = context.artifact_dir
    graphify_out = hooks.paths.project / "graphify-out"
    graphify_out.mkdir(parents=True, exist_ok=True)
    (graphify_out / "graph.json").write_text('{"nodes": [], "edges": []}\n', encoding="utf-8")
    hooks.file_effects.write_manifest(artifact_dir / "before-install-files.json", hooks.paths.roots)
    result = hooks.commands.capture(command, cwd=hooks.paths.project, env=env, artifact_dir=artifact_dir / "uninstall-purge", command_class="installer")
    purged = not graphify_out.exists()
    hooks.file_effects.write_manifest(artifact_dir / "after-uninstall-files.json", hooks.paths.roots)
    checks = hooks.file_effects.purge_checks(graphify_out, purged)
    passed = result.returncode == 0 and purged
    return hooks.artifacts.purge_result(
        context,
        scenario_name=scenario_name,
        command=command,
        uninstall_exit_code=result.returncode,
        checks=checks,
        passed=passed,
        command_artifact_dir=artifact_dir / "uninstall-purge",
    )


def universal_uninstall_scenarios(platforms: list[str], scope: str, *, hooks: ScenarioLifecycleHooks) -> list[tuple[str, list[Scenario]]]:
    return hooks.scenario_registry.universal_uninstall_groups(platforms, scope)


def run_matrix_scenarios(platforms: list[str], scope: str, env: dict[str, str], *, hooks: ScenarioLifecycleHooks, fail_fast_scenarios: bool = False) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    overrides = hooks.matrix_overrides
    run_one = overrides.run_scenario or (lambda scenario, scenario_env: run_scenario(scenario, scenario_env, hooks=hooks))
    universal_groups = overrides.universal_uninstall_scenarios or (lambda selected_platforms, selected_scope: universal_uninstall_scenarios(selected_platforms, selected_scope, hooks=hooks))
    run_universal = overrides.run_universal_uninstall_scenario or (lambda universal_scope, scenarios, scenario_env: run_universal_uninstall_scenario(universal_scope, scenarios, scenario_env, hooks=hooks))
    run_purge = overrides.run_purge_scenario or (lambda scenario_env: run_purge_scenario(scenario_env, hooks=hooks))
    platform_scenarios = overrides.platform_scenarios or hooks.scenario_registry.platform_scenarios
    for scenario in [scenario for platform_name in platforms for scenario in platform_scenarios(platform_name, scope)]:
        result = run_one(scenario, env)
        results.append(result)
        if fail_fast_scenarios and result.get("passed") is not True:
            return results
    if any(result.get("passed") is not True for result in results):
        return results
    for universal_scope, scenarios in universal_groups(platforms, scope):
        result = run_universal(universal_scope, scenarios, env)
        results.append(result)
    if scope in {"project", "both"}:
        result = run_purge(env)
        results.append(result)
    return results
