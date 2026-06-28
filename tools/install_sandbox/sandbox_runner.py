#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from .lifecycle import scenario_lifecycle_support
    from . import validation_plan
    from .effects import file_effect_state
    from .reporting import agent_summary
    from .reporting import harness_run
    from .reporting import reports
    from .reporting.status import RISK_GRAPHIFY_FAILED, RISK_GRAPHIFY_VERIFIED, combined_status, known_status_values
    from .runtime import harness_orchestration
    from .runtime.sandbox_run_environment import SandboxRunEnvironment
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.install_sandbox import validation_plan  # type: ignore[no-redef]
    from tools.install_sandbox.effects import file_effect_state  # type: ignore[no-redef]
    from tools.install_sandbox.lifecycle import scenario_lifecycle_support  # type: ignore[no-redef]
    from tools.install_sandbox.reporting import agent_summary  # type: ignore[no-redef]
    from tools.install_sandbox.reporting import harness_run  # type: ignore[no-redef]
    from tools.install_sandbox.reporting import reports  # type: ignore[no-redef]
    from tools.install_sandbox.reporting.status import RISK_GRAPHIFY_FAILED, RISK_GRAPHIFY_VERIFIED, combined_status, known_status_values  # type: ignore[no-redef]
    from tools.install_sandbox.runtime import harness_orchestration  # type: ignore[no-redef]
    from tools.install_sandbox.runtime.sandbox_run_environment import SandboxRunEnvironment  # type: ignore[no-redef]


RUN_ENVIRONMENT = SandboxRunEnvironment()
ROOT_REGISTRY = RUN_ENVIRONMENT.root_registry
RUNTIME_ROOTS = RUN_ENVIRONMENT.runtime_roots
HOME = RUN_ENVIRONMENT.home
XDG_CONFIG_HOME = RUN_ENVIRONMENT.xdg_config_home
PROJECT = RUN_ENVIRONMENT.project
USER_CWD = RUN_ENVIRONMENT.user_cwd
REPO_MOUNT = RUN_ENVIRONMENT.repo_mount
SRC = RUN_ENVIRONMENT.src
OUTPUT = RUN_ENVIRONMENT.output
HARNESS_VERSION = RUN_ENVIRONMENT.harness_version
SCENARIO_REGISTRY = RUN_ENVIRONMENT.scenario_registry
USER_SENTINEL = file_effect_state.USER_SENTINEL
STALE_GRAPHIFY_SENTINEL = file_effect_state.STALE_GRAPHIFY_SENTINEL
ScenarioRunContext = scenario_lifecycle_support.ScenarioRunContext
StandardScenarioStages = scenario_lifecycle_support.StandardScenarioStages


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="In-container Graphify install scenario runner.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--platform")
    target.add_argument("--all", action="store_true")
    parser.add_argument("--scope", choices=("user", "project", "both"), default="both")
    parser.add_argument("--copy-source", choices=("always", "auto"), default="always")
    parser.add_argument("--fail-fast-scenarios", action="store_true")
    return parser.parse_args(argv)


def sandbox_env() -> dict[str, str]:
    return RUN_ENVIRONMENT.sandbox_env()


def install_graphify(env: dict[str, str]) -> dict[str, object]:
    return RUN_ENVIRONMENT.install_graphify(env)


def risk_report(scenario, passed: bool) -> dict[str, object]:
    return RUN_ENVIRONMENT.risk_report(scenario, passed)


def preflight() -> dict[str, object]:
    return RUN_ENVIRONMENT.preflight()


def scenario_lifecycle_hooks(**kwargs) -> scenario_lifecycle_support.ScenarioLifecycleHooks:
    return RUN_ENVIRONMENT.scenario_lifecycle_hooks(**kwargs)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    run_environment = RUN_ENVIRONMENT
    run_result = harness_orchestration.run_harness(args, run_environment)
    manifest = run_result.manifest()
    reports.write_manifest_json(run_environment.output / "manifest.json", manifest)
    reports.write_report_md(run_environment.output / "report.md", manifest)
    agent_summary.write_summary(run_environment.output, agent_summary.summarize_output(run_environment.output))
    reports.print_summary(run_environment.output, passed=run_result.passed, failed=run_result.failed)
    return 0 if run_result.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
