"""PROTOTYPE ONLY: closed domain and application types for architecture issue #41.

The executable lab asks whether a Validation Plan can remain the sole domain
authority while all host activity crosses one correlated request/fact seam.
These values are deliberately frozen and contain no resource capabilities or
diagnostic classifications.
"""

# pyright: strict

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True, slots=True)
class RunId:
    value: str


@dataclass(frozen=True, slots=True)
class PlanId:
    value: str


@dataclass(frozen=True, slots=True)
class ActionId:
    run_id: RunId
    plan_id: PlanId
    ordinal: int


class Scope(Enum):
    USER = "user"
    PROJECT = "project"


@dataclass(frozen=True, slots=True)
class OwnedFileEffect:
    location: str
    expected_text: str


@dataclass(frozen=True, slots=True)
class TextEntryEffect:
    location: str
    entry: str
    required_text: str


type InstallEffect = OwnedFileEffect | TextEntryEffect


@dataclass(frozen=True, slots=True)
class SupportedScopeFacts:
    effects: tuple[InstallEffect, ...]


@dataclass(frozen=True, slots=True)
class UnsupportedScopeFacts:
    reason: str
    limitations: tuple[str, ...]


type ScopeFacts = SupportedScopeFacts | UnsupportedScopeFacts


@dataclass(frozen=True, slots=True)
class TargetScope:
    scope: Scope
    facts: ScopeFacts


@dataclass(frozen=True, slots=True)
class TargetFacts:
    name: str
    scopes: tuple[TargetScope, ...]

    def facts_for(self, scope: Scope) -> ScopeFacts:
        return next(item.facts for item in self.scopes if item.scope is scope)


@dataclass(frozen=True, slots=True)
class InstallTargetCatalog:
    targets: tuple[TargetFacts, ...]

    def target(self, name: str) -> TargetFacts | None:
        return next((target for target in self.targets if target.name == name), None)


type RawCatalogDocument = Mapping[str, object]


@dataclass(frozen=True, slots=True)
class CatalogReady:
    catalog: InstallTargetCatalog


@dataclass(frozen=True, slots=True)
class CatalogRejected:
    reasons: tuple[str, ...]


type CatalogCompilation = CatalogReady | CatalogRejected


@dataclass(frozen=True, slots=True)
class ExactTextRule:
    key: str
    location: str
    expected_text: str


@dataclass(frozen=True, slots=True)
class ContainsTextRule:
    key: str
    location: str
    required_text: str


@dataclass(frozen=True, slots=True)
class AbsentRule:
    key: str
    location: str


type ObservationRule = ExactTextRule | ContainsTextRule | AbsentRule


@dataclass(frozen=True, slots=True)
class ObservationSpecification:
    rules: tuple[ObservationRule, ...]


class PhaseKind(Enum):
    INSTALL = "install"
    REINSTALL = "reinstall"
    REPAIR = "repair"
    TARGET_UNINSTALL = "target-uninstall"
    CROSS_SCOPE_PRESERVATION = "cross-scope-preservation"
    AGGREGATE_PREPARE = "aggregate-prepare"
    AGGREGATE_UNINSTALL = "aggregate-uninstall"
    PURGE = "purge"


class ScenarioKind(Enum):
    LIFECYCLE = "lifecycle"
    UNSUPPORTED = "unsupported"
    AGGREGATE = "aggregate"
    ISOLATION = "isolation"


@dataclass(frozen=True, slots=True)
class PhasePlan:
    kind: PhaseKind
    target: str
    scope: Scope
    command: tuple[str, ...]
    observation: ObservationSpecification


@dataclass(frozen=True, slots=True)
class LifecycleScenario:
    name: str
    scope: Scope
    phases: tuple[PhasePlan, ...]


@dataclass(frozen=True, slots=True)
class UnsupportedScenario:
    name: str
    target: str
    scope: Scope
    reason: str
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AggregatePreparation:
    target: str
    scope: Scope
    effects: tuple[InstallEffect, ...]
    command: tuple[str, ...]
    observation: ObservationSpecification


@dataclass(frozen=True, slots=True)
class AggregateScenario:
    name: str
    scope: Scope
    preparations: tuple[AggregatePreparation, ...]
    uninstall_command: tuple[str, ...]
    removal_observation: ObservationSpecification


@dataclass(frozen=True, slots=True)
class IsolationScenario:
    name: str
    scope: Scope
    phase: PhasePlan
    preserved_scope: Scope
    preparations: tuple[PhasePlan, ...] = ()


