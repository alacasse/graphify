"""Descriptor-bound Diagnostic Bundle mechanics for the integrated prototype.

THROWAWAY PROTOTYPE - NOT PRODUCTION - NOT APPROVED.

This module owns bytes, identities, stable views, and exclusive publication.  It
does not decode diagnostic documents or decide whether a run passed or failed.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import secrets
import stat
import threading
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

RUN_RECORD = "run.json"
REPORT_RECORD = "report.md"
OWNER_MARKER = ".owner"
LEASE_RECORD = ".lease"
GENERATION_RECORD = ".generation"
QUIESCENCE_RECORD = ".quiescence"
TERMINAL_CLAIM = ".terminal-claim"
RECOVERY_CLAIM = ".recovery-claim"

_INTERNAL_NAMES = frozenset(
    {
        OWNER_MARKER,
        LEASE_RECORD,
        GENERATION_RECORD,
        QUIESCENCE_RECORD,
        TERMINAL_CLAIM,
        RECOVERY_CLAIM,
    }
)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


class BundleCoherenceError(OSError):
    """A stable view could not be proven."""


class PersistenceFailureKind(StrEnum):
    CONFLICT = "conflict"
    IDENTITY = "identity"
    IO = "io"
    ORDERING = "ordering"


@dataclass(frozen=True)
class ArtifactReference:
    relative_path: PurePosixPath
    size: int
    sha256: str


@dataclass(frozen=True)
class PersistedArtifact:
    reference: ArtifactReference


@dataclass(frozen=True)
class PersistenceRejected:
    kind: PersistenceFailureKind
    detail: str


type PersistenceResult = PersistedArtifact | PersistenceRejected


@dataclass(frozen=True)
class BundleEntry:
    relative_path: PurePosixPath
    content: bytes
    reference: ArtifactReference


@dataclass(frozen=True)
class BundleRevision:
    parent_device: int
    parent_inode: int
    device: int
    inode: int
    generation: int
    signature: str


@dataclass(frozen=True)
class CoherentBundleReadView:
    path: Path
    revision: BundleRevision
    entries: tuple[BundleEntry, ...]

    def all(self, relative_path: str | PurePosixPath) -> tuple[BundleEntry, ...]:
        selected = PurePosixPath(relative_path)
        return tuple(entry for entry in self.entries if entry.relative_path == selected)

    def one(self, relative_path: str | PurePosixPath) -> BundleEntry:
        matches = self.all(relative_path)
        if len(matches) != 1:
            raise BundleCoherenceError(
                f"expected exactly one {relative_path!s} entry; observed {len(matches)}"
            )
        return matches[0]


@dataclass(frozen=True)
class TerminalCommitted:
    reference: ArtifactReference


@dataclass(frozen=True)
class TerminalCommitRejected:
    kind: PersistenceFailureKind
    detail: str


type TerminalCommitResult = TerminalCommitted | TerminalCommitRejected


@dataclass(frozen=True)
class QuiescenceProof:
    owner_id: str
    device: int
    inode: int
    running_sha256: str


@dataclass(frozen=True)
class IncompleteTerminalIntent:
    """Recovery's only permitted terminal intent."""

    report: bytes
    run_record: bytes


@dataclass(frozen=True)
class RecoveryRejected:
    kind: PersistenceFailureKind
    detail: str


@dataclass(frozen=True)
class BundleFaults:
    fail_writes: frozenset[str] = frozenset()
    mutate_during_next_read: bool = False


_DEFAULT_BUNDLE_FAULTS = BundleFaults()


@dataclass(frozen=True)
class _Signature:
    path: PurePosixPath
    mode: int
    device: int
    inode: int
    size: int
    modified_ns: int
    changed_ns: int


