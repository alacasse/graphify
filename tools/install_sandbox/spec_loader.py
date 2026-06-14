from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

try:
    import yaml
except ImportError as exc:  # pragma: no cover - dependency is declared for dev/test use
    yaml = None  # type: ignore[assignment]
    _YAML_IMPORT_ERROR = exc
else:
    _YAML_IMPORT_ERROR = None

try:
    from . import platform_specs as model
    from .harness_specs import DEFAULT_SANDBOX_ROOT_REGISTRY
except ImportError:  # pragma: no cover - direct script import fallback
    import platform_specs as model  # type: ignore[no-redef]
    from harness_specs import DEFAULT_SANDBOX_ROOT_REGISTRY  # type: ignore[no-redef]


SCHEMA_VERSION = 1
DEFAULT_REGISTRY_PATH = Path(__file__).with_name("specs") / "registry.yaml"

_SCOPE_NAMES = {"user", "project"}
_EFFECT_KINDS = {"file", "skill", "text_section", "json_hooks", "json_plugin"}
_WIDENED_SCOPE_ROOTS = ("home", "project", "user_cwd")
_USER_OWNED_TEXT_SECTION_RELATIVES = {
    "AGENTS.md",
    "CLAUDE.md",
    ".claude/CLAUDE.md",
    "GEMINI.md",
    ".github/copilot-instructions.md",
}
_CLAUDE_HOME_INSTRUCTION_RELATIVE = ".claude/CLAUDE.md"
_RUNTIME_VALIDATION_POLICY_NAMES = {"simulated_linux_layout"}
_KNOWN_SCOPE_RISK_NOTES = {
    model.PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE,
    model.MIXED_SCOPE_PROJECT_WIRING_NOTE,
    model.MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE,
    model.SIMULATED_LINUX_LAYOUT_NOTE,
}


class SpecLoaderError(ValueError):
    pass


def _fail(context: str, message: str) -> None:
    raise SpecLoaderError(f"{context}: {message}")


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(context, "expected mapping")
    return value


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


