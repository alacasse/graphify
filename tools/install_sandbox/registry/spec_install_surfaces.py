from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Mapping

from ..sandbox_roots import DEFAULT_SANDBOX_ROOT_REGISTRY
from ..surfaces.install_surface_models import (
    FileEffect,
    InstallSurface,
    JsonExpectation,
    JsonHookExpectation,
    JsonHooksEffect,
    JsonPluginEffect,
    JsonPluginExpectation,
    SkillEffect,
    TextExpectation,
    TextSectionEffect,
)
from ..targets.install_target_models import GRAPHIFY_MARKER
from .spec_schema_validation import SpecSchemaValidationError, reject_unknown_fields


_EFFECT_KINDS = {"file", "skill", "text_section", "json_hooks", "json_plugin"}
_EFFECT_COMMON_FIELDS = {"kind", "relative", "remove_on_uninstall", "root"}
_EFFECT_FIELDS_BY_KIND = {
    "file": _EFFECT_COMMON_FIELDS,
    "skill": _EFFECT_COMMON_FIELDS,
    "text_section": _EFFECT_COMMON_FIELDS
    | {"marker", "preserve_user_content", "repair_stale_graphify_section"},
    "json_hooks": _EFFECT_COMMON_FIELDS | {"hooks", "schema_name"},
    "json_plugin": _EFFECT_COMMON_FIELDS | {"allow_file_uri", "plugin_relative", "schema_name"},
}
_JSON_HOOK_FIELDS = {"detail_name", "event", "matcher", "required_fragments"}
_USER_OWNED_TEXT_SECTION_RELATIVES = {
    "AGENTS.md",
    "CLAUDE.md",
    ".claude/CLAUDE.md",
    "GEMINI.md",
    ".github/copilot-instructions.md",
}
_CLAUDE_HOME_INSTRUCTION_RELATIVE = ".claude/CLAUDE.md"


class SpecInstallSurfaceError(ValueError):
    pass


def _fail(context: str, message: str) -> None:
    raise SpecInstallSurfaceError(f"{context}: {message}")


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(context, "expected mapping")
    return value


def _reject_unknown_fields(data: Mapping[str, object], allowed: set[str], context: str) -> None:
    try:
        reject_unknown_fields(data, allowed, context)
    except SpecSchemaValidationError as exc:
        raise SpecInstallSurfaceError(str(exc)) from exc