class BundleStore:
    """Private live-owner capability for one newly allocated bundle leaf."""

    def __init__(
        self,
        path: Path,
        owner_id: str,
        parent_descriptor: int,
        root_descriptor: int,
        lease_descriptor: int,
        faults: BundleFaults,
    ) -> None:
        self.path = path
        self.owner_id = owner_id
        self._parent_descriptor = parent_descriptor
        self._root_descriptor = root_descriptor
        self._lease_descriptor: int | None = lease_descriptor
        self._faults = faults
        self._lock = threading.RLock()
        self._evidence_sealed = False
        self._terminal_committed = False
        self._closed = False
        self._mutate_during_next_read = faults.mutate_during_next_read
        root = os.fstat(root_descriptor)
        parent = os.fstat(parent_descriptor)
        self._identity = (root.st_dev, root.st_ino)
        self._parent_identity = (parent.st_dev, parent.st_ino)

    @classmethod
    def allocate(
        cls,
        root: Path,
        leaf: str,
        owner_id: str,
        running_record: bytes,
        *,
        faults: BundleFaults = _DEFAULT_BUNDLE_FAULTS,
    ) -> BundleStore:
        _require_leaf(leaf)
        root.mkdir(parents=True, exist_ok=True)
        parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW)
        bundle: int | None = None
        lease: int | None = None
        try:
            bundle, lease = _initialize_bundle(parent, leaf, owner_id)
            store = cls(root / leaf, owner_id, parent, bundle, lease, faults)
            parent = -1
            bundle = None
            lease = None
            result = store.store_running(running_record)
            if isinstance(result, PersistenceRejected):
                store.close()
                raise OSError(result.detail)
            return store
        finally:
            if lease is not None:
                os.close(lease)
            if bundle is not None:
                os.close(bundle)
            if parent >= 0:
                os.close(parent)

    @property
    def identity(self) -> tuple[int, int]:
        return self._identity

    def store_running(self, content: bytes) -> PersistenceResult:
        with self._lock:
            if self._evidence_sealed:
                return PersistenceRejected(
                    PersistenceFailureKind.ORDERING,
                    "running evidence is sealed",
                )
            return self._replace_public(RUN_RECORD, content)

    def store_evidence_once(self, relative_path: str, content: bytes) -> PersistenceResult:
        with self._lock:
            if self._evidence_sealed:
                return PersistenceRejected(
                    PersistenceFailureKind.ORDERING,
                    "evidence writers are sealed",
                )
            return self._write_public_once(relative_path, content)

    def persist_report(self, content: bytes) -> PersistenceResult:
        with self._lock:
            if not self._evidence_sealed:
                return PersistenceRejected(
                    PersistenceFailureKind.ORDERING,
                    "evidence must be sealed before report persistence",
                )
            return self._write_public_once(REPORT_RECORD, content)

    def seal_evidence(self) -> None:
        with self._lock:
            self._evidence_sealed = True

    def read_coherent(self) -> CoherentBundleReadView:
        with self._lock:
            self._assert_path_binding()
            before = _snapshot_signatures(self._root_descriptor)
            if self._mutate_during_next_read:
                self._mutate_during_next_read = False
                _write_exclusive_at(self._root_descriptor, ".fault-mutation", b"changed\n")
            entries = _read_public_entries(self._root_descriptor, before)
            after = _snapshot_signatures(self._root_descriptor)
            self._assert_path_binding()
            if before != after:
                raise BundleCoherenceError("bundle changed while the coherent view was read")
            generation = _read_generation(self._root_descriptor)
            revision = BundleRevision(
                parent_device=self._parent_identity[0],
                parent_inode=self._parent_identity[1],
                device=self._identity[0],
                inode=self._identity[1],
                generation=generation,
                signature=_signature_digest(after),
            )
            return CoherentBundleReadView(self.path, revision, entries)

    def recheck(self, expected: CoherentBundleReadView) -> CoherentBundleReadView:
        current = self.read_coherent()
        if current.revision != expected.revision or current.entries != expected.entries:
            raise BundleCoherenceError("bundle changed after assessment")
        return current

    def commit_terminal(
        self,
        assessed: CoherentBundleReadView,
        run_record: bytes,
    ) -> TerminalCommitResult:
        with self._lock:
            if self._terminal_committed:
                return TerminalCommitRejected(
                    PersistenceFailureKind.CONFLICT,
                    "terminal Run Record was already committed",
                )
            if not self._evidence_sealed:
                return TerminalCommitRejected(
                    PersistenceFailureKind.ORDERING,
                    "evidence must be sealed before terminal publication",
                )
            try:
                self.recheck(assessed)
                assessed.one(REPORT_RECORD)
                assessed.one(RUN_RECORD)
                _write_exclusive_at(self._root_descriptor, TERMINAL_CLAIM, b"claimed\n")
                result = self._replace_public(RUN_RECORD, run_record)
                if isinstance(result, PersistenceRejected):
                    return TerminalCommitRejected(result.kind, result.detail)
                self._terminal_committed = True
                return TerminalCommitted(result.reference)
            except FileExistsError:
                return TerminalCommitRejected(
                    PersistenceFailureKind.CONFLICT,
                    "another terminal publisher already claimed the bundle",
                )
            except (BundleCoherenceError, OSError) as error:
                return TerminalCommitRejected(PersistenceFailureKind.IDENTITY, str(error))

    def issue_quiescence(
        self,
        *,
        processes_absent: bool,
        containers_absent: bool,
    ) -> QuiescenceProof:
        """Mint absence proof without releasing the live-owner lease."""

        with self._lock:
            if not processes_absent or not containers_absent:
                raise OSError("positive process and container absence is required")
            running = _read_file_at(self._root_descriptor, PurePosixPath(RUN_RECORD))
            proof = QuiescenceProof(
                self.owner_id,
                self._identity[0],
                self._identity[1],
                hashlib.sha256(running).hexdigest(),
            )
            content = _quiescence_bytes(proof)
            try:
                _write_exclusive_at(self._root_descriptor, QUIESCENCE_RECORD, content)
            except FileExistsError:
                if (
                    _read_file_at(self._root_descriptor, PurePosixPath(QUIESCENCE_RECORD))
                    != content
                ):
                    raise OSError("conflicting quiescence proof") from None
            return proof

    def _invalidate_owner_for_recovery(self, proof: QuiescenceProof) -> None:
        """Prototype-only crash boundary; never exposed by the public coordinator."""

        with self._lock:
            expected = _quiescence_bytes(proof)
            observed = _read_file_at(self._root_descriptor, PurePosixPath(QUIESCENCE_RECORD))
            if observed != expected or proof.owner_id != self.owner_id:
                raise OSError("quiescence proof does not belong to this owner")
            _atomic_replace_at(
                self._root_descriptor,
                OWNER_MARKER,
                _owner_bytes(self.owner_id, "invalidated"),
            )
            lease = self._lease_descriptor
            if lease is None:
                raise OSError("live-owner lease is already invalidated")
            _replace_descriptor_bytes(lease, b"state=invalidated\n")
            fcntl.flock(lease, fcntl.LOCK_UN)
            os.close(lease)
            self._lease_descriptor = None

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            lease = self._lease_descriptor
            if lease is not None:
                fcntl.flock(lease, fcntl.LOCK_UN)
                os.close(lease)
                self._lease_descriptor = None
            for descriptor in (self._root_descriptor, self._parent_descriptor):
                with suppress(OSError):
                    os.close(descriptor)
            self._closed = True

    def _write_public_once(self, relative_path: str, content: bytes) -> PersistenceResult:
        if relative_path in self._faults.fail_writes:
            return PersistenceRejected(
                PersistenceFailureKind.IO,
                f"injected persistence failure for {relative_path}",
            )
        try:
            self._assert_path_binding()
            parent, leaf = _open_parent(self._root_descriptor, _safe_parts(relative_path))
            try:
                _write_exclusive_at(parent, leaf, content)
            finally:
                if parent != self._root_descriptor:
                    os.close(parent)
            self._bump_generation()
            return PersistedArtifact(_artifact_reference(relative_path, content))
        except FileExistsError:
            return PersistenceRejected(
                PersistenceFailureKind.CONFLICT,
                f"write-once artifact already exists: {relative_path}",
            )
        except (OSError, ValueError) as error:
            return PersistenceRejected(PersistenceFailureKind.IO, str(error))

    def _replace_public(self, relative_path: str, content: bytes) -> PersistenceResult:
        if relative_path in self._faults.fail_writes:
            return PersistenceRejected(
                PersistenceFailureKind.IO,
                f"injected persistence failure for {relative_path}",
            )
        try:
            self._assert_path_binding()
            _atomic_replace_at(self._root_descriptor, relative_path, content)
            self._bump_generation()
            return PersistedArtifact(_artifact_reference(relative_path, content))
        except (OSError, ValueError) as error:
            return PersistenceRejected(PersistenceFailureKind.IO, str(error))

    def _bump_generation(self) -> None:
        generation = _read_generation(self._root_descriptor) + 1
        _atomic_replace_at(
            self._root_descriptor,
            GENERATION_RECORD,
            f"{generation}\n".encode(),
        )

    def _assert_path_binding(self) -> None:
        parent = os.fstat(self._parent_descriptor)
        if (parent.st_dev, parent.st_ino) != self._parent_identity:
            raise BundleCoherenceError("bundle parent identity changed")
        current = os.stat(
            self.path.name,
            dir_fd=self._parent_descriptor,
            follow_symlinks=False,
        )
        if not stat.S_ISDIR(current.st_mode):
            raise BundleCoherenceError("bundle path is no longer a directory")
        if (current.st_dev, current.st_ino) != self._identity:
            raise BundleCoherenceError("bundle path identity changed")


