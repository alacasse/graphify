from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

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
class ScenarioLifecycleHooks:
    output: Path
    roots: dict[str, Path]
    project: Path
    user_cwd: Path
    utc_timestamp: Callable[[], str]
    root_path: Callable[[str], Path]
    reset_sandbox_dirs: Callable[[], None]
    seed_user_owned_content: Callable[[Scenario], None]
    write_file_manifest: Callable[..., None]
    run_capture: Callable[..., subprocess.CompletedProcess[str]]
    scenario_file_state: Callable[[Scenario], dict[str, dict[str, object]]]
    assert_expected_files: Callable[[Scenario], list[dict[str, object]]]
    assert_scope_boundaries: Callable[[Scenario], list[dict[str, object]]]
    assert_no_unexpected_graphify_files: Callable[..., list[dict[str, object]]]
    copy_generated_files: Callable[[Scenario, Path], None]
    assert_idempotent_state: Callable[[dict[str, dict[str, object]], dict[str, dict[str, object]]], list[dict[str, object]]]
    seed_stale_skill_sidecars: Callable[[Scenario], list[dict[str, object]]]
    assert_installed_skill_sidecars: Callable[[Scenario], list[dict[str, object]]]
    assert_uninstalled: Callable[[Scenario], list[dict[str, object]]]
    run_equivalence_check: Callable[[Scenario, dict[str, str], Path], list[dict[str, object]]]
    risk_report: Callable[[Scenario, bool], dict[str, object]]
    command_artifact_summary: Callable[[Path], dict[str, object]]
    combined_status: Callable[[bool], str]
    known_status_values: Callable[[], list[str]]
    expected_generated_relative_keys: Callable[[Scenario], set[tuple[str, str]]]
    check_record: Callable[..., dict[str, object]]
    scenario_registry: ScenarioRegistry = DEFAULT_SCENARIO_REGISTRY
    platform_scenarios: Callable[[str, str], Iterable[Scenario]] | None = None
    run_scenario_func: Callable[[Scenario, dict[str, str]], dict[str, object]] | None = None
    universal_uninstall_scenarios_func: Callable[[list[str], str], list[tuple[str, list[Scenario]]]] | None = None
    run_universal_uninstall_scenario_func: Callable[[str, list[Scenario], dict[str, str]], dict[str, object]] | None = None
    run_purge_scenario_func: Callable[[dict[str, str]], dict[str, object]] | None = None


def scenario_artifact_dir(scenario_name: str, *, hooks: ScenarioLifecycleHooks) -> Path:
    return hooks.output / "scenarios" / scenario_name


def prepare_scenario_run(scenario: Scenario, env: dict[str, str], *, hooks: ScenarioLifecycleHooks, scenario_name: str | None = None) -> ScenarioRunContext:
    started_at = hooks.utc_timestamp()
    started_monotonic = time.monotonic()
    hooks.reset_sandbox_dirs()
    artifact_dir = scenario_artifact_dir(scenario_name or hooks.scenario_registry.scenario_id(scenario.platform, scenario.scope), hooks=hooks)
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return ScenarioRunContext(
        scenario=scenario,
        env=env,
        artifact_dir=artifact_dir,
        cwd=hooks.root_path(scenario.cwd_root),
        started_at=started_at,
        started_monotonic=started_monotonic,
    )


def scenario_duration_ms(context: ScenarioRunContext) -> int:
    return int((time.monotonic() - context.started_monotonic) * 1000)


