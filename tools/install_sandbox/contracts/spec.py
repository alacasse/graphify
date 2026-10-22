"""Shared strict values for effect descriptions and evidence."""

import math
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import cast


def fields(value: object, expected: str) -> dict[str, object]:
    """Require exactly the named fields at a transport boundary."""
    if not isinstance(value, dict) or set(cast(dict[object, object], value)) != set(
        expected.split()
    ):
        raise ValueError(f"Expected fields: {expected}")
    return cast(dict[str, object], value)


def text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected a non-empty string")
    return value


def relative_path(value: object) -> str:
    result = text(value)
    path = PurePosixPath(result)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in result.split("/")):
        raise ValueError(f"Expected a relative path without traversal: {result!r}")
    if "\\" in result or "\x00" in result:
        raise ValueError(f"Invalid relative path: {result!r}")
    return result


def _json_value(value: object) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    if isinstance(value, list):
        for item in cast(list[object], value):
            _json_value(item)
        return
    if isinstance(value, dict):
        for key, item in cast(dict[object, object], value).items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            _json_value(item)
        return
    raise ValueError("Expected a finite JSON value")


@dataclass(frozen=True)
class HookExpectation:
    id: str
    event: str
    matcher: str
    content: dict[str, object]

    @classmethod
    def from_data(cls, value: object) -> "HookExpectation":
        data = fields(value, "id event matcher content")
        content = data["content"]
        if not isinstance(content, dict) or not content:
            raise ValueError("Hook content must be a non-empty JSON object")
        try:
            _json_value(cast(dict[object, object], content))
        except RecursionError as error:
            raise ValueError("Hook content must be an acyclic JSON value") from error
        return cls(
            text(data["id"]),
            text(data["event"]),
            text(data["matcher"]),
            cast(dict[str, object], content),
        )
