"""Thin fail-closed lifecycle ordering for the integrated architecture prototype."""

# pyright: strict

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .bundle import (
    BundleAllocationError,
    BundleFaults,
    PersistenceRejected,
    RecoveryRejected,
    TerminalCommitPermit,
    TerminalCommitRejected,
)
from .diagnostics import (
    BundleAssessment,
    CIClassificationInput,
    CIDecision,
    CompletedAssessment,
    ExpectedDiagnostic,
    InvalidBundle,
    PublicationFact,
    Published,
    ReadyToCommit,
    TerminalFacts,
    assess_bundle,
    assessment_failures,
    authorize_retention,
    build_manifest,
    classify_ci,
    controller_failure,
    derive_abandoned_running_record,
    derive_terminal_facts,
    encode_failure_evidence,
    persistence_failure,
    prepare_recovery,
)
from .documents import (
    DiagnosticFailure,
    PersistenceFailure,
    RunningRunRecord,
    SchemaFailure,
    encode_document,
)
from .domain import build_validation_plan, compile_catalog, run_validation
from .model import (
    ActionId,
    ActionUnavailable,
    ApplicationOutcome,
    CatalogDocumentsFact,
    CatalogReadRequest,
    CatalogRejected,
    HarnessPolicy,
    ImageBuildRequest,
    ImmutableImageFact,
    PlanId,
    PlanProjection,
    PlanRejected,
    RunId,
    ValidationPlan,
    ValidationRequest,
)
from .resources import (
    ContainerClaimed,
    DockerDaemonAdapter,
    LeaseBackedFulfilment,
    ResourceFaults,
    ResourceInputs,
    RetentionAdapter,
    RetentionRejected,
    RetentionRequest,
    nominate_recovery,
    reopen_completed,
)


@dataclass(frozen=True)
class RunRequest:
    run_id: RunId
    selection: str
    source_revision: str
    validation: ValidationRequest
    policy: HarnessPolicy
    observed_raw_exit: int | None = None
    interrupt_signal: str | None = None


@dataclass(frozen=True)
class RecoveryRequest:
    bundle: Path
    expected: ExpectedDiagnostic
    reason: str


@dataclass(frozen=True)
class PreflightRejected:
    failures: tuple[DiagnosticFailure, ...]
    trace: tuple[str, ...]


@dataclass(frozen=True)
class DurableTerminal:
    bundle: Path
    outcome: ApplicationOutcome
    assessment: CompletedAssessment
    ci_decision: CIDecision
    trace: tuple[str, ...]


@dataclass(frozen=True)
class DurableNonterminal:
    bundle: Path
    failures: tuple[DiagnosticFailure, ...]
    trace: tuple[str, ...]


@dataclass(frozen=True)
class TerminalTrustFailure:
    bundle: Path
    failures: tuple[DiagnosticFailure, ...]
    trace: tuple[str, ...]


type RunDisposition = (
    PreflightRejected | DurableTerminal | DurableNonterminal | TerminalTrustFailure
)


@dataclass(frozen=True)
class RecoveryCommitted:
    bundle: Path
    assessment: CompletedAssessment
    trace: tuple[str, ...]


@dataclass(frozen=True)
class RecoveryDeclined:
    bundle: Path
    failures: tuple[DiagnosticFailure, ...]
    trace: tuple[str, ...]


type RecoveryDisposition = RecoveryCommitted | RecoveryDeclined


class PublicationAdapter(Protocol):
    def publish(self, bundle: Path, assessment: CompletedAssessment) -> PublicationFact: ...


@dataclass(frozen=True)
class _NamedPublicationAdapter:
    artifact_name: str = "prototype-bundle"

    def publish(self, bundle: Path, assessment: CompletedAssessment) -> PublicationFact:
        del bundle, assessment
        return Published(self.artifact_name)


@dataclass(frozen=True)
class _HarnessAdapters:
    resource_faults: ResourceFaults
    bundle_faults: BundleFaults
    before_terminal_commit: Callable[[LeaseBackedFulfilment, TerminalCommitPermit], None] | None = (
        None
    )


_DEFAULT_RESOURCE_FAULTS = ResourceFaults()
_DEFAULT_BUNDLE_FAULTS = BundleFaults()
_DEFAULT_HARNESS = _HarnessAdapters(_DEFAULT_RESOURCE_FAULTS, _DEFAULT_BUNDLE_FAULTS)


@dataclass(frozen=True)
class _ApplicationPrepared:
    expected: ExpectedDiagnostic
    plan: ValidationPlan


@dataclass(frozen=True)
class _PreparationFailed:
    failures: tuple[DiagnosticFailure, ...]


