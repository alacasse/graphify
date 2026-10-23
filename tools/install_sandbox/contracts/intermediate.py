"""Immutable description and observation-bound intermediate byte operation."""

import base64
import re
from dataclasses import dataclass

from tools.install_sandbox.contracts.effects import Destination
from tools.install_sandbox.contracts.spec import fields, relative_path, text


@dataclass(frozen=True)
class IntermediatePreparation:
    destination: Destination
    marker: str
    before: bytes
    after: bytes

    def to_data(self) -> dict[str, object]:
        return {
            "kind": "missing-markdown-section",
            "destination": {"root": self.destination.root, "path": self.destination.path},
            "marker": self.marker,
            "fragments": {
                "before": base64.b64encode(self.before).decode("ascii"),
                "after": base64.b64encode(self.after).decode("ascii"),
            },
        }

    @classmethod
    def from_data(cls, value: object) -> "IntermediatePreparation":
        data = fields(value, "kind destination marker fragments")
        if data["kind"] != "missing-markdown-section":
            raise ValueError("Unsupported intermediate preparation")
        fragments = fields(data["fragments"], "before after")
        return cls(
            Destination.from_data(data["destination"]),
            text(data["marker"]),
            base64.b64decode(text(fragments["before"]), validate=True),
            base64.b64decode(text(fragments["after"]), validate=True),
        )


@dataclass(frozen=True)
class PreparedByteRange:
    case_sha256: str
    observation_ref: str
    destination: Destination
    document_sha256: str
    start: int
    end: int

    def __post_init__(self) -> None:
        for digest in (self.case_sha256, self.document_sha256):
            if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise ValueError("Expected exact SHA-256 digest")
        relative_path(self.observation_ref)
        if type(self.start) is not int or type(self.end) is not int:
            raise ValueError("Expected integer byte bounds")
        if not 0 <= self.start < self.end:
            raise ValueError("Invalid byte bounds")

    def to_data(self) -> dict[str, object]:
        return {
            "format": "prepared-byte-range-v1",
            "case_sha256": self.case_sha256,
            "observation_ref": self.observation_ref,
            "destination": {"root": self.destination.root, "path": self.destination.path},
            "document_sha256": self.document_sha256,
            "start": self.start,
            "end": self.end,
        }

    @classmethod
    def from_data(cls, value: object) -> "PreparedByteRange":
        data = fields(
            value, "format case_sha256 observation_ref destination document_sha256 start end"
        )
        if data["format"] != "prepared-byte-range-v1":
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
        )
