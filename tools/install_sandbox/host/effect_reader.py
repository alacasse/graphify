"""Resolve the host effect YAML without a target-name registry."""

from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import cast

import yaml

from tools.install_sandbox.contracts.effects import (
    Destination,
    Effect,
    EffectSpec,
    effect_from_data,
)
from tools.install_sandbox.contracts.spec import fields, relative_path, text


def unique_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode) -> dict[str, object]:
    construct = cast(Callable[..., object], loader.construct_object)  # pyright: ignore[reportUnknownMemberType]
    result: dict[str, object] = {}
    for key_node, value_node in node.value:
        key = construct(key_node, deep=True)
        if not isinstance(key, str) or key in result:
            raise ValueError("Duplicate or non-string YAML field")
        result[key] = construct(value_node, deep=True)
    return result


class EffectLoader(yaml.SafeLoader):
    pass


EffectLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def _destination(value: object, directory: str) -> Destination:
    if not isinstance(value, dict):
        raise ValueError("Expected destination")
    incoming = cast(dict[str, object], value)
    data = fields(incoming, "path " + " ".join(sorted({"root", "directory"} & incoming.keys())))
    folder = text(data.get("directory", directory))
    if folder != ".":
        relative_path(folder)
    path = str(PurePosixPath(folder) / relative_path(data["path"]))
    return Destination(text(data.get("root", "project")), path)


def _hooks(value: object) -> list[dict[str, object]]:
    if not isinstance(value, dict) or not value:
        raise ValueError("Expected non-empty hook events")
    result: list[dict[str, object]] = []
    groups = (("search", ("shell", "search-content")), ("read", ("read-file", "find-files")))
    for event, raw in cast(dict[str, object], value).items():
        if event != "PreToolUse":
            raise ValueError(f"Unsupported hook event: {event}")
        tools = fields(raw, "tools")["tools"]
        tool_data = fields(tools, "shell search-content read-file find-files")
        for operation, names in groups:
            result.append(
                {
                    "id": f"{event}-{operation}",
                    "event": event,
                    "matcher": "|".join(text(tool_data[name]) for name in names),
                    "content": {
                        "type": "command",
                        "command": f"graphify hook-guard {operation}",
                        "timeout": 10,
                    },
                }
            )
    return result


def _effect(value: object, directory: str) -> Effect:
    if not isinstance(value, dict):
        raise ValueError("Expected effect")
    incoming = cast(dict[str, object], value)
    kind = incoming.get("kind")
    expected = {
        "skill": "kind source references destination",
        "markdown-section": "kind source destination",
        "json-hooks": "kind family destination events",
    }
    if kind not in expected:
        raise ValueError(f"Unsupported effect kind: {kind}")
    key = cast(str, kind)
    optional = " marker" if key == "markdown-section" and "marker" in incoming else ""
    data = fields(incoming, expected[key] + optional)
    destination = _destination(data["destination"], directory)
    resolved: dict[str, object] = {
        "kind": kind,
        "destination": {"root": destination.root, "path": destination.path},
    }
    if key == "json-hooks":
        if data["family"] != "pretooluse-context":
            raise ValueError("Unsupported hook family")
        resolved["hooks"] = _hooks(data["events"])
    else:
        resolved["source"] = relative_path(data["source"])
        if key == "skill":
            resolved["references"] = relative_path(data["references"])
        else:
            resolved["marker"] = data.get("marker", "## graphify")
    return effect_from_data(resolved)


class EffectSpecReader:
    def read(self, path: Path) -> EffectSpec:
        return self.from_yaml(path.read_text(encoding="utf-8"))

    def from_yaml(self, payload: str) -> EffectSpec:
        data = fields(yaml.load(payload, Loader=EffectLoader), "scope directory effects")
        directory = text(data["directory"])
        if directory != ".":
            relative_path(directory)
        raw = data["effects"]
        if not isinstance(raw, list):
            raise ValueError("Expected effects list")
        return EffectSpec(
            tuple(_effect(item, directory) for item in cast(list[object], raw)), text(data["scope"])
        )