class RunController:
    """Own lifecycle order; domain, resource, and diagnostic meaning stay delegated."""

    def __init__(
        self,
        output_root: Path,
        sandbox_root: Path,
        docker: DockerDaemonAdapter,
        inputs: ResourceInputs,
        publication: PublicationAdapter | None = None,
        retention: RetentionAdapter | None = None,
        *,
        _harness: _HarnessAdapters = _DEFAULT_HARNESS,
    ) -> None:
        self._output_root = output_root
        self._sandbox_root = sandbox_root
        self._docker = docker
        self._inputs = inputs
        self._publication = _NamedPublicationAdapter() if publication is None else publication
        self._retention = RetentionAdapter() if retention is None else retention
        self._harness = _harness

    @classmethod
    def _for_harness(
        cls,
        output_root: Path,
        sandbox_root: Path,
        docker: DockerDaemonAdapter,
        inputs: ResourceInputs,
        *,
        resource_faults: ResourceFaults = _DEFAULT_RESOURCE_FAULTS,
        bundle_faults: BundleFaults = _DEFAULT_BUNDLE_FAULTS,
        publication: PublicationAdapter | None = None,
        retention: RetentionAdapter | None = None,
        before_terminal_commit: (
            Callable[[LeaseBackedFulfilment, TerminalCommitPermit], None] | None
        ) = None,
    ) -> RunController:
        return cls(
            output_root,
            sandbox_root,
            docker,
            inputs,
            publication,
            retention,
            _harness=_HarnessAdapters(
                resource_faults,
                bundle_faults,
                before_terminal_commit,
            ),
        )

    def run(self, request: RunRequest) -> RunDisposition:
        """Run one validation; public callers cannot inject mid-run facts or faults."""

        trace: list[str] = []
        try:
            resources = self._allocate(request)
        except BundleAllocationError as error:
            return DurableNonterminal(
                error.path,
                (controller_failure("allocate-running", "run.json", error),),
                ("bundle allocated but initial Running persistence failed",),
            )
        except Exception as error:
            return PreflightRejected(
                (controller_failure("allocate", request.run_id.value, error),),
                tuple(trace),
            )
        trace.append("Running authority persisted before image and catalog acquisition")
        try:
            disposition = self._drive(resources, request, trace)
        except Exception as error:
            failures = _abandon_after_exception(
                resources,
                request,
                controller_failure("lifecycle", request.run_id.value, error),
            )
            disposition = DurableNonterminal(
                resources.snapshot().bundle_path,
                failures,
                tuple(
                    (*trace, "lifecycle exception persisted and resource owner abandoned safely")
                ),
            )
        try:
            resources.close()
        except Exception as error:
            failure = controller_failure("close", request.run_id.value, error)
            return _with_close_failure(disposition, failure)
        return disposition

    def recover(self, request: RecoveryRequest) -> RecoveryDisposition:
        """Claim, assess, terminalize, freshly reopen, and reassess an abandoned run."""

        trace: list[str] = []
        try:
            session = nominate_recovery(request.bundle)
            if isinstance(session, RecoveryRejected):
                return RecoveryDeclined(
                    request.bundle,
                    (persistence_failure("recovery-claim", "run.json", session.detail),),
                    tuple(trace),
                )
            try:
                prepared = prepare_recovery(
                    session.read_bundle(),
                    request.expected,
                    request.reason,
                )
                if isinstance(prepared, InvalidBundle):
                    return RecoveryDeclined(request.bundle, prepared.failures, tuple(trace))
                trace.append("abandoned Running bundle assessed and recovery permit issued")
                committed = session.commit_incomplete(prepared.permit)
                if isinstance(committed, TerminalCommitRejected):
                    return RecoveryDeclined(
                        request.bundle,
                        (persistence_failure("recovery-commit", "run.json", committed.detail),),
                        tuple(trace),
                    )
                trace.append("recovery report persisted before incomplete Run Record")
            finally:
                session.close()
            reopened = reopen_completed(request.bundle)
            if isinstance(reopened, RecoveryRejected):
                return RecoveryDeclined(
                    request.bundle,
                    (persistence_failure("recovery-reopen", "run.json", reopened.detail),),
                    tuple(trace),
                )
            assessed = assess_bundle(reopened, request.expected)
            if not isinstance(assessed, CompletedAssessment):
                return RecoveryDeclined(
                    request.bundle,
                    assessment_failures(assessed),
                    tuple(trace),
                )
            authorized = authorize_retention(assessed)
            retained = self._retention.apply(RetentionRequest(request.bundle, authorized.run_id))
            if isinstance(retained, RetentionRejected):
                return RecoveryDeclined(
                    request.bundle,
                    (persistence_failure("retention", "run.json", retained.detail),),
                    tuple(trace),
                )
            trace.append("diagnostic authorization preceded resource-owned keep-five retention")
            trace.append("recovered terminal bundle freshly reopened and reassessed")
            return RecoveryCommitted(request.bundle, assessed, tuple(trace))
        except Exception as error:
            return RecoveryDeclined(
                request.bundle,
                (controller_failure("recovery", "run.json", error),),
                tuple(trace),
            )

    def _abandon_for_harness(
        self,
        request: RunRequest,
    ) -> tuple[Path, ExpectedDiagnostic]:
        """Build one valid sealed Running bundle, then model owner loss."""

        trace: list[str] = []
        resources = self._allocate(request)
        try:
            prepared = _acquire_and_plan(resources, request, trace)
            if isinstance(prepared, _PreparationFailed):
                raise OSError("harness preparation failed")
            updated = resources.update_running(
                encode_document(_running(prepared.expected, "planned"))
            )
            if isinstance(updated, PersistenceRejected):
                raise OSError(updated.detail)
            claim = resources.reserve_container(f"graphify-{request.run_id.value}")
            if not isinstance(claim, ContainerClaimed):
                raise OSError(claim.detail)
            outcome = run_validation(prepared.plan, request.run_id, resources.fulfil)
            failures = _persist_diagnostic_inputs(resources, prepared.expected, outcome)
            if failures:
                raise OSError("harness diagnostic persistence failed")
            proof = resources.quiesce_and_seal()
            resources.abandon_after_failure(proof)
            return resources.snapshot().bundle_path, prepared.expected
        finally:
            resources.close()

    def _allocate(self, request: RunRequest) -> LeaseBackedFulfilment:
        running = RunningRunRecord(
            request.run_id.value,
            request.selection,
            "PENDING",
            "PENDING",
            "allocated",
        )
        return LeaseBackedFulfilment.allocate(
            self._output_root,
            request.run_id.value,
            request.run_id,
            encode_document(running),
            self._sandbox_root,
            self._docker,
            faults=self._harness.resource_faults,
            bundle_faults=self._harness.bundle_faults,
            inputs=self._inputs,
        )

    def _drive(
        self,
        resources: LeaseBackedFulfilment,
        request: RunRequest,
        trace: list[str],
    ) -> RunDisposition:
        prepared = _acquire_and_plan(resources, request, trace)
        if isinstance(prepared, _PreparationFailed):
            return DurableNonterminal(
                resources.snapshot().bundle_path,
                prepared.failures,
                tuple(trace),
            )
        expected, plan = prepared.expected, prepared.plan
        updated = resources.update_running(encode_document(_running(expected, "planned")))
        if isinstance(updated, PersistenceRejected):
            return DurableNonterminal(
                resources.snapshot().bundle_path,
                (persistence_failure("persist-running", "run.json", updated.detail),),
                tuple(trace),
            )
        trace.append("Running authority bound to acquired image and domain plan")
        claim = resources.reserve_container(f"graphify-{request.run_id.value}")
        if not isinstance(claim, ContainerClaimed):
            return DurableNonterminal(
                resources.snapshot().bundle_path,
                (persistence_failure("container-claim", claim.exact_name, claim.detail),),
                tuple(trace),
            )
        outcome = run_validation(plan, request.run_id, resources.fulfil)
        trace.append("application completed through one correlated fulfilment seam")
        failures = _persist_diagnostic_inputs(resources, expected, outcome)
        resources.quiesce_and_seal()
        trace.append("cleanup, absence proof, and evidence sealing completed")
        return self._terminalize(resources, request, expected, outcome, failures, trace)

    def _terminalize(
        self,
        resources: LeaseBackedFulfilment,
        request: RunRequest,
        expected: ExpectedDiagnostic,
        outcome: ApplicationOutcome,
        failures: tuple[DiagnosticFailure, ...],
        trace: list[str],
    ) -> RunDisposition:
        facts = derive_terminal_facts(
            outcome,
            request.observed_raw_exit,
            request.interrupt_signal,
            failures,
        )
        commit_failure = self._commit_assessed_terminal(
            resources,
            expected,
            facts,
            trace,
        )
        if commit_failure is not None:
            return commit_failure
        return self._finish_terminal(resources, expected, outcome, trace)

    def _commit_assessed_terminal(
        self,
        resources: LeaseBackedFulfilment,
        expected: ExpectedDiagnostic,
        facts: TerminalFacts,
        trace: list[str],
    ) -> DurableNonterminal | None:
        ready = assess_bundle(resources.read_bundle(), expected, facts)
        if not isinstance(ready, ReadyToCommit):
            return _nonterminal(resources, ready, trace)
        trace.append("whole bundle assessed before report persistence")
        report_result = resources.persist_report(ready.report.encode())
        if isinstance(report_result, PersistenceRejected):
            trace.append("report persistence failed; Running authority preserved")
            return DurableNonterminal(
                resources.snapshot().bundle_path,
                (persistence_failure("persist-report", "report.md", report_result.detail),),
                tuple(trace),
            )
        trace.append("report persisted before terminal Run Record")
        with_report = assess_bundle(resources.read_bundle(), expected, facts)
        if not isinstance(with_report, ReadyToCommit) or with_report.permit is None:
            return _nonterminal(resources, with_report, trace)
        hook = self._harness.before_terminal_commit
        if hook is not None:
            hook(resources, with_report.permit)
        committed = resources.commit_terminal(with_report.permit)
        if isinstance(committed, TerminalCommitRejected):
            return DurableNonterminal(
                resources.snapshot().bundle_path,
                (persistence_failure("commit-terminal", "run.json", committed.detail),),
                tuple(trace),
            )
        trace.append("diagnostics-bound terminal permit committed last and exclusively")
        return None

    def _finish_terminal(
        self,
        resources: LeaseBackedFulfilment,
        expected: ExpectedDiagnostic,
        outcome: ApplicationOutcome,
        trace: list[str],
    ) -> RunDisposition:
        reopened_view = reopen_completed(resources.snapshot().bundle_path)
        if isinstance(reopened_view, RecoveryRejected):
            return TerminalTrustFailure(
                resources.snapshot().bundle_path,
                (persistence_failure("terminal-reopen", "run.json", reopened_view.detail),),
                tuple((*trace, "fresh terminal reopen failed")),
            )
        reopened = assess_bundle(reopened_view, expected)
        if not isinstance(reopened, CompletedAssessment):
            return TerminalTrustFailure(
                resources.snapshot().bundle_path,
                assessment_failures(reopened),
                tuple((*trace, "fresh terminal reassessment failed")),
            )
        trace.append("fresh reopen and reassessment completed before publication")
        authorized = authorize_retention(reopened)
        retained = self._retention.apply(
            RetentionRequest(resources.snapshot().bundle_path, authorized.run_id)
        )
        if isinstance(retained, RetentionRejected):
            return TerminalTrustFailure(
                resources.snapshot().bundle_path,
                (persistence_failure("retention", "run.json", retained.detail),),
                tuple(trace),
            )
        trace.append("diagnostic authorization preceded resource-owned keep-five retention")
        try:
            publication = self._publication.publish(resources.snapshot().bundle_path, reopened)
        except Exception as error:
            return TerminalTrustFailure(
                resources.snapshot().bundle_path,
                (controller_failure("publication", "run.json", error),),
                tuple((*trace, "publication adapter failure classified after terminal proof")),
            )
        trace.append("publication fact obtained only after fresh reassessment")
        decision = classify_ci(
            CIClassificationInput(reopened, reopened.run_record.raw_exit, publication)
        )
        return DurableTerminal(
            resources.snapshot().bundle_path,
            outcome,
            reopened,
            decision,
            tuple(trace),
        )


