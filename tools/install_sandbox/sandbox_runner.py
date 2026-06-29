#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    # Public adapter owners.
    from . import validation_plan
    from .reporting import harness_run
    from .reporting.status import RISK_GRAPHIFY_FAILED, RISK_GRAPHIFY_VERIFIED, combined_status, known_status_values
    from .runtime import harness_orchestration
    from .runtime.sandbox_run_environment import SandboxRunEnvironment
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    # Public adapter owners.
    from tools.install_sandbox import validation_plan  # type: ignore[no-redef]
    from tools.install_sandbox.reporting import harness_run  # type: ignore[no-redef]
    from tools.install_sandbox.reporting.status import RISK_GRAPHIFY_FAILED, RISK_GRAPHIFY_VERIFIED, combined_status, known_status_values  # type: ignore[no-redef]
    from tools.install_sandbox.runtime import harness_orchestration  # type: ignore[no-redef]
    from tools.install_sandbox.runtime.sandbox_run_environment import SandboxRunEnvironment  # type: ignore[no-redef]


RUN_ENVIRONMENT = SandboxRunEnvironment()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="In-container Graphify install scenario runner.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--platform")
    target.add_argument("--all", action="store_true")
    parser.add_argument("--scope", choices=("user", "project", "both"), default="both")
    parser.add_argument("--copy-source", choices=("always", "auto"), default="always")
    parser.add_argument("--fail-fast-scenarios", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    run_result = harness_orchestration.run_harness(args, RUN_ENVIRONMENT)
    harness_run.write_harness_run_outputs(RUN_ENVIRONMENT.output, run_result)
    return 0 if run_result.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
