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
    target_uninstall: bool
    limitations: tuple[str, ...]


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


class ActionFamily(Enum):
    COMMAND = "command"
    OBSERVATION = "observation"
    IMAGE_BUILD = "image-build"
    CATALOG_READ = "catalog-read"
    SUBJECT_PREPARATION = "subject-preparation"
    SUBJECT_PROBE = "subject-probe"
    FIXTURE_PREPARATION = "fixture-preparation"


class ActionPurpose(Enum):
    HOST_IMAGE_BUILD = "host-image-build"
    HOST_CATALOG_READ = "host-catalog-read"
    PACKAGE_PREPARATION = "package-preparation"
    PACKAGE_PROBE = "package-probe"
    PRODUCT_LIFECYCLE = "product-lifecycle"
    PRODUCT_PURGE = "product-purge"
    HARNESS_PREPARATION = "harness-preparation"
    SEMANTIC_OBSERVATION = "semantic-observation"


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
class NotApplicablePhasePlan:
    kind: PhaseKind
    target: str
    scope: Scope
    reason: str


type PlannedPhase = PhasePlan | NotApplicablePhasePlan


@dataclass(frozen=True, slots=True)
class LifecycleScenario:
    name: str
    scope: Scope
    phases: tuple[PlannedPhase, ...]
    limitations: tuple[str, ...] = ()


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
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IsolationScenario:
    name: str
    scope: Scope
    phase: PhasePlan
    preserved_scope: Scope
    preparations: tuple[PhasePlan, ...] = ()
    limitations: tuple[str, ...] = ()


type ScenarioPlan = LifecycleScenario | UnsupportedScenario | AggregateScenario | IsolationScenario


@dataclass(frozen=True, slots=True)
class PurgePlan:
    fixture_entries: tuple[tuple[str, str], ...]
    command: tuple[str, ...]
    observation: ObservationSpecification


@dataclass(frozen=True, slots=True)
class ExpectedAction:
    ordinal: int
    scenario: str
    phase: str
    family: ActionFamily
    purpose: ActionPurpose


@dataclass(frozen=True, slots=True)
class ScenarioProjection:
    name: str
    kind: ScenarioKind
    scope: Scope
    target_names: tuple[str, ...]
    expected_phases: tuple[PhaseKind, ...]
    expected_actions: tuple[ExpectedAction, ...]
    runtime_limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanProjection:
    plan_id: PlanId
    subject_actions: tuple[ExpectedAction, ...]
    scenarios: tuple[ScenarioProjection, ...]
    purge_required: bool
    purge_actions: tuple[ExpectedAction, ...]
    runtime_limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SubjectPlan:
    target: str
    scope: Scope


@dataclass(frozen=True, slots=True)
class ValidationPlan:
    plan_id: PlanId
    scenarios: tuple[ScenarioPlan, ...]
    purge: PurgePlan
    projection: PlanProjection
    subjects: tuple[SubjectPlan, ...]


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
    runtime_limitations: tuple[str, ...] = ()


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
    purpose: ActionPurpose = ActionPurpose.PRODUCT_LIFECYCLE


@dataclass(frozen=True, slots=True)
class ObservationRequest:
    action_id: ActionId
    scenario: str
    phase: str
    specification: ObservationSpecification
    purpose: ActionPurpose = ActionPurpose.SEMANTIC_OBSERVATION


@dataclass(frozen=True, slots=True)
class ImageBuildRequest:
    action_id: ActionId
    source_revision: str


@dataclass(frozen=True, slots=True)
class CatalogReadRequest:
    action_id: ActionId
    immutable_image_identity: str


@dataclass(frozen=True, slots=True)
class SubjectPreparationRequest:
    action_id: ActionId
    target: str
    scope: Scope


@dataclass(frozen=True, slots=True)
class SubjectProbeRequest:
    action_id: ActionId
    target: str
    scope: Scope
    prepared_identity: str


@dataclass(frozen=True, slots=True)
class FixturePreparationRequest:
    action_id: ActionId
    scenario: str
    phase: str
    entries: tuple[tuple[str, str], ...]


type ActionRequest = (
    CommandRequest
    | ObservationRequest
    | ImageBuildRequest
    | CatalogReadRequest
    | SubjectPreparationRequest
    | SubjectProbeRequest
    | FixturePreparationRequest
)


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
    scenario: str = ""
    phase: str = ""
    purpose: ActionPurpose = ActionPurpose.PRODUCT_LIFECYCLE


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
    scenario: str = ""
    phase: str = ""


@dataclass(frozen=True, slots=True)
class ImmutableImageFact:
    action_id: ActionId
    source_revision: str
    immutable_image_identity: str


