"""Lease-backed resource custody for the integrated architecture prototype.

THROWAWAY PROTOTYPE - NOT PRODUCTION - NOT APPROVED.

The application supplies typed requests and receives lossless mechanism facts.
All filesystem descriptors, process handles, namespace claims, and bundle
mutation capabilities remain private to this module.
"""

from __future__ import annotations

import hashlib
import os
import signal
import stat
import subprocess
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol, cast

from .bundle import (
    BundleFaults,
    BundleStore,
    CoherentBundleReadView,
    PersistenceRejected,
    PersistenceResult,
    QuiescenceProof,
    RecoveryClaim,
    RecoveryManager,
    RecoveryRejected,
    TerminalCommitResult,
)
from .model import (
    ActionId,
    ActionRequest,
    ActionUnavailable,
    Cancelled,
    CapturedStream,
    CommandFact,
    CommandRequest,
    CommandTermination,
    Exited,
    ObservationFact,
    ObservationReadFailure,
    ObservationRequest,
    ObservedAbsent,
    ObservedContent,
    RawFact,
    RunId,
    Signalled,
    SpawnFailed,
    StreamCaptureFailure,
    TimedOut,
)

_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
type StreamFact = CapturedStream | StreamCaptureFailure


class _ObservationRule(Protocol):
    key: str
    location: str


@dataclass(frozen=True)
class ResourceFaults:
    fail_stream: Literal["stdout", "stderr"] | None = None
    fail_after_bytes: int = 0
    command_timeout_seconds: float = 5.0
    cancel_scenarios: frozenset[str] = frozenset()
    fail_observations: frozenset[str] = frozenset()
    max_observation_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        if self.fail_after_bytes < 0:
            raise ValueError("fail_after_bytes must be nonnegative")
        if self.command_timeout_seconds <= 0:
            raise ValueError("command timeout must be positive")
        if self.max_observation_bytes <= 0:
            raise ValueError("observation bound must be positive")


_DEFAULT_RESOURCE_FAULTS = ResourceFaults()
_DEFAULT_BUNDLE_FAULTS = BundleFaults()


@dataclass(frozen=True)
class ContainerClaimed:
    exact_name: str
    owner_id: str


@dataclass(frozen=True)
class ContainerClaimRejected:
    exact_name: str
    detail: str


type ContainerClaimResult = ContainerClaimed | ContainerClaimRejected


@dataclass(frozen=True)
class ResourceChronologyEntry:
    sequence: int
    action_id: ActionId | None
    operation: str
    detail: str


@dataclass(frozen=True)
class ResourceSnapshot:
    owner_id: str
    active: bool
    bundle_path: Path
    bundle_identity: tuple[int, int]
    sandbox_identity: tuple[int, int]
    exact_container_names: tuple[str, ...]
    active_processes: tuple[int, ...]
    evidence_sealed: bool
    chronology: tuple[ResourceChronologyEntry, ...]


class DockerNamespaceRegistry:
    """One exact-name registry shared by adapters for one daemon namespace."""

    def __init__(self, namespace: str = "default") -> None:
        self.namespace = namespace
        self._claims: dict[str, str] = {}
        self._external: set[str] = set()
        self._lock = threading.Lock()

    def claim_exact(self, owner_id: str, exact_name: str) -> ContainerClaimResult:
        if not exact_name or "/" in exact_name or "\0" in exact_name:
            return ContainerClaimRejected(exact_name, "invalid exact container name")
        with self._lock:
            current = self._claims.get(exact_name)
            if current is not None or exact_name in self._external:
                return ContainerClaimRejected(
                    exact_name,
                    "exact container name is already claimed or present",
                )
            self._claims[exact_name] = owner_id
        return ContainerClaimed(exact_name, owner_id)

    def release_exact(self, owner_id: str, exact_name: str) -> bool:
        with self._lock:
            if self._claims.get(exact_name) != owner_id:
                return False
            if exact_name in self._external:
                return False
            self._claims.pop(exact_name)
            return True

    def owned_by(self, owner_id: str) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(name for name, owner in self._claims.items() if owner == owner_id))

    def mark_external_presence(self, exact_name: str, *, present: bool) -> None:
        """Deterministic stand-in for daemon observation, not a claim bypass."""

        with self._lock:
            if present:
                self._external.add(exact_name)
            else:
                self._external.discard(exact_name)