def write_scenario_artifacts(artifact_dir: Path, assertions: dict[str, object], risks: dict[str, object]) -> None:
    (artifact_dir / "assertions.json").write_text(json.dumps(assertions, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (artifact_dir / "risk.json").write_text(json.dumps(risks, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def scenario_result_record(
    context: ScenarioRunContext,
    *,
    hooks: ScenarioLifecycleHooks,
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
        "command_artifact": hooks.command_artifact_summary(command_artifact_dir),
        "overall_status": hooks.combined_status(passed),
        "graphify_file_effects_passed": passed,
        "passed": passed,
        "risks": risks["statuses"],
    }


def run_initial_install(context: ScenarioRunContext, *, hooks: ScenarioLifecycleHooks) -> StandardScenarioStages:
    scenario = context.scenario
    hooks.seed_user_owned_content(scenario)
    hooks.write_file_manifest(context.artifact_dir / "before-install-files.json", hooks.roots, scenario=scenario)

    install_1 = hooks.run_capture(scenario.install_command, cwd=context.cwd, env=context.env, artifact_dir=context.artifact_dir, command_class="installer")
    state_after_install = hooks.scenario_file_state(scenario)
    install_checks = hooks.assert_expected_files(scenario)
    scope_checks = hooks.assert_scope_boundaries(scenario)
    unexpected_install_checks = hooks.assert_no_unexpected_graphify_files(scenario, phase="install")
    hooks.write_file_manifest(context.artifact_dir / "after-install-files.json", hooks.roots, scenario=scenario)
    hooks.copy_generated_files(scenario, context.artifact_dir)
    return StandardScenarioStages(
        install_1=install_1,
        state_after_install=state_after_install,
        install_checks=install_checks,
        scope_checks=scope_checks,
        unexpected_install_checks=unexpected_install_checks,
    )


def run_repeat_install(context: ScenarioRunContext, stages: StandardScenarioStages, *, hooks: ScenarioLifecycleHooks) -> None:
    scenario = context.scenario
    stages.install_2 = hooks.run_capture(scenario.install_command, cwd=context.cwd, env=context.env, artifact_dir=context.artifact_dir / "repeat-install", command_class="installer")
    stages.state_after_repeat = hooks.scenario_file_state(scenario)
    stages.idempotency_checks = hooks.assert_idempotent_state(stages.state_after_install, stages.state_after_repeat)
    stages.idempotency_checks.extend(hooks.assert_no_unexpected_graphify_files(scenario, phase="repeat_install"))
    hooks.write_file_manifest(context.artifact_dir / "after-repeat-install-files.json", hooks.roots, scenario=scenario)


def run_stale_sidecar_repair(context: ScenarioRunContext, stages: StandardScenarioStages, *, hooks: ScenarioLifecycleHooks) -> None:
    scenario = context.scenario
    stages.stale_sidecar_repair_seeded = hooks.seed_stale_skill_sidecars(scenario)
    if not stages.stale_sidecar_repair_seeded:
        return
    stages.stale_sidecar_repair_result = hooks.run_capture(scenario.install_command, cwd=context.cwd, env=context.env, artifact_dir=context.artifact_dir / "stale-sidecar-repair", command_class="installer")
    if stages.stale_sidecar_repair_result.returncode == 0:
        stages.stale_sidecar_repair_checks = hooks.assert_installed_skill_sidecars(scenario)
        stages.stale_sidecar_repair_checks.extend(hooks.assert_no_unexpected_graphify_files(scenario, phase="stale_sidecar_repair"))
    hooks.write_file_manifest(context.artifact_dir / "after-stale-sidecar-repair-files.json", hooks.roots, scenario=scenario)


def run_uninstall_stage(context: ScenarioRunContext, stages: StandardScenarioStages, *, hooks: ScenarioLifecycleHooks) -> None:
    scenario = context.scenario
    if not scenario.uninstall_command:
        return
    stages.uninstall_result = hooks.run_capture(scenario.uninstall_command, cwd=context.cwd, env=context.env, artifact_dir=context.artifact_dir / "uninstall", command_class="installer")
    stages.uninstall_checks = hooks.assert_uninstalled(scenario)
    stages.unexpected_uninstall_checks = hooks.assert_no_unexpected_graphify_files(scenario, phase="uninstall")
    hooks.write_file_manifest(context.artifact_dir / "after-uninstall-files.json", hooks.roots, scenario=scenario)


def run_equivalence_stage(context: ScenarioRunContext, stages: StandardScenarioStages, *, hooks: ScenarioLifecycleHooks) -> None:
    stages.equivalence_checks = hooks.run_equivalence_check(context.scenario, context.env, context.artifact_dir)


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
        "generic_direct_equivalence": hooks.scenario_registry.equivalence_status(scenario),
        "checks": checks,
    }
    risks = hooks.risk_report(scenario, passed)
    write_scenario_artifacts(context.artifact_dir, assertions, risks)
    return scenario_result_record(
        context,
        hooks=hooks,
        scenario_name=scenario_name,
        platform_name=scenario.platform,
        scope=scenario.scope,
        passed=passed,
        risks=risks,
        reproduction_command=scenario.install_command,
        command_artifact_dir=context.artifact_dir,
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
        hooks.seed_user_owned_content(scenario)
    hooks.write_file_manifest(artifact_dir / "before-install-files.json", hooks.roots)

    install_results = []
    install_checks: list[dict[str, object]] = []
    for scenario in scenarios:
        install_scenario_id = hooks.scenario_registry.scenario_id(scenario.platform, scenario.scope)
        install_dir = artifact_dir / "installs" / install_scenario_id
        result = hooks.run_capture(scenario.install_command, cwd=hooks.root_path(scenario.cwd_root), env=env, artifact_dir=install_dir, command_class="installer")
        scenario_install_checks = hooks.assert_expected_files(scenario) + hooks.assert_scope_boundaries(scenario)
        install_checks.extend(scenario_install_checks)
        install_results.append(
            {
                "scenario_id": install_scenario_id,
                "command": list(scenario.install_command),
                "exit_code": result.returncode,
                "checks": scenario_install_checks,
            }
        )
    hooks.write_file_manifest(artifact_dir / "after-install-files.json", hooks.roots, debug_full=True)

    if scope == "project":
        uninstall_command = ("graphify", "uninstall", "--project")
        cwd = hooks.project
    else:
        uninstall_command = ("graphify", "uninstall")
        cwd = hooks.user_cwd
    uninstall_result = hooks.run_capture(uninstall_command, cwd=cwd, env=env, artifact_dir=artifact_dir / "uninstall", command_class="installer")
    checks = install_checks + [check for scenario in scenarios for check in hooks.assert_uninstalled(scenario)]
    expected_keys = set().union(*(hooks.expected_generated_relative_keys(scenario) for scenario in scenarios))
    checks.extend(hooks.assert_no_unexpected_graphify_files(runner_scenario, phase="universal_uninstall", expected_keys=expected_keys))
    hooks.write_file_manifest(artifact_dir / "after-uninstall-files.json", hooks.roots, debug_full=True)
    passed = all(result["exit_code"] == 0 for result in install_results) and uninstall_result.returncode == 0 and all(check["ok"] for check in checks)
    assertions = {
        "scenario": {"id": scenario_name, "scope": scope, "platforms": [scenario.platform for scenario in scenarios]},
        "passed": passed,
        "install_results": install_results,
        "uninstall_command": list(uninstall_command),
        "uninstall_exit_code": uninstall_result.returncode,
        "checks": checks,
    }
    risks = {
        "statuses": ["graphify_install_verified" if passed else "graphify_install_failed"],
        "notes": ["universal uninstall covers Graphify-owned file effects after multiple installs"],
        "known_status_values": hooks.known_status_values(),
    }
    write_scenario_artifacts(artifact_dir, assertions, risks)
    return scenario_result_record(
        context,
        hooks=hooks,
        scenario_name=scenario_name,
        platform_name="multiple",
        scope=scope,
        passed=passed,
        risks=risks,
        reproduction_command=uninstall_command,
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
    graphify_out = hooks.project / "graphify-out"
    graphify_out.mkdir(parents=True, exist_ok=True)
    (graphify_out / "graph.json").write_text('{"nodes": [], "edges": []}\n', encoding="utf-8")
    hooks.write_file_manifest(artifact_dir / "before-install-files.json", hooks.roots)
    result = hooks.run_capture(command, cwd=hooks.project, env=env, artifact_dir=artifact_dir / "uninstall-purge", command_class="installer")
    purged = not graphify_out.exists()
    hooks.write_file_manifest(artifact_dir / "after-uninstall-files.json", hooks.roots)
    checks = [hooks.check_record(graphify_out, purged, "purged" if purged else "still_exists")]
    passed = result.returncode == 0 and purged
    assertions = {
        "scenario": {"id": scenario_name, "scope": "project", "platform": "purge"},
        "passed": passed,
        "uninstall_exit_code": result.returncode,
        "checks": checks,
    }
    risks = {
        "statuses": ["graphify_install_verified" if passed else "graphify_install_failed"],
        "notes": ["purge verified only against disposable sandbox graphify-out state"],
        "known_status_values": hooks.known_status_values(),
    }
    write_scenario_artifacts(artifact_dir, assertions, risks)
    return scenario_result_record(
        context,
        hooks=hooks,
        scenario_name=scenario_name,
        platform_name="purge",
        scope="project",
        passed=passed,
        risks=risks,
        reproduction_command=command,
        command_artifact_dir=artifact_dir / "uninstall-purge",
    )


def universal_uninstall_scenarios(platforms: list[str], scope: str, *, hooks: ScenarioLifecycleHooks) -> list[tuple[str, list[Scenario]]]:
    return hooks.scenario_registry.universal_uninstall_groups(platforms, scope)


def run_matrix_scenarios(platforms: list[str], scope: str, env: dict[str, str], *, hooks: ScenarioLifecycleHooks, fail_fast_scenarios: bool = False) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    run_one = hooks.run_scenario_func or (lambda scenario, scenario_env: run_scenario(scenario, scenario_env, hooks=hooks))
    universal_groups = hooks.universal_uninstall_scenarios_func or (lambda selected_platforms, selected_scope: universal_uninstall_scenarios(selected_platforms, selected_scope, hooks=hooks))
    run_universal = hooks.run_universal_uninstall_scenario_func or (lambda universal_scope, scenarios, scenario_env: run_universal_uninstall_scenario(universal_scope, scenarios, scenario_env, hooks=hooks))
    run_purge = hooks.run_purge_scenario_func or (lambda scenario_env: run_purge_scenario(scenario_env, hooks=hooks))
    platform_scenarios = hooks.platform_scenarios or hooks.scenario_registry.platform_scenarios
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
