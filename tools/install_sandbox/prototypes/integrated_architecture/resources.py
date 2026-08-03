"""Lease-backed resource custody for the integrated architecture prototype.

THROWAWAY PROTOTYPE - NOT PRODUCTION - NOT APPROVED.

The application supplies typed requests and receives lossless mechanism facts.
All filesystem descriptors, process handles, namespace claims, and bundle
mutation capabilities remain private to this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import stat
import subprocess
import threading
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import ClassVar, Literal, Protocol, cast

from .bundle import (
    BundleFaults,
    BundleStore,
    CoherentBundleReadView,
    PersistenceRejected,
    PersistenceResult,
    QuiescenceProof,
    RecoveryClaim,
    RecoveryCommitPermit,
    RecoveryManager,
    RecoveryRejected,
    TerminalCommitPermit,
    TerminalCommitResult,
    reopen_completed_bundle,
)
from .model import (
    ActionId,
    ActionRequest,
    ActionUnavailable,
    Cancelled,
    CapturedStream,
    CatalogDocumentsFact,
    CatalogReadRequest,
    CommandFact,
    CommandRequest,
    CommandTermination,
    Exited,
    FixturePreparationRequest,
    FixturePreparedFact,
    ImageBuildRequest,
    ImmutableImageFact,
    ObservationFact,
    ObservationReadFailure,
    ObservationRequest,
    ObservedAbsent,
    ObservedContent,
    RawCatalogDocument,
    RawFact,
    RunId,
    Signalled,
    SpawnFailed,
    StreamCaptureFailure,
    SubjectPreparationRequest,
    SubjectPreparedFact,
    SubjectProbeFact,
    SubjectProbeRequest,
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
    fail_image_build: bool = False
    fail_catalog_read: bool = False
    fail_preparations: frozenset[str] = frozenset()
    fail_probes: frozenset[str] = frozenset()

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
class ResourceInputs:
    """Immutable deterministic inputs owned by the resource adapter."""

    source_revision: str
    catalog_documents: tuple[RawCatalogDocument, ...]
    package_origin: str = "local-wheel"
    package_version: str = "prototype-1"
    interface_available: bool = True
    _catalog_payloads: tuple[str, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.source_revision:
            raise ValueError("source revision must be nonempty")
        if not self.catalog_documents:
            raise ValueError("resource-owned catalog must be nonempty")
        try:
            payloads = tuple(
                json.dumps(item, sort_keys=True, separators=(",", ":"))
                for item in self.catalog_documents
            )
        except (TypeError, ValueError) as error:
            raise ValueError("resource-owned catalog must be JSON data") from error
        object.__setattr__(self, "_catalog_payloads", payloads)


_DEFAULT_RESOURCE_INPUTS = ResourceInputs(
    "prototype-source",
    (
        {
            "source": "prototype.yaml",
            "name": "prototype",
            "scopes": {
                "user": {
                    "supported": True,
                    "target_uninstall": True,
                    "limitations": [],
                    "effects": [
                        {
                            "kind": "owned_file",
                            "location": "prototype.txt",
                            "expected_text": "prototype",
                        }
                    ],
                },
                "project": {
                    "supported": False,
                    "reason": "prototype default",
                    "limitations": ["prototype default catalog"],
                },
            },
        },
    ),
)


def _fresh_catalog_documents(inputs: ResourceInputs) -> tuple[RawCatalogDocument, ...]:
    documents: list[RawCatalogDocument] = []
    for payload in inputs._catalog_payloads:
        decoded: object = json.loads(payload)
        if not isinstance(decoded, dict):
            raise ValueError("resource-owned catalog document must be an object")
        documents.append(cast(RawCatalogDocument, decoded))
    return tuple(documents)


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


@dataclass(frozen=True)
class RetentionRequest:
    bundle: Path
    run_id: str
    keep_newest: int = 5


@dataclass(frozen=True)
class RetentionApplied:
    bundle: Path
    run_id: str
    keep_newest: int


@dataclass(frozen=True)
class RetentionRejected:
    detail: str


type RetentionResult = RetentionApplied | RetentionRejected


class RetentionAdapter:
    """Deterministic resource stand-in invoked only after diagnostic authorization."""

    def __init__(self) -> None:
        self._applied: list[RetentionApplied] = []

    def apply(self, request: RetentionRequest) -> RetentionResult:
        if request.keep_newest != 5:
            return RetentionRejected("prototype models the approved keep-five policy only")
        if not request.run_id:
            return RetentionRejected("retention run identity is empty")
        reopened = reopen_completed_bundle(request.bundle)
        if isinstance(reopened, RecoveryRejected):
            return RetentionRejected(reopened.detail)
        applied = RetentionApplied(request.bundle, request.run_id, request.keep_newest)
        self._applied.append(applied)
        return applied

    def applied(self) -> tuple[RetentionApplied, ...]:
        return tuple(self._applied)


class _DockerNamespaceRegistry:
    """Private exact-name registry for one daemon identity."""

    def __init__(self) -> None:
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


class _DockerNamespaceClient:
    """Owner-bound view; callers cannot claim or release another run's names."""

    def __init__(self, owner_id: str, registry: _DockerNamespaceRegistry) -> None:
        self.owner_id = owner_id
        self._registry = registry

    def claim_exact(self, exact_name: str) -> ContainerClaimResult:
        return self._registry.claim_exact(self.owner_id, exact_name)

    def release_exact(self, exact_name: str) -> bool:
        return self._registry.release_exact(self.owner_id, exact_name)

    def owned_names(self) -> tuple[str, ...]:
        return self._registry.owned_by(self.owner_id)


