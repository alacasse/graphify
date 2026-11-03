"""Pure repair requests, protected completions, and retained artifact codecs."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, is_dataclass
from typing import Literal

from tools.install_sandbox.contracts.bound_mutation import (
    BoundFileAppend,
    BoundFileRemoval,
    BoundMarkdownMutation,
    BoundMutation,
    PerformedMutation,
    mutation_from_data,
)
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import VerificationResult


@dataclass(frozen=True, init=False)
class JsonArtifact:
    reference: str
    _document: object

    def __init__(self, reference: str, document: object) -> None:
        object.__setattr__(self, "reference", reference)
        object.__setattr__(self, "_document", copy.deepcopy(document))

    @property
    def document(self) -> object:
        return copy.deepcopy(self._document)


@dataclass(frozen=True, init=False)
class SnapshotArtifact:
    reference: str
    _snapshot: FilesystemSnapshot

    def __init__(self, reference: str, snapshot: FilesystemSnapshot) -> None:
        object.__setattr__(self, "reference", reference)
        object.__setattr__(self, "_snapshot", copy.deepcopy(snapshot))

    @property
    def snapshot(self) -> FilesystemSnapshot:
        return copy.deepcopy(self._snapshot)


def _data(value: object) -> object:
    if isinstance(value, JsonArtifact):
        return value.document
    if isinstance(value, SnapshotArtifact):
        return _data(value.snapshot)
    if isinstance(value, FilesystemSnapshot):
        entries = [
            {k: v for k, v in item.items() if k not in {"content_file", "sha256"}}
            for item in value.entries
        ]
        return {
            "entries": sorted(entries, key=lambda item: (item["root"], item["path"])),
            "contents": [[*key, content.hex()] for key, content in sorted(value.contents.items())],
            "obstacles": copy.deepcopy(value.obstacles),
        }
    if isinstance(
        value,
        (
            BoundMarkdownMutation,
            BoundFileAppend,
            BoundFileRemoval,
            PerformedMutation,
            ExpectationSet,
        ),
    ):
        return value.to_data()
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return value


def artifact_digest(payload: object) -> str:
    """Hash logical content, independently of snapshot blob locations."""
    encoded = json.dumps(_data(payload), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ArtifactDescriptor:
    kind: str
    reference: str
    checkpoint: str
    transport: Literal["json", "snapshot"]
    _type: type[object] | tuple[type[object], ...]
    _decoder: Callable[[object], object]

    def decode(self, raw: object) -> object:
        return self._decoder(raw)

    def encode(self, value: object) -> JsonArtifact | SnapshotArtifact:
        if not isinstance(value, self._type):
            raise ValueError(f"Wrong result type for {self.kind}")
        if self.transport == "snapshot":
            assert isinstance(value, FilesystemSnapshot)
            return SnapshotArtifact(self.reference, value)
        return JsonArtifact(self.reference, _data(value))


def _snapshot(raw: object) -> FilesystemSnapshot:
    if not isinstance(raw, FilesystemSnapshot):
        raise ValueError("Expected loaded snapshot")
    return copy.deepcopy(raw)


ARTIFACTS = (
    ArtifactDescriptor(
        "operation",
        "intermediate/operation.json",
        "operation_retained",
        "json",
        (BoundMarkdownMutation, BoundFileRemoval, BoundFileAppend),
        mutation_from_data,
    ),
    ArtifactDescriptor(
        "preparation_expectations",
        "expectations/intermediate.json",
        "preparation_expectations_retained",
        "json",
        ExpectationSet,
        ExpectationSet.from_data,
    ),
    ArtifactDescriptor(
        "repair_plan",
        "intermediate/repair-plan.json",
        "repair_plan_retained",
        "json",
        ExpectationSet,
        ExpectationSet.from_data,
    ),
    ArtifactDescriptor(
        "before",
        "intermediate/before.json",
        "before_retained",
        "snapshot",
        FilesystemSnapshot,
        _snapshot,
    ),
    ArtifactDescriptor(
        "performed",
        "intermediate/performed.json",
        "mutation_recorded",
        "json",
        PerformedMutation,
        PerformedMutation.from_data,
    ),
    ArtifactDescriptor(
        "after",
        "intermediate/after.json",
        "after_retained",
        "snapshot",
        FilesystemSnapshot,
        _snapshot,
    ),
    ArtifactDescriptor(
        "verification",
        "intermediate/verification.json",
        "verification_retained",
        "json",
        VerificationResult,
        VerificationResult.from_data,
    ),
    ArtifactDescriptor(
        "effective_expectations",
        "expectations/reinstall.json",
        "ready",
        "json",
        ExpectationSet,
        ExpectationSet.from_data,
    ),
)


_COMPLETION_KEY = object()


@dataclass(frozen=True, init=False, eq=False)
class Completion:
    _identity: object
    _value: object

    def __init__(self, identity: object, value: object, *, _key: object = None) -> None:
        if _key is not _COMPLETION_KEY:
            raise TypeError("Completions are constructed by their request")
        object.__setattr__(self, "_identity", identity)
        object.__setattr__(self, "_value", copy.deepcopy(value))

    @property
    def value(self) -> object:
        return copy.deepcopy(self._value)

    def belongs_to(self, request: Request) -> bool:
        return self._identity is request


@dataclass(frozen=True, init=False, eq=False)
class RetainEvidence:
    _completion: Completion

    def __init__(self, value: object) -> None:
        object.__setattr__(self, "_completion", Completion(self, value, _key=_COMPLETION_KEY))

    @property
    def completion(self) -> Completion:
        return self._completion


@dataclass(frozen=True, init=False, eq=False)
class ObserveSnapshot:
    phase: Literal["before", "after"]

    def __init__(self, phase: Literal["before", "after"]) -> None:
        object.__setattr__(self, "phase", phase)

    def complete(self, snapshot: FilesystemSnapshot) -> Completion:
        return Completion(self, _require_snapshot(snapshot), _key=_COMPLETION_KEY)


@dataclass(frozen=True, init=False, eq=False)
class ApplyMutation:
    _operation: BoundMutation

    def __init__(self, operation: BoundMutation) -> None:
        object.__setattr__(self, "_operation", copy.deepcopy(operation))

    @property
    def operation(self) -> BoundMutation:
        return copy.deepcopy(self._operation)

    def complete(self, performed: PerformedMutation) -> Completion:
        return Completion(self, _require_performed(performed), _key=_COMPLETION_KEY)


Request = RetainEvidence | ObserveSnapshot | ApplyMutation


def _require_snapshot(value: object) -> FilesystemSnapshot:
    if not isinstance(value, FilesystemSnapshot):
        raise ValueError("Expected preparation observation")
    return value


def _require_performed(value: object) -> PerformedMutation:
    if not isinstance(value, PerformedMutation):
        raise ValueError("Expected performed mutation")
    return value
