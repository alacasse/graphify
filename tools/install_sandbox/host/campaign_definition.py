"""Read and construct a campaign without allocating evidence or invoking a runtime."""

import json
from dataclasses import dataclass
from pathlib import Path

from tools.install_sandbox.contracts.effect_case import (
    EffectCaseBuild,
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


def load_campaign_definition(
    *,
    spec_file: Path,
    subject_context_file: Path,
    subject_checkout: Path,
    prepare_only: bool = False,
) -> CampaignDefinition:
    """Validate inputs and retain the exact case transports for later materialization."""
    subject = subject_checkout.expanduser().resolve(strict=True)
    if not subject.is_dir():
        raise ValueError("subject_checkout must be a directory")
    effects = EffectSpecReader().read(spec_file)
    context = SubjectContext.from_data(
        json.loads(
            subject_context_file.read_text(encoding="utf-8"), object_pairs_hook=unique_object
        )
    )
    if prepare_only and context.package_root is None:
        raise ValueError("Preparation-only requires a package root and exact subject revision")
    built = (
        EffectCaseBuild(())
        if prepare_only
        else build_effect_cases(effects, context, context.identity)
    )
    transports = tuple(case.to_json() for case in built.cases)
    for transport in transports:
        transport.encode("utf-8")
    return CampaignDefinition(subject, effects, context, prepare_only, built, transports)