def _int(value: object, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        _fail(context, "expected integer")
    return value


def _string_list(value: object, context: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    items = _sequence(value, context)
    if not allow_empty and not items:
        _fail(context, "expected non-empty list")
    return tuple(_string(item, f"{context}[{index}]") for index, item in enumerate(items))


def _command(value: object, context: str) -> tuple[str, ...]:
    return _string_list(value, context, allow_empty=False)


def _optional_command(value: object, context: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    return _command(value, context)


def _validate_relative(relative: str, context: str) -> None:
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


def _root_names() -> tuple[set[str], set[str]]:
    expected_roots = DEFAULT_SANDBOX_ROOT_REGISTRY.declared_expected_root_names()
    all_roots = {root.name for root in DEFAULT_SANDBOX_ROOT_REGISTRY.roots}
    return expected_roots, all_roots


def _validate_expected_root(root: str, context: str) -> None:
    expected_roots, _ = _root_names()
    if root not in expected_roots:
        _fail(context, f"unknown expected root: {root}")


def _validate_cwd_root(root: str, context: str) -> None:
    _, all_roots = _root_names()
    if root not in all_roots:
        _fail(context, f"unknown cwd root: {root}")


def _effect_common(effect: Mapping[str, Any], context: str) -> tuple[str, str, bool]:
    root = _string(effect.get("root"), f"{context}.root")
    relative = _string(effect.get("relative"), f"{context}.relative")
    _validate_expected_root(root, f"{context}.root")
    _validate_relative(relative, f"{context}.relative")
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


def _json_hooks(effect: Mapping[str, Any], context: str) -> tuple[model.JsonHookExpectation, ...]:
    hooks = _sequence(effect.get("hooks"), f"{context}.hooks")
    parsed: list[model.JsonHookExpectation] = []
    for index, hook_value in enumerate(hooks):
        hook = _mapping(hook_value, f"{context}.hooks[{index}]")
        fragments = hook.get("required_fragments", ["graphify"])
        parsed.append(
            model.JsonHookExpectation(
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


def _paired_plugin_relative(effect: Mapping[str, Any], expected_values: list[Any], context: str) -> str:
    if "plugin_relative" in effect:
        return _string(effect.get("plugin_relative"), f"{context}.plugin_relative")
    root = _string(effect.get("root"), f"{context}.root")
    candidates: list[str] = []
    for index, candidate_value in enumerate(expected_values):
        candidate_context = f"{context.rsplit('.expected[', 1)[0]}.expected[{index}]"
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


def _expected_path(effect_value: object, context: str, *, expected_values: list[Any] | None = None) -> model.ExpectedPath:
    effect = _mapping(effect_value, context)
    root, relative, declared_remove_on_uninstall = _effect_common(effect, context)
    kind = _effect_kind(effect, relative, context)

    if kind == "skill":
        path = model.ExpectedPath(root, relative, remove_on_uninstall=declared_remove_on_uninstall, skill_sidecar_expectation=model.SkillSidecarExpectation())
    elif kind == "text_section":
        marker = _string(effect.get("marker", model.GRAPHIFY_MARKER), f"{context}.marker")
        preserve_user_content = _bool(effect.get("preserve_user_content", _text_section_preserves_user_content(root, relative)), f"{context}.preserve_user_content")
        remove_on_uninstall = _text_section_removes_on_uninstall(
            root,
            relative,
            _bool(effect.get("remove_on_uninstall"), f"{context}.remove_on_uninstall") if "remove_on_uninstall" in effect else None,
        )
        path = model.ExpectedPath(
            root,
            relative,
            marker=marker,
            remove_on_uninstall=remove_on_uninstall,
            text_expectation=model.TextExpectation(
                preserve_user_content=preserve_user_content,
                repair_stale_graphify_section=_bool(effect.get("repair_stale_graphify_section", marker == model.GRAPHIFY_MARKER), f"{context}.repair_stale_graphify_section"),
                require_user_content_on_uninstall=preserve_user_content,
            ),
        )
    elif kind == "json_hooks":
        path = model.ExpectedPath(
            root,
            relative,
            content_kind="json",
            marker="graphify",
            remove_on_uninstall=declared_remove_on_uninstall,
            json_expectation=model.JsonExpectation(
                schema_name=_string(effect.get("schema_name"), f"{context}.schema_name"),
                hooks=_json_hooks(effect, context),
            ),
        )
    elif kind == "json_plugin":
        if expected_values is None:
            _fail(context, "json_plugin derivation requires scope expected context")
        path = model.ExpectedPath(
            root,
            relative,
            content_kind="json",
            marker="graphify",
            remove_on_uninstall=declared_remove_on_uninstall,
            json_expectation=model.JsonExpectation(
                schema_name=_string(effect.get("schema_name"), f"{context}.schema_name"),
                plugin=model.JsonPluginExpectation(
                    expected_entry=_paired_plugin_relative(effect, expected_values, context),
                    allow_file_uri=_bool(effect.get("allow_file_uri", False), f"{context}.allow_file_uri"),
                ),
            ),
        )
    else:
        path = model.ExpectedPath(root, relative, remove_on_uninstall=declared_remove_on_uninstall)

    return path


def _install_variants(value: object, context: str) -> tuple[model.InstallCommandVariant, ...]:
    variants = _sequence(value, context)
    labels: set[str] = set()
    parsed: list[model.InstallCommandVariant] = []
    for index, variant_value in enumerate(variants):
        variant = _mapping(variant_value, f"{context}[{index}]")
        label = _string(variant.get("label"), f"{context}[{index}].label")
        if label in labels:
            _fail(f"{context}[{index}].label", f"duplicate install variant label: {label}")
        labels.add(label)
        parsed.append(model.InstallCommandVariant(label, _command(variant.get("command"), f"{context}[{index}].command")))
    return tuple(parsed)


def _generated_file_expectation(value: object, context: str) -> model.GeneratedFileExpectation:
    data = _mapping(value, context)
    return model.GeneratedFileExpectation(
        relative_substrings=_string_list(data.get("relative_substrings", ["graphify"]), f"{context}.relative_substrings"),
        text_suffixes=_string_list(data.get("text_suffixes", [".json", ".js", ".md", ".mdc", ".txt", ""]), f"{context}.text_suffixes"),
        content_markers=_string_list(data.get("content_markers", ["graphify"]), f"{context}.content_markers"),
        include_user_content_sentinel=_bool(data.get("include_user_content_sentinel", True), f"{context}.include_user_content_sentinel"),
        max_text_bytes=_int(data.get("max_text_bytes", 1024 * 1024), f"{context}.max_text_bytes"),
    )


def _dedupe(items: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for item in items if item))


def _scope_locality(scope_name: str, expected: tuple[model.ExpectedPath, ...]) -> tuple[str | None, tuple[str, ...]]:
    roots = {entry.root for entry in expected}
    if scope_name == "project":
        if roots <= {"project"}:
            return None, ("project",)
        return model.MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE, _WIDENED_SCOPE_ROOTS
    if roots <= {"home"}:
        return None, ("home",)
    return model.MIXED_SCOPE_PROJECT_WIRING_NOTE, _WIDENED_SCOPE_ROOTS


def _scope_risk_notes(explicit_notes: tuple[str, ...], locality_note: str | None, *, simulated_linux_layout: bool) -> tuple[str, ...]:
    notes: tuple[str, ...] = explicit_notes
    if locality_note is not None:
        notes = (locality_note, *notes)
    if simulated_linux_layout:
        notes = (*notes, model.SIMULATED_LINUX_LAYOUT_NOTE)
    return _dedupe(notes)


def _scope_spec(platform_name: str, scope_name: str, value: object, context: str, *, simulated_linux_layout: bool) -> model.ScopeSpec:
    data = _mapping(value, context)
    if scope_name not in _SCOPE_NAMES:
        _fail(context, f"invalid platform scope: {scope_name}")
    expected_values = _sequence(data.get("expected"), f"{context}.expected")
    if not expected_values:
        _fail(f"{context}.expected", "runnable scope must declare at least one expected file effect")
    expected = tuple(_expected_path(effect, f"{context}.expected[{index}]", expected_values=expected_values) for index, effect in enumerate(expected_values))
    explicit_risk_notes = _string_list(data.get("risk_notes", []), f"{context}.risk_notes")
    for note in explicit_risk_notes:
        if note not in _KNOWN_SCOPE_RISK_NOTES:
            _fail(f"{context}.risk_notes", f"unknown structured risk note: {note}")
    locality_note, derived_allowed_roots = _scope_locality(scope_name, expected)
    risk_notes = _scope_risk_notes(explicit_risk_notes, locality_note, simulated_linux_layout=simulated_linux_layout)

    install_command = None
    if "install_command" in data:
        install_command = _command(data.get("install_command"), f"{context}.install_command")
    uninstall_command: tuple[str, ...] | None | str
    if "uninstall_command" in data:
        uninstall_command = _optional_command(data.get("uninstall_command"), f"{context}.uninstall_command")
    else:
        uninstall_command = "generic"
    cwd_root = None
    if "cwd_root" in data:
        cwd_root = _string(data.get("cwd_root"), f"{context}.cwd_root")
        _validate_cwd_root(cwd_root, f"{context}.cwd_root")
    equivalent_install_command = None
    if "equivalent_install_command" in data:
        equivalent_install_command = _optional_command(data.get("equivalent_install_command"), f"{context}.equivalent_install_command")

    scope = model._scenario(  # type: ignore[attr-defined]
        platform_name,
        scope_name,
        expected,
        install_command=install_command,
        uninstall_command=uninstall_command,
        cwd_root=cwd_root,
        risk_notes=risk_notes,
        equivalent_install_command=equivalent_install_command,
    )
    scope = replace(scope, allowed_roots=derived_allowed_roots)
    if "install_variants" in data:
        scope = replace(scope, install_variants=_install_variants(data.get("install_variants"), f"{context}.install_variants"))
    if "allowed_roots" in data:
        allowed_roots = _string_list(data.get("allowed_roots"), f"{context}.allowed_roots")
        for root in allowed_roots:
            _validate_cwd_root(root, f"{context}.allowed_roots")
        scope = replace(scope, allowed_roots=allowed_roots)
    if "generated_file_expectation" in data:
        scope = replace(scope, generated_file_expectation=_generated_file_expectation(data.get("generated_file_expectation"), f"{context}.generated_file_expectation"))
    return scope


def _reference_bundle(value: object, context: str) -> model.ReferenceBundle:
    if isinstance(value, str):
        return model.ReferenceBundle(value)
    data = _mapping(value, context)
    required = data.get("required_package_relative")
    return model.ReferenceBundle(
        _string(data.get("name"), f"{context}.name"),
        required_package_relative=None if required is None else _string(required, f"{context}.required_package_relative"),
    )


def _runtime_validation(value: object, context: str) -> model.TargetRuntimeValidationSpec:
    data = _mapping(value, context)
    evidence = data.get("evidence_path")
    return model.TargetRuntimeValidationSpec(
        section_title=_string(data.get("section_title"), f"{context}.section_title"),
        status=_string(data.get("status"), f"{context}.status"),
        strategy=_string(data.get("strategy"), f"{context}.strategy"),
        targets=_string_list(data.get("targets"), f"{context}.targets", allow_empty=False),
        notes=_string_list(data.get("notes"), f"{context}.notes", allow_empty=False),
        evidence_path=None if evidence is None else _string(evidence, f"{context}.evidence_path"),
    )


def _runtime_validation_policies(value: object, context: str) -> dict[str, model.TargetRuntimeValidationSpec]:
    policies = _mapping(value, context)
    for name in policies:
        if name not in _RUNTIME_VALIDATION_POLICY_NAMES:
            _fail(f"{context}.{name}", f"unknown runtime validation policy: {name}")
    return {name: _runtime_validation(policy, f"{context}.{name}") for name, policy in policies.items()}


def _platform_runtime_validations(
    data: Mapping[str, Any],
    context: str,
    *,
    simulated_linux_layout: bool,
    shared_runtime_validations: Mapping[str, model.TargetRuntimeValidationSpec],
) -> tuple[model.TargetRuntimeValidationSpec, ...]:
    validations = [
        _runtime_validation(validation, f"{context}.target_runtime_validation[{index}]")
        for index, validation in enumerate(_sequence(data.get("target_runtime_validation", []), f"{context}.target_runtime_validation"))
    ]
    if simulated_linux_layout and (validation := shared_runtime_validations.get("simulated_linux_layout")) is not None:
        validations.append(validation)
    return tuple(dict.fromkeys(validations))


def _platform_spec(
    platform_key: str,
    value: object,
    context: str,
    *,
    shared_runtime_validations: Mapping[str, model.TargetRuntimeValidationSpec],
) -> model.PlatformSpec:
    data = _mapping(value, context)
    name = platform_key
    if "name" in data:
        name = _string(data.get("name"), f"{context}.name")
        if name != platform_key:
            _fail(f"{context}.name", f"platform key/name mismatch: {platform_key} != {name}")

    scopes_value = _mapping(data.get("scopes", {}), f"{context}.scopes")
    unsupported_value = _mapping(data.get("unsupported_scopes", {}), f"{context}.unsupported_scopes")
    for scope_name in (*scopes_value, *unsupported_value):
        if scope_name not in _SCOPE_NAMES:
            _fail(context, f"invalid platform scope: {scope_name}")
    for scope_name in sorted(_SCOPE_NAMES):
        runnable = scope_name in scopes_value
        unsupported = scope_name in unsupported_value
        if runnable == unsupported:
            _fail(f"{context}.{scope_name}", "expected exactly one runnable scope or unsupported reason")

    simulated_linux_layout = _bool(data.get("simulated_linux_layout", False), f"{context}.simulated_linux_layout")
    scopes = {
        scope_name: _scope_spec(platform_key, scope_name, scope_value, f"{context}.scopes.{scope_name}", simulated_linux_layout=simulated_linux_layout)
        for scope_name, scope_value in scopes_value.items()
    }
    unsupported_scopes = {
        scope_name: _string(reason, f"{context}.unsupported_scopes.{scope_name}")
        for scope_name, reason in unsupported_value.items()
    }
    user_skill = data.get("user_skill")
    project_skill = data.get("project_skill")
    reference_bundles = tuple(
        _reference_bundle(bundle, f"{context}.reference_bundles[{index}]")
        for index, bundle in enumerate(_sequence(data.get("reference_bundles", []), f"{context}.reference_bundles"))
    )
    return model.PlatformSpec(
        name=name,
        user_skill=None if user_skill is None else _string(user_skill, f"{context}.user_skill"),
        project_skill=None if project_skill is None else _string(project_skill, f"{context}.project_skill"),
        scopes=scopes,
        unsupported_scopes=unsupported_scopes,
        uses_packaged_references=_bool(data.get("uses_packaged_references", False if reference_bundles else True), f"{context}.uses_packaged_references"),
        reference_bundles=reference_bundles,
        simulated_linux_layout=simulated_linux_layout,
        universal_uninstall_scopes=_string_list(data.get("universal_uninstall_scopes", []), f"{context}.universal_uninstall_scopes"),
        target_runtime_validation=_platform_runtime_validations(
            data,
            context,
            simulated_linux_layout=simulated_linux_layout,
            shared_runtime_validations=shared_runtime_validations,
        ),
    )


def _universal_uninstall(value: object, context: str) -> model.UniversalUninstallScenarioSpec:
    if isinstance(value, str):
        if value == "user":
            return model.UniversalUninstallScenarioSpec(
                scenario_id="universal-uninstall-user",
                platform_label="multiple",
                scope="user",
                command=("graphify", "uninstall"),
                cwd_root="user_cwd",
                eligible_platform_scope="user",
            )
        if value == "project":
            return model.UniversalUninstallScenarioSpec(
                scenario_id="universal-uninstall-project",
                platform_label="multiple",
                scope="project",
                command=("graphify", "uninstall", "--project"),
                cwd_root="project",
                eligible_platform_scope="project",
            )
        _fail(context, f"unknown compact universal uninstall scope: {value}")
    data = _mapping(value, context)
    cwd_root = _string(data.get("cwd_root"), f"{context}.cwd_root")
    _validate_cwd_root(cwd_root, f"{context}.cwd_root")
    return model.UniversalUninstallScenarioSpec(
        scenario_id=_string(data.get("scenario_id"), f"{context}.scenario_id"),
        platform_label=_string(data.get("platform_label"), f"{context}.platform_label"),
        scope=_string(data.get("scope"), f"{context}.scope"),
        command=_command(data.get("command"), f"{context}.command"),
        cwd_root=cwd_root,
        eligible_platform_scope=_string(data.get("eligible_platform_scope"), f"{context}.eligible_platform_scope"),
        minimum_installed_scenarios=_int(data.get("minimum_installed_scenarios", 2), f"{context}.minimum_installed_scenarios"),
        artifact_subdir=_string(data.get("artifact_subdir", "uninstall"), f"{context}.artifact_subdir"),
        risk_note=_string(data.get("risk_note", "universal uninstall covers Graphify-owned file effects after multiple installs"), f"{context}.risk_note"),
    )


def _disposable_seed(value: object, context: str) -> model.DisposableSeedFile:
    data = _mapping(value, context)
    relative = _string(data.get("relative"), f"{context}.relative")
    _validate_relative(relative, f"{context}.relative")
    return model.DisposableSeedFile(relative, _string(data.get("content"), f"{context}.content"))


def _disposable_artifact(value: object, context: str) -> model.DisposableArtifactScenarioSpec:
    data = _mapping(value, context)
    cwd_root = _string(data.get("cwd_root"), f"{context}.cwd_root")
    _validate_cwd_root(cwd_root, f"{context}.cwd_root")
    disposable_path_root = _string(data.get("disposable_path_root"), f"{context}.disposable_path_root")
    _validate_expected_root(disposable_path_root, f"{context}.disposable_path_root")
    disposable_path_relative = _string(data.get("disposable_path_relative"), f"{context}.disposable_path_relative")
    _validate_relative(disposable_path_relative, f"{context}.disposable_path_relative")
    return model.DisposableArtifactScenarioSpec(
        scenario_id=_string(data.get("scenario_id"), f"{context}.scenario_id"),
        platform_label=_string(data.get("platform_label"), f"{context}.platform_label"),
        scope=_string(data.get("scope"), f"{context}.scope"),
        command=_command(data.get("command"), f"{context}.command"),
        cwd_root=cwd_root,
        artifact_subdir=_string(data.get("artifact_subdir"), f"{context}.artifact_subdir"),
        disposable_path_root=disposable_path_root,
        disposable_path_relative=disposable_path_relative,
        seed_files=tuple(
            _disposable_seed(seed, f"{context}.seed_files[{index}]")
            for index, seed in enumerate(_sequence(data.get("seed_files", []), f"{context}.seed_files"))
        ),
        scope_eligibility=_string_list(data.get("scope_eligibility"), f"{context}.scope_eligibility", allow_empty=False),
        risk_note=_string(data.get("risk_note"), f"{context}.risk_note"),
    )


def load_registry_from_data(data: object, *, source: str = "<data>") -> model.ScenarioRegistry:
    registry = _mapping(data, source)
    version = registry.get("schema_version")
    if version != SCHEMA_VERSION:
        _fail(f"{source}.schema_version", f"expected schema version {SCHEMA_VERSION}")
    platform_order = _string_list(registry.get("platform_order"), f"{source}.platform_order", allow_empty=False)
    platforms_value = _mapping(registry.get("platforms"), f"{source}.platforms")
    loaded_names = tuple(platforms_value.keys())
    if set(platform_order) != set(loaded_names) or tuple(platform_order) != loaded_names:
        _fail(f"{source}.platform_order", "declared platform order must equal loaded platform names")
    shared_runtime_validations = _runtime_validation_policies(
        registry.get("target_runtime_validation_policies", {}),
        f"{source}.target_runtime_validation_policies",
    )

    specs = {
        platform_name: _platform_spec(
            platform_name,
            platforms_value[platform_name],
            f"{source}.platforms.{platform_name}",
            shared_runtime_validations=shared_runtime_validations,
        )
        for platform_name in platform_order
    }
    universal = tuple(
        _universal_uninstall(spec, f"{source}.universal_uninstall_specs[{index}]")
        for index, spec in enumerate(_sequence(registry.get("universal_uninstall_specs", []), f"{source}.universal_uninstall_specs"))
    )
    disposable = tuple(
        _disposable_artifact(spec, f"{source}.disposable_artifact_specs[{index}]")
        for index, spec in enumerate(_sequence(registry.get("disposable_artifact_specs", []), f"{source}.disposable_artifact_specs"))
    )
    loaded = model.ScenarioRegistry(specs, universal_uninstall_specs=universal, disposable_artifact_specs=disposable)
    loaded.validate_roots({root.name for root in DEFAULT_SANDBOX_ROOT_REGISTRY.roots})
    return loaded


def load_registry_from_yaml(path: Path | str = DEFAULT_REGISTRY_PATH) -> model.ScenarioRegistry:
    if yaml is None:
        raise SpecLoaderError("PyYAML is required to load install sandbox YAML specs") from _YAML_IMPORT_ERROR
    registry_path = Path(path)
    with registry_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return load_registry_from_data(data, source=str(registry_path))


def load_default_registry() -> model.ScenarioRegistry:
    return load_registry_from_yaml(DEFAULT_REGISTRY_PATH)
