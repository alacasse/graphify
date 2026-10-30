"""Immutable description and observation-bound intermediate byte operation."""

import base64
import re
from dataclasses import dataclass
from typing import cast

from tools.install_sandbox.contracts.effects import Destination
from tools.install_sandbox.contracts.spec import fields, relative_path, text


def _decoded(value: object) -> bytes:
    if not isinstance(value, str):
        raise ValueError("Expected base64 string")
    return base64.b64decode(value, validate=True)


@dataclass(frozen=True)
class IntermediatePreparation:
    destination: Destination
    marker: str
    before: bytes
    after: bytes
    kind: str = "missing-markdown-section"
    body: bytes | None = None

    def to_data(self) -> dict[str, object]:
        data: dict[str, object] = {
            "kind": self.kind,
            "destination": {"root": self.destination.root, "path": self.destination.path},
            "marker": self.marker,
            "fragments": {
                "before": base64.b64encode(self.before).decode("ascii"),
                "after": base64.b64encode(self.after).decode("ascii"),
            },
        }
        if self.kind == "altered-markdown-body":
            if not isinstance(self.body, bytes):
                raise ValueError("Altered preparation requires body bytes")
            data["body"] = base64.b64encode(self.body).decode("ascii")
        elif self.kind != "missing-markdown-section" or self.body is not None:
            raise ValueError("Unsupported intermediate preparation")
        return data

    @classmethod
    def from_data(cls, value: object) -> "IntermediatePreparation":
        if not isinstance(value, dict):
            raise ValueError("Expected intermediate preparation object")
        incoming = cast(dict[str, object], value)
        kind = incoming.get("kind")
        data = fields(
            incoming,
            "kind destination marker fragments"
            + (" body" if kind == "altered-markdown-body" else ""),
        )
        if kind not in ("missing-markdown-section", "altered-markdown-body"):
            raise ValueError("Unsupported intermediate preparation")
        fragments = fields(data["fragments"], "before after")
        return cls(
            Destination.from_data(data["destination"]),
            text(data["marker"]),
            _decoded(fragments["before"]),
            _decoded(fragments["after"]),
            text(kind),
            _decoded(data["body"]) if kind == "altered-markdown-body" else None,
        )


@dataclass(frozen=True)
class PreparedByteRange:
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
    def from_data(cls, value: object) -> "PreparedByteRange":
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
            _decoded(data["replacement"]),
        )