def _acquire_and_plan(
    resources: LeaseBackedFulfilment,
    request: RunRequest,
    trace: list[str],
) -> _ApplicationPrepared | _PreparationFailed:
    acquisition_plan = PlanId("preflight-acquisition")
    image = resources.fulfil(
        ImageBuildRequest(ActionId(request.run_id, acquisition_plan, 0), request.source_revision)
    )
    if isinstance(image, ActionUnavailable):
        return _PreparationFailed((PersistenceFailure("image-build", "image", image.detail),))
    if not isinstance(image, ImmutableImageFact):
        return _PreparationFailed(
            (SchemaFailure("image-build", "image", "resource returned wrong fact family"),)
        )
    catalog_fact = resources.fulfil(
        CatalogReadRequest(
            ActionId(request.run_id, acquisition_plan, 1),
            # Acquisition has a separate PlanId, so nonnegative ordinals do not
            # collide with the later Validation Plan.
            image.immutable_image_identity,
        )
    )
    if isinstance(catalog_fact, ActionUnavailable):
        return _PreparationFailed(
            (PersistenceFailure("catalog-read", "catalog", catalog_fact.detail),)
        )
    if not isinstance(catalog_fact, CatalogDocumentsFact):
        return _PreparationFailed(
            (SchemaFailure("catalog-read", "catalog", "resource returned wrong fact family"),)
        )
    trace.append("immutable image built and catalog acquired from that exact image")
    catalog = compile_catalog(catalog_fact.documents)
    if isinstance(catalog, CatalogRejected):
        return _PreparationFailed(
            tuple(SchemaFailure("catalog", "catalog", reason) for reason in catalog.reasons)
        )
    planned = build_validation_plan(catalog.catalog, request.validation, request.policy)
    if isinstance(planned, PlanRejected):
        return _PreparationFailed(
            tuple(SchemaFailure("plan", "plan", reason) for reason in planned.reasons)
        )
    subject_identity = _subject_identity(planned.plan.projection)
    expected = ExpectedDiagnostic(
        request.run_id.value,
        request.selection,
        image.immutable_image_identity,
        subject_identity,
        planned.plan.projection,
    )
    trace.append("domain-owned Validation Plan compiled")
    return _ApplicationPrepared(expected, planned.plan)


