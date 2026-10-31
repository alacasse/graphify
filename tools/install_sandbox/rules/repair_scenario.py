"""Prepare a bounded mutation and independent transition expectations without effects."""

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import ClassVar

from tools.install_sandbox.contracts.bound_mutation import BoundMarkdownMutation
from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.effects import MarkdownSectionEffect
from tools.install_sandbox.contracts.expectations import (
    Expectation,
    ExpectationSet,
)
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import VerificationResult
from tools.install_sandbox.rules.comparison import markdown_byte_parts
from tools.install_sandbox.rules.effect_verifier import EffectVerifier
from tools.install_sandbox.rules.expectation_builder import (
    preservation_baseline,
    retained_bytes,
)


@dataclass(frozen=True)
class PreparationBlocked:
    reason: str


@dataclass(frozen=True)
class PreparationPlan:
    operation: BoundMarkdownMutation
    after_preparation_expectations: ExpectationSet
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


@dataclass(frozen=True)
class MarkdownRepairScenario(ABC):
    """Own the applicable scenario and authorize binding to validated facts."""

    case: EffectInstallCase
    sources: FilesystemSnapshot
    provenance: ClassVar[str]

    @abstractmethod
    def mutation(
        self, parts: tuple[bytes, bytes, bytes], document: bytes
    ) -> tuple[int, int, bytes]: ...

    @abstractmethod
    def expected_preparation(self) -> bytes: ...

    def bind(
        self,
        first_after: FilesystemSnapshot,
        observation_ref: str,
        validation: VerificationResult,
        installed: ExpectationSet,
        case_bytes: bytes,
    ) -> PreparationPlan | PreparationBlocked:
        try:
            if EffectInstallCase.from_json(case_bytes.decode("utf-8")) != self.case:
                raise ValueError("Archived case differs from the unchanged case definition")
            if installed.phase != "install" or installed.roots is None:
                raise ValueError("Preparation requires bound first-install expectations")
            actual = EffectVerifier().verify(installed, first_after)
            if not _conforming(validation) or not _conforming(actual) or validation != actual:
                raise ValueError("Preparation requires a conforming verdict for this observation")
            return self._build_bound(first_after, observation_ref, installed, case_bytes)
        except (ValueError, UnicodeError, StopIteration) as exc:
            return PreparationBlocked(str(exc))

    def _build_bound(
        self,
        first_after: FilesystemSnapshot,
        observation_ref: str,
        installed: ExpectationSet,
        case_bytes: bytes,
    ) -> PreparationPlan:
        case, sources = self.case, self.sources
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
        start, end, replacement = self.mutation(parts, document)
        expected = self.expected_preparation()
        removed = Expectation(
            "file",
            destination.root,
            destination.path,
            "intermediate",
            self.provenance,
            expected,
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
        operation = BoundMarkdownMutation(
            hashlib.sha256(case_bytes).hexdigest(),
            observation_ref,
            destination,
            hashlib.sha256(document).hexdigest(),
            start,
            end,
            replacement,
        )
        return PreparationPlan(
            operation,
            _transition(installed, first_after, removed, "intermediate"),
            _transition(installed, first_after, repaired, "reinstall"),
        )

    @classmethod
    def from_case(
        cls, case: EffectInstallCase, sources: FilesystemSnapshot
    ) -> "MarkdownRepairScenario":
        preparation = case.intermediate_preparation
        if preparation is None:
            raise ValueError("Case has no intermediate preparation")
        if preparation.kind == "missing-markdown-section":
            return MissingSectionScenario(case, sources)
        if preparation.kind == "altered-markdown-body":
            if not isinstance(preparation.body, bytes):
                raise ValueError("Altered scenario requires body bytes")
            return AlteredBodyScenario(case, sources, preparation.body)
        raise ValueError("Unsupported Markdown scenario")


@dataclass(frozen=True)
class MissingSectionScenario(MarkdownRepairScenario):
    provenance = "case:fragments"

    def mutation(self, parts: tuple[bytes, bytes, bytes], document: bytes):
        return len(parts[0]), len(parts[0]) + len(parts[1]), b""

    def expected_preparation(self) -> bytes:
        preparation = self.case.intermediate_preparation
        assert preparation is not None
        return preparation.before + preparation.after


@dataclass(frozen=True)
class AlteredBodyScenario(MarkdownRepairScenario):
    provenance = "case:fragments+marker+body"
    altered_body: bytes

    def mutation(self, parts: tuple[bytes, bytes, bytes], document: bytes):
        preparation = self.case.intermediate_preparation
        assert preparation is not None
        header = preparation.marker.encode("utf-8") + b"\n"
        if not parts[1].startswith(header):
            raise ValueError("Section has no applicable LF-terminated body")
        start, end = len(parts[0]) + len(header), len(parts[0]) + len(parts[1])
        if start >= end or document[start:end] == self.altered_body:
            raise ValueError("Preparation must change an applicable section body")
        return start, end, self.altered_body

    def expected_preparation(self) -> bytes:
        preparation = self.case.intermediate_preparation
        assert preparation is not None
        return (
            preparation.before
            + preparation.marker.encode("utf-8")
            + b"\n"
            + self.altered_body
            + preparation.after
        )
