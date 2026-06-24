from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

try:
    from .. import validation_plan
    from ..platform_specs import Scenario, SelectedUniversalUninstallScenario, UniversalUninstallScenarioSpec
    from .scenario_lifecycle_support import (
        ScenarioLifecycleHooks,
        ScenarioRunContext,
        UniversalUninstallOutcome,
        prepare_scenario_run,
    )
except ImportError:  # pragma: no cover - direct script import fallback
    import validation_plan  # type: ignore[no-redef]
    from platform_specs import Scenario, SelectedUniversalUninstallScenario, UniversalUninstallScenarioSpec  # type: ignore[no-redef]
    from .scenario_lifecycle_support import (  # type: ignore[no-redef]
        ScenarioLifecycleHooks,
        ScenarioRunContext,
        UniversalUninstallOutcome,
        prepare_scenario_run,
    )


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


def run_universal_uninstall_scenario(
    selected_or_scope: SelectedUniversalUninstallScenario | str,
    scenarios: list[Scenario] | None = None,
    env: dict[str, str] | None = None,
    *,
    hooks: ScenarioLifecycleHooks,
) -> dict[str, object]:
    if isinstance(selected_or_scope, SelectedUniversalUninstallScenario):
        selected = selected_or_scope
        scenario_env = env or {}
    else:
        if scenarios is None:
            raise TypeError("scenarios are required when running a universal uninstall by scope")
        selected = SelectedUniversalUninstallScenario(universal_uninstall_spec_for_scope(selected_or_scope, hooks=hooks), tuple(scenarios))
        scenario_env = env or {}
    return UniversalUninstallLifecycle(selected.spec, list(selected.installed_scenarios), scenario_env, hooks).run()