class _SandboxLease:
    """Pinned sandbox root used for cwd checks and bounded observations."""

    def __init__(self, root: Path) -> None:
        self.path = root.resolve(strict=True)
        self._descriptor = os.open(
            self.path,
            os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW,
        )
        details = os.fstat(self._descriptor)
        self.identity = (details.st_dev, details.st_ino)
        self._closed = False

    def checked_cwd(self, requested: str) -> Path:
        candidate = Path(requested)
        if not candidate.is_absolute():
            candidate = self.path / candidate
        resolved = candidate.resolve(strict=True)
        try:
            resolved.relative_to(self.path)
        except ValueError as error:
            raise OSError("command cwd escapes the sandbox root") from error
        if not resolved.is_dir():
            raise OSError("command cwd is not a directory")
        self._assert_identity()
        return resolved

    def read_bounded(self, relative: str, maximum: int) -> bytes | None:
        path = PurePosixPath(relative)
        if path.is_absolute() or not path.parts:
            raise OSError("observation path must be relative")
        current, opened = _open_observation_parent(self._descriptor, path.parts[:-1])
        try:
            leaf = path.parts[-1]
            _require_leaf(leaf)
            content = _read_observation_leaf(current, leaf, maximum)
            self._assert_identity()
            return content
        finally:
            for descriptor in reversed(opened):
                os.close(descriptor)

    def close(self) -> None:
        if not self._closed:
            os.close(self._descriptor)
            self._closed = True

    def _assert_identity(self) -> None:
        details = os.stat(self.path, follow_symlinks=False)
        if not stat.S_ISDIR(details.st_mode):
            raise OSError("sandbox root is no longer a directory")
        if (details.st_dev, details.st_ino) != self.identity:
            raise OSError("sandbox root identity changed")


class _HostRunLease:
    """Private owner for processes, Docker claims, and the bundle lease."""

    def __init__(
        self,
        owner_id: str,
        store: BundleStore,
        sandbox: _SandboxLease,
        registry: DockerNamespaceRegistry,
    ) -> None:
        self.owner_id = owner_id
        self.store = store
        self.sandbox = sandbox
        self.registry = registry
        self.active_processes: set[int] = set()
        self.container_names: set[str] = set()
        self.active = True
        self.evidence_sealed = False
        self._closed = False
        self._lock = threading.RLock()

    def claim_container(self, exact_name: str) -> ContainerClaimResult:
        with self._lock:
            if not self.active:
                return ContainerClaimRejected(exact_name, "host owner is closed")
            result = self.registry.claim_exact(self.owner_id, exact_name)
            if isinstance(result, ContainerClaimed):
                self.container_names.add(exact_name)
            return result

    def release_containers(self) -> bool:
        with self._lock:
            for name in tuple(sorted(self.container_names)):
                if self.registry.release_exact(self.owner_id, name):
                    self.container_names.discard(name)
            return not self.container_names and not self.registry.owned_by(self.owner_id)

    def prove_quiescence(self) -> QuiescenceProof:
        with self._lock:
            containers_absent = self.release_containers()
            processes_absent = not self.active_processes
            if not self.evidence_sealed:
                self.store.seal_evidence()
                self.evidence_sealed = True
            return self.store.issue_quiescence(
                processes_absent=processes_absent,
                containers_absent=containers_absent,
            )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self.release_containers()
            self.sandbox.close()
            self.store.close()
            self.active = False
            self._closed = True


