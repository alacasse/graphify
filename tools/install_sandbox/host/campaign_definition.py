"""Enumerate the obligations of one declaration, then project the requested keys."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from tools.install_sandbox.contracts.effect_case import (
    CaseKey,
    CaseNonConstruction,
    EffectCaseBuild,
    EffectInstallCase,
    SubjectContext,
    build_effect_cases,
    unique_object,
)
from tools.install_sandbox.contracts.effects import EffectSpec, JsonHooksEffect, ToolDeclaration
from tools.install_sandbox.contracts.spec import fields, text
from tools.install_sandbox.host.effect_reader import EffectSpecReader

Entry = EffectInstallCase | CaseNonConstruction


@dataclass(frozen=True)
class CampaignDefinition:
    subject_checkout: Path
    context: SubjectContext
    prepare_only: bool
    built: EffectCaseBuild
    transports: tuple[str, ...]
    declaration: ToolDeclaration
    manifest: dict[str, object]
    omitted: tuple[CaseKey, ...]
    requested_cases: tuple[str, ...] | None

    @property
    def partial(self) -> bool:
        return self.requested_cases is not None or self.manifest["request"] is not None

    @property
    def effects(self) -> tuple[EffectSpec, ...]:
        selected = {case.scope for case in self.built.cases}
        return tuple(
            scope.effects
            for scope in self.declaration.scopes
            if scope.effects is not None and (self.prepare_only or scope.scope in selected)
        )


def _operations(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("Case selection must be a non-empty list")
    names = tuple(text(name) for name in cast(list[object], value))
    if len(frozenset(names)) != len(names):
        raise ValueError(f"Duplicate case name(s): {names}")
    return names


def _inventory(declaration: ToolDeclaration, context: SubjectContext) -> tuple[Entry, ...]:
    entries: list[Entry] = []
    for scope in declaration.scopes:
        if scope.effects is None:
            assert (
                scope.classification in ("unconstructible", "not_applicable")
                and scope.reason is not None
            )
            entries.append(
                CaseNonConstruction(
                    CaseKey(declaration.tool, scope.scope, "scope"),
                    scope.classification,
                    scope.reason,
                )
            )
        else:
            entries.extend(build_effect_cases(scope.effects, context, declaration.tool).entries)
    return tuple(entries)


def _scope_projection(declaration: ToolDeclaration, request: object) -> set[str]:
    names = set(_operations(fields(request, "scopes")["scopes"]))
    unknown = names - {scope.scope for scope in declaration.scopes}
    if unknown:
        raise ValueError("Unknown scope(s): " + ", ".join(sorted(unknown)))
    return names


def _target_key(request: object) -> CaseKey:
    data = fields(request, "operation target")
    operation = text(data["operation"])
    operation = "duplicate-json-hook" if operation == "duplicate" else operation
    if operation not in {"duplicate-json-hook", "missing-json-hook", "altered-json-hook"}:
        raise ValueError("Unknown target operation: " + text(data["operation"]))
    target = fields(data["target"], "participant effect_id member")
    participant = text(target["participant"]).split(":")
    if len(participant) != 2 or not all(participant):
        raise ValueError("Expected participant tool:scope")
    return CaseKey(
        participant[0], participant[1], operation, text(target["effect_id"]), text(target["member"])
    )


def _select(
    entries: tuple[Entry, ...],
    declaration: ToolDeclaration,
    operations: tuple[str, ...] | None,
    request: object,
) -> tuple[Entry, ...]:
    if operations is not None:
        known = {entry.name for entry in entries}
        unknown = set(operations) - known
        if unknown:
            raise ValueError("Unknown case name(s): " + ", ".join(sorted(unknown)))
        return tuple(entry for entry in entries if entry.name in operations)
    if request is None:
        return entries
    if isinstance(request, dict) and "scopes" in request:
        scopes = _scope_projection(declaration, cast(dict[str, object], request))
        return tuple(entry for entry in entries if entry.key.scope in scopes)
    key = _target_key(cast(object, request))
    matches = tuple(entry for entry in entries if entry.key == key)
    return matches or (_missing_target(declaration, key),)


def _missing_target(declaration: ToolDeclaration, key: CaseKey) -> CaseNonConstruction:
    for scope in declaration.scopes:
        if (declaration.tool, scope.scope) != (key.tool, key.scope) or scope.effects is None:
            continue
        for effect in scope.effects.effects:
            if effect.effect_id == key.effect_id and not isinstance(effect, JsonHooksEffect):
                return CaseNonConstruction(
                    key, "not_applicable", "Effect does not declare JSON hooks"
                )
    return CaseNonConstruction(key, "unconstructible", "Requested hook is unavailable")


def define_campaign(manifest: object, checkout: Path) -> CampaignDefinition:
    data = fields(manifest, "format spec context prepare_only operations request")
    if data["format"] != "tool-campaign-v1" or type(data["prepare_only"]) is not bool:
        raise ValueError("Unsupported campaign definition")
    prepare_only = data["prepare_only"]
    declaration = EffectSpecReader().from_yaml(text(data["spec"]))
    context = SubjectContext.from_data(data["context"])
    operations = None if data["operations"] is None else _operations(data["operations"])
    request = data["request"]
    if operations is not None and request is not None:
        raise ValueError("--case and --request cannot be combined")
    if prepare_only and (
        request is not None or operations is not None or context.package_root is None
    ):
        raise ValueError("--prepare-only requires a packaged subject and cannot include a filter")
    entries = () if prepare_only else _inventory(declaration, context)
    built = EffectCaseBuild(_select(entries, declaration, operations, request))
    selected = {entry.key for entry in built.entries}
    omitted = tuple(entry.key for entry in entries if entry.key not in selected)
    transports = tuple(case.to_json() for case in built.cases)
    for transport in transports:
        transport.encode("utf-8")
    return CampaignDefinition(
        checkout, context, prepare_only, built, transports, declaration, data, omitted, operations
    )


def load_campaign_definition(
    *,
    spec_file: Path,
    subject_context_file: Path,
    subject_checkout: Path,
    prepare_only: bool = False,
    requested_cases: tuple[str, ...] | None = None,
    request_file: Path | None = None,
) -> CampaignDefinition:
    subject = subject_checkout.expanduser().resolve(strict=True)
    if not subject.is_dir():
        raise ValueError("subject_checkout must be a directory")
    request = None
    if request_file is not None:
        request = json.loads(
            request_file.read_text(encoding="utf-8"), object_pairs_hook=unique_object
        )
        if not isinstance(request, dict):
            raise ValueError("--request requires a JSON object")
    return define_campaign(
        {
            "format": "tool-campaign-v1",
            "spec": spec_file.read_text(encoding="utf-8"),
            "context": json.loads(
                subject_context_file.read_text(encoding="utf-8"), object_pairs_hook=unique_object
            ),
            "prepare_only": prepare_only,
            "operations": None if requested_cases is None else list(requested_cases),
            "request": cast(object, request),
        },
        subject,
    )
