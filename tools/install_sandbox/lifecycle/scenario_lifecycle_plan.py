from __future__ import annotations

from typing import cast

from .. import validation_plan
from ..targets.install_target_models import DisposableArtifactScenarioSpec, Scenario, SelectedUniversalUninstallScenario
from .scenario_lifecycle_disposable import run_disposable_artifact_scenario
from .scenario_lifecycle_standard import run_scenario
from .scenario_lifecycle_support import ScenarioLifecycleHooks
from .scenario_lifecycle_universal import run_universal_uninstall_scenario

def run_validation_plan(plan: validation_plan.ValidationPlan, env: dict[str, str], hooks: ScenarioLifecycleHooks, fail_fast_scenarios: bool = False) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    overrides = hooks.matrix_overrides
    run_one = overrides.run_scenario or (lambda scenario, scenario_env: run_scenario(scenario, scenario_env, hooks=hooks))
    run_universal = overrides.run_universal_uninstall_scenario or (
        lambda selected, scenario_env: run_universal_uninstall_scenario(selected, env=scenario_env, hooks=hooks)
    )
    run_disposable = overrides.run_disposable_artifact_scenario or (lambda spec, scenario_env: run_disposable_artifact_scenario(spec, scenario_env, hooks=hooks))
    standard_failed = False
    synthetic_work_started = False
    for work_item in plan.validation_work_items:
        if work_item.kind == "standard_scenario":
            scenario = cast(Scenario, work_item.payload)
            result = run_one(scenario, env)
            results.append(result)
            if fail_fast_scenarios and result.get("passed") is not True:
                return results
            if result.get("passed") is not True:
                standard_failed = True
            continue

        if not synthetic_work_started:
            synthetic_work_started = True
            if standard_failed:
                return results

        if work_item.kind == "universal_uninstall":
            selected = cast(SelectedUniversalUninstallScenario, work_item.payload)
            result = run_universal(selected, env)
            results.append(result)
            continue

        if work_item.kind == "disposable_artifact":
            disposable_spec = cast(DisposableArtifactScenarioSpec, work_item.payload)
            result = run_disposable(disposable_spec, env)
            results.append(result)
            continue

        raise RuntimeError(f"unknown validation work item kind: {work_item.kind}")
    return results
