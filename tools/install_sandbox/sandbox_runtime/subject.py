"""Prepare, install, and origin-bind one fictional subject package."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from tools.install_sandbox.validation.protocol import OperationEvent, OperationKind, StreamCapture

from .process import MINIMUM_TERMINATION_GRACE_SECONDS, LocalProcessRunner
from .process_types import IncompleteProcessExecution, ProcessExecution, ProcessFailure
from .subject_types import (
    PreparedSubjectFact,
    SubjectAssessment,
    SubjectCommandFact,
    SubjectRejected,
    SubjectVerified,
)

_EXCLUDED_NAMES = (".git", ".venv", "__pycache__", "graphify-out", "my-docs")
_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}$")
_ORIGIN_PROBE = """
import importlib.metadata
import json
import shutil
from pathlib import Path
import graphify

distribution = importlib.metadata.distribution("graphify-fictional")
print(json.dumps({
    "distribution_root": str(Path(distribution.locate_file("")).resolve()),
    "executable_path": str(Path(shutil.which("graphify") or "").resolve()),
    "import_path": str(Path(graphify.__file__).resolve()),
    "version": distribution.version,
}, sort_keys=True))
""".strip()


@dataclass(frozen=True, slots=True)
class _SubjectWorkspace:
    prepared: Path
    environment: Path
    artifacts: Path
    neutral: Path


@dataclass(frozen=True, slots=True)
class _OriginBinding:
    version: str
    distribution_root: Path
    executable_path: Path
    import_path: Path


class SubjectProcessRunner(Protocol):
    """Controllable process-custody boundary used by subject preparation."""

    def run(
        self,
        argv: tuple[str, ...],
        cwd: Path,
        environment: dict[str, str],
        event: Callable[[OperationKind], OperationEvent],
    ) -> ProcessExecution | IncompleteProcessExecution | ProcessFailure: ...


class SubjectRuntime:
    """Own the writable subject copy, isolated installation, and probe sequence."""

    def __init__(
        self,
        timeout_seconds: float = 60.0,
        capture_limit_bytes: int = 1_000_000,
        process_runner: SubjectProcessRunner | None = None,
    ):
        self._runner = process_runner or LocalProcessRunner(
            timeout_seconds, MINIMUM_TERMINATION_GRACE_SECONDS, capture_limit_bytes
        )
        self._sequence = 0

    def _event(self, kind: OperationKind) -> OperationEvent:
        value = OperationEvent(self._sequence, kind, time.monotonic_ns())
        self._sequence += 1
        return value

    def _command(
        self,
        stage: str,
        argv: tuple[str, ...],
        cwd: Path,
        environment: dict[str, str],
    ) -> SubjectCommandFact:
        result = self._runner.run(argv, cwd, environment, self._event)
        if isinstance(result, ProcessFailure):
            occurred = (
                result.chronology[0].occurred_ns if result.chronology else time.monotonic_ns()
            )
            return SubjectCommandFact(
                stage,
                argv,
                str(cwd),
                None,
                False,
                StreamCapture(b"", True),
                StreamCapture(b"", True),
                occurred,
                occurred,
                f"{result.operation}: {result.detail}",
            )
        failure = None
        if isinstance(result, IncompleteProcessExecution):
            failure = f"{result.operation}: {result.detail}"
        return SubjectCommandFact(
            stage,
            argv,
            str(cwd),
            result.exit_code,
            result.timed_out,
            result.stdout,
            result.stderr,
            result.started_ns,
            result.finished_ns,
            failure,
        )

    def _reject(
        self,
        stage: str,
        detail: str,
        preparation: PreparedSubjectFact | None,
        commands: list[SubjectCommandFact],
    ) -> SubjectRejected:
        return SubjectRejected(stage, detail, preparation, tuple(commands))

    @staticmethod
    def _valid_inputs(
        source_root: Path,
        work_root: Path,
        target_names: tuple[str, ...],
    ) -> bool:
        try:
            resolved_source = source_root.resolve(strict=True)
            resolved_work = work_root.resolve(strict=False)
        except OSError:
            return False
        roots_alias = resolved_source.is_relative_to(resolved_work) or resolved_work.is_relative_to(
            resolved_source
        )
        return (
            not source_root.is_symlink()
            and source_root.is_dir()
            and not work_root.exists()
            and not work_root.is_symlink()
            and not roots_alias
            and bool(target_names)
            and len(target_names) == len(set(target_names))
        )

    def _prepare(
        self,
        source_root: Path,
        work_root: Path,
        target_names: tuple[str, ...],
    ) -> tuple[_SubjectWorkspace, PreparedSubjectFact] | SubjectRejected:
        if not self._valid_inputs(source_root, work_root, target_names):
            return self._reject("prepare-source", "subject roots or targets are invalid", None, [])
        workspace = _SubjectWorkspace(
            work_root / "prepared",
            work_root / "environment",
            work_root / "artifacts",
            work_root / "neutral",
        )
        try:
            work_root.mkdir(parents=True)
            shutil.copytree(
                source_root,
                workspace.prepared,
                ignore=shutil.ignore_patterns(*_EXCLUDED_NAMES),
            )
            workspace.neutral.mkdir()
            workspace.artifacts.mkdir()
            copied = tuple(
                sorted(
                    path.relative_to(workspace.prepared).as_posix()
                    for path in workspace.prepared.rglob("*")
                    if path.is_file()
                )
            )
        except OSError as error:
            return self._reject("prepare-source", str(error), None, [])
        return workspace, PreparedSubjectFact(
            str(source_root.resolve()),
            str(workspace.prepared.resolve()),
            copied,
            _EXCLUDED_NAMES,
        )

    @staticmethod
    def _environment() -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONNOUSERSITE="1",
            PIP_NO_INDEX="1",
        )
        environment.pop("PYTHONHOME", None)
        environment.pop("PYTHONPATH", None)
        return environment

    def _run_required(
        self,
        stage: str,
        argv: tuple[str, ...],
        workspace: _SubjectWorkspace,
        environment: dict[str, str],
        preparation: PreparedSubjectFact,
        commands: list[SubjectCommandFact],
    ) -> SubjectCommandFact | SubjectRejected:
        fact = self._command(stage, argv, workspace.neutral, environment)
        commands.append(fact)
        if fact.failure is None and not fact.timed_out and fact.exit_code == 0:
            return fact
        detail = fact.failure or (
            "command timed out" if fact.timed_out else f"command exited {fact.exit_code}"
        )
        return self._reject(stage, detail, preparation, commands)

    def _install(
        self,
        workspace: _SubjectWorkspace,
        environment: dict[str, str],
        preparation: PreparedSubjectFact,
        commands: list[SubjectCommandFact],
    ) -> tuple[Path, Path] | SubjectRejected:
        built = self._run_required(
            "build-subject",
            (
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--no-isolation",
                "--outdir",
                str(workspace.artifacts),
                str(workspace.prepared),
            ),
            workspace,
            environment,
            preparation,
            commands,
        )
        if isinstance(built, SubjectRejected):
            return built
        wheels = tuple(workspace.artifacts.glob("*.whl"))
        if len(wheels) != 1 or not wheels[0].is_file():
            return self._reject(
                "build-subject",
                "package build did not produce exactly one wheel",
                preparation,
                commands,
            )
        artifact = wheels[0]
        created = self._run_required(
            "create-environment",
            (sys.executable, "-m", "venv", str(workspace.environment)),
            workspace,
            environment,
            preparation,
            commands,
        )
        if isinstance(created, SubjectRejected):
            return created
        executable = workspace.environment / "bin/graphify"
        environment["PATH"] = f"{executable.parent}{os.pathsep}{environment.get('PATH', '')}"
        installed = self._run_required(
            "install-subject",
            (
                str(workspace.environment / "bin/python"),
                "-m",
                "pip",
                "install",
                "--no-deps",
                str(artifact),
            ),
            workspace,
            environment,
            preparation,
            commands,
        )
        return installed if isinstance(installed, SubjectRejected) else (artifact, executable)

    @staticmethod
    def _decode_origin(fact: SubjectCommandFact) -> _OriginBinding | str:
        try:
            body = json.loads(fact.stdout.data.decode("utf-8"))
            version = body["version"]
            if not isinstance(version, str):
                return "origin probe version is not a string"
            return _OriginBinding(
                version,
                Path(body["distribution_root"]),
                Path(body["executable_path"]),
                Path(body["import_path"]),
            )
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
            return f"malformed origin probe: {error}"

    @staticmethod
    def _origin_is_bound(
        binding: _OriginBinding,
        environment_root: Path,
        executable: Path,
    ) -> bool:
        return (
            _VERSION.fullmatch(binding.version) is not None
            and binding.distribution_root.is_relative_to(environment_root)
            and binding.import_path.is_relative_to(environment_root)
            and binding.executable_path == executable.resolve()
            and executable.is_file()
            and os.access(executable, os.X_OK)
        )

    def _probe(
        self,
        workspace: _SubjectWorkspace,
        environment: dict[str, str],
        executable: Path,
        artifact: Path,
        target_names: tuple[str, ...],
        preparation: PreparedSubjectFact,
        commands: list[SubjectCommandFact],
    ) -> SubjectAssessment:
        def run(stage: str, argv: tuple[str, ...]) -> SubjectCommandFact | SubjectRejected:
            return self._run_required(stage, argv, workspace, environment, preparation, commands)

        origin = run(
            "probe-origins",
            (str(workspace.environment / "bin/python"), "-c", _ORIGIN_PROBE),
        )
        if isinstance(origin, SubjectRejected):
            return origin
        binding = self._decode_origin(origin)
        if isinstance(binding, str):
            return self._reject("probe-origins", binding, preparation, commands)
        if not self._origin_is_bound(binding, workspace.environment, executable):
            return self._reject(
                "probe-origins", "subject origins or version are invalid", preparation, commands
            )
        public_targets = self._probe_public_interface(
            workspace,
            environment,
            executable,
            binding.version,
            target_names,
            preparation,
            commands,
        )
        if isinstance(public_targets, SubjectRejected):
            return public_targets
        return SubjectVerified(
            f"graphify-fictional@{binding.version}",
            binding.version,
            executable,
            workspace.prepared,
            artifact,
            public_targets,
            preparation,
            tuple(commands),
        )

    def _probe_public_interface(
        self,
        workspace: _SubjectWorkspace,
        environment: dict[str, str],
        executable: Path,
        version: str,
        target_names: tuple[str, ...],
        preparation: PreparedSubjectFact,
        commands: list[SubjectCommandFact],
    ) -> tuple[str, ...] | SubjectRejected:
        version_probe = self._run_required(
            "probe-version",
            (str(executable), "--version"),
            workspace,
            environment,
            preparation,
            commands,
        )
        if isinstance(version_probe, SubjectRejected):
            return version_probe
        public_version = version_probe.stdout.data.decode("utf-8", errors="replace").strip()
        if public_version != f"graphify-fictional {version}":
            return self._reject(
                "probe-version", "public version disagrees with distribution", preparation, commands
            )
        targets_probe = self._run_required(
            "probe-targets",
            (str(executable), "install", "--list"),
            workspace,
            environment,
            preparation,
            commands,
        )
        if isinstance(targets_probe, SubjectRejected):
            return targets_probe
        observed_targets = tuple(
            line.strip()
            for line in targets_probe.stdout.data.decode("utf-8", errors="replace").splitlines()
            if line.strip()
        )
        if observed_targets != target_names:
            return self._reject(
                "probe-targets",
                "public target list disagrees with the catalog",
                preparation,
                commands,
            )
        return observed_targets

    def assess(
        self,
        source_root: Path,
        work_root: Path,
        target_names: tuple[str, ...],
    ) -> SubjectAssessment:
        """Return verified origin evidence or one fail-closed preparation rejection."""

        prepared = self._prepare(source_root, work_root, target_names)
        if isinstance(prepared, SubjectRejected):
            return prepared
        workspace, preparation = prepared
        commands: list[SubjectCommandFact] = []
        environment = self._environment()
        installed = self._install(workspace, environment, preparation, commands)
        if isinstance(installed, SubjectRejected):
            return installed
        artifact, executable = installed
        return self._probe(
            workspace,
            environment,
            executable,
            artifact,
            target_names,
            preparation,
            commands,
        )
