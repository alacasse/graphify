"""Mechanical validation for command, capture, snapshot, and chronology facts."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import cast

from .catalog import Scope, SurfaceRoot
from .protocol import (
    CommandFact,
    CommandFailureFact,
    CommandRequest,
    EntryKind,
    FilesystemSnapshot,
    OperationEvent,
    OperationKind,
    SnapshotEntry,
    StreamCapture,
)


def valid_relative_path(value: object, *, root_marker: bool = False) -> bool:
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


def valid_chronology(
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


def valid_sha256(value: object) -> bool:
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


def _valid_snapshot_entry(value: object) -> bool:
    if not isinstance(value, SnapshotEntry):
        return False
    if (
        type(cast(object, value.root)) is not SurfaceRoot
        or not valid_relative_path(cast(object, value.path), root_marker=True)
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
            and valid_sha256(cast(object, value.sha256))
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


def _valid_exit(exit_code: object, signal_value: object, *, optional: bool) -> bool:
    if exit_code is None:
        return optional and signal_value is None
    if type(exit_code) is not int:
        return False
    if exit_code < 0:
        return type(signal_value) is int and signal_value == -exit_code
    return signal_value is None


def _valid_command_mechanics(
    request: CommandRequest,
    value: CommandFact | CommandFailureFact,
) -> bool:
    timed_out = cast(object, value.timed_out)
    expected_cwd = SurfaceRoot.USER_CWD if request.scope is Scope.USER else SurfaceRoot.PROJECT
    return (
        isinstance(cast(object, value.argv), tuple)
        and value.argv == request.argv
        and value.working_directory is expected_cwd
        and type(timed_out) is bool
        and _valid_stream_capture(cast(object, value.stdout), timed_out=timed_out)
        and _valid_stream_capture(cast(object, value.stderr), timed_out=timed_out)
        and _valid_snapshot(cast(object, value.before_snapshot))
        and _valid_snapshot(cast(object, value.after_snapshot))
    )


def valid_command(request: CommandRequest, value: CommandFact) -> bool:
    timed_out = cast(object, value.timed_out)
    exit_code = cast(object, value.exit_code)
    if not _valid_command_mechanics(request, value) or not _valid_exit(
        exit_code, cast(object, value.signal), optional=False
    ):
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
    return valid_chronology(value.chronology, value.started_ns, value.finished_ns, kinds)


def valid_command_failure(request: CommandRequest, value: CommandFailureFact) -> bool:
    exit_code = cast(object, value.exit_code)
    timed_out = cast(object, value.timed_out)
    if (
        not _valid_command_mechanics(request, value)
        or not _valid_exit(exit_code, cast(object, value.signal), optional=True)
        or not isinstance(cast(object, value.operation), str)
        or not value.operation
        or not isinstance(cast(object, value.detail), str)
        or not value.detail
    ):
        return False
    kinds = (
        (
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
        if timed_out
        else (
            (OperationKind.COMMAND_STARTED, OperationKind.COMMAND_FAILED),
            (
                OperationKind.COMMAND_STARTED,
                OperationKind.COMMAND_TERMINATED,
                OperationKind.COMMAND_FAILED,
            ),
            (
                OperationKind.COMMAND_STARTED,
                OperationKind.COMMAND_TERMINATED,
                OperationKind.COMMAND_KILL_ESCALATED,
                OperationKind.COMMAND_FAILED,
            ),
        )
    )
    return valid_chronology(value.chronology, value.started_ns, value.finished_ns, kinds)
