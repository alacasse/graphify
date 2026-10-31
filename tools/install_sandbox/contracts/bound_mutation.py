"""An immutable mutation owns its observation binding and physical preconditions."""

import base64
import hashlib
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tools.install_sandbox.container.effect_environment import EffectEnvironment
    from tools.install_sandbox.container.environment import FilesystemSnapshot
from tools.install_sandbox.contracts.effects import Destination
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

    def apply(
        self, environment: "EffectEnvironment", case_bytes: bytes, first_after: "FilesystemSnapshot"
    ) -> None:
        preparation = environment.case.intermediate_preparation
        if preparation is None or preparation.destination != self.destination:
            raise ValueError("Operation destination differs from case")
        retained = self.verify_binding(case_bytes, first_after)
        root = environment.project if self.destination.root == "project" else environment.home
        path = root / self.destination.path
        if path.resolve() != path or not path.is_file():
            raise ValueError("Operation requires original regular document")
        with os.fdopen(os.open(path, os.O_RDWR | os.O_NOFOLLOW), "r+b") as stream:
            current = stream.read()
            if current != retained:
                raise ValueError("Document changed since validated observation")
            stream.seek(0)
            stream.write(current[: self.start] + self.replacement + current[self.end :])
            stream.truncate()

    def to_data(self) -> dict[str, object]:
        return {
            "format": "prepared-byte-range-v2",
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
            "format case_sha256 observation_ref destination document_sha256 start end replacement",
        )
        if data["format"] != "prepared-byte-range-v2":
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


@dataclass(frozen=True)
class PerformedMutation:
    """Retained actual mutation identity and physical result, separate from the oracle."""

    operation: BoundMarkdownMutation
    document_sha256: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"[0-9a-f]{64}", self.document_sha256) is None:
            raise ValueError("Expected actual document SHA-256 digest")

    @classmethod
    def capture(
        cls, operation: BoundMarkdownMutation, environment: "EffectEnvironment"
    ) -> "PerformedMutation":
        root = environment.project if operation.destination.root == "project" else environment.home
        path = root / operation.destination.path
        if path.resolve() != path or not path.is_file():
            raise ValueError("Performed mutation requires a regular document")
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
            return cls(operation, hashlib.sha256(stream.read()).hexdigest())

    def to_data(self) -> dict[str, object]:
        return {"operation": self.operation.to_data(), "document_sha256": self.document_sha256}

    @classmethod
    def from_data(cls, value: object) -> "PerformedMutation":
        data = fields(value, "operation document_sha256")
        return cls(
            BoundMarkdownMutation.from_data(data["operation"]), text(data["document_sha256"])
        )

    def verify(self, operation: BoundMarkdownMutation, observed: "FilesystemSnapshot") -> None:
        if operation != self.operation:
            raise ValueError("Retained byte operation contradicts performed mutation")
        key = operation.destination.root, operation.destination.path
        document = observed.contents.get(key)
        if document is None:
            self._require_read_obstacle(observed)
            return
        if hashlib.sha256(document).hexdigest() != self.document_sha256:
            raise ValueError("Observation contradicts retained performed mutation")

    def _require_read_obstacle(self, observed: "FilesystemSnapshot") -> None:
        destination = self.operation.destination
        entry = observed.entry(destination.root, destination.path)
        obstructed = any(
            (item["root"], item["path"], item["operation"])
            == (destination.root, destination.path, "read_file")
            for item in observed.obstacles
        )
        if entry is None or entry["kind"] != "file" or not obstructed:
            raise ValueError("Performed mutation requires document bytes or explicit read obstacle")