@dataclass(frozen=True, slots=True)
class CatalogDocumentsFact:
    action_id: ActionId
    immutable_image_identity: str
    documents: tuple[RawCatalogDocument, ...]


@dataclass(frozen=True, slots=True)
class SubjectPreparedFact:
    action_id: ActionId
    target: str
    scope: Scope
    prepared_identity: str


@dataclass(frozen=True, slots=True)
class SubjectProbeFact:
    action_id: ActionId
    target: str
    scope: Scope
    prepared_identity: str
    package_origin: str
    package_version: str
    interface_available: bool


@dataclass(frozen=True, slots=True)
class FixturePreparedFact:
    action_id: ActionId
    entries: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ActionUnavailable:
    action_id: ActionId
    detail: str
    chronology: tuple[str, ...]


type RawFact = (
    CommandFact
    | ObservationFact
    | ImmutableImageFact
    | CatalogDocumentsFact
    | SubjectPreparedFact
    | SubjectProbeFact
    | FixturePreparedFact
    | ActionUnavailable
)


@dataclass(frozen=True, slots=True)
class SubjectReady:
    target: str
    scope: Scope
    prepared_identity: str = ""
    package_origin: str = ""
    package_version: str = ""
    evidence: tuple[ActionId, ...] = ()


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
    evidence: tuple[ActionId, ...] = ()


@dataclass(frozen=True, slots=True)
class PhaseFinding:
    phase: PhaseKind
    finding: ProductFinding
    evidence: tuple[ActionId, ...] = ()


@dataclass(frozen=True, slots=True)
class PhaseIncomplete:
    phase: PhaseKind
    reason: str
    evidence: tuple[ActionId, ...] = ()


@dataclass(frozen=True, slots=True)
class PhaseBlocked:
    phase: PhaseKind
    missing_witness: str


@dataclass(frozen=True, slots=True)
class PhaseNotApplicable:
    phase: PhaseKind
    reason: str


type PhaseResult = PhasePassed | PhaseFinding | PhaseIncomplete | PhaseBlocked | PhaseNotApplicable


@dataclass(frozen=True, slots=True)
class PreparationPassed:
    target: str
    witness: InstallationEstablished
    evidence: tuple[ActionId, ...] = ()


@dataclass(frozen=True, slots=True)
class PreparationFinding:
    target: str
    finding: ProductFinding
    evidence: tuple[ActionId, ...] = ()


@dataclass(frozen=True, slots=True)
class PreparationIncomplete:
    target: str
    reason: str
    evidence: tuple[ActionId, ...] = ()


type AggregatePreparationResult = PreparationPassed | PreparationFinding | PreparationIncomplete


@dataclass(frozen=True, slots=True)
class AggregateUninstallPassed:
    installations: tuple[str, ...]
    evidence: tuple[ActionId, ...] = ()


@dataclass(frozen=True, slots=True)
class AggregateUninstallFinding:
    installations: tuple[str, ...]
    finding: ProductFinding
    evidence: tuple[ActionId, ...] = ()


@dataclass(frozen=True, slots=True)
class AggregateUninstallIncomplete:
    installations: tuple[str, ...]
    reason: str
    evidence: tuple[ActionId, ...] = ()


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
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScenarioFinding:
    name: str
    findings: tuple[ProductFinding, ...]
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScenarioUnsupported:
    name: str
    reason: str
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScenarioIncomplete:
    name: str
    reasons: tuple[str, ...]
    limitations: tuple[str, ...] = ()


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
    evidence: tuple[ActionId, ...] = ()


@dataclass(frozen=True, slots=True)
class PurgeFinding:
    finding: ProductFinding
    evidence: tuple[ActionId, ...] = ()


@dataclass(frozen=True, slots=True)
class PurgeIncomplete:
    reason: str
    evidence: tuple[ActionId, ...] = ()


type PurgeResult = PurgePassed | PurgeFinding | PurgeIncomplete


@dataclass(frozen=True, slots=True)
class CompletedValidation:
    plan: PlanProjection
    subjects: tuple[SubjectReady, ...]
    scenario_records: tuple[ScenarioRecord, ...]
    purge_result: PurgeResult
    raw_facts: tuple[RawFact, ...]
    findings: tuple[ProductFinding, ...]
    chronology: tuple[ActionId, ...]


@dataclass(frozen=True, slots=True)
class ValidationIncomplete:
    plan: PlanProjection
    subjects: tuple[SubjectReady, ...]
    reason: str
    scenario_records: tuple[ScenarioRecord, ...]
    raw_facts: tuple[RawFact, ...]
    findings: tuple[ProductFinding, ...]
    chronology: tuple[ActionId, ...]


type ApplicationOutcome = CompletedValidation | ValidationIncomplete