class RecoveryClaim:
    """Exclusive descriptor-bound recovery capability."""

    def __init__(
        self,
        path: Path,
        parent_descriptor: int,
        root_descriptor: int,
        lease_descriptor: int,
        identity: tuple[int, int],
        parent_identity: tuple[int, int],
        owner_marker: bytes,
        running_record: bytes,
        quiescence_record: bytes,
    ) -> None:
        self.path = path
        self._parent_descriptor = parent_descriptor
        self._root_descriptor = root_descriptor
        self._lease_descriptor: int | None = lease_descriptor
        self._identity = identity
        self._parent_identity = parent_identity
        self._owner_marker = owner_marker
        self._running_record = running_record
        self._quiescence_record = quiescence_record
        self._lock = threading.Lock()
        self._consumed = False

    def read_coherent(self) -> CoherentBundleReadView:
        self._recheck_basis()
        before = _snapshot_signatures(self._root_descriptor)
        entries = _read_public_entries(self._root_descriptor, before)
        after = _snapshot_signatures(self._root_descriptor)
        self._recheck_basis()
        if before != after:
            raise BundleCoherenceError("bundle changed during recovery assessment")
        revision = BundleRevision(
            self._parent_identity[0],
            self._parent_identity[1],
            self._identity[0],
            self._identity[1],
            _read_generation(self._root_descriptor),
            _signature_digest(after),
        )
        return CoherentBundleReadView(self.path, revision, entries)

    def commit_incomplete(
        self,
        intent: IncompleteTerminalIntent,
    ) -> TerminalCommitResult:
        with self._lock:
            if self._consumed:
                return TerminalCommitRejected(
                    PersistenceFailureKind.CONFLICT,
                    "recovery claim was already consumed",
                )
            self._consumed = True
            try:
                self._recheck_basis()
                _persist_recovery_report(self._root_descriptor, intent.report)
                self._recheck_basis()
                _write_exclusive_at(self._root_descriptor, TERMINAL_CLAIM, b"recovery\n")
                _atomic_replace_at(self._root_descriptor, RUN_RECORD, intent.run_record)
                _bump_generation_at(self._root_descriptor)
                return TerminalCommitted(_artifact_reference(RUN_RECORD, intent.run_record))
            except FileExistsError as error:
                return TerminalCommitRejected(PersistenceFailureKind.CONFLICT, str(error))
            except (BundleCoherenceError, OSError) as error:
                return TerminalCommitRejected(PersistenceFailureKind.IDENTITY, str(error))
            finally:
                self.close()

    def close(self) -> None:
        lease = self._lease_descriptor
        if lease is None:
            return
        fcntl.flock(lease, fcntl.LOCK_UN)
        os.close(lease)
        os.close(self._root_descriptor)
        os.close(self._parent_descriptor)
        self._lease_descriptor = None

    def _recheck_basis(self) -> None:
        parent = os.fstat(self._parent_descriptor)
        if (parent.st_dev, parent.st_ino) != self._parent_identity:
            raise BundleCoherenceError("recovery parent identity changed")
        current = os.stat(
            self.path.name,
            dir_fd=self._parent_descriptor,
            follow_symlinks=False,
        )
        if not stat.S_ISDIR(current.st_mode):
            raise BundleCoherenceError("recovery path is no longer a directory")
        if (current.st_dev, current.st_ino) != self._identity:
            raise BundleCoherenceError("recovery path identity changed")
        expected = (
            (OWNER_MARKER, self._owner_marker),
            (RUN_RECORD, self._running_record),
            (QUIESCENCE_RECORD, self._quiescence_record),
            (LEASE_RECORD, b"state=invalidated\n"),
        )
        for relative, content in expected:
            if _read_file_at(self._root_descriptor, PurePosixPath(relative)) != content:
                raise BundleCoherenceError(f"{relative} changed after recovery claim")


