"""An immutable mutation owns its observation binding and physical preconditions."""

import base64
import hashlib
import re
from dataclasses import dataclass
from typing import cast

from tools.install_sandbox.contracts.effects import Destination
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.spec import fields, relative_path, text


def _replacement(value: object) -> bytes:
    if not isinstance(value, str):
        raise ValueError("Expected base64 replacement string")
    return base64.b64decode(value, validate=True)


@dataclass(frozen=True)
class BoundMarkdownMutation:
    case_sha256: str
    observation_ref: str
    destination: Destination
    document_sha256: str
    start: int
    end: int
    replacement: bytes = b""

    def __post_init__(self) -> None:
        for digest in (self.case_sha256, self.document_sha256):
            if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise ValueError("Expected exact SHA-256 digest")
        relative_path(self.observation_ref)
        if type(self.start) is not int or type(self.end) is not int:
            raise ValueError("Expected integer byte bounds")
        if not 0 <= self.start < self.end:
            raise ValueError("Invalid byte bounds")

    def verify_binding(self, case_bytes: bytes, first_after: "FilesystemSnapshot") -> bytes:
        if self.case_sha256 != hashlib.sha256(case_bytes).hexdigest():
            raise ValueError("Operation case digest differs from retained case")
        if self.observation_ref != "steps/0/after.json":
            raise ValueError("Operation requires validated first observation")
        document = first_after.contents.get((self.destination.root, self.destination.path))
        if (
            document is None
            or hashlib.sha256(document).hexdigest() != self.document_sha256
            or self.end > len(document)
        ):
            raise ValueError("Operation document binding or bounds invalid")
        return document

    def to_data(self) -> dict[str, object]:
        return {
            "format": "prepared-mutation-v2",
            "kind": "markdown",
            "case_sha256": self.case_sha256,
            "observation_ref": self.observation_ref,
            "destination": {"root": self.destination.root, "path": self.destination.path},
            "document_sha256": self.document_sha256,
            "start": self.start,
            "end": self.end,
            "replacement": base64.b64encode(self.replacement).decode("ascii"),
        }

    @classmethod
    def from_data(cls, value: object) -> "BoundMarkdownMutation":
        data = fields(
            value,
            "format kind case_sha256 observation_ref destination document_sha256 "
            "start end replacement",
        )
        if data["format"] != "prepared-mutation-v2" or data["kind"] != "markdown":
            raise ValueError("Unsupported prepared operation")
        if type(data["start"]) is not int or type(data["end"]) is not int:
            raise ValueError("Expected integer byte bounds")
        return cls(
            text(data["case_sha256"]),
            text(data["observation_ref"]),
            Destination.from_data(data["destination"]),
            text(data["document_sha256"]),
            data["start"],
            data["end"],
            _replacement(data["replacement"]),
        )


def _validate_file_binding(case_sha256: str, observation_ref: str, document_sha256: str) -> None:
    for digest in (case_sha256, document_sha256):
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("Expected exact SHA-256 digest")
    relative_path(observation_ref)


def _bound_file_bytes(
    case_sha256: str,
    observation_ref: str,
    destination: Destination,
    document_sha256: str,
    case_bytes: bytes,
    first_after: FilesystemSnapshot,
) -> bytes:
    if case_sha256 != hashlib.sha256(case_bytes).hexdigest():
        raise ValueError("Operation case digest differs from retained case")
    if observation_ref != "steps/0/after.json":
        raise ValueError("Operation requires validated first observation")
    entry = first_after.entry(destination.root, destination.path)
    content = first_after.contents.get((destination.root, destination.path))
    if entry is None or entry["kind"] != "file" or content is None:
        raise ValueError("Operation requires retained regular file")
    if hashlib.sha256(content).hexdigest() != document_sha256:
        raise ValueError("Operation document binding invalid")
    return content


@dataclass(frozen=True)
class BoundFileRemoval:
    case_sha256: str
    observation_ref: str
    destination: Destination
    document_sha256: str

    def __post_init__(self) -> None:
        _validate_file_binding(self.case_sha256, self.observation_ref, self.document_sha256)

    def verify_binding(self, case_bytes: bytes, first_after: FilesystemSnapshot) -> bytes:
        return _bound_file_bytes(
            self.case_sha256,
            self.observation_ref,
            self.destination,
            self.document_sha256,
            case_bytes,
            first_after,
        )

    def to_data(self) -> dict[str, object]:
        return {
            "format": "prepared-mutation-v2",
            "kind": "file-removal",
            "case_sha256": self.case_sha256,
            "observation_ref": self.observation_ref,
            "destination": {"root": self.destination.root, "path": self.destination.path},
            "document_sha256": self.document_sha256,
        }

    @classmethod
    def from_data(cls, value: object) -> "BoundFileRemoval":
        data = fields(value, "format kind case_sha256 observation_ref destination document_sha256")
        if data["format"] != "prepared-mutation-v2" or data["kind"] != "file-removal":
            raise ValueError("Unsupported prepared operation")
        return cls(
            text(data["case_sha256"]),
            text(data["observation_ref"]),
            Destination.from_data(data["destination"]),
            text(data["document_sha256"]),
        )


