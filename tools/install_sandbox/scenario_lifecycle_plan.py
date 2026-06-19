from __future__ import annotations

import inspect
from typing import Callable

try:
    from . import validation_plan
    from .platform_specs import DisposableArtifactScenarioSpec, SelectedUniversalUninstallScenario
    from .scenario_lifecycle_disposable import run_disposable_artifact_scenario
    from .scenario_lifecycle_standard import run_scenario
    from .scenario_lifecycle_support import ScenarioLifecycleHooks
    from .scenario_lifecycle_universal import run_universal_uninstall_scenario
except ImportError:  # pragma: no cover - direct script import fallback
    import validation_plan  # type: ignore[no-redef]
    from platform_specs import DisposableArtifactScenarioSpec, SelectedUniversalUninstallScenario  # type: ignore[no-redef]
    from scenario_lifecycle_disposable import run_disposable_artifact_scenario  # type: ignore[no-redef]
    from scenario_lifecycle_standard import run_scenario  # type: ignore[no-redef]
    from scenario_lifecycle_support import ScenarioLifecycleHooks  # type: ignore[no-redef]
    from scenario_lifecycle_universal import run_universal_uninstall_scenario  # type: ignore[no-redef]


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