class RecoveryManager:
    """Accept a path nomination and mint a recovery capability only from proof."""

    def claim(self, path: Path) -> RecoveryClaim | RecoveryRejected:
        handles: _RecoveryHandles | None = None
        try:
            handles = _open_recovery_handles(path)
            owner, running, quiescence = _read_recovery_basis(handles)
            _write_exclusive_at(
                handles.root,
                RECOVERY_CLAIM,
                secrets.token_hex(16).encode(),
            )
            claim = RecoveryClaim(
                path,
                handles.parent,
                handles.root,
                handles.lease,
                handles.identity,
                handles.parent_identity,
                owner,
                running,
                quiescence,
            )
            handles.transferred = True
            return claim
        except BlockingIOError:
            return RecoveryRejected(
                PersistenceFailureKind.CONFLICT,
                "live owner or another recovery claim still holds the bundle",
            )
        except FileExistsError:
            return RecoveryRejected(
                PersistenceFailureKind.CONFLICT,
                "another recovery claim already exists",
            )
        except (OSError, ValueError) as error:
            return RecoveryRejected(PersistenceFailureKind.IDENTITY, str(error))
        finally:
            if handles is not None:
                handles.close()


@dataclass
class _RecoveryHandles:
    parent: int
    root: int
    lease: int
    identity: tuple[int, int]
    parent_identity: tuple[int, int]
    transferred: bool = False

    def close(self) -> None:
        if self.transferred:
            return
        with suppress(OSError):
            fcntl.flock(self.lease, fcntl.LOCK_UN)
        os.close(self.lease)
        os.close(self.root)
        os.close(self.parent)


