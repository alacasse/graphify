"""Validation-owned closed action and Raw Fact protocol."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from .catalog import InstallSurface, Scope, SurfaceRoot


@dataclass(frozen=True, slots=True)
class ActionId:
    plan_id: str
    ordinal: int


class SurfaceExpectation(StrEnum):
    INSTALLED = "installed"
    ABSENT = "absent"


class PhaseKind(StrEnum):
    """The closed lifecycle and aggregate phases carried across the boundary."""

    INSTALL = "install"
    REINSTALL = "reinstall"
    REPAIR = "repair"
    TARGET_UNINSTALL = "target-uninstall"
    AGGREGATE_PREPARE = "aggregate-prepare"
    AGGREGATE_UNINSTALL = "aggregate-uninstall"


class OperationKind(StrEnum):
    """Mechanically observed runtime events in one total session chronology."""

    COMMAND_STARTED = "command_started"
    COMMAND_FAILED = "command_failed"
    COMMAND_TIMED_OUT = "command_timed_out"
    COMMAND_TERMINATED = "command_terminated"
    COMMAND_FINISHED = "command_finished"
    OBSERVATION_STARTED = "observation_started"
    OBSERVATION_FINISHED = "observation_finished"
    CLEANUP_STARTED = "cleanup_started"
    CLEANUP_FINISHED = "cleanup_finished"


@dataclass(frozen=True, slots=True)
class OperationEvent:
    sequence: int
    kind: OperationKind
    occurred_ns: int


@dataclass(frozen=True, slots=True)
class StreamCapture:
    """Bounded exact bytes captured from one subprocess stream."""

    data: bytes
    complete: bool
    omitted_bytes: int = 0


class ActionKind(StrEnum):
    COMMAND = "command"
    OBSERVATION = "observation"


@dataclass(frozen=True, slots=True)
class ByteCapture:
    """Bounded bytes captured from one filesystem entry."""

    data: bytes
    complete: bool
    omitted_bytes: int = 0


@dataclass(frozen=True, slots=True)
class SandboxPath:
    root: SurfaceRoot
    path: str


@dataclass(frozen=True, slots=True)
class PreparedSourcePath:
    path: str


type ObservedLocation = SandboxPath | PreparedSourcePath


class EntryKind(StrEnum):
    MISSING = "missing"
    FILE = "file"
    DIRECTORY = "directory"
    SYMLINK = "symlink"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class EntryFact:
    location: ObservedLocation
    kind: EntryKind
    size: int | None = None
    sha256: str | None = None
    content: ByteCapture | None = None
    symlink_target: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SurfaceFact:
    surface: InstallSurface
    destination: EntryFact
    source: EntryFact | None


@dataclass(frozen=True, slots=True)
class SnapshotEntry:
    root: SurfaceRoot
    path: str
    kind: EntryKind
    size: int | None = None
    sha256: str | None = None
    symlink_target: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class FilesystemSnapshot:
    entries: tuple[SnapshotEntry, ...]


@dataclass(frozen=True, slots=True)
class TargetSubject:
    name: str


@dataclass(frozen=True, slots=True)
class AggregateSubject:
    preparation_targets: tuple[str, ...]


type ActionSubject = TargetSubject | AggregateSubject


@dataclass(frozen=True, slots=True)
class CommandRequest:
    """Ask the Sandbox Runtime to invoke one planned product command."""

    action_id: ActionId
    subject: ActionSubject
    scope: Scope
    phase: PhaseKind
    argv: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ObservationRequest:
    """Ask the Sandbox Runtime to observe planned Install Surfaces."""

    action_id: ActionId
    subject: ActionSubject
    scope: Scope
    phase: PhaseKind
    surfaces: tuple[InstallSurface, ...]
    expectation: SurfaceExpectation


type ActionRequest = CommandRequest | ObservationRequest


@dataclass(frozen=True, slots=True)
class CommandFact:
    """Lossless command mechanics without semantic classification."""

    action_id: ActionId
    exit_code: int
    argv: tuple[str, ...] = ()
    working_directory: SurfaceRoot | None = None
    signal: int | None = None
    timed_out: bool = False
    stdout: StreamCapture = field(default_factory=lambda: StreamCapture(b"", False))
    stderr: StreamCapture = field(default_factory=lambda: StreamCapture(b"", False))
    started_ns: int = 0
    finished_ns: int = 0
    chronology: tuple[OperationEvent, ...] = ()
    before_snapshot: FilesystemSnapshot = field(default_factory=lambda: FilesystemSnapshot(()))
    after_snapshot: FilesystemSnapshot = field(default_factory=lambda: FilesystemSnapshot(()))


@dataclass(frozen=True, slots=True)
class ObservationFact:
    """Raw filesystem mechanics without semantic classification."""

    action_id: ActionId
    surfaces: tuple[SurfaceFact, ...]
    started_ns: int = 0
    finished_ns: int = 0
    chronology: tuple[OperationEvent, ...] = ()


@dataclass(frozen=True, slots=True)
class ActionFailureFact:
    """A mechanical failure that prevented one requested Raw Fact."""

    action_id: ActionId
    action_kind: ActionKind
    operation: str
    detail: str
    chronology: tuple[OperationEvent, ...]


type RawFact = CommandFact | ObservationFact | ActionFailureFact
type Fulfil = Callable[[ActionRequest], RawFact]
