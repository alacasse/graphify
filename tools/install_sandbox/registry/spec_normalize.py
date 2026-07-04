from __future__ import annotations

from typing import Any

from ..surfaces.install_surface_models import (
    InstallSurface,
    JsonExpectation,
    JsonHookExpectation,
    JsonPluginExpectation,
    SkillSidecarExpectation,
    TextExpectation,
    effect_type_name,
)
from ..targets.install_target_catalog import InstallTargetCatalog
from ..targets.install_target_models import (
    GeneratedFileExpectation,
    InstallCommandVariant,
    InstallTargetSpec,
    ReferenceBundle,
    ScopeSpec,
    TargetRuntimeValidationSpec,
)


def _command(command: tuple[str, ...] | None) -> list[str] | None:
    return None if command is None else list(command)


def _text_expectation(expectation: TextExpectation) -> dict[str, object]:
    return {
        "preserve_user_content": expectation.preserve_user_content,
        "repair_stale_graphify_section": expectation.repair_stale_graphify_section,
        "remove_graphify_section_on_uninstall": expectation.remove_graphify_section_on_uninstall,
        "require_user_content_on_uninstall": expectation.require_user_content_on_uninstall,
    }


def _json_hook(expectation: JsonHookExpectation) -> dict[str, object]:
    return {
        "event": expectation.event,
        "matcher": expectation.matcher,
        "detail_name": expectation.detail_name,
        "required_fragments": list(expectation.required_fragments),
    }


def _json_plugin(expectation: JsonPluginExpectation) -> dict[str, object]:
    return {
        "expected_entry": expectation.expected_entry,
        "allow_file_uri": expectation.allow_file_uri,
        "detail_name": expectation.detail_name,
    }


def _json_expectation(expectation: JsonExpectation | None) -> dict[str, object] | None:
    if expectation is None:
        return None
    return {
        "schema_name": expectation.schema_name,
        "hooks": [_json_hook(hook) for hook in expectation.hooks],
        "plugin": _json_plugin(expectation.plugin) if expectation.plugin is not None else None,
    }


def _skill_sidecar(expectation: SkillSidecarExpectation | None) -> dict[str, object] | None:
    if expectation is None:
        return None
    return {
        "version_name": expectation.version_name,
        "references_dir": expectation.references_dir,
        "references_tmp_dir": expectation.references_tmp_dir,
        "reference_pointer_pattern": expectation.reference_pointer_pattern,
    }


def _generated_file_expectation(expectation: GeneratedFileExpectation) -> dict[str, object]:
    return {
        "relative_substrings": list(expectation.relative_substrings),
        "text_suffixes": list(expectation.text_suffixes),
        "content_markers": list(expectation.content_markers),
        "include_user_content_sentinel": expectation.include_user_content_sentinel,
        "max_text_bytes": expectation.max_text_bytes,
    }


def _install_surface(surface: InstallSurface) -> dict[str, object]:
    return {
        "effect_type": effect_type_name(surface),
        "root": surface.root,
        "relative": surface.relative,
        "kind": surface.kind,
        "content_kind": surface.content_kind,
        "marker": surface.marker,
        "remove_on_uninstall": surface.remove_on_uninstall,
        "text_expectation": _text_expectation(surface.text_expectation),
        "json_expectation": _json_expectation(surface.json_expectation),
        "skill_sidecar_expectation": _skill_sidecar(surface.skill_sidecar_expectation),
    }


def _install_variant(variant: InstallCommandVariant) -> dict[str, object]:
    return {"label": variant.label, "command": list(variant.command)}


def _scope_spec(scope: ScopeSpec) -> dict[str, object]:
    effects = [_install_surface(surface) for surface in scope.expected]
    return {
        "install_command": list(scope.install_command),
        "uninstall_command": _command(scope.uninstall_command),
        "cwd_root": scope.cwd_root,
        "effects": effects,
        "risk_notes": list(scope.risk_notes),
        "equivalent_install_command": _command(scope.equivalent_install_command),
        "install_variants": [_install_variant(variant) for variant in scope.install_variants],
        "allowed_roots": list(scope.allowed_roots),
        "generated_file_expectation": _generated_file_expectation(scope.generated_file_expectation),
    }


def _reference_bundle(bundle: ReferenceBundle) -> dict[str, object]:
    return {"name": bundle.name, "required_package_relative": bundle.required_package_relative}


def _runtime_validation(validation: TargetRuntimeValidationSpec) -> dict[str, object]:
    return {
        "section_title": validation.section_title,
        "status": validation.status,
        "strategy": validation.strategy,
        "targets": list(validation.targets),
        "notes": list(validation.notes),
        "evidence_path": validation.evidence_path,
    }


def _target_spec(target: InstallTargetSpec) -> dict[str, object]:
    return {
        "name": target.name,
        "display_name": target.display_name,
        "target_kind": target.target_kind,
        "user_skill": target.user_skill,
        "project_skill": target.project_skill,
        "uses_packaged_references": target.uses_packaged_references,
        "simulated_linux_layout": target.simulated_linux_layout,
        "scopes": {scope: _scope_spec(target.scopes[scope]) for scope in sorted(target.scopes)},
        "unsupported_scopes": dict(sorted(target.unsupported_scopes.items())),
        "reference_bundles": [_reference_bundle(bundle) for bundle in target.reference_bundles],
        "universal_uninstall_scopes": list(target.universal_uninstall_scopes),
        "target_runtime_validation": [_runtime_validation(validation) for validation in target.target_runtime_validation],
    }


def normalize_registry(registry: InstallTargetCatalog) -> dict[str, Any]:
    """Return deterministic primitive data for registry equivalence tests."""

    return {
        "targets": {name: _target_spec(registry.specs[name]) for name in registry.target_names},
    }
