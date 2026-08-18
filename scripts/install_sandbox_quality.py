#!/usr/bin/env python3
"""Canonical development quality gate for the install sandbox."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


CONFIGURATION_EXIT = 2
RUFF_CONFIG = "ruff.install-sandbox.toml"
INSTALL_SANDBOX = "tools/install_sandbox"


@dataclass(frozen=True)
class Check:
    name: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class CheckResult:
    name: str
    exit_code: int
    stdout: str
    stderr: str


FAST_CHECKS = (
    Check(
        name="ruff-format",
        command=(
            "uv",
            "run",
            "--frozen",
            "--python",
            "3.12",
            "ruff",
            "format",
            "--config",
            RUFF_CONFIG,
            "--check",
            INSTALL_SANDBOX,
        ),
    ),
    Check(
        name="ruff-lint",
        command=(
            "uv",
            "run",
            "--frozen",
            "--python",
            "3.12",
            "ruff",
            "check",
            "--config",
            RUFF_CONFIG,
            INSTALL_SANDBOX,
        ),
    ),
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("fast", help="run the inexpensive install-sandbox checks")
    return parser


def _run_check(check: Check, repository: Path) -> CheckResult:
    try:
        completed = subprocess.run(
            check.command,
            cwd=repository,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        return CheckResult(
            name=check.name,
            exit_code=CONFIGURATION_EXIT,
            stdout="",
            stderr=f"unable to start child command: {error}\n",
        )
    return CheckResult(
        name=check.name,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _report(result: CheckResult) -> None:
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
    status = "PASS" if result.exit_code == 0 else "FAIL"
    print(f"[{status}] {result.name} (exit {result.exit_code})")


def _fast(repository: Path) -> int:
    missing = [path for path in (RUFF_CONFIG, INSTALL_SANDBOX) if not (repository / path).exists()]
    if missing:
        print(
            "fast: CONFIGURATION ERROR: missing " + ", ".join(missing),
            file=sys.stderr,
        )
        return CONFIGURATION_EXIT

    results = tuple(_run_check(check, repository) for check in FAST_CHECKS)
    for result in results:
        _report(result)

    if any(result.exit_code == CONFIGURATION_EXIT for result in results):
        print("fast: CONFIGURATION ERROR")
        return CONFIGURATION_EXIT
    if any(result.exit_code != 0 for result in results):
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
