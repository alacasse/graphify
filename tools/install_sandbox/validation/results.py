"""Closed semantic results produced only by the Validation Engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from .catalog import Scope
from .protocol import (
    ActionFailureFact,
    CommandFact,
    CommandFailureFact,
    ObservationFact,
    PhaseKind,
    PreparationFact,
)


class PhaseStatus(StrEnum):
    PASS = "PASS"
    FINDING = "FINDING"
    BLOCKED = "BLOCKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INCOMPLETE = "INCOMPLETE"


class ScenarioStatus(StrEnum):
    PASS = "PASS"
    FINDING = "FINDING"
    UNSUPPORTED = "UNSUPPORTED"
    INCOMPLETE = "INCOMPLETE"


class PurgeStatus(StrEnum):
    PASS = "PASS"
    FINDING = "FINDING"
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True, slots=True)
class ProductFinding:
    check: str
    detail: str

    def __post_init__(self) -> None:
        if not self.check or not self.detail:
            raise ValueError("a Product Finding requires a check and detail")


@dataclass(frozen=True, slots=True)
class PhaseResult:
    kind: PhaseKind
    status: PhaseStatus
    command: CommandFact | CommandFailureFact | None
    observation: ObservationFact | None
    findings: tuple[ProductFinding, ...] = ()
    reason: str | None = None
    blocked_by: PhaseKind | None = None
    failure: ActionFailureFact | None = None

    def __post_init__(self) -> None:
        if (
            type(cast(object, self.kind)) is not PhaseKind
            or type(cast(object, self.status)) is not PhaseStatus
        ):
            raise ValueError("phase result kind and status must be closed variants")
        has_command = isinstance(self.command, CommandFact)
        has_observation = self.observation is not None
        if self.status is PhaseStatus.PASS and not (
            has_command
            and has_observation
            and not self.findings
            and self.reason is None
            and self.blocked_by is None
            and self.failure is None
        ):
            raise ValueError("PASS requires complete command and observation evidence")
        if self.status is PhaseStatus.FINDING and not (
            has_command
            and has_observation
            and self.findings
            and self.reason is None
            and self.blocked_by is None
            and self.failure is None
        ):
            raise ValueError("FINDING requires complete evidence and Product Findings")
        if self.status is PhaseStatus.BLOCKED and not (
            not has_command
            and not has_observation
            and not self.findings
            and self.reason
            and self.blocked_by is not None
            and self.failure is None
        ):
            raise ValueError("BLOCKED requires only a reason and blocking phase")
        if self.status is PhaseStatus.NOT_APPLICABLE and not (
            not has_command
            and not has_observation
            and not self.findings
            and self.reason
            and self.blocked_by is None
            and self.failure is None
        ):
            raise ValueError("NOT_APPLICABLE requires only a plan-owned reason")
        if self.status is PhaseStatus.INCOMPLETE and not (
            not self.findings
            and self.reason
            and not (self.failure is not None and self.blocked_by is not None)
        ):
            raise ValueError("INCOMPLETE requires a diagnostic reason without findings")


@dataclass(frozen=True, slots=True)
class LifecycleResult:
    target: str
    scope: Scope
    status: ScenarioStatus
    phases: tuple[PhaseResult, ...]
    runtime_limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_scenario_result(self.status, self.phases)
        if not self.target or type(cast(object, self.scope)) is not Scope:
            raise ValueError("lifecycle result requires a target and closed scope")


@dataclass(frozen=True, slots=True)
class AggregateResult:
    scope: Scope
    status: ScenarioStatus
    phases: tuple[PhaseResult, ...]
    runtime_limitations: tuple[str, ...]
    preparation: PreparationFact | ActionFailureFact | None = None

    def __post_init__(self) -> None:
        _validate_scenario_result(self.status, self.phases)
        if type(cast(object, self.scope)) is not Scope:
            raise ValueError("aggregate result requires a closed scope")


@dataclass(frozen=True, slots=True)
class ScopeIsolationResult:
    selected_scope: Scope
    preserved_scope: Scope
    status: ScenarioStatus
    phases: tuple[PhaseResult, ...]
    runtime_limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_scenario_result(self.status, self.phases)
        if (
            type(cast(object, self.selected_scope)) is not Scope
            or type(cast(object, self.preserved_scope)) is not Scope
            or self.selected_scope is self.preserved_scope
        ):
            raise ValueError("scope isolation result requires two closed distinct scopes")


@dataclass(frozen=True, slots=True)
class UnsupportedResult:
    target: str
    scope: Scope
    status: ScenarioStatus
    reason: str
    runtime_limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not self.target
            or type(cast(object, self.scope)) is not Scope
            or self.status is not ScenarioStatus.UNSUPPORTED
            or not self.reason
        ):
            raise ValueError("unsupported result requires a target, scope, and reason")


@dataclass(frozen=True, slots=True)
class PurgeResult:
    status: PurgeStatus
    phases: tuple[PhaseResult, ...]
    preparation: PreparationFact | ActionFailureFact | None
    runtime_limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(cast(object, self.status)) is not PurgeStatus or not self.phases:
            raise ValueError("purge result requires a closed status and phase evidence")
        expected = PurgeStatus.PASS
        if any(phase.status is PhaseStatus.INCOMPLETE for phase in self.phases):
            expected = PurgeStatus.INCOMPLETE
        elif any(
            phase.status in {PhaseStatus.FINDING, PhaseStatus.BLOCKED} for phase in self.phases
        ):
            expected = PurgeStatus.FINDING
        if self.status is not expected:
            raise ValueError("purge status disagrees with its phase results")


def _validate_scenario_result(
    status: ScenarioStatus,
    phases: tuple[PhaseResult, ...],
) -> None:
    if type(cast(object, status)) is not ScenarioStatus or status is ScenarioStatus.UNSUPPORTED:
        raise ValueError("executed scenario status is not a closed executable variant")
    untrusted_phases = cast(tuple[object, ...], phases)
    if not untrusted_phases or not all(
        isinstance(phase, PhaseResult) for phase in untrusted_phases
    ):
        raise ValueError("executed scenario requires closed phase results")
    expected = ScenarioStatus.PASS
    if any(phase.status is PhaseStatus.INCOMPLETE for phase in phases):
        expected = ScenarioStatus.INCOMPLETE
    elif any(phase.status in {PhaseStatus.FINDING, PhaseStatus.BLOCKED} for phase in phases):
        expected = ScenarioStatus.FINDING
    if status is not expected:
        raise ValueError("scenario status disagrees with its phase results")


type DetailedScenarioResult = (
    LifecycleResult | AggregateResult | ScopeIsolationResult | UnsupportedResult
)
