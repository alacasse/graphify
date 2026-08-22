"""Serialize lossless Raw Facts into content-addressable diagnostic evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from tools.install_sandbox.sandbox_runtime.subject_types import (
    SubjectCommandFact,
    SubjectRejected,
    SubjectVerified,
)
from tools.install_sandbox.validation.protocol import (
    ActionFailureFact,
    ActionId,
    CommandFact,
    CommandFailureFact,
    EntryFact,
    FilesystemSnapshot,
    ObservationFact,
    OperationEvent,
    PreparationFact,
    RawFact,
    SandboxPath,
    StreamCapture,
)

_COMMAND_KIND = "graphify.install-sandbox.command-record"
_OBSERVATION_KIND = "graphify.install-sandbox.observation-record"
_PREPARATION_KIND = "graphify.install-sandbox.preparation-record"
_FAILURE_KIND = "graphify.install-sandbox.action-failure"
_SNAPSHOT_KIND = "graphify.install-sandbox.filesystem-snapshot"
_SUBJECT_PREPARATION_KIND = "graphify.install-sandbox.subject-preparation"
_SUBJECT_COMMAND_KIND = "graphify.install-sandbox.subject-command"


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    path: str
    kind: str
    size: int
    sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "kind": self.kind,
            "size": self.size,
            "sha256": self.sha256,
        }


class EvidenceWriter:
    """Own fresh subordinate evidence writes and their content references."""

    def __init__(self, output: Path) -> None:
        self._output = output
        self._references: list[EvidenceReference] = []

    @property
    def references(self) -> tuple[EvidenceReference, ...]:
        return tuple(sorted(self._references, key=lambda item: item.path))

    def write_bytes(self, relative: str, kind: str, payload: bytes) -> str:
        path = _safe_output_path(self._output, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(payload)
        self._references.append(
            EvidenceReference(
                relative,
                kind,
                len(payload),
                hashlib.sha256(payload).hexdigest(),
            )
        )
        return relative

    def write_document(self, relative: str, kind: str, body: dict[str, object]) -> str:
        document = {"schema": {"kind": kind, "version": 1}, **body}
        payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
        return self.write_bytes(relative, kind, payload)


def _safe_output_path(output: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if not pure.parts or pure.is_absolute() or pure.as_posix() != relative or ".." in pure.parts:
        raise ValueError(f"unsafe evidence path: {relative!r}")
    path = output.joinpath(*pure.parts)
    if path.exists() or path.is_symlink():
        raise ValueError(f"evidence path is not fresh: {relative!r}")
    return path


def _action_id(action_id: ActionId) -> dict[str, object]:
    return {"plan_id": action_id.plan_id, "ordinal": action_id.ordinal}


def _entry(entry: EntryFact) -> dict[str, object]:
    location = entry.location
    body: dict[str, object] = {
        "location": {
            "kind": "sandbox" if isinstance(location, SandboxPath) else "prepared-source",
            "path": location.path,
        },
        "entry_kind": entry.kind.value,
    }
    if isinstance(location, SandboxPath):
        body["location"] = {
            "kind": "sandbox",
            "root": location.root.value,
            "path": location.path,
        }
    for key, value in (
        ("size", entry.size),
        ("sha256", entry.sha256),
        ("symlink_target", entry.symlink_target),
        ("error", entry.error),
    ):
        if value is not None:
            body[key] = value
    return body


def _snapshot(snapshot: FilesystemSnapshot) -> dict[str, object]:
    return {
        "entries": [
            {
                "root": entry.root.value,
                "path": entry.path,
                "entry_kind": entry.kind.value,
                **({"size": entry.size} if entry.size is not None else {}),
                **({"sha256": entry.sha256} if entry.sha256 is not None else {}),
                **(
                    {"symlink_target": entry.symlink_target}
                    if entry.symlink_target is not None
                    else {}
                ),
                **({"error": entry.error} if entry.error is not None else {}),
            }
            for entry in snapshot.entries
        ]
    }


def _chronology(events: tuple[OperationEvent, ...]) -> list[dict[str, object]]:
    return [
        {
            "sequence": event.sequence,
            "kind": event.kind.value,
            "occurred_ns": event.occurred_ns,
        }
        for event in events
    ]


def _fact_stem(fact: RawFact) -> str:
    return f"facts/{fact.action_id.ordinal:04d}"


def _stream(path: str, stream: StreamCapture) -> dict[str, object]:
    return {
        "path": path,
        "complete": stream.complete,
        "omitted_bytes": stream.omitted_bytes,
        "error": stream.error,
    }


def _write_command_fact(
    writer: EvidenceWriter,
    fact: CommandFact | CommandFailureFact,
) -> str:
    stem = _fact_stem(fact)
    stdout_path = writer.write_bytes(f"{stem}.stdout.log", "command-stdout", fact.stdout.data)
    stderr_path = writer.write_bytes(f"{stem}.stderr.log", "command-stderr", fact.stderr.data)
    before_path = writer.write_document(
        f"{stem}.before.json",
        _SNAPSHOT_KIND,
        _snapshot(fact.before_snapshot),
    )
    after_path = writer.write_document(
        f"{stem}.after.json",
        _SNAPSHOT_KIND,
        _snapshot(fact.after_snapshot),
    )
    body: dict[str, object] = {
        "action_id": _action_id(fact.action_id),
        "argv": list(fact.argv),
        "working_directory": fact.working_directory.value,
        "exit_code": fact.exit_code,
        "signal": fact.signal,
        "timed_out": fact.timed_out,
        "started_ns": fact.started_ns,
        "finished_ns": fact.finished_ns,
        "chronology": _chronology(fact.chronology),
        "stdout": _stream(stdout_path, fact.stdout),
        "stderr": _stream(stderr_path, fact.stderr),
        "before_snapshot": before_path,
        "after_snapshot": after_path,
    }
    if isinstance(fact, CommandFailureFact):
        body.update({"operation": fact.operation, "diagnostic_failure": fact.detail})
    return writer.write_document(f"{stem}.command.json", _COMMAND_KIND, body)


def _write_observation_fact(writer: EvidenceWriter, fact: ObservationFact) -> str:
    return writer.write_document(
        f"{_fact_stem(fact)}.observation.json",
        _OBSERVATION_KIND,
        {
            "action_id": _action_id(fact.action_id),
            "started_ns": fact.started_ns,
            "finished_ns": fact.finished_ns,
            "chronology": _chronology(fact.chronology),
            "surfaces": [
                {
                    "destination": _entry(surface.destination),
                    "source": _entry(surface.source) if surface.source is not None else None,
                }
                for surface in fact.surfaces
            ],
        },
    )


def _write_preparation_fact(writer: EvidenceWriter, fact: PreparationFact) -> str:
    return writer.write_document(
        f"{_fact_stem(fact)}.preparation.json",
        _PREPARATION_KIND,
        {
            "action_id": _action_id(fact.action_id),
            "started_ns": fact.started_ns,
            "finished_ns": fact.finished_ns,
            "chronology": _chronology(fact.chronology),
            "files": [_entry(entry) for entry in fact.files],
        },
    )


def _write_failure_fact(writer: EvidenceWriter, fact: ActionFailureFact) -> str:
    return writer.write_document(
        f"{_fact_stem(fact)}.failure.json",
        _FAILURE_KIND,
        {
            "action_id": _action_id(fact.action_id),
            "action_kind": fact.action_kind.value,
            "operation": fact.operation,
            "diagnostic_failure": fact.detail,
            "chronology": _chronology(fact.chronology),
        },
    )


def write_raw_facts(
    writer: EvidenceWriter,
    facts: tuple[RawFact, ...],
) -> dict[ActionId, str]:
    """Persist each correlated Raw Fact without adding semantic classification."""

    paths: dict[ActionId, str] = {}
    for fact in facts:
        if isinstance(fact, (CommandFact, CommandFailureFact)):
            path = _write_command_fact(writer, fact)
        elif isinstance(fact, ObservationFact):
            path = _write_observation_fact(writer, fact)
        elif isinstance(fact, PreparationFact):
            path = _write_preparation_fact(writer, fact)
        else:
            assert isinstance(fact, ActionFailureFact)
            path = _write_failure_fact(writer, fact)
        paths[fact.action_id] = path
    return paths


def _write_subject_command(
    writer: EvidenceWriter,
    index: int,
    fact: SubjectCommandFact,
) -> str:
    stem = f"subject/commands/{index:02d}-{fact.stage}"
    stdout_path = writer.write_bytes(f"{stem}.stdout.log", "command-stdout", fact.stdout.data)
    stderr_path = writer.write_bytes(f"{stem}.stderr.log", "command-stderr", fact.stderr.data)
    body: dict[str, object] = {
        "stage": fact.stage,
        "argv": list(fact.argv),
        "working_directory": fact.working_directory,
        "exit_code": fact.exit_code,
        "timed_out": fact.timed_out,
        "started_ns": fact.started_ns,
        "finished_ns": fact.finished_ns,
        "stdout": _stream(stdout_path, fact.stdout),
        "stderr": _stream(stderr_path, fact.stderr),
    }
    if fact.failure is not None:
        body["diagnostic_failure"] = fact.failure
    return writer.write_document(f"{stem}.json", _SUBJECT_COMMAND_KIND, body)


def write_subject_evidence(
    writer: EvidenceWriter,
    subject: SubjectVerified | SubjectRejected,
) -> dict[str, object]:
    """Persist package-preparation and probe evidence before lifecycle facts."""

    preparation_path: str | None = None
    if subject.preparation is not None:
        preparation = subject.preparation
        preparation_path = writer.write_document(
            "subject/preparation.json",
            _SUBJECT_PREPARATION_KIND,
            {
                "source_root": preparation.source_root,
                "prepared_root": preparation.prepared_root,
                "copied_files": list(preparation.copied_files),
                "excluded_names": list(preparation.excluded_names),
            },
        )
    command_paths = [
        _write_subject_command(writer, index, command)
        for index, command in enumerate(subject.commands)
    ]
    return {
        "preparation": preparation_path,
        "commands": command_paths,
    }
