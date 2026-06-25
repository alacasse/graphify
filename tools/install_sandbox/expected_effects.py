from __future__ import annotations

"""Compatibility facade for legacy install-surface model imports."""

try:
    from .surfaces.install_surface_models import (
        ExpectedPath,
        FileEffect,
        InstallSurface,
        JsonExpectation,
        JsonHookExpectation,
        JsonHooksEffect,
        JsonPluginEffect,
        JsonPluginExpectation,
        SkillEffect,
        SkillSidecarExpectation,
        TextExpectation,
        TextSectionEffect,
        effect_type_name,
        is_json_effect,
        is_skill_effect,
        is_text_section_effect,
    )
except ImportError:  # pragma: no cover - direct script import fallback
    from surfaces.install_surface_models import (  # type: ignore[no-redef]
        ExpectedPath,
        FileEffect,
        InstallSurface,
        JsonExpectation,
        JsonHookExpectation,
        JsonHooksEffect,
        JsonPluginEffect,
        JsonPluginExpectation,
        SkillEffect,
        SkillSidecarExpectation,
        TextExpectation,
        TextSectionEffect,
        effect_type_name,
        is_json_effect,
        is_skill_effect,
        is_text_section_effect,
    )

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