class DockerDaemonAdapter:
    """Daemon-scoped owner that manufactures private per-run namespace clients.

    The identity map is process-wide in this deterministic stand-in. Constructing
    two adapters for the same daemon identity therefore cannot manufacture two
    independent ownership authorities for the same Docker namespace.
    """

    _registries: ClassVar[dict[str, _DockerNamespaceRegistry]] = {}
    _registries_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, daemon_identity: str = "default") -> None:
        if not daemon_identity or "\0" in daemon_identity:
            raise ValueError("daemon identity must be a nonempty safe string")
        self.daemon_identity = daemon_identity
        with self._registries_lock:
            self._registry = self._registries.setdefault(
                daemon_identity,
                _DockerNamespaceRegistry(),
            )

    def _client(self, owner_id: str) -> _DockerNamespaceClient:
        return _DockerNamespaceClient(owner_id, self._registry)

    def mark_external_presence(self, exact_name: str, *, present: bool) -> None:
        """Deterministic daemon observation used by the prototype harness."""

        self._registry.mark_external_presence(exact_name, present=present)


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

    def prepare_fixtures(
        self,
        entries: tuple[tuple[str, str], ...],
    ) -> tuple[tuple[str, str], ...]:
        prepared: list[tuple[str, str]] = []
        for relative, text in entries:
            path = PurePosixPath(relative)
            if path.is_absolute() or not path.parts:
                raise OSError("fixture path must be relative")
            if any(part in {"", ".", ".."} for part in path.parts):
                raise OSError("fixture path must be canonical")
            parent = self.path.joinpath(*path.parts[:-1])
            parent.mkdir(parents=True, exist_ok=True)
            resolved_parent = parent.resolve(strict=True)
            resolved_parent.relative_to(self.path)
            leaf = resolved_parent / path.parts[-1]
            descriptor = os.open(
                leaf,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _NOFOLLOW,
                0o600,
            )
            try:
                content = text.encode()
                view = memoryview(content)
                while view:
                    written = os.write(descriptor, view)
                    view = view[written:]
            finally:
                os.close(descriptor)
            prepared.append((relative, hashlib.sha256(text.encode()).hexdigest()))
        self._assert_identity()
        return tuple(prepared)

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
        docker: DockerDaemonAdapter,
    ) -> None:
        self.owner_id = owner_id
        self.store = store
        self.sandbox = sandbox
        self.docker = docker._client(owner_id)
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
            result = self.docker.claim_exact(exact_name)
            if isinstance(result, ContainerClaimed):
                self.container_names.add(exact_name)
            return result

    def release_containers(self) -> bool:
        with self._lock:
            for name in tuple(sorted(self.container_names)):
                if self.docker.release_exact(name):
                    self.container_names.discard(name)
            return not self.container_names and not self.docker.owned_names()

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
        docker: DockerDaemonAdapter,
        *,
        faults: ResourceFaults = _DEFAULT_RESOURCE_FAULTS,
        inputs: ResourceInputs = _DEFAULT_RESOURCE_INPUTS,
    ) -> None:
        self.run_id = run_id
        self._faults = faults
        self._inputs = inputs
        self._prepared_subjects: dict[tuple[str, str], str] = {}
        self._host = _HostRunLease(
            run_id.value,
            store,
            _SandboxLease(sandbox_root),
            docker,
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
        docker: DockerDaemonAdapter,
        *,
        faults: ResourceFaults = _DEFAULT_RESOURCE_FAULTS,
        bundle_faults: BundleFaults = _DEFAULT_BUNDLE_FAULTS,
        inputs: ResourceInputs = _DEFAULT_RESOURCE_INPUTS,
    ) -> LeaseBackedFulfilment:
        store = BundleStore.allocate(
            root,
            leaf,
            run_id.value,
            running_record,
            faults=bundle_faults,
        )
        return cls(run_id, store, sandbox_root, docker, faults=faults, inputs=inputs)

    def fulfil(self, request: ActionRequest) -> RawFact:
        if request.action_id.run_id != self.run_id:
            return self._unavailable(request.action_id, "request belongs to another run")
        control_fact = self._fulfil_control(request)
        if control_fact is not None:
            return control_fact
        if isinstance(request, CommandRequest):
            return self._execute(request)
        if isinstance(request, ObservationRequest):
            return self._observe(request)
        return self._unavailable(request.action_id, "unsupported resource request")

    def _fulfil_control(self, request: ActionRequest) -> RawFact | None:
        if isinstance(request, ImageBuildRequest):
            return self._build_image(request)
        if isinstance(request, CatalogReadRequest):
            return self._read_catalog(request)
        if isinstance(request, SubjectPreparationRequest):
            return self._prepare_subject(request)
        if isinstance(request, SubjectProbeRequest):
            return self._probe_subject(request)
        if isinstance(request, FixturePreparationRequest):
            return self._prepare_fixtures(request)
        return None

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
        permit: TerminalCommitPermit,
    ) -> TerminalCommitResult:
        result = self._host.store.commit_terminal(permit)
        self._record(None, "commit-terminal", type(result).__name__)
        return result

    def abandon_after_failure(self, proof: QuiescenceProof) -> None:
        """Invalidate ownership only from this lease's positive quiescence proof."""

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

    def _build_image(self, request: ImageBuildRequest) -> RawFact:
        if self._faults.fail_image_build:
            return self._unavailable(request.action_id, "immutable image build failed")
        if request.source_revision != self._inputs.source_revision:
            return self._unavailable(request.action_id, "source revision is not resource-owned")
        identity = "sha256:" + hashlib.sha256(request.source_revision.encode()).hexdigest()
        self._record(request.action_id, "image-built", identity)
        return ImmutableImageFact(request.action_id, request.source_revision, identity)

    def _read_catalog(self, request: CatalogReadRequest) -> RawFact:
        if self._faults.fail_catalog_read:
            return self._unavailable(request.action_id, "catalog acquisition failed")
        expected = "sha256:" + hashlib.sha256(self._inputs.source_revision.encode()).hexdigest()
        if request.immutable_image_identity != expected:
            return self._unavailable(request.action_id, "catalog image identity mismatch")
        self._record(
            request.action_id, "catalog-read", f"{len(self._inputs.catalog_documents)} docs"
        )
        return CatalogDocumentsFact(
            request.action_id,
            request.immutable_image_identity,
            _fresh_catalog_documents(self._inputs),
        )

    def _prepare_subject(self, request: SubjectPreparationRequest) -> RawFact:
        key = f"{request.target}:{request.scope.value}"
        if key in self._faults.fail_preparations:
            return self._unavailable(request.action_id, "subject preparation failed")
        identity = hashlib.sha256(f"{self._inputs.source_revision}:{key}".encode()).hexdigest()
        self._prepared_subjects[(request.target, request.scope.value)] = identity
        self._record(request.action_id, "subject-prepared", key)
        return SubjectPreparedFact(
            request.action_id,
            request.target,
            request.scope,
            identity,
        )

    def _probe_subject(self, request: SubjectProbeRequest) -> RawFact:
        key = f"{request.target}:{request.scope.value}"
        prepared = self._prepared_subjects.get((request.target, request.scope.value))
        if key in self._faults.fail_probes or prepared != request.prepared_identity:
            return self._unavailable(request.action_id, "subject probe failed")
        self._record(request.action_id, "subject-probed", key)
        return SubjectProbeFact(
            request.action_id,
            request.target,
            request.scope,
            request.prepared_identity,
            self._inputs.package_origin,
            self._inputs.package_version,
            self._inputs.interface_available,
        )

    def _prepare_fixtures(self, request: FixturePreparationRequest) -> RawFact:
        try:
            prepared = self._host.sandbox.prepare_fixtures(request.entries)
        except (OSError, ValueError) as error:
            return self._unavailable(request.action_id, f"fixture preparation failed: {error}")
        self._record(request.action_id, "fixtures-prepared", str(len(prepared)))
        return FixturePreparedFact(request.action_id, prepared)

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
            request.scenario,
            request.phase,
            request.purpose,
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
        return ObservationFact(
            request.action_id,
            tuple(items),
            tuple(chronology),
            request.scenario,
            request.phase,
        )

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


class RecoverySession:
    """Opaque resource-owned recovery session; raw descriptors never escape."""

    def __init__(self, claim: RecoveryClaim) -> None:
        self._claim = claim

    @property
    def bundle_path(self) -> Path:
        return self._claim.path

    def read_bundle(self) -> CoherentBundleReadView:
        return self._claim.read_coherent()

    def commit_incomplete(self, permit: RecoveryCommitPermit) -> TerminalCommitResult:
        return self._claim.commit_incomplete(permit)

    def close(self) -> None:
        self._claim.close()


def nominate_recovery(path: Path) -> RecoverySession | RecoveryRejected:
    """Nominate a path; only an opaque permit-bound session may escape."""

    claimed = RecoveryManager().claim(path)
    return claimed if isinstance(claimed, RecoveryRejected) else RecoverySession(claimed)


def reopen_completed(path: Path) -> CoherentBundleReadView | RecoveryRejected:
    """Open a terminal bundle through a fresh descriptor-bound stable reader."""

    return reopen_completed_bundle(path)


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
        request.scenario,
        request.phase,
        request.purpose,
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