class LeaseBackedFulfilment:
    """Small application seam backed by private typed capabilities."""

    def __init__(
        self,
        run_id: RunId,
        store: BundleStore,
        sandbox_root: Path,
        registry: DockerNamespaceRegistry,
        *,
        faults: ResourceFaults = _DEFAULT_RESOURCE_FAULTS,
    ) -> None:
        self.run_id = run_id
        self._faults = faults
        self._host = _HostRunLease(
            run_id.value,
            store,
            _SandboxLease(sandbox_root),
            registry,
        )
        self._chronology: list[ResourceChronologyEntry] = []
        self._chronology_lock = threading.Lock()

    @classmethod
    def allocate(
        cls,
        root: Path,
        leaf: str,
        run_id: RunId,
        running_record: bytes,
        sandbox_root: Path,
        registry: DockerNamespaceRegistry,
        *,
        faults: ResourceFaults = _DEFAULT_RESOURCE_FAULTS,
        bundle_faults: BundleFaults = _DEFAULT_BUNDLE_FAULTS,
    ) -> LeaseBackedFulfilment:
        store = BundleStore.allocate(
            root,
            leaf,
            run_id.value,
            running_record,
            faults=bundle_faults,
        )
        return cls(run_id, store, sandbox_root, registry, faults=faults)

    def fulfil(self, request: ActionRequest) -> RawFact:
        if request.action_id.run_id != self.run_id:
            return self._unavailable(request.action_id, "request belongs to another run")
        if isinstance(request, CommandRequest):
            return self._execute(request)
        if isinstance(request, ObservationRequest):
            return self._observe(request)
        return self._unavailable(request.action_id, "unsupported resource request")

    def reserve_container(self, exact_name: str) -> ContainerClaimResult:
        result = self._host.claim_container(exact_name)
        self._record(None, "container-claim", f"{exact_name}: {type(result).__name__}")
        return result

    def persist_evidence(self, relative_path: str, content: bytes) -> PersistenceResult:
        result = self._host.store.store_evidence_once(relative_path, content)
        self._record(None, "persist-evidence", f"{relative_path}: {type(result).__name__}")
        return result

    def update_running(self, content: bytes) -> PersistenceResult:
        result = self._host.store.store_running(content)
        self._record(None, "persist-running", type(result).__name__)
        return result

    def quiesce_and_seal(self) -> QuiescenceProof:
        proof = self._host.prove_quiescence()
        self._record(None, "quiescence", "processes and containers positively absent")
        return proof

    def read_bundle(self) -> CoherentBundleReadView:
        view = self._host.store.read_coherent()
        self._record(None, "stable-read", f"generation={view.revision.generation}")
        return view

    def recheck_bundle(self, expected: CoherentBundleReadView) -> CoherentBundleReadView:
        view = self._host.store.recheck(expected)
        self._record(None, "stable-recheck", f"generation={view.revision.generation}")
        return view

    def persist_report(self, content: bytes) -> PersistenceResult:
        result = self._host.store.persist_report(content)
        self._record(None, "persist-report", type(result).__name__)
        return result

    def commit_terminal(
        self,
        assessed: CoherentBundleReadView,
        run_record: bytes,
    ) -> TerminalCommitResult:
        result = self._host.store.commit_terminal(assessed, run_record)
        self._record(None, "commit-terminal", type(result).__name__)
        return result

    def recovery_manager(self) -> RecoveryManager:
        """Return the path-nomination service, never the live capabilities."""

        return RecoveryManager()

    def _invalidate_owner_for_recovery_demo(self, proof: QuiescenceProof) -> None:
        """Simulate owner loss only after the resource layer minted absence proof."""

        self._host.store._invalidate_owner_for_recovery(proof)
        self._host.active = False
        self._record(None, "owner-invalidated", "live owner capability invalidated")

    def snapshot(self) -> ResourceSnapshot:
        return ResourceSnapshot(
            self._host.owner_id,
            self._host.active,
            self._host.store.path,
            self._host.store.identity,
            self._host.sandbox.identity,
            tuple(sorted(self._host.container_names)),
            tuple(sorted(self._host.active_processes)),
            self._host.evidence_sealed,
            tuple(self._chronology),
        )

    def close(self) -> None:
        self._host.close()

    def _execute(self, request: CommandRequest) -> CommandFact:
        started_ns = time.monotonic_ns()
        started = self._start_process(request, started_ns)
        if isinstance(started, CommandFact):
            return started
        process = started
        self._host.active_processes.add(process.pid)
        try:
            completed = self._finish_process(request, process)
        finally:
            self._host.active_processes.discard(process.pid)
        stdout_fact = self._capture(request, "stdout", completed.stdout)
        stderr_fact = self._capture(request, "stderr", completed.stderr)
        lines = [f"{request.action_id.ordinal}: command requested", completed.detail]
        if isinstance(stdout_fact, StreamCaptureFailure):
            lines.append("stdout capture incomplete")
        if isinstance(stderr_fact, StreamCaptureFailure):
            lines.append("stderr capture incomplete")
        finished_ns = time.monotonic_ns()
        self._record(request.action_id, "command-completed", "; ".join(lines[1:]))
        return CommandFact(
            request.action_id,
            request.argv,
            request.cwd,
            started_ns,
            finished_ns,
            completed.termination,
            completed.reaped,
            stdout_fact,
            stderr_fact,
            tuple(lines),
        )

    def _start_process(
        self,
        request: CommandRequest,
        started_ns: int,
    ) -> subprocess.Popen[bytes] | CommandFact:
        try:
            if not request.argv:
                raise OSError("empty argv")
            cwd = self._host.sandbox.checked_cwd(request.cwd)
            return subprocess.Popen(
                request.argv,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as error:
            self._record(request.action_id, "spawn-failed", str(error))
            return _spawn_failure_fact(request, started_ns, str(error))

    def _finish_process(
        self,
        request: CommandRequest,
        process: subprocess.Popen[bytes],
    ) -> _CompletedProcess:
        if request.scenario in self._faults.cancel_scenarios:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                stdout, stderr = process.communicate(timeout=self._faults.command_timeout_seconds)
                detail = "command cancelled and reaped"
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate()
                detail = "command cancelled, forcibly terminated, and reaped"
            return _CompletedProcess(
                Cancelled("injected cancellation"),
                process.poll() is not None,
                stdout,
                stderr,
                detail,
            )
        try:
            stdout, stderr = process.communicate(timeout=self._faults.command_timeout_seconds)
        except subprocess.TimeoutExpired:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
            termination: CommandTermination = TimedOut(self._faults.command_timeout_seconds)
            detail = "command timed out and was forcibly reaped"
        else:
            code = process.returncode
            termination = Signalled(-code) if code < 0 else Exited(code)
            detail = f"command exited raw={code}"
        return _CompletedProcess(termination, process.poll() is not None, stdout, stderr, detail)

    def _capture(
        self,
        request: CommandRequest,
        stream: Literal["stdout", "stderr"],
        content: bytes,
    ) -> StreamFact:
        failed = self._faults.fail_stream == stream
        boundary = min(self._faults.fail_after_bytes, len(content)) if failed else len(content)
        captured = content[:boundary]
        relative = f"commands/{request.action_id.ordinal:04d}.{stream}"
        persisted = self._host.store.store_evidence_once(relative, captured)
        digest = hashlib.sha256(captured).hexdigest()
        if failed:
            detail = "injected stream write OSError; partial evidence retained"
            return StreamCaptureFailure(captured, digest, len(captured), detail)
        if isinstance(persisted, PersistenceRejected):
            return StreamCaptureFailure(
                captured,
                digest,
                len(captured),
                f"stream persistence failed: {persisted.detail}",
            )
        return CapturedStream(content, hashlib.sha256(content).hexdigest(), len(content))

    def _observe(self, request: ObservationRequest) -> ObservationFact:
        items: list[ObservedContent | ObservedAbsent | ObservationReadFailure] = []
        chronology = [f"{request.action_id.ordinal}: observation requested"]
        rules = cast(tuple[_ObservationRule, ...], request.specification.rules)
        for rule in rules:
            try:
                if rule.location in self._faults.fail_observations:
                    raise OSError("injected observation read failure")
                content = self._host.sandbox.read_bounded(
                    rule.location,
                    self._faults.max_observation_bytes,
                )
                if content is None:
                    items.append(ObservedAbsent(rule.key, rule.location))
                    chronology.append(f"{rule.key}: absent")
                    continue
                items.append(
                    ObservedContent(
                        rule.key,
                        rule.location,
                        content,
                        hashlib.sha256(content).hexdigest(),
                        len(content),
                    )
                )
                chronology.append(f"{rule.key}: {len(content)} bounded bytes supplied")
            except (OSError, ValueError) as error:
                items.append(ObservationReadFailure(rule.key, rule.location, str(error)))
                chronology.append(f"{rule.key}: read failure")
        self._record(request.action_id, "observation-completed", "; ".join(chronology[1:]))
        return ObservationFact(request.action_id, tuple(items), tuple(chronology))

    def _unavailable(self, action_id: ActionId, detail: str) -> ActionUnavailable:
        chronology = (f"{action_id.ordinal}: action unavailable", detail)
        self._record(action_id, "action-unavailable", detail)
        return ActionUnavailable(action_id, detail, chronology)

    def _record(self, action_id: ActionId | None, operation: str, detail: str) -> None:
        with self._chronology_lock:
            self._chronology.append(
                ResourceChronologyEntry(
                    len(self._chronology) + 1,
                    action_id,
                    operation,
                    detail,
                )
            )


def nominate_recovery(path: Path) -> RecoveryClaim | RecoveryRejected:
    """Public recovery seam: callers nominate a path and receive no live lease."""

    return RecoveryManager().claim(path)


@dataclass(frozen=True)
class _CompletedProcess:
    termination: CommandTermination
    reaped: bool
    stdout: bytes
    stderr: bytes
    detail: str


def _spawn_failure_fact(request: CommandRequest, started_ns: int, detail: str) -> CommandFact:
    empty = _captured(b"")
    return CommandFact(
        request.action_id,
        request.argv,
        request.cwd,
        started_ns,
        time.monotonic_ns(),
        SpawnFailed(detail),
        True,
        empty,
        empty,
        (f"{request.action_id.ordinal}: command requested", f"spawn failed: {detail}"),
    )


def _captured(content: bytes) -> CapturedStream:
    return CapturedStream(content, hashlib.sha256(content).hexdigest(), len(content))


def _read_up_to(descriptor: int, maximum: int) -> bytes:
    chunks: list[bytes] = []
    remaining = maximum + 1
    while remaining > 0:
        chunk = os.read(descriptor, min(64 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    content = b"".join(chunks)
    if len(content) > maximum:
        raise OSError("observed content exceeded the configured bound while reading")
    return content


def _open_observation_parent(
    root: int,
    parts: tuple[str, ...],
) -> tuple[int, list[int]]:
    current = root
    opened: list[int] = []
    for part in parts:
        _require_leaf(part)
        current = os.open(
            part,
            os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW,
            dir_fd=current,
        )
        opened.append(current)
    return current, opened


def _read_observation_leaf(directory: int, leaf: str, maximum: int) -> bytes | None:
    try:
        details = os.stat(leaf, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(details.st_mode):
        raise OSError("observed path is not a regular file")
    if details.st_size > maximum:
        raise OSError("observed content exceeds the configured bound")
    descriptor = os.open(leaf, os.O_RDONLY | _NOFOLLOW, dir_fd=directory)
    try:
        content = _read_up_to(descriptor, maximum)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if _stat_key(details) != _stat_key(after):
        raise OSError("observed file changed while being read")
    return content


def _stat_key(details: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        details.st_mode,
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
    )


def _require_leaf(leaf: str) -> None:
    if not leaf or leaf in {".", ".."} or "/" in leaf or "\0" in leaf:
        raise OSError(f"unsafe path component: {leaf!r}")
