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


@dataclass(frozen=True)
class JsonHookPreparation:
    destination: Destination
    kind: str
    effect_id: str
    member: str

    def to_data(self) -> dict[str, object]:
        if self.kind != "missing-json-hook":
            raise ValueError("Unsupported JSON hook preparation")
        return {
            "kind": self.kind,
            "effect_id": text(self.effect_id),
            "member": text(self.member),
            "destination": {"root": self.destination.root, "path": self.destination.path},
        }

    @classmethod
    def from_data(cls, value: object) -> "JsonHookPreparation":
        data = fields(value, "kind destination effect_id member")
        result = cls(
            Destination.from_data(data["destination"]),
            text(data["kind"]),
            text(data["effect_id"]),
            text(data["member"]),
        )
        result.to_data()
        return result


REFERENCE_REPAIR_SUFFIX = b"\nSandbox repair witness.\n"


@dataclass(frozen=True)
class AlteredReferencePreparation:
    destination: Destination
    selection: str = "first-regular-file-lexical"
    suffix: bytes = REFERENCE_REPAIR_SUFFIX
    kind: str = "altered-reference"

    def to_data(self) -> dict[str, object]:
        if (
            self.selection != "first-regular-file-lexical"
            or self.kind != "altered-reference"
            or self.suffix != REFERENCE_REPAIR_SUFFIX
        ):
            raise ValueError("Unsupported altered reference preparation")
        return {
            "kind": self.kind,
            "destination": {"root": self.destination.root, "path": self.destination.path},
            "selection": self.selection,
            "suffix": base64.b64encode(self.suffix).decode("ascii"),
        }

    @classmethod
    def from_data(cls, value: object) -> "AlteredReferencePreparation":
        data = fields(value, "kind destination selection suffix")
        result = cls(
            Destination.from_data(data["destination"]),
            text(data["selection"]),
            _decoded(data["suffix"]),
            text(data["kind"]),
        )
        result.to_data()
        return result


SKILL_REPAIR_SUFFIX = b"\nSandbox skill repair witness.\n"


@dataclass(frozen=True)
class AlteredSkillPreparation:
    destination: Destination
    suffix: bytes = SKILL_REPAIR_SUFFIX
    kind: str = "altered-skill"

    def to_data(self) -> dict[str, object]:
        if self.kind != "altered-skill" or self.suffix != SKILL_REPAIR_SUFFIX:
            raise ValueError("Unsupported altered skill preparation")
        return {
            "kind": self.kind,
            "destination": {"root": self.destination.root, "path": self.destination.path},
            "suffix": base64.b64encode(self.suffix).decode("ascii"),
        }

    @classmethod
    def from_data(cls, value: object) -> "AlteredSkillPreparation":
        data = fields(value, "kind destination suffix")
        result = cls(
            Destination.from_data(data["destination"]),
            _decoded(data["suffix"]),
            text(data["kind"]),
        )
        result.to_data()
        return result


PRESERVE_SKILL_BACKUP_SUFFIX = b"\nSandbox previous backup witness.\n"


@dataclass(frozen=True)
class PreserveSkillBackupPreparation:
    destination: Destination
    suffix: bytes = PRESERVE_SKILL_BACKUP_SUFFIX
    kind: str = "preserve-skill-backup"

    def to_data(self) -> dict[str, object]:
        if self.kind != "preserve-skill-backup" or self.suffix != PRESERVE_SKILL_BACKUP_SUFFIX:
            raise ValueError("Unsupported preserve skill backup preparation")
        return {
            "kind": self.kind,
            "destination": {"root": self.destination.root, "path": self.destination.path},
            "suffix": base64.b64encode(self.suffix).decode("ascii"),
        }

    @classmethod
    def from_data(cls, value: object) -> "PreserveSkillBackupPreparation":
        data = fields(value, "kind destination suffix")
        result = cls(
            Destination.from_data(data["destination"]),
            _decoded(data["suffix"]),
            text(data["kind"]),
        )
        result.to_data()
        return result


@dataclass(frozen=True)
class StaleVersionPreparation:
    destination: Destination
    kind: str = "stale-version"

    def to_data(self) -> dict[str, object]:
        if self.kind != "stale-version":
            raise ValueError("Unsupported stale version preparation")
        return {
            "kind": self.kind,
            "destination": {"root": self.destination.root, "path": self.destination.path},
        }

    @classmethod
    def from_data(cls, value: object) -> "StaleVersionPreparation":
        data = fields(value, "kind destination")
        result = cls(Destination.from_data(data["destination"]), text(data["kind"]))
        result.to_data()
        return result


STALE_REFERENCE_CONTENT = b"Stale reference.\n"


@dataclass(frozen=True)
class StaleReferencePreparation:
    destination: Destination
    kind: str = "stale-reference"

    def to_data(self) -> dict[str, object]:
        if self.kind != "stale-reference":
            raise ValueError("Unsupported stale reference preparation")
        return {
            "kind": self.kind,
            "destination": {"root": self.destination.root, "path": self.destination.path},
        }

    @classmethod
    def from_data(cls, value: object) -> "StaleReferencePreparation":
        data = fields(value, "kind destination")
        result = cls(Destination.from_data(data["destination"]), text(data["kind"]))
        result.to_data()
        return result


def preparation_from_data(
    value: object,
) -> (
    IntermediatePreparation
    | MissingReferencePreparation
    | JsonHookPreparation
    | AlteredReferencePreparation
    | AlteredSkillPreparation
    | PreserveSkillBackupPreparation
    | StaleVersionPreparation
    | StaleReferencePreparation
):
    if not isinstance(value, dict):
        raise ValueError("Expected discriminated operation object")
    incoming = cast(dict[str, object], value)
    parsers = {
        "missing-json-hook": JsonHookPreparation.from_data,
        "stale-reference": StaleReferencePreparation.from_data,
        "stale-version": StaleVersionPreparation.from_data,
        "preserve-skill-backup": PreserveSkillBackupPreparation.from_data,
        "missing-reference": MissingReferencePreparation.from_data,
        "altered-reference": AlteredReferencePreparation.from_data,
        "altered-skill": AlteredSkillPreparation.from_data,
    }
    parser = parsers.get(text(incoming.get("kind")), IntermediatePreparation.from_data)
    return parser(incoming)
