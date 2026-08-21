"""Validate and correlate untrusted Raw Facts at the fulfil boundary."""

from __future__ import annotations

import hashlib
from pathlib import PurePosixPath
from typing import cast

from .catalog import (
    OwnedFileSurface,
    RepairableBundleSurface,
    Scope,
    SurfaceRoot,
    TextEntrySurface,
)
from .protocol import (
    ActionFailureFact,
    ActionId,
    ActionKind,
    ActionRequest,
    ByteCapture,
    CommandFact,
    CommandRequest,
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


def _valid_action_id(value: object) -> bool:
    if not isinstance(value, ActionId):
        return False
    plan_id = cast(object, value.plan_id)
    ordinal = cast(object, value.ordinal)
    return isinstance(plan_id, str) and bool(plan_id) and type(ordinal) is int and ordinal >= 0


def _valid_relative_path(value: object, *, root_marker: bool = False) -> bool:
    if not isinstance(value, str):
        return False
    if root_marker and value == ".":
        return True
    path = PurePosixPath(value)
    return (
        bool(path.parts)
        and not path.is_absolute()
        and path.as_posix() == value
        and ".." not in path.parts
    )


def _valid_chronology(
    chronology: object,
    started_ns: object,
    finished_ns: object,
    expected_kinds: tuple[tuple[OperationKind, ...], ...],
) -> bool:
    if not isinstance(chronology, tuple) or not chronology:
        return False
    values = cast(tuple[object, ...], chronology)
    if not all(isinstance(value, OperationEvent) for value in values):
        return False
    events = cast(tuple[OperationEvent, ...], values)
    if tuple(event.kind for event in events) not in expected_kinds:
        return False
    if any(
        type(cast(object, event.sequence)) is not int
        or event.sequence < 0
        or type(cast(object, event.occurred_ns)) is not int
        or event.occurred_ns < 0
        or type(cast(object, event.kind)) is not OperationKind
        for event in events
    ):
        return False
    return (
        tuple(event.sequence for event in events)
        == tuple(range(events[0].sequence, events[0].sequence + len(events)))
        and tuple(event.occurred_ns for event in events)
        == tuple(sorted(event.occurred_ns for event in events))
        and (started_ns is None or started_ns == events[0].occurred_ns)
        and (finished_ns is None or finished_ns == events[-1].occurred_ns)
    )


def _valid_byte_capture(value: object) -> bool:
    if not isinstance(value, ByteCapture):
        return False
    data = cast(object, value.data)
    complete = cast(object, value.complete)
    omitted = cast(object, value.omitted_bytes)
    return (
        isinstance(data, bytes)
        and type(complete) is bool
        and type(omitted) is int
        and omitted >= 0
        and (not complete or omitted == 0)
        and (complete or omitted > 0)
    )


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _valid_stream_capture(value: object, *, timed_out: bool) -> bool:
    if not isinstance(value, StreamCapture):
        return False
    data = cast(object, value.data)
    complete = cast(object, value.complete)
    omitted = cast(object, value.omitted_bytes)
    error = cast(object, value.error)
    return (
        isinstance(data, bytes)
        and type(complete) is bool
        and type(omitted) is int
        and omitted >= 0
        and (error is None or (isinstance(error, str) and bool(error)))
        and (not complete or (omitted == 0 and error is None))
        and (complete or omitted > 0 or timed_out or error is not None)
    )


def _valid_location(location: object) -> bool:
    if isinstance(location, SandboxPath):
        return not (
            type(cast(object, location.root)) is not SurfaceRoot
            or not _valid_relative_path(cast(object, location.path))
        )
    if isinstance(location, PreparedSourcePath):
        return _valid_relative_path(cast(object, location.path))
    return False


def _valid_entry_payload(value: EntryFact) -> bool:
    kind = cast(object, value.kind)
    error = cast(object, value.error)
    if error is not None:
        return isinstance(error, str) and bool(error)
    if kind is EntryKind.FILE:
        raw_size = cast(object, value.size)
        raw_content = cast(object, value.content)
        if (
            type(raw_size) is not int
            or raw_size < 0
            or not _valid_sha256(cast(object, value.sha256))
            or not _valid_byte_capture(raw_content)
            or value.symlink_target is not None
        ):
            return False
        content = cast(ByteCapture, raw_content)
        if raw_size != len(content.data) + content.omitted_bytes:
            return False
        return not content.complete or value.sha256 == hashlib.sha256(content.data).hexdigest()
    if kind is EntryKind.SYMLINK:
        return (
            value.size is None
            and value.sha256 is None
            and value.content is None
            and isinstance(value.symlink_target, str)
        )
    return (
        value.size is None
        and value.sha256 is None
        and value.content is None
        and value.symlink_target is None
    )


def _valid_entry(value: object) -> bool:
    return (
        isinstance(value, EntryFact)
        and _valid_location(cast(object, value.location))
        and type(cast(object, value.kind)) is EntryKind
        and _valid_entry_payload(value)
    )


def _valid_snapshot_entry(value: object) -> bool:
    if not isinstance(value, SnapshotEntry):
        return False
    if (
        type(cast(object, value.root)) is not SurfaceRoot
        or not _valid_relative_path(cast(object, value.path), root_marker=True)
        or type(cast(object, value.kind)) is not EntryKind
    ):
        return False
    error = cast(object, value.error)
    if error is not None:
        return isinstance(error, str) and bool(error)
    if value.kind is EntryKind.FILE:
        return (
            type(cast(object, value.size)) is int
            and cast(int, value.size) >= 0
            and _valid_sha256(cast(object, value.sha256))
            and value.symlink_target is None
        )
    if value.kind is EntryKind.SYMLINK:
        return value.size is None and value.sha256 is None and isinstance(value.symlink_target, str)
    return value.size is None and value.sha256 is None and value.symlink_target is None


def _valid_snapshot(value: object) -> bool:
    if not isinstance(value, FilesystemSnapshot):
        return False
    raw_entries = cast(object, value.entries)
    if not isinstance(raw_entries, tuple):
        return False
    entries = cast(tuple[object, ...], raw_entries)
    if not all(_valid_snapshot_entry(entry) for entry in entries):
        return False
    closed = cast(tuple[SnapshotEntry, ...], entries)
    locations = tuple((entry.root, entry.path) for entry in closed)
    roots = {(entry.root, entry.path) for entry in closed if entry.path == "."}
    return len(locations) == len(set(locations)) and roots == {(root, ".") for root in SurfaceRoot}


def _valid_command(request: CommandRequest, value: CommandFact) -> bool:
    timed_out = cast(object, value.timed_out)
    exit_code = cast(object, value.exit_code)
    signal = cast(object, value.signal)
    expected_cwd = SurfaceRoot.USER_CWD if request.scope is Scope.USER else SurfaceRoot.PROJECT
    if (
        type(exit_code) is not int
        or not isinstance(cast(object, value.argv), tuple)
        or value.argv != request.argv
        or value.working_directory is not expected_cwd
        or type(timed_out) is not bool
        or not _valid_stream_capture(cast(object, value.stdout), timed_out=timed_out)
        or not _valid_stream_capture(cast(object, value.stderr), timed_out=timed_out)
        or not _valid_snapshot(cast(object, value.before_snapshot))
        or not _valid_snapshot(cast(object, value.after_snapshot))
    ):
        return False
    if exit_code < 0:
        if type(signal) is not int or signal != -exit_code:
            return False
    elif signal is not None:
        return False
    if timed_out and exit_code >= 0:
        return False
    kinds = (
        (
            (
                OperationKind.COMMAND_STARTED,
                OperationKind.COMMAND_TIMED_OUT,
                OperationKind.COMMAND_TERMINATED,
                OperationKind.COMMAND_FINISHED,
            ),
            (
                OperationKind.COMMAND_STARTED,
                OperationKind.COMMAND_TIMED_OUT,
                OperationKind.COMMAND_TERMINATED,
                OperationKind.COMMAND_KILL_ESCALATED,
                OperationKind.COMMAND_FINISHED,
            ),
        )
        if timed_out
        else (
            (OperationKind.COMMAND_STARTED, OperationKind.COMMAND_FINISHED),
            (
                OperationKind.COMMAND_STARTED,
                OperationKind.COMMAND_TERMINATED,
                OperationKind.COMMAND_FINISHED,
            ),
            (
                OperationKind.COMMAND_STARTED,
                OperationKind.COMMAND_TERMINATED,
                OperationKind.COMMAND_KILL_ESCALATED,
                OperationKind.COMMAND_FINISHED,
            ),
        )
    )
    return _valid_chronology(value.chronology, value.started_ns, value.finished_ns, kinds)


def _valid_surface_fact(expected: object, value: object) -> bool:
    if not isinstance(value, SurfaceFact) or value.surface != expected:
        return False
    if not _valid_entry(cast(object, value.destination)):
        return False
    surface = cast(OwnedFileSurface | RepairableBundleSurface | TextEntrySurface, expected)
    if value.destination.location != SandboxPath(surface.root, surface.path):
        return False
    if isinstance(surface, (OwnedFileSurface, RepairableBundleSurface)):
        return _valid_entry(cast(object, value.source)) and cast(
            EntryFact, value.source
        ).location == PreparedSourcePath(surface.source)
    return value.source is None


def _valid_observation(request: ObservationRequest, value: ObservationFact) -> bool:
    raw_surfaces = cast(object, value.surfaces)
    if not isinstance(raw_surfaces, tuple):
        return False
    surfaces = cast(tuple[object, ...], raw_surfaces)
    if len(surfaces) != len(request.surfaces):
        return False
    if not all(
        _valid_surface_fact(expected, observed)
        for expected, observed in zip(
            request.surfaces,
            surfaces,
            strict=True,
        )
    ):
        return False
    return _valid_chronology(
        value.chronology,
        value.started_ns,
        value.finished_ns,
        ((OperationKind.OBSERVATION_STARTED, OperationKind.OBSERVATION_FINISHED),),
    )


def _valid_failure(request: ActionRequest, value: ActionFailureFact) -> bool:
    expected_kind = (
        ActionKind.COMMAND if isinstance(request, CommandRequest) else ActionKind.OBSERVATION
    )
    expected_events = (
        (
            (OperationKind.COMMAND_STARTED, OperationKind.COMMAND_FAILED),
            (
                OperationKind.COMMAND_STARTED,
                OperationKind.COMMAND_TIMED_OUT,
                OperationKind.COMMAND_TERMINATED,
                OperationKind.COMMAND_FAILED,
            ),
            (
                OperationKind.COMMAND_STARTED,
                OperationKind.COMMAND_TIMED_OUT,
                OperationKind.COMMAND_TERMINATED,
                OperationKind.COMMAND_KILL_ESCALATED,
                OperationKind.COMMAND_FAILED,
            ),
        )
        if expected_kind is ActionKind.COMMAND
        else ((OperationKind.OBSERVATION_STARTED, OperationKind.OBSERVATION_FAILED),)
    )
    return (
        value.action_kind is expected_kind
        and isinstance(cast(object, value.operation), str)
        and bool(value.operation)
        and isinstance(cast(object, value.detail), str)
        and bool(value.detail)
        and _valid_chronology(
            value.chronology,
            None,
            None,
            expected_events,
        )
    )


def validate_raw_fact(request: ActionRequest, value: object) -> RawFact | str:
    """Return one coherent correlated Raw Fact or a fail-closed protocol reason."""

    if not isinstance(value, (CommandFact, ObservationFact, ActionFailureFact)):
        return "Raw Fact has an unknown variant"
    if not _valid_action_id(cast(object, value.action_id)):
        return "Raw Fact action identity is invalid"
    if value.action_id != request.action_id:
        return "Raw Fact action identity disagrees with the request"
    if isinstance(value, ActionFailureFact):
        return value if _valid_failure(request, value) else "Raw Fact failure evidence is invalid"
    if isinstance(request, CommandRequest) and isinstance(value, CommandFact):
        return value if _valid_command(request, value) else "Raw Fact command evidence is invalid"
    if isinstance(request, ObservationRequest) and isinstance(value, ObservationFact):
        return (
            value
            if _valid_observation(request, value)
            else "Raw Fact observation evidence is invalid"
        )
    return "Raw Fact variant disagrees with the request"


def validate_session_chronology(facts: tuple[RawFact, ...]) -> str | None:
    """Require all accepted facts to extend one gapless session chronology."""

    events = tuple(event for fact in facts for event in fact.chronology)
    if tuple(event.sequence for event in events) != tuple(range(len(events))):
        return "Raw Facts do not form one total session chronology"
    occurred = tuple(event.occurred_ns for event in events)
    if occurred != tuple(sorted(occurred)):
        return "Raw Facts do not form one total session chronology"
    return None
