from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

try:
    from .. import validation_plan
    from ..targets.install_target_models import DisposableArtifactScenarioSpec, Scenario
    from .scenario_lifecycle_support import (
        DisposableArtifactOutcome,
        ScenarioLifecycleHooks,
        ScenarioRunContext,
        prepare_scenario_run,
    )
except ImportError:  # pragma: no cover - direct script import fallback
    import validation_plan  # type: ignore[no-redef]
    from targets.install_target_models import DisposableArtifactScenarioSpec, Scenario  # type: ignore[no-redef]
    from .scenario_lifecycle_support import (  # type: ignore[no-redef]
        DisposableArtifactOutcome,
        ScenarioLifecycleHooks,
        ScenarioRunContext,
        prepare_scenario_run,
    )


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


def run_disposable_artifact_scenario(spec: DisposableArtifactScenarioSpec, env: dict[str, str], *, hooks: ScenarioLifecycleHooks) -> dict[str, object]:
    return DisposableArtifactLifecycle(spec, env, hooks).run()


def disposable_artifact_scenarios(scope: str, *, hooks: ScenarioLifecycleHooks) -> list[DisposableArtifactScenarioSpec]:
    specs = hooks.scenario_registry.disposable_artifact_specs or validation_plan.DEFAULT_HARNESS_POLICY.disposable_artifact_specs
    return [spec for spec in specs if scope in spec.scope_eligibility]
