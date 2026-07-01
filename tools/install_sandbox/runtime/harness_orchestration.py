from __future__ import annotations

import platform as platform_mod
import sys
from pathlib import Path

from .. import validation_plan
from ..lifecycle import scenario_lifecycle_plan
from ..reporting import harness_run
from .sandbox_run_environment import SandboxRunEnvironment


def read_os_release() -> dict[str, str]:
    data: dict[str, str] = {}
    path = Path("/etc/os-release")
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            data[key] = value.strip().strip('"')
    return data


def run_harness(
    args,
    run_environment: SandboxRunEnvironment,
    *,
    selected_target_name: str | None,
) -> harness_run.HarnessRunResult:
    env = run_environment.sandbox_env()
    preflight_data = run_environment.preflight()
    src_data = run_environment.copy_source_tree(args.copy_source)
    package_data = run_environment.install_graphify(env)
    hooks = run_environment.scenario_lifecycle_hooks()
    plan = validation_plan.build_validation_plan(
        run_environment.scenario_registry,
        all_targets=args.all,
        target_name=selected_target_name,
        scope=args.scope,
    )

    results = scenario_lifecycle_plan.run_validation_plan(plan, env, hooks, fail_fast_scenarios=args.fail_fast_scenarios)
    return harness_run.harness_run_result(
        harness_version=run_environment.harness_version,
        python_version=sys.version,
        os_release=read_os_release(),
        architecture=platform_mod.machine(),
        package_install=package_data,
        source_snapshot=src_data,
        preflight=preflight_data,
        plan=plan,
        results=results,
    )
