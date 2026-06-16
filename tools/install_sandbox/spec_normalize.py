from __future__ import annotations

from typing import Any

try:
    from .expected_effects import effect_type_name
    from . import platform_specs as specs
except ImportError:  # pragma: no cover - direct script import fallback
    from expected_effects import effect_type_name  # type: ignore[no-redef]
    import platform_specs as specs  # type: ignore[no-redef]


def _command(command: tuple[str, ...] | None) -> list[str] | None:
    return None if command is None else list(command)


def _text_expectation(expectation: specs.TextExpectation) -> dict[str, object]:
    return {
        "preserve_user_content": expectation.preserve_user_content,
        "repair_stale_graphify_section": expectation.repair_stale_graphify_section,
        "remove_graphify_section_on_uninstall": expectation.remove_graphify_section_on_uninstall,
        "require_user_content_on_uninstall": expectation.require_user_content_on_uninstall,
    }


def _json_hook(expectation: specs.JsonHookExpectation) -> dict[str, object]:
    return {
        "event": expectation.event,
        "matcher": expectation.matcher,
        "detail_name": expectation.detail_name,
        "required_fragments": list(expectation.required_fragments),
    }


def _json_plugin(expectation: specs.JsonPluginExpectation) -> dict[str, object]:
    return {
        "expected_entry": expectation.expected_entry,
        "allow_file_uri": expectation.allow_file_uri,
        "detail_name": expectation.detail_name,
    }


def _json_expectation(expectation: specs.JsonExpectation | None) -> dict[str, object] | None:
    if expectation is None:
        return None
    return {
        "schema_name": expectation.schema_name,
        "hooks": [_json_hook(hook) for hook in expectation.hooks],
        "plugin": _json_plugin(expectation.plugin) if expectation.plugin is not None else None,
    }


def _skill_sidecar(expectation: specs.SkillSidecarExpectation | None) -> dict[str, object] | None:
    if expectation is None:
        return None
    return {
        "version_name": expectation.version_name,
        "references_dir": expectation.references_dir,
        "references_tmp_dir": expectation.references_tmp_dir,
        "reference_pointer_pattern": expectation.reference_pointer_pattern,
    }


def _generated_file_expectation(expectation: specs.GeneratedFileExpectation) -> dict[str, object]:
    return {
        "relative_substrings": list(expectation.relative_substrings),
        "text_suffixes": list(expectation.text_suffixes),
        "content_markers": list(expectation.content_markers),
        "include_user_content_sentinel": expectation.include_user_content_sentinel,
        "max_text_bytes": expectation.max_text_bytes,
    }


def _expected_path(path: specs.ExpectedPath) -> dict[str, object]:
    return {
        "effect_type": effect_type_name(path),
        "root": path.root,
        "relative": path.relative,
        "kind": path.kind,
        "content_kind": path.content_kind,
        "marker": path.marker,
        "remove_on_uninstall": path.remove_on_uninstall,
        "text_expectation": _text_expectation(path.text_expectation),
        "json_expectation": _json_expectation(path.json_expectation),
        "skill_sidecar_expectation": _skill_sidecar(path.skill_sidecar_expectation),
    }


def _install_variant(variant: specs.InstallCommandVariant) -> dict[str, object]:
    return {"label": variant.label, "command": list(variant.command)}


def _scope_spec(scope: specs.ScopeSpec) -> dict[str, object]:
    return {
        "install_command": list(scope.install_command),
        "uninstall_command": _command(scope.uninstall_command),
        "cwd_root": scope.cwd_root,
        "expected": [_expected_path(path) for path in scope.expected],
        "risk_notes": list(scope.risk_notes),
        "equivalent_install_command": _command(scope.equivalent_install_command),
        "install_variants": [_install_variant(variant) for variant in scope.install_variants],
        "allowed_roots": list(scope.allowed_roots),
        "generated_file_expectation": _generated_file_expectation(scope.generated_file_expectation),
    }


def _reference_bundle(bundle: specs.ReferenceBundle) -> dict[str, object]:
    return {"name": bundle.name, "required_package_relative": bundle.required_package_relative}


def _runtime_validation(validation: specs.TargetRuntimeValidationSpec) -> dict[str, object]:
    return {
        "section_title": validation.section_title,
        "status": validation.status,
        "strategy": validation.strategy,
        "targets": list(validation.targets),
        "notes": list(validation.notes),
        "evidence_path": validation.evidence_path,
    }


def _platform_spec(platform: specs.PlatformSpec) -> dict[str, object]:
    return {
        "name": platform.name,
        "user_skill": platform.user_skill,
        "project_skill": platform.project_skill,
        "uses_packaged_references": platform.uses_packaged_references,
        "simulated_linux_layout": platform.simulated_linux_layout,
        "scopes": {scope: _scope_spec(platform.scopes[scope]) for scope in sorted(platform.scopes)},
        "unsupported_scopes": dict(sorted(platform.unsupported_scopes.items())),
        "reference_bundles": [_reference_bundle(bundle) for bundle in platform.reference_bundles],
        "universal_uninstall_scopes": list(platform.universal_uninstall_scopes),
        "target_runtime_validation": [_runtime_validation(validation) for validation in platform.target_runtime_validation],
    }


def normalize_registry(registry: specs.ScenarioRegistry) -> dict[str, Any]:
    """Return deterministic primitive data for registry equivalence tests."""

    return {
        "platforms": {name: _platform_spec(registry.specs[name]) for name in registry.platform_names},
    }
