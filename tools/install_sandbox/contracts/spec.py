"""Target facts and validation for the reference YAML format."""

import math
from dataclasses import asdict, dataclass
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
    event: str
    matcher: str
    content: dict[str, object]

    @classmethod
    def from_data(cls, value: object) -> "HookExpectation":
        data = fields(value, "event matcher content")
        content = data["content"]
        if not isinstance(content, dict) or not content:
            raise ValueError("Hook content must be a non-empty JSON object")
        try:
            _json_value(cast(dict[object, object], content))
        except RecursionError as error:
            raise ValueError("Hook content must be an acyclic JSON value") from error
        return cls(text(data["event"]), text(data["matcher"]), cast(dict[str, object], content))


def _hooks(value: object) -> tuple[HookExpectation, ...]:
    if not isinstance(value, list):
        raise ValueError("Expected a hooks list")
    return tuple(HookExpectation.from_data(item) for item in cast(list[object], value))


@dataclass(frozen=True)
class InstallTestSpec:
    """Validated target facts; source paths remain relative to the subject."""

    scopes: tuple[str, ...]
    directory: str
    skill_file: str
    skill_source: str
    references_source: str
    markdown_file: str
    markdown_marker: str
    markdown_source: str
    json_file: str
    json_list: str
    json_hooks: tuple[HookExpectation, ...]

    @classmethod
    def from_data(cls, value: object) -> "InstallTestSpec":
        data = fields(value, "scopes directory skill markdown json")
        scopes = data["scopes"]
        if not isinstance(scopes, list) or not scopes:
            raise ValueError("Expected a non-empty scopes list")
        scopes = cast(list[object], scopes)
        if any(scope not in ("user", "project") for scope in scopes):
            raise ValueError("Scopes must be user or project")
        if len(set(cast(list[str], scopes))) != len(scopes):
            raise ValueError("Duplicate scopes")
        skill = fields(data["skill"], "file source references")
        markdown = fields(data["markdown"], "file marker source")
        config = fields(data["json"], "file list hooks")
        return cls(
            tuple(cast(list[str], scopes)),
            relative_path(data["directory"]),
            relative_path(skill["file"]),
            relative_path(skill["source"]),
            relative_path(skill["references"]),
            relative_path(markdown["file"]),
            text(markdown["marker"]),
            relative_path(markdown["source"]),
            relative_path(config["file"]),
            text(config["list"]),
            _hooks(config["hooks"]),
        )

    def to_data(self) -> dict[str, object]:
        return {
            "scopes": list(self.scopes),
            "directory": self.directory,
            "skill": {
                "file": self.skill_file,
                "source": self.skill_source,
                "references": self.references_source,
            },
            "markdown": {
                "file": self.markdown_file,
                "marker": self.markdown_marker,
                "source": self.markdown_source,
            },
            "json": {
                "file": self.json_file,
                "list": self.json_list,
                "hooks": [asdict(hook) for hook in self.json_hooks],
            },
        }
