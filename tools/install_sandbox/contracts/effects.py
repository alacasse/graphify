"""Independent, portable installation effects and their physical destinations."""

import json
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import cast

from tools.install_sandbox.contracts.spec import HookExpectation, fields, relative_path, text


@dataclass(frozen=True)
class Destination:
    root: str
    path: str

    def __post_init__(self) -> None:
        if self.root not in {"home", "project"}:
            raise ValueError("Destination root must be home or project")
        relative_path(self.path)

    @classmethod
    def from_data(cls, value: object) -> "Destination":
        data = fields(value, "root path")
        return cls(text(data["root"]), relative_path(data["path"]))


@dataclass(frozen=True)
class SkillEffect:
    source: str
    references: str
    destination: Destination
    kind: str = "skill"


@dataclass(frozen=True)
class MarkdownSectionEffect:
    source: str
    destination: Destination
    marker: str = "## graphify"
    kind: str = "markdown-section"


@dataclass(frozen=True)
class JsonHooksEffect:
    destination: Destination
    hooks: tuple[HookExpectation, ...]
    kind: str = "json-hooks"


Effect = SkillEffect | MarkdownSectionEffect | JsonHooksEffect


def effect_identity(effect: Effect) -> tuple[str, ...]:
    identity = (effect.kind, effect.destination.root, effect.destination.path)
    return identity + ((effect.marker,) if isinstance(effect, MarkdownSectionEffect) else ())


def effect_from_data(value: object) -> Effect:
    if not isinstance(value, dict):
        raise ValueError("Expected effect object")
    incoming = cast(dict[str, object], value)
    kind = incoming.get("kind")
    if kind == "skill":
        data = fields(incoming, "kind source references destination")
        return SkillEffect(
            relative_path(data["source"]),
            relative_path(data["references"]),
            Destination.from_data(data["destination"]),
        )
    if kind == "markdown-section":
        data = fields(incoming, "kind source marker destination")
        marker = text(data["marker"])
        if not marker.startswith("## ") or "\n" in marker:
            raise ValueError("Expected a level-two Markdown marker")
        return MarkdownSectionEffect(
            relative_path(data["source"]), Destination.from_data(data["destination"]), marker
        )
    if kind == "json-hooks":
        data = fields(incoming, "kind destination hooks")
        hooks = data["hooks"]
        if not isinstance(hooks, list) or not hooks:
            raise ValueError("Expected non-empty hooks")
        resolved = tuple(HookExpectation.from_data(item) for item in cast(list[object], hooks))
        if len({(h.event, h.matcher) for h in resolved}) != len(resolved):
            raise ValueError("Duplicate hook destination")
        return JsonHooksEffect(Destination.from_data(data["destination"]), resolved)
    raise ValueError(f"Unsupported effect kind: {kind}")


def physical_destinations(effect: Effect) -> tuple[Destination, ...]:
    destination = effect.destination
    if isinstance(effect, SkillEffect):
        # Reserve the complete skill tree, including metadata and persistent lock.
        return (destination, Destination("home", ".cache/graphify/skill-locks"))
    if isinstance(effect, JsonHooksEffect):
        return tuple(
            Destination(destination.root, destination.path + suffix)
            for suffix in (
                "",
                ".graphify-bak",
                ".bak",
                ".graphify-state.json",
                ".graphify.lock",
                ".graphify-journal.json",
            )
        )
    return (destination,)


def validate_effects(effects: tuple[Effect, ...]) -> None:
    if not effects:
        raise ValueError("Expected at least one effect")
    owned: list[Destination] = []
    for effect in effects:
        for destination in physical_destinations(effect):
            if (
                isinstance(effect, SkillEffect)
                and destination == Destination("home", ".cache/graphify/skill-locks")
                and destination in owned
            ):
                continue
            path = PurePosixPath(destination.path)
            for previous in owned:
                other = PurePosixPath(previous.path)
                if previous.root == destination.root and (
                    path == other or path in other.parents or other in path.parents
                ):
                    raise ValueError("Effect destinations overlap, including auxiliary files")
            owned.append(destination)


@dataclass(frozen=True)
class EffectSpec:
    effects: tuple[Effect, ...]
    scope: str = "project"

    def __post_init__(self) -> None:
        if self.scope != "project":
            raise ValueError("Only project scope is supported")
        validate_effects(self.effects)

    def to_data(self) -> dict[str, object]:
        return {
            "scope": self.scope,
            "effects": json.loads(json.dumps([asdict(effect) for effect in self.effects])),
        }

    @classmethod
    def from_data(cls, value: object) -> "EffectSpec":
        data = fields(value, "scope effects")
        raw = data["effects"]
        if not isinstance(raw, list):
            raise ValueError("Expected effects list")
        return cls(
            tuple(effect_from_data(item) for item in cast(list[object], raw)), text(data["scope"])
        )