def _subject_identity(plan: PlanProjection) -> str:
    payload = "\n".join(
        f"{action.ordinal}:{action.scenario}:{action.phase}:{action.family.value}"
        for action in plan.subject_actions
    ).encode()
    return "subjects:" + hashlib.sha256(payload).hexdigest()[:16]


def _running(expected: ExpectedDiagnostic, phase: str) -> RunningRunRecord:
    return RunningRunRecord(
        expected.run_id,
        expected.selection,
        expected.image_identity,
        expected.subject_identity,
        phase,
    )


def _persist_diagnostic_inputs(
    resources: LeaseBackedFulfilment,
    expected: ExpectedDiagnostic,
    outcome: ApplicationOutcome,
) -> tuple[DiagnosticFailure, ...]:
    failures: list[DiagnosticFailure] = []
    host_log = "\n".join(item.operation for item in resources.snapshot().chronology).encode()
    host_result = resources.persist_evidence("runner.log", host_log)
    if isinstance(host_result, PersistenceRejected):
        failures.append(persistence_failure("persist", "runner.log", host_result.detail))
    inventory = tuple(
        entry.reference
        for entry in resources.read_bundle().entries
        if str(entry.relative_path) not in {"run.json", "runner.log", "manifest.json", "report.md"}
    )
    manifest = build_manifest(expected, outcome, inventory)
    manifest_result = resources.persist_evidence("manifest.json", encode_document(manifest))
    if isinstance(manifest_result, PersistenceRejected):
        failures.append(persistence_failure("persist", "manifest.json", manifest_result.detail))
    return tuple(failures)


