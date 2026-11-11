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
    effect_id: str = "skill"


@dataclass(frozen=True)
class MarkdownSectionEffect:
    source: str
    destination: Destination
    marker: str = "## graphify"
    kind: str = "markdown-section"
    effect_id: str = "markdown-section"


@dataclass(frozen=True)
class JsonHooksEffect:
    destination: Destination
    hooks: tuple[HookExpectation, ...]
    kind: str = "json-hooks"
    effect_id: str = "json-hooks"


Effect = SkillEffect | MarkdownSectionEffect | JsonHooksEffect


def effect_from_data(value: object) -> Effect:
    if not isinstance(value, dict):
        raise ValueError("Expected effect object")
    incoming = cast(dict[str, object], value)
    kind = incoming.get("kind")
    if kind == "skill":
        data = fields(incoming, "kind source references destination effect_id")
        return SkillEffect(
            relative_path(data["source"]),
            relative_path(data["references"]),
            Destination.from_data(data["destination"]),
            effect_id=text(data["effect_id"]),
        )
    if kind == "markdown-section":
        data = fields(incoming, "kind source marker destination effect_id")
        marker = text(data["marker"])
        if not marker.startswith("## ") or "\n" in marker:
            raise ValueError("Expected a level-two Markdown marker")
        return MarkdownSectionEffect(
            relative_path(data["source"]),
            Destination.from_data(data["destination"]),
            marker,
            effect_id=text(data["effect_id"]),
        )
    if kind == "json-hooks":
        return _json_hooks_from_data(incoming)
    raise ValueError(f"Unsupported effect kind: {kind}")


def _json_hooks_from_data(incoming: dict[str, object]) -> JsonHooksEffect:
    data = fields(incoming, "kind destination hooks effect_id")
    hooks = data["hooks"]
    if not isinstance(hooks, list) or not hooks:
        raise ValueError("Expected non-empty hooks")
    resolved = tuple(HookExpectation.from_data(item) for item in cast(list[object], hooks))
    if len({h.id for h in resolved}) != len(resolved):
        raise ValueError("Duplicate hook member ID")
    if any(
        not isinstance(h.content.get("type"), str) or not isinstance(h.content.get("command"), str)
        for h in resolved
    ):
        raise ValueError("Hook disk identity requires type and command")
    if len(
        {(h.event, h.matcher, h.content["type"], h.content["command"]) for h in resolved}
    ) != len(resolved):
        raise ValueError("Duplicate hook destination")
    return JsonHooksEffect(
        Destination.from_data(data["destination"]), resolved, effect_id=text(data["effect_id"])
    )


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
    if len({text(e.effect_id) for e in effects}) != len(effects):
        raise ValueError("Duplicate effect ID")
    owned: dict[Destination, bool] = {}
    for effect in effects:
        for destination in physical_destinations(effect):
            # Only the skill's auxiliary lock directory is shareable, never its destination.
            shared_lock = isinstance(effect, SkillEffect) and destination != effect.destination
            if shared_lock and owned.get(destination) is True:
                continue
            path = PurePosixPath(destination.path)
            for previous in owned:
                other = PurePosixPath(previous.path)
                if previous.root == destination.root and (
                    path == other or path in other.parents or other in path.parents
                ):
                    raise ValueError("Effect destinations overlap, including auxiliary files")
            owned[destination] = shared_lock


@dataclass(frozen=True)
class EffectSpec:
    effects: tuple[Effect, ...]
    scope: str = "project"

    def __post_init__(self) -> None:
        text(self.scope)
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


@dataclass(frozen=True)
class ScopeDeclaration:
    scope: str
    effects: EffectSpec | None = None
    classification: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        text(self.scope)
        if self.effects is not None:
            if (
                self.effects.scope != self.scope
                or self.classification is not None
                or self.reason is not None
            ):
                raise ValueError("Inconsistent executable scope")
        else:
            if self.classification not in {"unconstructible", "not_applicable"}:
                raise ValueError("Unresolved scope requires a classification and reason")
            text(self.reason)

    def to_data(self) -> dict[str, object]:
        return {
            "scope": self.scope,
            "effects": None if self.effects is None else self.effects.to_data(),
            "classification": self.classification,
            "reason": self.reason,
        }

    @classmethod
    def from_data(cls, value: object) -> "ScopeDeclaration":
        data = fields(value, "scope effects classification reason")
        return cls(
            text(data["scope"]),
            None if data["effects"] is None else EffectSpec.from_data(data["effects"]),
            None if data["classification"] is None else text(data["classification"]),
            None if data["reason"] is None else text(data["reason"]),
        )


@dataclass(frozen=True)
class ToolDeclaration:
    tool: str
    scopes: tuple[ScopeDeclaration, ...]

    def __post_init__(self) -> None:
        text(self.tool)
        if not self.scopes or len({s.scope for s in self.scopes}) != len(self.scopes):
            raise ValueError("Expected distinct declared scopes")

    def to_data(self) -> dict[str, object]:
        return {"tool": self.tool, "scopes": [s.to_data() for s in self.scopes]}

    @classmethod
    def from_data(cls, value: object) -> "ToolDeclaration":
        data = fields(value, "tool scopes")
        if not isinstance(data["scopes"], list):
            raise ValueError("Expected declared scopes")
        return cls(
            text(data["tool"]),
            tuple(ScopeDeclaration.from_data(s) for s in cast(list[object], data["scopes"])),
        )
