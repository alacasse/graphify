from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Literal


@dataclass(frozen=True)
class JsonHookExpectation:
    event: str
    matcher: str
    detail_name: str
    required_fragments: tuple[str, ...] = ("graphify",)


@dataclass(frozen=True)
class JsonPluginExpectation:
    expected_entry: str
    allow_file_uri: bool = False
    detail_name: str = "plugin_present"


@dataclass(frozen=True)
class JsonExpectation:
    schema_name: str
    hooks: tuple[JsonHookExpectation, ...] = ()
    plugin: JsonPluginExpectation | None = None


@dataclass(frozen=True)
class TextExpectation:
    preserve_user_content: bool = False
    repair_stale_graphify_section: bool = False
    remove_graphify_section_on_uninstall: bool = True
    require_user_content_on_uninstall: bool = False


@dataclass(frozen=True)
class SkillSidecarExpectation:
    version_name: str = ".graphify_version"
    references_dir: str = "references"
    references_tmp_dir: str = "references.tmp"
    reference_pointer_pattern: str = r"references/([A-Za-z0-9_.-]+\.md)\b"


@dataclass(frozen=True)
class FileEffect:
    effect_type: ClassVar[str] = "file"

    root: str
    relative: str
    kind: str = "file"
    content_kind: Literal["text", "json"] = "text"
    marker: str | None = None
    remove_on_uninstall: bool = True
    json_expectation: JsonExpectation | None = None
    text_expectation: TextExpectation = field(default_factory=TextExpectation)
    skill_sidecar_expectation: SkillSidecarExpectation | None = None


@dataclass(frozen=True)
class SkillEffect(FileEffect):
    effect_type: ClassVar[str] = "skill"

    skill_sidecar_expectation: SkillSidecarExpectation | None = field(default_factory=SkillSidecarExpectation)


@dataclass(frozen=True)
class TextSectionEffect(FileEffect):
    effect_type: ClassVar[str] = "text_section"

    marker: str | None = "## graphify"


@dataclass(frozen=True)
class JsonHooksEffect(FileEffect):
    effect_type: ClassVar[str] = "json_hooks"

    content_kind: Literal["text", "json"] = "json"
    marker: str | None = "graphify"


@dataclass(frozen=True)
class JsonPluginEffect(FileEffect):
    effect_type: ClassVar[str] = "json_plugin"

    content_kind: Literal["text", "json"] = "json"
    marker: str | None = "graphify"


InstallSurface = FileEffect
ExpectedPath = InstallSurface


def _has_text_section_policy(effect: FileEffect) -> bool:
    return effect.text_expectation != TextExpectation()


def effect_type_name(effect: FileEffect) -> str:
    if isinstance(effect, SkillEffect):
        return SkillEffect.effect_type
    if isinstance(effect, TextSectionEffect):
        return TextSectionEffect.effect_type
    if isinstance(effect, JsonHooksEffect):
        return JsonHooksEffect.effect_type
    if isinstance(effect, JsonPluginEffect):
        return JsonPluginEffect.effect_type
    if effect.skill_sidecar_expectation is not None:
        return SkillEffect.effect_type
    if effect.json_expectation is not None:
        if effect.json_expectation.plugin is not None:
            return JsonPluginEffect.effect_type
        if effect.json_expectation.hooks:
            return JsonHooksEffect.effect_type
    if effect.content_kind == "text" and (effect.marker is not None or _has_text_section_policy(effect)):
        return TextSectionEffect.effect_type
    return FileEffect.effect_type


def is_skill_effect(effect: FileEffect) -> bool:
    return isinstance(effect, SkillEffect) or effect.skill_sidecar_expectation is not None


def is_text_section_effect(effect: FileEffect) -> bool:
    return isinstance(effect, TextSectionEffect) or (effect.content_kind == "text" and (effect.marker is not None or _has_text_section_policy(effect)))


def is_json_effect(effect: FileEffect) -> bool:
    return isinstance(effect, (JsonHooksEffect, JsonPluginEffect)) or effect.content_kind == "json"


__all__ = [
    "ExpectedPath",
    "FileEffect",
    "InstallSurface",
    "JsonExpectation",
    "JsonHookExpectation",
    "JsonHooksEffect",
    "JsonPluginEffect",
    "JsonPluginExpectation",
    "SkillEffect",
    "SkillSidecarExpectation",
    "TextExpectation",
    "TextSectionEffect",
    "effect_type_name",
    "is_json_effect",
    "is_skill_effect",
    "is_text_section_effect",
]
