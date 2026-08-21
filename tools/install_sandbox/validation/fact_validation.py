"""Validate and correlate untrusted Raw Facts at the fulfil boundary."""

from __future__ import annotations

import hashlib
from typing import cast

from .catalog import (
    OwnedFileSurface,
    RepairableBundleSurface,
    SurfaceRoot,
    TextEntrySurface,
)
from .command_fact_validation import (
    valid_chronology,
    valid_command,
    valid_command_failure,
    valid_relative_path,
    valid_sha256,
)
from .protocol import (
    ActionFailureFact,
    ActionId,
    ActionKind,
    ActionRequest,
    ByteCapture,
    CommandFact,
    CommandFailureFact,
    CommandRequest,
    EntryFact,
    EntryKind,
    ObservationFact,
    ObservationRequest,
    OperationKind,
    PreparedSourcePath,
    RawFact,
    SandboxPath,
    SurfaceFact,
)

_PRE_SPAWN_COMMAND_FAILURE_OPERATIONS = frozenset({"spawn_command", "establish_process_custody"})


def _valid_action_id(value: object) -> bool:
    if not isinstance(value, ActionId):
        return False
    plan_id = cast(object, value.plan_id)
    ordinal = cast(object, value.ordinal)
    return isinstance(plan_id, str) and bool(plan_id) and type(ordinal) is int and ordinal >= 0


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


def _valid_location(location: object) -> bool:
    if isinstance(location, SandboxPath):
        return not (
            type(cast(object, location.root)) is not SurfaceRoot
            or not valid_relative_path(cast(object, location.path))
        )
    if isinstance(location, PreparedSourcePath):
        return valid_relative_path(cast(object, location.path))
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
            or not valid_sha256(cast(object, value.sha256))
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
    return valid_chronology(
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
        ((OperationKind.COMMAND_STARTED, OperationKind.COMMAND_FAILED),)
        if expected_kind is ActionKind.COMMAND
        else ((OperationKind.OBSERVATION_STARTED, OperationKind.OBSERVATION_FAILED),)
    )
    operation = cast(object, value.operation)
    return (
        value.action_kind is expected_kind
        and isinstance(operation, str)
        and bool(operation)
        and (
            expected_kind is ActionKind.OBSERVATION
            or operation in _PRE_SPAWN_COMMAND_FAILURE_OPERATIONS
        )
        and isinstance(cast(object, value.detail), str)
        and bool(value.detail)
        and valid_chronology(
            value.chronology,
            None,
            None,
            expected_events,
        )
    )


def validate_raw_fact(request: ActionRequest, value: object) -> RawFact | str:
    """Return one coherent correlated Raw Fact or a fail-closed protocol reason."""

    if not isinstance(
        value,
        (CommandFact, CommandFailureFact, ObservationFact, ActionFailureFact),
    ):
        return "Raw Fact has an unknown variant"
    if not _valid_action_id(cast(object, value.action_id)):
        return "Raw Fact action identity is invalid"
    if value.action_id != request.action_id:
        return "Raw Fact action identity disagrees with the request"
    if isinstance(value, ActionFailureFact):
        return value if _valid_failure(request, value) else "Raw Fact failure evidence is invalid"
    if isinstance(request, CommandRequest) and isinstance(value, CommandFact):
        return value if valid_command(request, value) else "Raw Fact command evidence is invalid"
    if isinstance(request, CommandRequest) and isinstance(value, CommandFailureFact):
        return (
            value
            if valid_command_failure(request, value)
            else "Raw Fact incomplete command evidence is invalid"
        )
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
