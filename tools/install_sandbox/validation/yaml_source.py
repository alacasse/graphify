"""Strict YAML syntax decoding for fictional catalog documents."""

from __future__ import annotations

from typing import Protocol, cast

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode


class _DisposableLoader(Protocol):
    def dispose(self) -> None: ...


def _mapping_duplicate(node: MappingNode) -> str | None:
    seen: set[tuple[str, str]] = set()
    for key_node, value_node in node.value:
        if isinstance(key_node, ScalarNode):
            identity = (key_node.tag, key_node.value)
            if identity in seen:
                return key_node.value
            seen.add(identity)
        duplicate = _duplicate_yaml_key(value_node)
        if duplicate is not None:
            return duplicate
    return None


def _sequence_duplicate(node: SequenceNode) -> str | None:
    for item in node.value:
        duplicate = _duplicate_yaml_key(item)
        if duplicate is not None:
            return duplicate
    return None


def _duplicate_yaml_key(node: Node | None) -> str | None:
    if isinstance(node, MappingNode):
        return _mapping_duplicate(node)
    if isinstance(node, SequenceNode):
        return _sequence_duplicate(node)
    return None


def _compose_yaml(text: str) -> Node | None:
    loader = yaml.SafeLoader(text)
    try:
        return loader.get_single_node()
    finally:
        cast(_DisposableLoader, loader).dispose()


def load_yaml_document(text: str, filename: str) -> object:
    """Decode one document while rejecting duplicate keys at every depth."""

    try:
        duplicate = _duplicate_yaml_key(_compose_yaml(text))
        if duplicate is not None:
            raise ValueError(f"{filename} contains duplicate YAML key: {duplicate!r}")
        return cast(object, yaml.safe_load(text))
    except yaml.YAMLError as error:
        raise ValueError(f"{filename} is malformed YAML: {error}") from error