type ScenarioPlan = LifecycleScenario | UnsupportedScenario | AggregateScenario | IsolationScenario


@dataclass(frozen=True, slots=True)
class PurgePlan:
    command: tuple[str, ...]
    observation: ObservationSpecification


@dataclass(frozen=True, slots=True)
class ScenarioProjection:
    name: str
    kind: ScenarioKind
    scope: Scope
    target_names: tuple[str, ...]
    expected_phases: tuple[PhaseKind, ...]


@dataclass(frozen=True, slots=True)
class PlanProjection:
    plan_id: PlanId
    scenarios: tuple[ScenarioProjection, ...]
    purge_required: bool


@dataclass(frozen=True, slots=True)
class ValidationPlan:
    plan_id: PlanId
    scenarios: tuple[ScenarioPlan, ...]
    purge: PurgePlan
    projection: PlanProjection


@dataclass(frozen=True, slots=True)
class LifecycleValidation:
    target: str
    scope: Scope


@dataclass(frozen=True, slots=True)
class UnsupportedValidation:
    target: str
    scope: Scope


@dataclass(frozen=True, slots=True)
class AggregateValidation:
    scope: Scope


@dataclass(frozen=True, slots=True)
class CompleteValidation:
    targets: tuple[str, ...]
    scopes: tuple[Scope, ...]


type ValidationRequest = (
    LifecycleValidation | UnsupportedValidation | AggregateValidation | CompleteValidation
)


@dataclass(frozen=True, slots=True)
class HarnessPolicy:
    install_argv: tuple[str, ...] = ("graphify", "install")
    uninstall_argv: tuple[str, ...] = ("graphify", "uninstall")
    aggregate_uninstall_argv: tuple[str, ...] = ("graphify", "uninstall", "--all")
    purge_argv: tuple[str, ...] = ("graphify", "purge")
    reinstall: bool = True
    repair: bool = True


@dataclass(frozen=True, slots=True)
class PlanReady:
    plan: ValidationPlan


@dataclass(frozen=True, slots=True)
class PlanRejected:
    reasons: tuple[str, ...]


type PlanCompilation = PlanReady | PlanRejected


@dataclass(frozen=True, slots=True)
class CommandRequest:
    action_id: ActionId
    scenario: str
    phase: str
    argv: tuple[str, ...]
    cwd: str


@dataclass(frozen=True, slots=True)
class ObservationRequest:
    action_id: ActionId
    scenario: str
    phase: str
    specification: ObservationSpecification


type ActionRequest = CommandRequest | ObservationRequest


@dataclass(frozen=True, slots=True)
class Exited:
    code: int


@dataclass(frozen=True, slots=True)
class Signalled:
    signal: int


@dataclass(frozen=True, slots=True)
class TimedOut:
    seconds: float


@dataclass(frozen=True, slots=True)
class Cancelled:
    reason: str


@dataclass(frozen=True, slots=True)
class SpawnFailed:
    detail: str


type CommandTermination = Exited | Signalled | TimedOut | Cancelled | SpawnFailed


@dataclass(frozen=True, slots=True)
class CapturedStream:
    content: bytes
    digest: str
    size: int


@dataclass(frozen=True, slots=True)
class StreamCaptureFailure:
    partial_content: bytes
    digest: str
    size: int
    detail: str


type StreamCapture = CapturedStream | StreamCaptureFailure


@dataclass(frozen=True, slots=True)
class CommandFact:
    action_id: ActionId
    argv: tuple[str, ...]
    cwd: str
    started_ns: int
    finished_ns: int
    termination: CommandTermination
    reaped: bool
    stdout: StreamCapture
    stderr: StreamCapture
    chronology: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ObservedContent:
    rule_key: str
    location: str
    content: bytes
    digest: str
    size: int


@dataclass(frozen=True, slots=True)
class ObservedAbsent:
    rule_key: str
    location: str


@dataclass(frozen=True, slots=True)
class ObservationReadFailure:
    rule_key: str
    location: str
    detail: str


type ObservationItem = ObservedContent | ObservedAbsent | ObservationReadFailure


@dataclass(frozen=True, slots=True)
class ObservationFact:
    action_id: ActionId
    items: tuple[ObservationItem, ...]
    chronology: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ActionUnavailable:
    action_id: ActionId
    detail: str
    chronology: tuple[str, ...]


