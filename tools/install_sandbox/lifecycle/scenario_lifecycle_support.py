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
    from ..targets.install_target_catalog import ScenarioRegistry
    from ..targets.install_target_defaults import default_install_target_catalog
    from ..targets.install_target_models import DisposableArtifactScenarioSpec, Scenario
except ImportError:  # pragma: no cover - direct script import fallback
    from targets.install_target_catalog import ScenarioRegistry  # type: ignore[no-redef]
    from targets.install_target_defaults import default_install_target_catalog  # type: ignore[no-redef]
    from targets.install_target_models import DisposableArtifactScenarioSpec, Scenario  # type: ignore[no-redef]


DEFAULT_SCENARIO_REGISTRY = default_install_target_catalog()


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
    command_ok: bool
    generic_direct_equivalence: dict[str, object]

    @property
    def passed(self) -> bool:
        return self.command_ok and all(check["ok"] for check in self.checks)

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

    def initial_install_effects(self, scenario: Scenario, artifact_dir: Path, *, phase: str) -> InitialInstallEffects: ...

    def archive_initial_install_artifacts(self, scenario: Scenario, artifact_dir: Path) -> None: ...

    def repeat_install_effects(
        self,
        scenario: Scenario,
        before: dict[str, dict[str, object]],
        *,
        phase: str,
    ) -> RepeatInstallEffects: ...

    def seed_stale_sidecar_repair(self, scenario: Scenario) -> list[dict[str, object]]: ...

    def stale_sidecar_repair_effects(self, scenario: Scenario, *, phase: str) -> StaleSidecarRepairEffects: ...

    def uninstall_effects(self, scenario: Scenario, *, phase: str) -> UninstallEffects: ...

    def equivalence_checks(self, scenario: Scenario, env: dict[str, str], artifact_dir: Path) -> list[dict[str, object]]: ...

    def universal_install_effects(self, scenario: Scenario) -> list[dict[str, object]]: ...

    def universal_uninstall_checks(
        self,
        runner_scenario: Scenario,
        installed_scenarios: Iterable[Scenario],
        install_checks: list[dict[str, object]],
    ) -> list[dict[str, object]]: ...

    def disposable_artifact_checks(self, disposable_path: Path, removed: bool) -> list[dict[str, object]]: ...


class InitialInstallEffects(Protocol):
    state_after_install: dict[str, dict[str, object]]
    install_checks: list[dict[str, object]]
    scope_checks: list[dict[str, object]]
    unexpected_install_checks: list[dict[str, object]]


class RepeatInstallEffects(Protocol):
    state_after_repeat: dict[str, dict[str, object]]
    idempotency_checks: list[dict[str, object]]


class StaleSidecarRepairEffects(Protocol):
    stale_sidecar_repair_checks: list[dict[str, object]]


class UninstallEffects(Protocol):
    uninstall_checks: list[dict[str, object]]
    unexpected_uninstall_checks: list[dict[str, object]]


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
        command_ok: bool,
        generic_direct_equivalence: dict[str, object],
    ) -> dict[str, object]:
        return self.recorded_result(context, StandardScenarioOutcome(scenario_name, stages, checks, command_ok, generic_direct_equivalence))

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
    run_scenario: Callable[[Scenario, dict[str, str]], dict[str, object]] | None = None
    run_universal_uninstall_scenario: Callable[..., dict[str, object]] | None = None
    run_purge_scenario: Callable[..., dict[str, object]] | None = None
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
