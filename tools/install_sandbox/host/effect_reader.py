"""Resolve the host effect YAML without a target-name registry."""

from collections.abc import Callable
from pathlib import Path
from typing import cast

import yaml

from tools.install_sandbox.contracts.effects import (
    Effect,
    EffectSpec,
    ScopeDeclaration,
    ToolDeclaration,
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


def _effect(value: object) -> Effect:
    if not isinstance(value, dict):
        raise ValueError("Expected effect")
    incoming = cast(dict[str, object], value)
    family = incoming.get("family")
    extra = {
        "file": "content",
        "skill": "source references",
        "markdown-section": "source",
        "json-hooks": "hooks",
    }
    if family not in extra:
        raise ValueError(f"Unsupported effect family: {family}")
    optional = " marker" if "marker" in incoming and family == "markdown-section" else ""
    data = fields(incoming, "effect_id family root path " + extra[cast(str, family)] + optional)
    roots = {"HOME": "home", "PROJECT": "project"}
    root = text(data["root"])
    if root not in roots:
        raise ValueError("Expected HOME or PROJECT destination root")
    resolved: dict[str, object] = {
        "effect_id": text(data["effect_id"]),
        "kind": family,
        "destination": {"root": roots[root], "path": relative_path(data["path"])},
    }
    if family == "file":
        resolved["content"] = data["content"]
    elif family == "json-hooks":
        resolved["hooks"] = data["hooks"]
    else:
        resolved["source"] = data["source"]
        if family == "skill":
            resolved["references"] = data["references"]
        elif family == "markdown-section":
            resolved["marker"] = data.get("marker", "## graphify")
    return effect_from_data(resolved)


class EffectSpecReader:
    def read(self, path: Path) -> ToolDeclaration:
        return self.from_yaml(path.read_text(encoding="utf-8"))

    def from_yaml(self, payload: str) -> ToolDeclaration:
        raw = yaml.load(payload, Loader=EffectLoader)
        if isinstance(raw, dict) and "tool" not in raw:
            raise ValueError("Historical spec has not been converted to tool/scopes declarations")
        data = fields(cast(object, raw), "tool scopes")
        if not isinstance(data["scopes"], dict) or not data["scopes"]:
            raise ValueError("Expected non-empty declared scopes")
        scopes: list[ScopeDeclaration] = []
        for scope, value in cast(dict[str, object], data["scopes"]).items():
            if isinstance(value, list):
                scopes.append(
                    ScopeDeclaration(
                        scope,
                        EffectSpec(tuple(_effect(e) for e in cast(list[object], value)), scope),
                    )
                )
            else:
                state = fields(value, "state reason")
                scopes.append(
                    ScopeDeclaration(
                        scope, classification=text(state["state"]), reason=text(state["reason"])
                    )
                )
        return ToolDeclaration(text(data["tool"]), tuple(scopes))
