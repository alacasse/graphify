"""Enumerate the obligations of one declaration, then project the requested keys."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from tools.install_sandbox.contracts.effect_case import (
    CaseKey,
    CaseNonConstruction,
    EffectCaseBuild,
    EffectInstallCase,
    GroupCaseKey,
    SubjectContext,
    build_effect_cases,
    unique_object,
)
from tools.install_sandbox.contracts.effects import EffectSpec, JsonHooksEffect, ToolDeclaration
from tools.install_sandbox.contracts.group_case import GroupNotConstructible
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
        groups = tuple(
            spec
            for case in self.built.cases
            if case.group
            for spec in case.group.participants.values()
        )
        if groups:
            return groups
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
    participant = text(target["participant"]).rsplit(":", 1)
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


def _group_query(
    request: dict[str, object], selected: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    query = fields(request, "operation prepare remove")
    prepare, remove = _operations(query["prepare"]), _operations(query["remove"])
    if any(re.fullmatch(r"[A-Za-z0-9_-]+:[A-Za-z0-9_-]+", p) is None for p in (*prepare, *remove)):
        raise ValueError("Invalid canonical participant name")
    if not set(remove) <= set(prepare):
        raise ValueError("Removed participants must have been prepared")
    if selected not in {p.rsplit(":", 1)[0] for p in prepare}:
        raise ValueError("Selected tool must participate in group preparation")
    return prepare, remove


def _group_participants(
    declarations: dict[str, ToolDeclaration], prepare: tuple[str, ...]
) -> dict[str, EffectSpec]:
    participants: dict[str, EffectSpec] = {}
    for participant in prepare:
        parts = participant.rsplit(":", 1)
        if len(parts) != 2 or parts[0] not in declarations:
            raise ValueError("Unknown prepared participant: " + participant)
        matches = [
            scope.effects
            for scope in declarations[parts[0]].scopes
            if scope.scope == parts[1] and scope.effects is not None
        ]
        if len(matches) != 1:
            raise GroupNotConstructible("Participant scope is unavailable: " + participant)
        participants[participant] = matches[0]
    return participants


def _group_build(
    request: dict[str, object],
    catalog_data: object,
    declaration: ToolDeclaration,
    context: SubjectContext,
) -> EffectCaseBuild:
    from tools.install_sandbox.contracts.group_case import build_group_case

    prepare, remove = _group_query(request, declaration.tool)
    if not isinstance(catalog_data, dict):
        raise ValueError("Expected archived catalog sources")
    catalog = cast(dict[str, object], catalog_data)
    expected_tools = {p.rsplit(":", 1)[0] for p in prepare} - {declaration.tool}
    if set(catalog) != expected_tools:
        raise ValueError("Archived catalog does not match requested participants")
    declarations = {declaration.tool: declaration}
    for tool, source in catalog.items():
        loaded = EffectSpecReader().from_yaml(text(source))
        if loaded.tool != tool or tool == declaration.tool:
            raise ValueError("Catalog tool identity does not match filename")
        declarations[tool] = loaded
    try:
        participants = _group_participants(declarations, prepare)
        group = build_group_case(participants, prepare, remove, context, declaration.tool)
        built = EffectCaseBuild((group,))
    except GroupNotConstructible as exc:
        built = EffectCaseBuild(
            (
                CaseNonConstruction(
                    GroupCaseKey(
                        declaration.tool,
                        "group",
                        "group-uninstall",
                        prepare=prepare,
                        remove=remove,
                    ),
                    "unconstructible",
                    str(exc),
                ),
            )
        )
    return built


def define_campaign(manifest: object, checkout: Path) -> CampaignDefinition:
    if not isinstance(manifest, dict):
        raise ValueError("Expected campaign definition object")
    data = fields(
        {"catalog": {}, **cast(dict[str, object], manifest)},
        "format spec context prepare_only operations request catalog",
    )
    if (
        data["format"] not in {"tool-campaign-v1", "tool-campaign-v2"}
        or type(data["prepare_only"]) is not bool
    ):
        raise ValueError("Unsupported campaign definition")
    if data["format"] == "tool-campaign-v1" and (
        data["catalog"]
        or (
            isinstance(data["request"], dict)
            and cast(dict[str, object], data["request"]).get("operation") == "group-uninstall"
        )
    ):
        raise ValueError("Grouped campaigns require tool-campaign-v2")
    prepare_only = data["prepare_only"]
    declaration = EffectSpecReader().from_yaml(text(data["spec"]))
    context = SubjectContext.from_data(data["context"])
    operations = None if data["operations"] is None else _operations(data["operations"])
    request = cast(dict[str, object] | None, data["request"])
    if operations is not None and request is not None:
        raise ValueError("--case and --request cannot be combined")
    if prepare_only and (
        request is not None or operations is not None or context.package_root is None
    ):
        raise ValueError("--prepare-only requires a packaged subject and cannot include a filter")
    entries = () if prepare_only else _inventory(declaration, context)
    if isinstance(request, dict) and request.get("operation") == "group-uninstall":
        built = _group_build(request, data["catalog"], declaration, context)
    else:
        built = EffectCaseBuild(_select(entries, declaration, operations, request))
    selected = {entry.key for entry in built.entries}
    omitted = tuple(entry.key for entry in entries if entry.key not in selected)
    transports = tuple(case.to_json() for case in built.cases)
    for transport in transports:
        transport.encode("utf-8")
    return CampaignDefinition(
        checkout, context, prepare_only, built, transports, declaration, data, omitted, operations
    )


def _catalog_sources(
    spec_file: Path, spec_source: str, request: dict[str, object] | None
) -> dict[str, str]:
    catalog: dict[str, str] = {}
    if isinstance(request, dict) and request.get("operation") == "group-uninstall":
        selected = EffectSpecReader().from_yaml(spec_source).tool
        prepare, _ = _group_query(request, selected)
        for participant in prepare:
            tool = participant.rsplit(":", 1)[0]
            if tool == selected or tool in catalog:
                continue
            if not tool or Path(tool).name != tool or tool in {".", ".."}:
                raise ValueError("Invalid canonical tool name")
            catalog_file = (spec_file.parent / (tool + ".yaml")).resolve(strict=True)
            if catalog_file.parent != spec_file.parent.resolve(strict=True):
                raise ValueError("Catalog source escapes selected catalog directory")
            catalog[tool] = catalog_file.read_text(encoding="utf-8")
    return catalog


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
    request = cast(dict[str, object] | None, request)
    spec_source = spec_file.read_text(encoding="utf-8")
    catalog = _catalog_sources(spec_file, spec_source, request)
    return define_campaign(
        {
            "format": "tool-campaign-v2",
            "catalog": catalog,
            "spec": spec_source,
            "context": json.loads(
                subject_context_file.read_text(encoding="utf-8"), object_pairs_hook=unique_object
            ),
            "prepare_only": prepare_only,
            "operations": None if requested_cases is None else list(requested_cases),
            "request": cast(object, request),
        },
        subject,
    )
