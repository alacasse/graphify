#!/usr/bin/env python3
"""Canonical development quality gate for the install sandbox."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from install_sandbox_quality_checks import (
    CONFIGURATION_EXIT,
    CheckResult,
    CheckStatus,
    FastCheckConfigurationError,
    run_fast_checks,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("fast", help="run the inexpensive install-sandbox checks")
    return parser


def _report(result: CheckResult) -> None:
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
    suffix = "" if result.exit_code is None else f" (exit {result.exit_code})"
    print(f"[{result.status.value}] {result.name}{suffix}")


def _fast(repository: Path) -> int:
    run = run_fast_checks(repository)
    if isinstance(run, FastCheckConfigurationError):
        print(f"fast: CONFIGURATION ERROR: {run.message}", file=sys.stderr)
        return CONFIGURATION_EXIT

    for result in run.results:
        _report(result)

    if any(result.configuration_error for result in run.results):
        print("fast: CONFIGURATION ERROR")
        return CONFIGURATION_EXIT
    if any(result.status is CheckStatus.FAIL for result in run.results):
        print("fast: FAIL")
        return 1
    print("fast: PASS")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "fast":
        return _fast(Path.cwd().resolve())
    raise AssertionError(f"unhandled command: {arguments.command}")


if __name__ == "__main__":
    raise SystemExit(main())
