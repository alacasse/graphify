"""Stateful custody of one isolated lifecycle subprocess session."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
from pathlib import Path, PurePosixPath

from tools.install_sandbox.validation.catalog import (
    OwnedFileSurface,
    RepairableBundleSurface,
    Scope,
    SurfaceRoot,
)
from tools.install_sandbox.validation.protocol import (
    ActionFailureFact,
    ActionKind,
    ActionRequest,
    ByteCapture,
    CommandFact,
    EntryFact,
    EntryKind,
    FilesystemSnapshot,
    ObservationFact,
    ObservationRequest,
    OperationEvent,
    OperationKind,
    PreparedSourcePath,
    RawFact,
    SandboxPath,
    SnapshotEntry,
    StreamCapture,
    SurfaceFact,
)

from .types import SandboxCleanupFact, SandboxFinishReason, SandboxRuntimeFailure


class SandboxConfigurationError(ValueError):
    """The requested local session cannot provide isolated runtime roots."""


class SandboxRuntime:
    """Own isolated roots, subprocess execution, chronology, and cleanup."""

    def __init__(
        self,
        session_root: Path,
        prepared_source: Path,
        command_timeout_seconds: float,
        capture_limit_bytes: int,
    ) -> None:
        self._session_root = session_root
        self._prepared_source = prepared_source
        self._roots = {root: session_root / root.value for root in SurfaceRoot}
        self._command_timeout_seconds = command_timeout_seconds
        self._capture_limit_bytes = capture_limit_bytes
        self._next_sequence = 0
        self._finished = False

    @classmethod
    def open(
        cls,
        session_root: Path,
        prepared_source: Path,
        *,
        command_timeout_seconds: float = 30.0,
        capture_limit_bytes: int = 1_000_000,
    ) -> SandboxRuntime:
        """Allocate one fresh session whose logical roots never alias."""

        if session_root.exists() or session_root.is_symlink():
            raise SandboxConfigurationError(f"sandbox session root already exists: {session_root}")
        if prepared_source.is_symlink() or not prepared_source.is_dir():
            raise SandboxConfigurationError(
                f"prepared source is not a real directory: {prepared_source}"
            )
        resolved_session = session_root.resolve(strict=False)
        resolved_source = prepared_source.resolve()
        if resolved_session.is_relative_to(resolved_source) or resolved_source.is_relative_to(
            resolved_session
        ):
            raise SandboxConfigurationError(
                "sandbox session and prepared source must not alias or contain one another"
            )
        if command_timeout_seconds <= 0 or capture_limit_bytes <= 0:
            raise SandboxConfigurationError("sandbox timeout and capture limit must be positive")
        session_root.mkdir(parents=True)
        runtime = cls(
            resolved_session,
            resolved_source,
            command_timeout_seconds,
            capture_limit_bytes,
        )
        for root in runtime._roots.values():
            root.mkdir()
        return runtime

    def _event(self, kind: OperationKind) -> OperationEvent:
        event = OperationEvent(self._next_sequence, kind, time.monotonic_ns())
        self._next_sequence += 1
        return event

    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment["HOME"] = str(self._roots[SurfaceRoot.HOME])
        environment["XDG_CONFIG_HOME"] = str(self._roots[SurfaceRoot.XDG])
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment.pop("CLAUDE_CONFIG_DIR", None)
        environment.pop("LOCALAPPDATA", None)
        return environment

    def _working_directory(self, scope: Scope) -> tuple[SurfaceRoot, Path]:
        logical = SurfaceRoot.USER_CWD if scope is Scope.USER else SurfaceRoot.PROJECT
        return logical, self._roots[logical]

    def _capture(self, value: bytes, *, complete: bool) -> StreamCapture:
        visible = value[: self._capture_limit_bytes]
        omitted = len(value) - len(visible)
        return StreamCapture(
            visible,
            complete and omitted == 0,
            omitted,
        )

    def _relative_path(self, value: str) -> PurePosixPath | None:
        path = PurePosixPath(value)
        if (
            not path.parts
            or path.is_absolute()
            or str(path) != value
            or any(part == ".." for part in path.parts)
            or "\\" in value
        ):
            return None
        return path

    def _observed_path(
        self,
        location: SandboxPath | PreparedSourcePath,
    ) -> tuple[Path | None, str | None]:
        relative = self._relative_path(location.path)
        if isinstance(location, SandboxPath):
            base = self._roots[location.root]
        else:
            base = self._prepared_source
        if relative is None:
            return None, "path is not a safe relative path"
        path = base.joinpath(*relative.parts)
        try:
            resolved_parent = path.parent.resolve(strict=False)
            if not resolved_parent.is_relative_to(base):
                return None, "path parent escapes its root"
        except OSError as error:
            return None, str(error)
        return path, None

    def _file_entry(
        self,
        location: SandboxPath | PreparedSourcePath,
        path: Path,
    ) -> EntryFact:
        digest = hashlib.sha256()
        size = 0
        captured = bytearray()
        with path.open("rb") as handle:
            while chunk := handle.read(64 * 1024):
                digest.update(chunk)
                size += len(chunk)
                remaining = self._capture_limit_bytes - len(captured)
                if remaining > 0:
                    captured.extend(chunk[:remaining])
        omitted = size - len(captured)
        return EntryFact(
            location,
            EntryKind.FILE,
            size=size,
            sha256=digest.hexdigest(),
            content=ByteCapture(bytes(captured), omitted == 0, omitted),
        )

    def _entry(self, location: SandboxPath | PreparedSourcePath) -> EntryFact:
        path, error = self._observed_path(location)
        if path is None:
            return EntryFact(location, EntryKind.OTHER, error=error)
        try:
            if path.is_symlink():
                return EntryFact(
                    location,
                    EntryKind.SYMLINK,
                    symlink_target=str(path.readlink()),
                )
            if not path.exists():
                return EntryFact(location, EntryKind.MISSING)
            if path.is_dir():
                return EntryFact(location, EntryKind.DIRECTORY)
            return (
                self._file_entry(location, path)
                if path.is_file()
                else EntryFact(location, EntryKind.OTHER)
            )
        except OSError as error:
            return EntryFact(location, EntryKind.OTHER, error=str(error))

    def _observe(self, request: ObservationRequest) -> ObservationFact:
        started = self._event(OperationKind.OBSERVATION_STARTED)
        facts: list[SurfaceFact] = []
        for surface in request.surfaces:
            destination = self._entry(SandboxPath(surface.root, surface.path))
            source = (
                self._entry(PreparedSourcePath(surface.source))
                if isinstance(surface, (OwnedFileSurface, RepairableBundleSurface))
                else None
            )
            facts.append(SurfaceFact(surface, destination, source))
        finished = self._event(OperationKind.OBSERVATION_FINISHED)
        return ObservationFact(
            request.action_id,
            tuple(facts),
            started.occurred_ns,
            finished.occurred_ns,
            (started, finished),
        )

    def _snapshot_entry(
        self,
        root: SurfaceRoot,
        base: Path,
        path: Path,
    ) -> SnapshotEntry:
        relative = path.relative_to(base).as_posix()
        try:
            if path.is_symlink():
                return SnapshotEntry(
                    root,
                    relative,
                    EntryKind.SYMLINK,
                    symlink_target=str(path.readlink()),
                )
            if not path.exists():
                return SnapshotEntry(root, relative, EntryKind.MISSING)
            if path.is_dir():
                return SnapshotEntry(root, relative, EntryKind.DIRECTORY)
            if not path.is_file():
                return SnapshotEntry(root, relative, EntryKind.OTHER)
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as handle:
                while chunk := handle.read(64 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
            return SnapshotEntry(
                root,
                relative,
                EntryKind.FILE,
                size=size,
                sha256=digest.hexdigest(),
            )
        except OSError as error:
            return SnapshotEntry(root, relative, EntryKind.OTHER, error=str(error))

    def _snapshot_root(
        self,
        root: SurfaceRoot,
        base: Path,
    ) -> tuple[SnapshotEntry, ...]:
        root_entry = self._snapshot_entry(root, base, base)
        if root_entry.kind is not EntryKind.DIRECTORY:
            return (root_entry,)
        try:
            descendants = tuple(sorted(base.rglob("*")))
        except OSError as error:
            return (
                SnapshotEntry(
                    root,
                    ".",
                    EntryKind.DIRECTORY,
                    error=str(error),
                ),
            )
        return (
            root_entry,
            *(self._snapshot_entry(root, base, path) for path in descendants),
        )

    def _snapshot(self) -> FilesystemSnapshot:
        entries = tuple(
            entry for root, base in self._roots.items() for entry in self._snapshot_root(root, base)
        )
        return FilesystemSnapshot(entries)

    def fulfil(self, request: ActionRequest) -> RawFact:
        """Fulfil one validation-owned request without assigning semantic meaning."""

        if self._finished:
            raise RuntimeError("sandbox session is already finished")
        if isinstance(request, ObservationRequest):
            return self._observe(request)
        logical_cwd, cwd = self._working_directory(request.scope)
        before_snapshot = self._snapshot()
        started = self._event(OperationKind.COMMAND_STARTED)
        try:
            process = subprocess.Popen(
                request.argv,
                cwd=cwd,
                env=self._environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
        except OSError as error:
            failed = self._event(OperationKind.COMMAND_FAILED)
            return ActionFailureFact(
                request.action_id,
                ActionKind.COMMAND,
                "spawn_command",
                str(error),
                (started, failed),
            )
        chronology = [started]
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=self._command_timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            chronology.append(self._event(OperationKind.COMMAND_TIMED_OUT))
            process.kill()
            chronology.append(self._event(OperationKind.COMMAND_TERMINATED))
            stdout, stderr = process.communicate()
        finished = self._event(OperationKind.COMMAND_FINISHED)
        chronology.append(finished)
        signal = -process.returncode if process.returncode < 0 else None
        after_snapshot = self._snapshot()
        return CommandFact(
            action_id=request.action_id,
            exit_code=process.returncode,
            argv=request.argv,
            working_directory=logical_cwd,
            signal=signal,
            timed_out=timed_out,
            stdout=self._capture(stdout, complete=not timed_out),
            stderr=self._capture(stderr, complete=not timed_out),
            started_ns=started.occurred_ns,
            finished_ns=finished.occurred_ns,
            chronology=tuple(chronology),
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
        )

    def finish(self, reason: SandboxFinishReason) -> SandboxCleanupFact:
        """Remove every owned runtime root and return raw cleanup evidence."""

        started = self._event(OperationKind.CLEANUP_STARTED)
        failures: list[SandboxRuntimeFailure] = []
        try:
            shutil.rmtree(self._session_root)
        except OSError as error:
            failures.append(SandboxRuntimeFailure("remove_session_root", str(error)))
        self._finished = True
        finished = self._event(OperationKind.CLEANUP_FINISHED)
        return SandboxCleanupFact(
            reason=reason,
            removed=not self._session_root.exists(),
            failures=tuple(failures),
            chronology=(started, finished),
        )
