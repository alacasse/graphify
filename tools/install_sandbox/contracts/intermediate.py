"""Immutable description and observation-bound intermediate byte operation."""

import base64
from dataclasses import dataclass
from typing import cast

from tools.install_sandbox.contracts.effects import Destination
from tools.install_sandbox.contracts.spec import fields, text


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
class MissingReferencePreparation:
    destination: Destination
    selection: str = "first-regular-file-lexical"
    kind: str = "missing-reference"

    def to_data(self) -> dict[str, object]:
        if self.selection != "first-regular-file-lexical" or self.kind != "missing-reference":
            raise ValueError("Unsupported reference selection")
        return {
            "kind": self.kind,
            "destination": {"root": self.destination.root, "path": self.destination.path},
            "selection": self.selection,
        }

    @classmethod
    def from_data(cls, value: object) -> "MissingReferencePreparation":
        data = fields(value, "kind destination selection")
        result = cls(
            Destination.from_data(data["destination"]), text(data["selection"]), text(data["kind"])
        )
        result.to_data()
        return result


def preparation_from_data(value: object) -> IntermediatePreparation | MissingReferencePreparation:
    if not isinstance(value, dict):
        raise ValueError("Expected discriminated operation object")
    incoming = cast(dict[str, object], value)
    if incoming.get("kind") == "missing-reference":
        return MissingReferencePreparation.from_data(incoming)
    return IntermediatePreparation.from_data(incoming)
