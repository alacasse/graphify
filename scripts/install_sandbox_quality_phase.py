"""Single owner for install-sandbox gate phase policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class GatePhase(Enum):
    GATE_INSTALLATION = "gate installation"
    REPLACEMENT_CONSTRUCTION = "replacement construction"
    ATOMIC_CUTOVER = "atomic cutover"


class EvidencePolicy(Enum):
    NOT_APPLICABLE = "not applicable"
    REQUIRED = "required"
    PROHIBITED = "prohibited"


class CoveragePolicy(Enum):
    NOT_APPLICABLE = "not applicable"
    LEGACY_EXCLUSIONS = "exact legacy exclusions"
    NO_EXCLUSIONS = "no exclusions"


class DockerClassifier(Enum):
    LEGACY = "legacy"
    REPLACEMENT = "replacement"


class ProductFindingPolicy(Enum):
    BLOCK = "block"
    EXACT_LEGACY_ADVISORY = "exact legacy advisory"


@dataclass(frozen=True)
class GatePhasePolicy:
    phase: GatePhase
    replacement_evidence: EvidencePolicy
    behavioral_evidence: EvidencePolicy
    coverage: CoveragePolicy
    docker_classifier: DockerClassifier
    product_findings: ProductFindingPolicy


class HasGatePhase(Protocol):
    @property
    def phase(self) -> GatePhase:
        """Return the closed repository phase."""

        ...


_PHASE_POLICIES = {
    GatePhase.GATE_INSTALLATION: GatePhasePolicy(
        phase=GatePhase.GATE_INSTALLATION,
        replacement_evidence=EvidencePolicy.NOT_APPLICABLE,
        behavioral_evidence=EvidencePolicy.PROHIBITED,
        coverage=CoveragePolicy.NOT_APPLICABLE,
        docker_classifier=DockerClassifier.LEGACY,
        product_findings=ProductFindingPolicy.BLOCK,
    ),
    GatePhase.REPLACEMENT_CONSTRUCTION: GatePhasePolicy(
        phase=GatePhase.REPLACEMENT_CONSTRUCTION,
        replacement_evidence=EvidencePolicy.REQUIRED,
        behavioral_evidence=EvidencePolicy.PROHIBITED,
        coverage=CoveragePolicy.LEGACY_EXCLUSIONS,
        docker_classifier=DockerClassifier.LEGACY,
        product_findings=ProductFindingPolicy.EXACT_LEGACY_ADVISORY,
    ),
    GatePhase.ATOMIC_CUTOVER: GatePhasePolicy(
        phase=GatePhase.ATOMIC_CUTOVER,
        replacement_evidence=EvidencePolicy.REQUIRED,
        behavioral_evidence=EvidencePolicy.REQUIRED,
        coverage=CoveragePolicy.NO_EXCLUSIONS,
        docker_classifier=DockerClassifier.REPLACEMENT,
        product_findings=ProductFindingPolicy.BLOCK,
    ),
}


def policy_for_phase(phase: GatePhase) -> GatePhasePolicy:
    return _PHASE_POLICIES[phase]


def policy_for_state(state: HasGatePhase) -> GatePhasePolicy:
    return policy_for_phase(state.phase)
