"""Prepare a bounded mutation and independent transition expectations without effects."""

import hashlib
from dataclasses import dataclass, replace

from tools.install_sandbox.container.comparison import markdown_byte_parts
from tools.install_sandbox.container.effect_verifier import EffectVerifier
from tools.install_sandbox.container.environment import FilesystemSnapshot
from tools.install_sandbox.container.expectation_builder import (
    preservation_baseline,
    retained_bytes,
)
from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.effects import MarkdownSectionEffect
from tools.install_sandbox.contracts.expectations import Expectation, ExpectationSet
from tools.install_sandbox.contracts.intermediate import PreparedByteRange
from tools.install_sandbox.contracts.results import VerificationResult


@dataclass(frozen=True)
class PreparationBlocked:
    reason: str


@dataclass(frozen=True)
class PreparationPlan:
    operation: PreparedByteRange
    after_removal_expectations: ExpectationSet
    second_install_expectations: ExpectationSet


def _conforming(validation: VerificationResult) -> bool:
    return validation.complete and not validation.mismatches and not validation.obstacles


def _transition(
    installed: ExpectationSet,
    first_after: FilesystemSnapshot,
    replacement: Expectation,
    phase: str,
) -> ExpectationSet:
    constraints = tuple(
        replacement
        if (item.root, item.path) == (replacement.root, replacement.path)
        else replace(item, phase=phase)
        for item in installed.expectations
    )
    return replace(
        installed,
        phase=phase,
        expectations=constraints,
        baseline=preservation_baseline(first_after, phase),
        allowed_changes=((replacement.root, replacement.path),),
    )


def _plan(
    case: EffectInstallCase,
    sources: FilesystemSnapshot,
    first_after: FilesystemSnapshot,
    observation_ref: str,
    installed: ExpectationSet,
    case_bytes: bytes,
) -> PreparationPlan:
    preparation = case.intermediate_preparation
    if preparation is None:
        raise ValueError("Case has no intermediate preparation")
    destination = preparation.destination
    document = retained_bytes(first_after, destination.root, destination.path)
    parts = markdown_byte_parts(document, preparation.marker)
    if parts is None:
        raise ValueError("Validated document has no unique section")
    effect = next(
        e
        for e in case.effects.effects
        if isinstance(e, MarkdownSectionEffect) and e.destination == destination
    )
    source = retained_bytes(sources, "subject", effect.source)
    if document != preparation.before + source + preparation.after:
        raise ValueError("First installation differs from exact retained fragments and source")
    exterior = preparation.before + preparation.after
    removed = Expectation(
        "file", destination.root, destination.path, "intermediate", "case:fragments", exterior
    )
    repaired = Expectation(
        "markdown-composed",
        destination.root,
        destination.path,
        "reinstall",
        "case:fragments+source",
        source,
        exterior,
        preparation.marker,
    )
    operation = PreparedByteRange(
        hashlib.sha256(case_bytes).hexdigest(),
        observation_ref,
        destination,
        hashlib.sha256(document).hexdigest(),
        len(parts[0]),
        len(parts[0]) + len(parts[1]),
    )
    return PreparationPlan(
        operation,
        _transition(installed, first_after, removed, "intermediate"),
        _transition(installed, first_after, repaired, "reinstall"),
    )


def prepare_intermediate(
    case: EffectInstallCase,
    sources: FilesystemSnapshot,
    first_after: FilesystemSnapshot,
    observation_ref: str,
    validation: VerificationResult,
    installed: ExpectationSet,
    case_bytes: bytes,
) -> PreparationPlan | PreparationBlocked:
    """Require a conforming verdict for this very observation before planning."""
    try:
        if EffectInstallCase.from_json(case_bytes.decode("utf-8")) != case:
            raise ValueError("Archived case differs from the unchanged case definition")
        if installed.phase != "install" or installed.roots is None:
            raise ValueError("Preparation requires bound first-install expectations")
        actual = EffectVerifier().verify(installed, first_after)
        if not _conforming(validation) or not _conforming(actual) or validation != actual:
            raise ValueError("Preparation requires a conforming verdict for this observation")
        return _plan(case, sources, first_after, observation_ref, installed, case_bytes)
    except (ValueError, UnicodeError, StopIteration) as exc:
        return PreparationBlocked(str(exc))