def _open_recovery_handles(path: Path) -> _RecoveryHandles:
    _require_leaf(path.name)
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW)
    lease: int | None = None
    try:
        leaf = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISDIR(leaf.st_mode):
            raise BundleCoherenceError("recovery nomination is not a directory")
        root = os.open(
            path.name,
            os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW,
            dir_fd=parent,
        )
    except BaseException:
        os.close(parent)
        raise
    try:
        opened = os.fstat(root)
        identity = (opened.st_dev, opened.st_ino)
        if identity != (leaf.st_dev, leaf.st_ino):
            raise BundleCoherenceError("recovery path changed while opening")
        lease = os.open(LEASE_RECORD, os.O_RDWR | _NOFOLLOW, dir_fd=root)
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        if lease is not None:
            os.close(lease)
        os.close(root)
        os.close(parent)
        raise
    parent_details = os.fstat(parent)
    return _RecoveryHandles(
        parent,
        root,
        lease,
        identity,
        (parent_details.st_dev, parent_details.st_ino),
    )


def _initialize_bundle(parent: int, leaf: str, owner_id: str) -> tuple[int, int]:
    os.mkdir(leaf, mode=0o700, dir_fd=parent)
    bundle = os.open(
        leaf,
        os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW,
        dir_fd=parent,
    )
    try:
        os.mkdir("commands", mode=0o700, dir_fd=bundle)
        _write_exclusive_at(bundle, OWNER_MARKER, _owner_bytes(owner_id, "active"))
        _write_exclusive_at(bundle, GENERATION_RECORD, b"0\n")
        lease = os.open(
            LEASE_RECORD,
            os.O_CREAT | os.O_EXCL | os.O_RDWR | _NOFOLLOW,
            0o600,
            dir_fd=bundle,
        )
        try:
            os.write(lease, b"state=active\n")
            os.fsync(lease)
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(lease)
            raise
        return bundle, lease
    except BaseException:
        os.close(bundle)
        raise