def _sequence(value: object, context: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(context, "expected list")
    return value


def _string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(context, "expected non-empty string")
    return value


def _bool(value: object, context: str) -> bool:
    if not isinstance(value, bool):
        _fail(context, "expected boolean")
    return value


def _string_list(value: object, context: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    items = _sequence(value, context)
    if not allow_empty and not items:
        _fail(context, "expected non-empty list")
    return tuple(_string(item, f"{context}[{index}]") for index, item in enumerate(items))


def validate_relative_path(relative: str, context: str) -> None:
    if "\\" in relative:
        _fail(context, "relative path must use POSIX separators")
    path = PurePosixPath(relative)
    if path.is_absolute() or relative.startswith("/"):
        _fail(context, "relative path must not be absolute")
    if path.as_posix() in {"", "."}:
        _fail(context, "relative path must not be empty")
    if ".." in path.parts:
        _fail(context, "relative path must not escape its root")
    if path.as_posix() != relative:
        _fail(context, "relative path must be normalized POSIX")


def validate_install_surface_root(root: str, context: str) -> None:
    if root not in DEFAULT_SANDBOX_ROOT_REGISTRY.install_surface_root_names():
        _fail(context, f"unknown expected root: {root}")


def _effect_common(effect: Mapping[str, Any], context: str) -> tuple[str, str, bool]:
    root = _string(effect.get("root"), f"{context}.root")
    relative = _string(effect.get("relative"), f"{context}.relative")
    validate_install_surface_root(root, f"{context}.root")
    validate_relative_path(relative, f"{context}.relative")
    remove_on_uninstall = effect.get("remove_on_uninstall", True)
    return root, relative, _bool(remove_on_uninstall, f"{context}.remove_on_uninstall")


def _effect_kind(effect: Mapping[str, Any], relative: str, context: str) -> str:
    if "kind" in effect:
        kind = _string(effect.get("kind"), f"{context}.kind")
    else:
        kind = "skill" if relative.endswith("SKILL.md") else "file"
    if kind not in _EFFECT_KINDS:
        _fail(f"{context}.kind", f"unknown effect kind: {kind}")
    if relative.endswith("SKILL.md") and kind != "skill":
        _fail(context, "SKILL.md effects must use kind: skill or omit kind for derived skill sidecar policy")
    return kind


def _hook_detail_name(hook: Mapping[str, Any], hook_count: int, context: str) -> str:
    if "detail_name" in hook:
        return _string(hook.get("detail_name"), f"{context}.detail_name")
    if hook_count == 1:
        return "graphify_hook_present"
    matcher = _string(hook.get("matcher"), f"{context}.matcher")
    stem = re.sub(r"[^a-z0-9]+", "_", matcher.lower()).strip("_") or "graphify"
    return f"{stem}_hook_present"


def _json_hooks(effect: Mapping[str, Any], context: str) -> tuple[JsonHookExpectation, ...]:
    hooks = _sequence(effect.get("hooks"), f"{context}.hooks")
    parsed: list[JsonHookExpectation] = []
    for index, hook_value in enumerate(hooks):
        hook = _mapping(hook_value, f"{context}.hooks[{index}]")
        _reject_unknown_fields(hook, _JSON_HOOK_FIELDS, f"{context}.hooks[{index}]")
        fragments = hook.get("required_fragments", ["graphify"])
        parsed.append(
            JsonHookExpectation(
                event=_string(hook.get("event"), f"{context}.hooks[{index}].event"),
                matcher=_string(hook.get("matcher"), f"{context}.hooks[{index}].matcher"),
                detail_name=_hook_detail_name(hook, len(hooks), f"{context}.hooks[{index}]"),
                required_fragments=_string_list(fragments, f"{context}.hooks[{index}].required_fragments", allow_empty=False),
            )
        )
    return tuple(parsed)


def _is_plugin_payload(effect: Mapping[str, Any], context: str) -> bool:
    root, relative, _ = _effect_common(effect, context)
    kind = _effect_kind(effect, relative, context)
    path = PurePosixPath(relative)
    return kind == "file" and root and path.suffix == ".js" and "plugins" in path.parts


def _scope_effects_context(context: str) -> tuple[str, str]:
    for key in ("expected", "effects"):
        token = f".{key}["
        if token in context:
            return context.rsplit(token, 1)[0], key
    return context, "effects"


def _paired_plugin_relative(effect: Mapping[str, Any], effect_values: list[Any], context: str) -> str:
    if "plugin_relative" in effect:
        return _string(effect.get("plugin_relative"), f"{context}.plugin_relative")
    root = _string(effect.get("root"), f"{context}.root")
    scope_context, effects_key = _scope_effects_context(context)
    candidates: list[str] = []
    for index, candidate_value in enumerate(effect_values):
        candidate_context = f"{scope_context}.{effects_key}[{index}]"
        candidate = _mapping(candidate_value, candidate_context)
        candidate_root = _string(candidate.get("root"), f"{candidate_context}.root")
        if candidate_root != root:
            continue
        if _is_plugin_payload(candidate, candidate_context):
            candidates.append(_string(candidate.get("relative"), f"{candidate_context}.relative"))
    if not candidates:
        _fail(context, "json_plugin effect must declare plugin_relative or have one paired JavaScript plugin payload in the same scope/root")
    if len(candidates) > 1:
        _fail(context, "json_plugin effect has ambiguous paired JavaScript plugin payloads")
    return candidates[0]


def _text_section_preserves_user_content(root: str, relative: str) -> bool:
    return relative in _USER_OWNED_TEXT_SECTION_RELATIVES


def _text_section_removes_on_uninstall(root: str, relative: str, declared_remove: bool | None) -> bool:
    if declared_remove is not None:
        return declared_remove
    if root == "home" and relative == _CLAUDE_HOME_INSTRUCTION_RELATIVE:
        return False
    return True


def _install_surface(effect_value: object, context: str, *, effect_values: list[Any] | None = None) -> InstallSurface:
    effect = _mapping(effect_value, context)
    root, relative, declared_remove_on_uninstall = _effect_common(effect, context)
    kind = _effect_kind(effect, relative, context)
    _reject_unknown_fields(effect, _EFFECT_FIELDS_BY_KIND[kind], context)

    if kind == "skill":
        path = SkillEffect(root, relative, remove_on_uninstall=declared_remove_on_uninstall)
    elif kind == "text_section":
        marker = _string(effect.get("marker", GRAPHIFY_MARKER), f"{context}.marker")
        preserve_user_content = _bool(
            effect.get("preserve_user_content", _text_section_preserves_user_content(root, relative)),
            f"{context}.preserve_user_content",
        )
        remove_on_uninstall = _text_section_removes_on_uninstall(
            root,
            relative,
            _bool(effect.get("remove_on_uninstall"), f"{context}.remove_on_uninstall") if "remove_on_uninstall" in effect else None,
        )
        path = TextSectionEffect(
            root,
            relative,
            marker=marker,
            remove_on_uninstall=remove_on_uninstall,
            text_expectation=TextExpectation(
                preserve_user_content=preserve_user_content,
                repair_stale_graphify_section=_bool(
                    effect.get("repair_stale_graphify_section", marker == GRAPHIFY_MARKER),
                    f"{context}.repair_stale_graphify_section",
                ),
                require_user_content_on_uninstall=preserve_user_content,
            ),
        )
    elif kind == "json_hooks":
        path = JsonHooksEffect(
            root,
            relative,
            remove_on_uninstall=declared_remove_on_uninstall,
            json_expectation=JsonExpectation(
                schema_name=_string(effect.get("schema_name"), f"{context}.schema_name"),
                hooks=_json_hooks(effect, context),
            ),
        )
    elif kind == "json_plugin":
        if effect_values is None:
            _fail(context, "json_plugin derivation requires scope effects context")
        path = JsonPluginEffect(
            root,
            relative,
            remove_on_uninstall=declared_remove_on_uninstall,
            json_expectation=JsonExpectation(
                schema_name=_string(effect.get("schema_name"), f"{context}.schema_name"),
                plugin=JsonPluginExpectation(
                    expected_entry=_paired_plugin_relative(effect, effect_values, context),
                    allow_file_uri=_bool(effect.get("allow_file_uri", False), f"{context}.allow_file_uri"),
                ),
            ),
        )
    else:
        path = FileEffect(root, relative, remove_on_uninstall=declared_remove_on_uninstall)

    return path


def _scope_effect_values(data: Mapping[str, Any], context: str) -> tuple[str, list[Any]]:
    has_expected = "expected" in data
    has_effects = "effects" in data
    if has_expected and has_effects:
        _fail(context, "invalid legacy expected input; runnable scope must declare effects only")
    if has_effects:
        return "effects", _sequence(data.get("effects"), f"{context}.effects")
    if has_expected:
        _fail(context, "invalid legacy expected input; runnable scope must declare effects")
    _fail(context, "runnable scope must declare effects")


def derive_scope_install_surfaces(data: Mapping[str, Any], context: str) -> tuple[InstallSurface, ...]:
    effect_key, effect_values = _scope_effect_values(data, context)
    if not effect_values:
        _fail(f"{context}.{effect_key}", f"runnable scope must declare at least one {effect_key} file effect")
    return tuple(
        _install_surface(effect, f"{context}.{effect_key}[{index}]", effect_values=effect_values)
        for index, effect in enumerate(effect_values)
    )
