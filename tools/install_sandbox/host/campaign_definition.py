"""Read and construct a campaign without allocating evidence or invoking a runtime."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from tools.install_sandbox.contracts.effect_case import (
    EffectCaseBuild,
    GroupInstall,
    SubjectContext,
    build_effect_cases,
    unique_object,
)
from tools.install_sandbox.contracts.effects import EffectSpec
from tools.install_sandbox.host.effect_reader import EffectSpecReader


@dataclass(frozen=True)
class CampaignDefinition:
    subject_checkout: Path
    effects: EffectSpec
    context: SubjectContext
    prepare_only: bool
    built: EffectCaseBuild
    transports: tuple[str, ...]
    requested_cases: tuple[str, ...] | None = None
    omitted_cases: tuple[str, ...] = ()


def load_campaign_definition(
    *,
    spec_file: Path,
    subject_context_file: Path,
    subject_checkout: Path,
    prepare_only: bool = False,
    requested_cases: tuple[str, ...] | None = None,
) -> CampaignDefinition:
    """Validate inputs and retain the exact case transports for later materialization."""
    _validate_selection(requested_cases, prepare_only)
    subject = subject_checkout.expanduser().resolve(strict=True)
    if not subject.is_dir():
        raise ValueError("subject_checkout must be a directory")
    effects, group_installs = EffectSpecReader().read_campaign(spec_file)
    context = _read_context(subject_context_file, group_installs)
    if prepare_only and context.package_root is None:
        raise ValueError("Preparation-only requires a package root and exact subject revision")
    built = (
        EffectCaseBuild(())
        if prepare_only and group_installs is None
        else build_effect_cases(effects, context, context.identity)
    )
    if prepare_only:
        built = EffectCaseBuild(())
    omitted: tuple[str, ...] = ()
    if requested_cases is not None:
        catalogue = {entry.name for entry in built.entries}
        unknown = set(requested_cases) - catalogue
        if unknown:
            raise ValueError("Unknown case name(s): " + ", ".join(sorted(unknown)))
        omitted = tuple(entry.name for entry in built.entries if entry.name not in requested_cases)
        built = EffectCaseBuild(tuple(e for e in built.entries if e.name in requested_cases))
    transports = tuple(case.to_json() for case in built.cases)
    for transport in transports:
        transport.encode("utf-8")
    return CampaignDefinition(
        subject, effects, context, prepare_only, built, transports, requested_cases, omitted
    )


def _validate_selection(requested_cases: tuple[str, ...] | None, prepare_only: bool) -> None:
    if requested_cases is not None:
        if prepare_only:
            raise ValueError("--case cannot be combined with --prepare-only")
        if not requested_cases:
            raise ValueError("Case selection must be non-empty")
        duplicates = {name for name in requested_cases if requested_cases.count(name) > 1}
        if duplicates:
            raise ValueError("Duplicate case name(s): " + ", ".join(sorted(duplicates)))


def _read_context(path: Path, group_installs: tuple[GroupInstall, ...] | None) -> SubjectContext:
    context_data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    if not isinstance(context_data, dict):
        raise ValueError("Expected subject context object")
    context_data = cast(dict[str, object], context_data)
    if (
        context_data.get("group_installs") is not None
        or "group_install_invocations" in context_data
    ):
        raise ValueError("Grouped installations must be declared only by the composition manifest")
    if group_installs is not None:
        first_invocation = list(group_installs[0].invocation)
        if "invocation" in context_data and context_data["invocation"] != first_invocation:
            raise ValueError("Subject invocation contradicts first composition member")
        context_data["invocation"] = first_invocation
        context_data["group_installs"] = [install.to_data() for install in group_installs]
    return SubjectContext.from_data(context_data)