def _read_recovery_basis(handles: _RecoveryHandles) -> tuple[bytes, bytes, bytes]:
    if _read_descriptor(handles.lease) != b"state=invalidated\n":
        raise BundleCoherenceError("owner was not positively invalidated")
    owner = _read_file_at(handles.root, PurePosixPath(OWNER_MARKER))
    if b"state=invalidated\n" not in owner:
        raise BundleCoherenceError("owner marker remains active")
    running = _read_file_at(handles.root, PurePosixPath(RUN_RECORD))
    quiescence = _read_file_at(handles.root, PurePosixPath(QUIESCENCE_RECORD))
    _validate_quiescence(quiescence, owner, handles.identity, running)
    try:
        os.stat(TERMINAL_CLAIM, dir_fd=handles.root, follow_symlinks=False)
    except FileNotFoundError:
        return owner, running, quiescence
    raise BundleCoherenceError("terminal publication was already claimed")


def _owner_bytes(owner_id: str, state: str) -> bytes:
    return f"owner={owner_id}\npid={os.getpid()}\nstate={state}\n".encode()


def _quiescence_bytes(proof: QuiescenceProof) -> bytes:
    return (
        f"owner={proof.owner_id}\n"
        f"device={proof.device}\n"
        f"inode={proof.inode}\n"
        f"running_sha256={proof.running_sha256}\n"
        "processes=absent\ncontainers=absent\n"
    ).encode()


def _validate_quiescence(
    proof: bytes,
    owner: bytes,
    identity: tuple[int, int],
    running: bytes,
) -> None:
    fields = _parse_fields(proof)
    owner_fields = _parse_fields(owner)
    expected = {
        "owner": owner_fields.get("owner", ""),
        "device": str(identity[0]),
        "inode": str(identity[1]),
        "running_sha256": hashlib.sha256(running).hexdigest(),
        "processes": "absent",
        "containers": "absent",
    }
    if any(fields.get(key) != value for key, value in expected.items()):
        raise BundleCoherenceError("quiescence proof does not match recovery basis")


def _parse_fields(content: bytes) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in content.decode("utf-8", errors="strict").splitlines():
        key, separator, value = line.partition("=")
        if not separator or not key or key in fields:
            raise BundleCoherenceError("invalid resource proof record")
        fields[key] = value
    return fields


def _snapshot_signatures(root: int) -> tuple[_Signature, ...]:
    signatures: list[_Signature] = []

    def visit(directory: int, prefix: PurePosixPath) -> None:
        for name in sorted(os.listdir(directory)):
            details = os.stat(name, dir_fd=directory, follow_symlinks=False)
            relative = prefix / name
            signatures.append(
                _Signature(
                    relative,
                    details.st_mode,
                    details.st_dev,
                    details.st_ino,
                    details.st_size,
                    details.st_mtime_ns,
                    details.st_ctime_ns,
                )
            )
            if stat.S_ISLNK(details.st_mode):
                raise BundleCoherenceError(f"symlink in bundle: {relative}")
            if stat.S_ISDIR(details.st_mode):
                child = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW,
                    dir_fd=directory,
                )
                try:
                    visit(child, relative)
                finally:
                    os.close(child)
            elif not stat.S_ISREG(details.st_mode):
                raise BundleCoherenceError(f"unsupported bundle entry: {relative}")

    visit(root, PurePosixPath())
    return tuple(signatures)


def _read_public_entries(
    root: int,
    signatures: tuple[_Signature, ...],
) -> tuple[BundleEntry, ...]:
    entries: list[BundleEntry] = []
    for signature in signatures:
        if not stat.S_ISREG(signature.mode) or signature.path.parts[0] in _INTERNAL_NAMES:
            continue
        content = _read_file_at(root, signature.path)
        if len(content) != signature.size:
            raise BundleCoherenceError(f"size changed while reading {signature.path}")
        entries.append(
            BundleEntry(
                signature.path,
                content,
                _artifact_reference(str(signature.path), content),
            )
        )
    return tuple(entries)


