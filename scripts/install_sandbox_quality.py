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
    status = "PASS" if result.exit_code == 0 else "FAIL"
    print(f"[{status}] {result.name} (exit {result.exit_code})")


def _fast(repository: Path) -> int:
    run = run_fast_checks(repository)
    if run.configuration_error is not None:
        print(f"fast: CONFIGURATION ERROR: {run.configuration_error}", file=sys.stderr)
        return CONFIGURATION_EXIT

    for result in run.results:
        _report(result)

    if any(result.exit_code == CONFIGURATION_EXIT for result in run.results):
        print("fast: CONFIGURATION ERROR")
        return CONFIGURATION_EXIT
    if any(result.exit_code != 0 for result in run.results):
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
