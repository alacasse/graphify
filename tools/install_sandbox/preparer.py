"""Copy the local subject and prepare its package in a separate Python environment."""

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from tools.install_sandbox.driver import CommandExecutor, command_environment, execute_command
from tools.install_sandbox.results import TestResultWriter


@dataclass(frozen=True)
class GraphifyPreparationResult:
    ready: bool
    executable: Path | None = None
    reason: str | None = None


class GraphifyPreparer:
    def __init__(self, execute: CommandExecutor = execute_command, *, timeout: float = 300):
        if timeout <= 0:
            raise ValueError("Preparation timeout must be positive")
        self.execute = execute
        self.timeout = timeout

    def prepare(
        self, subject: Path, directory: Path, writer: TestResultWriter
    ) -> GraphifyPreparationResult:
        writer.append_log("preparation.log", "Copying local subject sources\n")
        try:
            return self._prepare(subject, directory, writer)
        except OSError as error:
            reason = f"Software preparation failed: {error}"
            writer.append_log("preparation.log", reason + "\n")
            return GraphifyPreparationResult(False, reason=reason)

    def _prepare(
        self, subject: Path, directory: Path, writer: TestResultWriter
    ) -> GraphifyPreparationResult:
        directory.mkdir(parents=True, exist_ok=False)
        source = directory / "source"
        shutil.copytree(
            subject,
            source,
            symlinks=True,
            ignore=shutil.ignore_patterns(
                ".git",
                ".venv",
                "__pycache__",
                ".pytest_cache",
                ".ruff_cache",
                "graphify-out",
            ),
        )
        home = directory / "home"
        home.mkdir()
        (directory / "tmp").mkdir()
        environment = command_environment(home, directory / "tmp")
        python = directory / "venv/bin/python"
        commands = [
            [sys.executable, "-m", "venv", str(directory / "venv")],
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", str(source)],
        ]
        for args in commands:
            writer.append_log("preparation.log", f"Running {args!r}\n")
            result = self.execute(args, source, environment, self.timeout)
            writer.append_log("preparation.log", result.stdout + b"\n" + result.stderr + b"\n")
            if result.state != "completed" or result.exit_code != 0:
                reason = result.reason or f"Preparation command exited with code {result.exit_code}"
                writer.append_log("preparation.log", reason + "\n")
                return GraphifyPreparationResult(False, reason=reason)
        return GraphifyPreparationResult(True, directory / "venv/bin/graphify")