type RawFact = CommandFact | ObservationFact | ActionUnavailable


@dataclass(frozen=True, slots=True)
class SubjectReady:
    target: str
    scope: Scope


@dataclass(frozen=True, slots=True)
class InstallationEstablished:
    target: str
    scope: Scope
    surfaces: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class StableInstallationEstablished:
    target: str
    scope: Scope
    surfaces: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class CleanupSafe:
    target: str
    scope: Scope


type InstallationWitness = InstallationEstablished | StableInstallationEstablished


@dataclass(frozen=True, slots=True)
class ProductFinding:
    action_id: ActionId
    summary: str
    witness: InstallationWitness | None = None


@dataclass(frozen=True, slots=True)
class PhasePassed:
    phase: PhaseKind


@dataclass(frozen=True, slots=True)
class PhaseFinding:
    phase: PhaseKind
    finding: ProductFinding


@dataclass(frozen=True, slots=True)
class PhaseIncomplete:
    phase: PhaseKind
    reason: str


@dataclass(frozen=True, slots=True)
class PhaseBlocked:
    phase: PhaseKind
    missing_witness: str


type PhaseResult = PhasePassed | PhaseFinding | PhaseIncomplete


@dataclass(frozen=True, slots=True)
class PreparationPassed:
    target: str
    witness: InstallationEstablished


@dataclass(frozen=True, slots=True)
class PreparationFinding:
    target: str
    finding: ProductFinding


@dataclass(frozen=True, slots=True)
class PreparationIncomplete:
    target: str
    reason: str


type AggregatePreparationResult = PreparationPassed | PreparationFinding | PreparationIncomplete


@dataclass(frozen=True, slots=True)
class AggregateUninstallPassed:
    installations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AggregateUninstallFinding:
    installations: tuple[str, ...]
    finding: ProductFinding


@dataclass(frozen=True, slots=True)
class AggregateUninstallIncomplete:
    installations: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class AggregateUninstallNotApplicable:
    reason: str


type AggregateUninstallResult = (
    AggregateUninstallPassed
    | AggregateUninstallFinding
    | AggregateUninstallIncomplete
    | AggregateUninstallNotApplicable
)


@dataclass(frozen=True, slots=True)
class ScenarioPassed:
    name: str


@dataclass(frozen=True, slots=True)
class ScenarioFinding:
    name: str
    findings: tuple[ProductFinding, ...]


@dataclass(frozen=True, slots=True)
class ScenarioUnsupported:
    name: str
    reason: str
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScenarioIncomplete:
    name: str
    reasons: tuple[str, ...]


type ScenarioResult = ScenarioPassed | ScenarioFinding | ScenarioUnsupported | ScenarioIncomplete


@dataclass(frozen=True, slots=True)
class PhaseScenarioRecord:
    result: ScenarioResult
    phases: tuple[PhaseResult, ...]
    blocked: tuple[PhaseBlocked, ...]


@dataclass(frozen=True, slots=True)
class AggregateScenarioRecord:
    result: ScenarioResult
    preparations: tuple[AggregatePreparationResult, ...]
    removal: AggregateUninstallResult
    established_installations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UnsupportedScenarioRecord:
    result: ScenarioUnsupported


type ScenarioRecord = PhaseScenarioRecord | AggregateScenarioRecord | UnsupportedScenarioRecord


@dataclass(frozen=True, slots=True)
class PurgePassed:
    pass


@dataclass(frozen=True, slots=True)
class PurgeFinding:
    finding: ProductFinding


@dataclass(frozen=True, slots=True)
class PurgeIncomplete:
    reason: str


type PurgeResult = PurgePassed | PurgeFinding | PurgeIncomplete


@dataclass(frozen=True, slots=True)
class CompletedValidation:
    plan: PlanProjection
    scenario_records: tuple[ScenarioRecord, ...]
    purge_result: PurgeResult
    raw_facts: tuple[RawFact, ...]
    findings: tuple[ProductFinding, ...]
    chronology: tuple[ActionId, ...]


@dataclass(frozen=True, slots=True)
class ValidationIncomplete:
    plan: PlanProjection
    reason: str
    scenario_records: tuple[ScenarioRecord, ...]
    raw_facts: tuple[RawFact, ...]
    findings: tuple[ProductFinding, ...]
    chronology: tuple[ActionId, ...]


type ApplicationOutcome = CompletedValidation | ValidationIncomplete