def _abandon_after_exception(
    resources: LeaseBackedFulfilment,
    request: RunRequest,
    failure: DiagnosticFailure,
) -> tuple[DiagnosticFailure, ...]:
    failures: list[DiagnosticFailure] = [failure]
    try:
        view = resources.read_bundle()
        manifest_present = bool(view.all("manifest.json"))
        running = derive_abandoned_running_record(view)
        if isinstance(running, RunningRunRecord):
            updated = resources.update_running(encode_document(running))
        else:
            failures.append(running)
            updated = None
        if isinstance(updated, PersistenceRejected):
            failures.append(persistence_failure("persist-running", "run.json", updated.detail))
        if not manifest_present:
            persisted = resources.persist_evidence(
                "controller-failure.json",
                encode_failure_evidence((failure,)),
            )
            if isinstance(persisted, PersistenceRejected):
                failures.append(
                    persistence_failure(
                        "persist-controller-failure",
                        "controller-failure.json",
                        persisted.detail,
                    )
                )
        proof = resources.quiesce_and_seal()
        resources.abandon_after_failure(proof)
    except Exception as error:
        failures.append(controller_failure("abandon-after-failure", request.run_id.value, error))
    return tuple(failures)


def _nonterminal(
    resources: LeaseBackedFulfilment,
    assessment: BundleAssessment,
    trace: list[str],
) -> DurableNonterminal:
    return DurableNonterminal(
        resources.snapshot().bundle_path,
        assessment_failures(assessment),
        tuple(trace),
    )


def _with_close_failure(
    disposition: RunDisposition,
    failure: DiagnosticFailure,
) -> RunDisposition:
    if isinstance(disposition, PreflightRejected):
        return PreflightRejected((*disposition.failures, failure), disposition.trace)
    if isinstance(disposition, DurableNonterminal):
        return DurableNonterminal(
            disposition.bundle,
            (*disposition.failures, failure),
            disposition.trace,
        )
    return TerminalTrustFailure(
        disposition.bundle,
        (failure,),
        (*disposition.trace, "resource close failed after terminal publication"),
    )