@dataclass(frozen=True)
class BoundFileAppend:
    case_sha256: str
    observation_ref: str
    destination: Destination
    document_sha256: str
    suffix: bytes

    def __post_init__(self) -> None:
        _validate_file_binding(self.case_sha256, self.observation_ref, self.document_sha256)
        if type(self.suffix) is not bytes or not self.suffix:
            raise ValueError("Append requires nonempty suffix bytes")
        if self.observation_ref != "steps/0/after.json":
            raise ValueError("Append requires validated first observation")

    def verify_binding(self, case_bytes: bytes, first_after: FilesystemSnapshot) -> bytes:
        return _bound_file_bytes(
            self.case_sha256,
            self.observation_ref,
            self.destination,
            self.document_sha256,
            case_bytes,
            first_after,
        )

    def to_data(self) -> dict[str, object]:
        return {
            "format": "prepared-mutation-v2",
            "case_sha256": self.case_sha256,
            "observation_ref": self.observation_ref,
            "destination": {"root": self.destination.root, "path": self.destination.path},
            "document_sha256": self.document_sha256,
            "kind": "file-append",
            "suffix": base64.b64encode(self.suffix).decode("ascii"),
        }

    @classmethod
    def from_data(cls, value: object) -> "BoundFileAppend":
        data = fields(
            value, "format kind case_sha256 observation_ref destination document_sha256 suffix"
        )
        if data["format"] != "prepared-mutation-v2" or data["kind"] != "file-append":
            raise ValueError("Unsupported prepared operation")
        return cls(
            text(data["case_sha256"]),
            text(data["observation_ref"]),
            Destination.from_data(data["destination"]),
            text(data["document_sha256"]),
            _replacement(data["suffix"]),
        )


BoundMutation = BoundMarkdownMutation | BoundFileRemoval | BoundFileAppend


def mutation_from_data(value: object) -> BoundMutation:
    if not isinstance(value, dict):
        raise ValueError("Expected discriminated operation object")
    incoming = cast(dict[str, object], value)
    if incoming.get("kind") == "file-append":
        return BoundFileAppend.from_data(incoming)
    if incoming.get("kind") == "file-removal":
        return BoundFileRemoval.from_data(incoming)
    return BoundMarkdownMutation.from_data(incoming)


@dataclass(frozen=True)
class PerformedMutation:
    """Actual physical result, retained separately from the oracle."""

    operation: BoundMutation
    document_sha256: str | None

    def __post_init__(self) -> None:
        if type(self.operation) not in (BoundFileRemoval, BoundMarkdownMutation, BoundFileAppend):
            raise ValueError("Unsupported performed mutation")
        if type(self.operation) is BoundFileRemoval:
            if self.document_sha256 is not None:
                raise ValueError("Removed file cannot have resulting bytes")
        elif (
            not isinstance(self.document_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.document_sha256) is None
        ):
            raise ValueError("Expected actual document SHA-256 digest")

    def to_data(self) -> dict[str, object]:
        return {
            "format": "performed-mutation-v2",
            "kind": self.operation.to_data()["kind"],
            "operation": self.operation.to_data(),
            "document_sha256": self.document_sha256,
        }

    @classmethod
    def from_data(cls, value: object) -> "PerformedMutation":
        data = fields(value, "format kind operation document_sha256")
        operation = mutation_from_data(data["operation"])
        kind = operation.to_data()["kind"]
        if data["format"] != "performed-mutation-v2" or data["kind"] != kind:
            raise ValueError("Unsupported performed operation")
        digest = data["document_sha256"]
        return cls(operation, None if digest is None else text(digest))

    def verify(self, operation: BoundMutation, observed: FilesystemSnapshot) -> None:
        if operation != self.operation:
            raise ValueError("Retained operation contradicts performed mutation")
        destination = operation.destination
        key = destination.root, destination.path
        if type(operation) is BoundFileRemoval:
            # Completeness and absence are checked by the independent expectation verifier.
            # A physical claim must not turn an observed failed removal into a replay error.
            return
        document = observed.contents.get(key)
        if document is None:
            entry = observed.entry(*key)
            obstructed = any(
                (item["root"], item["path"], item["operation"]) == (*key, "read_file")
                for item in observed.obstacles
            )
            if entry is None or entry["kind"] != "file" or not obstructed:
                raise ValueError("Performed mutation requires bytes or explicit read obstacle")
            return
        if hashlib.sha256(document).hexdigest() != self.document_sha256:
            raise ValueError("Observation contradicts retained performed mutation")