def _read_file_at(root: int, relative: PurePosixPath) -> bytes:
    parent, leaf = _open_parent(root, relative.parts)
    try:
        before = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise BundleCoherenceError(f"not a regular file: {relative}")
        descriptor = os.open(leaf, os.O_RDONLY | _NOFOLLOW, dir_fd=parent)
        try:
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 64 * 1024):
                chunks.append(chunk)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if _stat_key(before) != _stat_key(after):
            raise BundleCoherenceError(f"file changed while reading {relative}")
        return b"".join(chunks)
    finally:
        if parent != root:
            os.close(parent)


def _signature_digest(signatures: tuple[_Signature, ...]) -> str:
    digest = hashlib.sha256()
    for item in signatures:
        digest.update(
            (
                f"{item.path}\0{item.mode}\0{item.device}\0{item.inode}\0"
                f"{item.size}\0{item.modified_ns}\0{item.changed_ns}\n"
            ).encode()
        )
    return digest.hexdigest()


def _stat_key(details: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        details.st_mode,
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
    )


def _artifact_reference(relative_path: str, content: bytes) -> ArtifactReference:
    return ArtifactReference(
        PurePosixPath(relative_path),
        len(content),
        hashlib.sha256(content).hexdigest(),
    )


def _read_generation(root: int) -> int:
    content = _read_file_at(root, PurePosixPath(GENERATION_RECORD))
    try:
        return int(content)
    except ValueError as error:
        raise BundleCoherenceError("invalid bundle generation") from error


def _bump_generation_at(root: int) -> None:
    generation = _read_generation(root) + 1
    _atomic_replace_at(root, GENERATION_RECORD, f"{generation}\n".encode())


def _persist_recovery_report(root: int, content: bytes) -> None:
    try:
        _write_exclusive_at(root, REPORT_RECORD, content)
    except FileExistsError:
        if _read_file_at(root, PurePosixPath(REPORT_RECORD)) != content:
            raise BundleCoherenceError("existing recovery report bytes disagree") from None
        return
    _bump_generation_at(root)


def _write_exclusive_at(directory: int, leaf: str, content: bytes) -> None:
    descriptor = os.open(
        leaf,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY | _NOFOLLOW,
        0o600,
        dir_fd=directory,
    )
    try:
        _write_all(descriptor, content)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.fsync(directory)


def _atomic_replace_at(directory: int, leaf: str, content: bytes) -> None:
    _require_leaf(leaf)
    temporary = f".{leaf}.{secrets.token_hex(8)}"
    descriptor = os.open(
        temporary,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY | _NOFOLLOW,
        0o600,
        dir_fd=directory,
    )
    try:
        _write_all(descriptor, content)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, leaf, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    except BaseException:
        with suppress(OSError):
            os.unlink(temporary, dir_fd=directory)
        raise


def _replace_descriptor_bytes(descriptor: int, content: bytes) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    os.ftruncate(descriptor, 0)
    _write_all(descriptor, content)
    os.fsync(descriptor)


def _read_descriptor(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while chunk := os.read(descriptor, 4096):
        chunks.append(chunk)
    return b"".join(chunks)


def _write_all(descriptor: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        written = os.write(descriptor, remaining)
        if written == 0:
            raise OSError("zero-byte write")
        remaining = remaining[written:]


def _open_parent(root: int, parts: tuple[str, ...]) -> tuple[int, str]:
    if not parts:
        raise ValueError("empty relative path")
    current = root
    for part in parts[:-1]:
        _require_leaf(part)
        nested = os.open(
            part,
            os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW,
            dir_fd=current,
        )
        if current != root:
            os.close(current)
        current = nested
    _require_leaf(parts[-1])
    return current, parts[-1]


def _safe_parts(relative_path: str) -> tuple[str, ...]:
    path = PurePosixPath(relative_path)
    if path.is_absolute() or not path.parts:
        raise ValueError("artifact path must be relative")
    for part in path.parts:
        _require_leaf(part)
    return path.parts


def _require_leaf(leaf: str) -> None:
    if not leaf or leaf in {".", ".."} or "/" in leaf or "\0" in leaf:
        raise ValueError(f"unsafe path leaf: {leaf!r}")
