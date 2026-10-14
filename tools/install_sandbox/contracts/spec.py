"""Target facts and validation for the reference YAML format."""

import math
import re
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


def _hooks(value: object) -> tuple[HookExpectation, ...]:
    if not isinstance(value, list):
        raise ValueError("Expected a hooks list")
    hooks = tuple(HookExpectation.from_data(item) for item in cast(list[object], value))
    if len({hook.id for hook in hooks}) != len(hooks):
        raise ValueError("Duplicate hook identities")
    return hooks


def _skill(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Expected skill fields")
    data = cast(dict[str, object], value)
    optional = {"lock", "version_source"} & data.keys()
    result = fields(data, "file source references " + " ".join(sorted(optional)))
    if "lock" in result and result["lock"] != "persistent":
        raise ValueError("Skill lock must be persistent")
    return result


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
    json_list: str | None
    json_hooks: tuple[HookExpectation, ...]
    json_hook_management: str
    skill_lock: str | None = None
    command: tuple[str, ...] | None = None
    destinations: dict[str, dict[str, str]] | None = None
    json_backup: str | None = None
    version_source: str | None = None

    @classmethod
    def from_data(cls, value: object) -> "InstallTestSpec":
        if not isinstance(value, dict):
            raise ValueError("Expected target facts")
        incoming = cast(dict[str, object], value)
        optional = {"command", "destinations"} & incoming.keys()
        data = fields(
            incoming, "scopes directory skill markdown json " + " ".join(sorted(optional))
        )
        scopes = data["scopes"]
        if not isinstance(scopes, list) or not scopes:
            raise ValueError("Expected a non-empty scopes list")
        scopes = cast(list[object], scopes)
        if any(scope not in ("user", "project") for scope in scopes):
            raise ValueError("Scopes must be user or project")
        if len(set(cast(list[str], scopes))) != len(scopes):
            raise ValueError("Duplicate scopes")
        skill = _skill(data["skill"])
        markdown = fields(data["markdown"], "file marker source")
        config = _config(data["json"])
        command = _command(data.get("command"))
        destinations = _destinations(data.get("destinations"))
        result = cls(
            tuple(cast(list[str], scopes)),
            relative_path(data["directory"]),
            relative_path(skill["file"]),
            relative_path(skill["source"]),
            relative_path(skill["references"]),
            relative_path(markdown["file"]),
            text(markdown["marker"]),
            relative_path(markdown["source"]),
            relative_path(config["file"]),
            text(config["list"]) if config["list"] is not None else None,
            _hooks(config["hooks"]),
            text(config["hook_management"]),
            cast(str | None, skill.get("lock")),
            command,
            destinations,
            cast(str | None, config.get("backup")),
            relative_path(skill["version_source"]) if "version_source" in skill else None,
        )
        _validate_paths(result)
        return result

    def to_data(self) -> dict[str, object]:
        return {
            **({"command": list(self.command)} if self.command is not None else {}),
            **({"destinations": self.destinations} if self.destinations is not None else {}),
            "scopes": list(self.scopes),
            "directory": self.directory,
            "skill": {
                **(
                    {"version_source": self.version_source}
                    if self.version_source is not None
                    else {}
                ),
                "file": self.skill_file,
                "source": self.skill_source,
                "references": self.references_source,
                **({"lock": self.skill_lock} if self.skill_lock is not None else {}),
            },
            "markdown": {
                "file": self.markdown_file,
                "marker": self.markdown_marker,
                "source": self.markdown_source,
            },
            "json": {
                **({"backup": self.json_backup} if self.json_backup is not None else {}),
                "file": self.json_file,
                "list": self.json_list,
                "hooks": [asdict(hook) for hook in self.json_hooks],
                "hook_management": self.json_hook_management,
            },
        }


def _config(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Expected JSON facts")
    data = cast(dict[str, object], value)
    config = fields(
        data, "file list hooks hook_management" + (" backup" if "backup" in data else "")
    )
    if config["hook_management"] not in ("registry", "none"):
        raise ValueError("JSON hook management must be registry or none")
    if config["hook_management"] == "registry" and config["list"] is None:
        raise ValueError("Registry JSON requires an instruction list")
    if "backup" in config and not re.fullmatch(r"\.[A-Za-z0-9_-]+", text(config["backup"])):
        raise ValueError("JSON backup must be a safe filename suffix")
    if config["hook_management"] == "registry" and "backup" in config:
        raise ValueError("Registry JSON does not permit a backup")
    return config


def _command(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise ValueError("Expected a command argument list")
    arguments = tuple(text(item) for item in cast(list[object], value))
    if any(not re.fullmatch(r"[a-z][a-z0-9-]*", item) for item in arguments):
        raise ValueError("Command arguments must be plain command words")
    if arguments[-1] != "install" or any("resolution" in item for item in arguments):
        raise ValueError("Command must select installation without resolution options")
    return arguments


def _destinations(value: object) -> dict[str, dict[str, str]] | None:
    if value is None:
        return None
    data = fields(value, "skill markdown json")
    result: dict[str, dict[str, str]] = {}
    for name, entry in data.items():
        destination = fields(entry, "root path")
        root = text(destination["root"])
        if root not in {"project", "home"}:
            raise ValueError("Destination root must be project or home")
        result[name] = {"root": root, "path": relative_path(destination["path"])}
    skill = PurePosixPath(result["skill"]["path"])
    owned = [(entry["root"], PurePosixPath(entry["path"])) for entry in result.values()]
    owned.append((result["skill"]["root"], PurePosixPath(str(skill) + ".bak")))
    owned.extend(
        (result["skill"]["root"], skill.parent / name)
        for name in ("references", ".graphify_version")
    )
    for index, (root, path) in enumerate(owned):
        for other_root, other in owned[index + 1 :]:
            if root == other_root and (
                path == other or path in other.parents or other in path.parents
            ):
                raise ValueError("Installation destinations overlap")
    return result


def _validate_paths(spec: InstallTestSpec) -> None:
    declared = spec.destinations or {
        "skill": {"root": "project", "path": str(PurePosixPath(spec.directory) / spec.skill_file)},
        "markdown": {
            "root": "project",
            "path": str(PurePosixPath(spec.directory) / spec.markdown_file),
        },
        "json": {"root": "project", "path": str(PurePosixPath(spec.directory) / spec.json_file)},
    }
    _destinations(declared)
    json_path = declared["json"]["path"]
    reserved = [
        json_path + suffix
        for suffix in (
            ".graphify-state.json",
            ".graphify.lock",
            ".graphify-journal.json",
        )
    ]
    if spec.json_backup is not None:
        reserved.append(json_path + spec.json_backup)
    for name in ("skill", "markdown"):
        entry = declared[name]
        if entry["root"] != declared["json"]["root"]:
            continue
        path = PurePosixPath(entry["path"])
        if any(
            path == PurePosixPath(other) or path in PurePosixPath(other).parents
            for other in reserved
        ):
            raise ValueError("Installation destination collides with JSON evidence")
