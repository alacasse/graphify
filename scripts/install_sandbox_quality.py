#!/usr/bin/env python3
"""Canonical development quality gate for the install sandbox."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

CONFIGURATION_EXIT = 2
RUFF_CONFIG = "ruff.install-sandbox.toml"
PYRIGHT_CONFIG = "pyrightconfig.install-sandbox.json"
INSTALL_SANDBOX = "tools/install_sandbox"
REPLACEMENT_TEST_PATHS = (
    "tests/install_sandbox/unit",
    "tests/install_sandbox/component",
    "tests/install_sandbox/behavioral",
)
LEGACY_TYPING_AST_FINGERPRINTS = {
    "ci_result.py": "65e3207460cb20a707997a6e88230cbaf86e3d7dc9f44c6921786f7992368e85",
    "effects.py": "806bed5536360b7e4027bf046253d8803b54378d5ce1e282382565bed6704123",
    "lifecycle.py": "237ffd31bc012c069d9b026602e1d791668514c42fe872477e6a5a351beaad36",
    "models.py": "3c5aea03ea372eff699741d530f8f456e5241c814a249aeb3c13415f475b9e9c",
    "run.py": "055d9dc205b5293d8f108d7829829992a3d7e7dcd03ebabd3ba5cd13261280dc",
    "run_artifacts.py": "25aaa6c8e2b1679f7f7aeb7f5c9e472b7544d91575aab487a355cc61010c4e66",
    "sandbox_runner.py": "60892e468253bb4235ffc52ff4d12928538ef988db4d62ac10f7313d83d7ab5a",
    "specs.py": "13d21c1ded61b625887ee795aafc8c8b3edf7fd512ae89b70c65904f3d521b3c",
}
LEGACY_TYPING_FILES = frozenset(
    f"{INSTALL_SANDBOX}/{name}" for name in LEGACY_TYPING_AST_FINGERPRINTS
)
APPROVED_BANDIT_DISPOSITIONS = frozenset(
    {
        (
            f"{INSTALL_SANDBOX}/docker.py",
            23,
            'CONTAINER_HOME = "/tmp/graphify-home"  # nosec B108',
        ),
        (
            f"{INSTALL_SANDBOX}/docker.py",
            24,
            'CONTAINER_XDG = "/tmp/graphify-xdg"  # nosec B108',
        ),
        (
            f"{INSTALL_SANDBOX}/docker.py",
            25,
            'CONTAINER_PROJECT = "/tmp/graphify-project"  # nosec B108',
        ),
        (
            f"{INSTALL_SANDBOX}/docker.py",
            26,
            'CONTAINER_USER_CWD = "/tmp/graphify-user-cwd"  # nosec B108',
        ),
        (
            f"{INSTALL_SANDBOX}/docker.py",
            27,
            'CONTAINER_SOURCE = "/tmp/graphify-source"  # nosec B108',
        ),
        (
            f"{INSTALL_SANDBOX}/lifecycle.py",
            674,
            'result = execute_command(argv, Path("/tmp"), env, package_dir, "pip-install")'
            "  # nosec B108",
        ),
        (f"{INSTALL_SANDBOX}/lifecycle.py", 679, 'Path("/tmp"),  # nosec B108'),
        (f"{INSTALL_SANDBOX}/lifecycle.py", 693, 'Path("/tmp"),  # nosec B108'),
    }
)

ConfigurationCheck = Callable[[Path], str | None]


@dataclass(frozen=True)
class Check:
    name: str
    command: tuple[str, ...]
    configuration_check: ConfigurationCheck | None = None


@dataclass(frozen=True)
class CheckResult:
    name: str
    exit_code: int
    stdout: str
    stderr: str


def _path_is_covered(relative: Path, configured_paths: tuple[Path, ...]) -> bool:
    return any(relative == path or path in relative.parents for path in configured_paths)


def _ast_fingerprint(source: Path) -> str:
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    serialized = ast.dump(tree, include_attributes=False)
    return hashlib.sha256(serialized.encode()).hexdigest()


def _pyright_settings_error(config: dict[str, object]) -> str | None:
    if config.get("pythonVersion") != "3.12":
        return f"{PYRIGHT_CONFIG}: Pyright runtime must remain Python 3.12"
    if config.get("typeCheckingMode") != "basic":
        return f"{PYRIGHT_CONFIG}: default typing mode must remain basic"
    if config.get("exclude") or config.get("ignore"):
        return "typing exclusions are not permitted in declared scope"
    return None


def _configuration_paths(config: dict[str, object], key: str) -> tuple[Path, ...]:
    values = config.get(key)
    if not isinstance(values, list) or not all(isinstance(path, str) for path in values):
        raise ValueError(f"{PYRIGHT_CONFIG}: {key} must be a list of paths")
    return tuple(Path(path) for path in values)


def _required_scope_error(
    configured_paths: tuple[Path, ...],
    required_paths: tuple[str, ...],
    label: str,
) -> str | None:
    for required in required_paths:
        if not _path_is_covered(Path(required), configured_paths):
            return f"{label} scope does not cover {required}"
    return None


def _legacy_typing_scope_error(
    source: Path,
    relative: Path,
    strict_paths: tuple[Path, ...],
) -> str | None:
    if _path_is_covered(relative, strict_paths):
        return None
    relative_text = relative.as_posix()
    try:
        current = _ast_fingerprint(source)
    except (OSError, SyntaxError) as error:
        return f"unable to verify legacy typing scope for {relative_text}: {error}"
    if current != LEGACY_TYPING_AST_FINGERPRINTS[relative.name]:
        return f"changed legacy typing file is not strict: {relative_text}"
    return None


def _production_strict_scope_error(
    repository: Path,
    strict_paths: tuple[Path, ...],
) -> str | None:
    production = repository / INSTALL_SANDBOX
    for source in sorted(production.rglob("*.py")):
        relative = source.relative_to(repository)
        relative_text = relative.as_posix()
        if relative_text in LEGACY_TYPING_FILES:
            error = _legacy_typing_scope_error(source, relative, strict_paths)
            if error is not None:
                return error
        elif not _path_is_covered(relative, strict_paths):
            return f"strict scope does not cover {relative_text}"
    return None


def _strict_scope_configuration_error(repository: Path) -> str | None:
    config_path = repository / PYRIGHT_CONFIG
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return f"unable to read {PYRIGHT_CONFIG}: {error}"
    if not isinstance(config, dict):
        return f"{PYRIGHT_CONFIG}: top level must be an object"
    error = _pyright_settings_error(config)
    if error is not None:
        return error
    try:
        include_paths = _configuration_paths(config, "include")
        strict_paths = _configuration_paths(config, "strict")
    except ValueError as error:
        return str(error)
    error = _required_scope_error(
        include_paths,
        (INSTALL_SANDBOX, *REPLACEMENT_TEST_PATHS),
        "analysis",
    )
    if error is not None:
        return error
    error = _required_scope_error(strict_paths, REPLACEMENT_TEST_PATHS, "strict")
    if error is not None:
        return error
    return _production_strict_scope_error(repository, strict_paths)


def _security_disposition_configuration_error(repository: Path) -> str | None:
    production = repository / INSTALL_SANDBOX
    for source in sorted(production.rglob("*.py")):
        relative = source.relative_to(repository).as_posix()
        try:
            lines = source.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            return f"unable to verify Bandit dispositions for {relative}: {error}"
        for line_number, line in enumerate(lines, start=1):
            if "# nosec" not in line.lower():
                continue
            disposition = (relative, line_number, line.strip())
            if disposition not in APPROVED_BANDIT_DISPOSITIONS:
                return f"unapproved Bandit disposition: {relative}:{line_number}"
    return None


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
    Check(
        name="pyright",
        command=(
            "uv",
            "run",
            "--frozen",
            "--python",
            "3.12",
            "pyright",
            "--project",
            PYRIGHT_CONFIG,
            "--warnings",
        ),
        configuration_check=_strict_scope_configuration_error,
    ),
    Check(
        name="bandit",
        command=(
            "uv",
            "run",
            "--frozen",
            "--python",
            "3.12",
            "bandit",
            "-r",
            INSTALL_SANDBOX,
            "-ll",
            "-ii",
        ),
        configuration_check=_security_disposition_configuration_error,
    ),
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("fast", help="run the inexpensive install-sandbox checks")
    return parser


def _run_check(check: Check, repository: Path) -> CheckResult:
    if check.configuration_check is not None:
        error = check.configuration_check(repository)
        if error is not None:
            return CheckResult(
                name=check.name,
                exit_code=CONFIGURATION_EXIT,
                stdout="",
                stderr=f"{error}\n",
            )
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
    missing = [
        path
        for path in (RUFF_CONFIG, PYRIGHT_CONFIG, INSTALL_SANDBOX)
        if not (repository / path).exists()
    ]
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
