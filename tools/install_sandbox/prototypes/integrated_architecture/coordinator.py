"""Thin lifecycle ordering for the integrated architecture prototype."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .bundle import (
    BundleFaults,
    PersistenceRejected,
    TerminalCommitRejected,
)
from .diagnostics import (
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
    build_manifest,
    classify_ci,
)
from .documents import (
    DiagnosticFailure,
    PersistenceFailure,
    RunningRunRecord,
    encode_document,
)
from .domain import build_validation_plan, compile_catalog, run_validation
from .model import (
    ApplicationOutcome,
    CatalogRejected,
    HarnessPolicy,
    PlanRejected,
    RawCatalogDocument,
    RunId,
    ValidationIncomplete,
    ValidationRequest,
)
from .resources import (
    ContainerClaimed,
    DockerNamespaceRegistry,
    LeaseBackedFulfilment,
    ResourceFaults,
)


@dataclass(frozen=True)
class RunRequest:
    run_id: RunId
    selection: str
    image_identity: str
    subject_identity: str
    catalog_documents: tuple[RawCatalogDocument, ...]
    validation: ValidationRequest
    policy: HarnessPolicy
    observed_raw_exit: int | None = None
    interrupt_signal: str | None = None


@dataclass(frozen=True)
class PreflightRejected:
    reasons: tuple[str, ...]


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
    failures: tuple[str, ...]
    trace: tuple[str, ...]


@dataclass(frozen=True)
class TerminalTrustFailure:
    bundle: Path
    failures: tuple[DiagnosticFailure, ...]
    trace: tuple[str, ...]


type RunDisposition = (
    PreflightRejected | DurableTerminal | DurableNonterminal | TerminalTrustFailure
)


class RunController:
    """Own the order while delegating every domain, resource, and trust decision."""

    def __init__(
        self,
        output_root: Path,
        sandbox_root: Path,
        registry: DockerNamespaceRegistry,
    ) -> None:
        self._output_root = output_root
        self._sandbox_root = sandbox_root
        self._registry = registry

    def run(
        self,
        request: RunRequest,
        *,
        resource_faults: ResourceFaults | None = None,
        bundle_faults: BundleFaults | None = None,
        publication: PublicationFact | None = None,
    ) -> RunDisposition:
        trace: list[str] = []
        running = RunningRunRecord(
            request.run_id.value,
            request.selection,
            request.image_identity,
            request.subject_identity,
            "allocated",
        )
        resources = LeaseBackedFulfilment.allocate(
            self._output_root,
            request.run_id.value,
            request.run_id,
            encode_document(running),
            self._sandbox_root,
            self._registry,
            faults=ResourceFaults() if resource_faults is None else resource_faults,
            bundle_faults=BundleFaults() if bundle_faults is None else bundle_faults,
        )
        trace.append("running Run Record persisted before catalog compilation")
        try:
            prepared = self._run_application(resources, request, trace)
            if isinstance(prepared, DurableNonterminal):
                return prepared
            expected, outcome = prepared
            persistence_failures = self._persist_diagnostic_inputs(resources, expected, outcome)
            resources.quiesce_and_seal()
            trace.append("cleanup, absence proof, and evidence sealing completed")
            return self._terminalize(
                resources,
                request,
                expected,
                outcome,
                persistence_failures,
                Published("prototype-bundle") if publication is None else publication,
                trace,
            )
        finally:
            resources.close()

    @staticmethod
    def _run_application(
        resources: LeaseBackedFulfilment,
        request: RunRequest,
        trace: list[str],
    ) -> tuple[ExpectedDiagnostic, ApplicationOutcome] | DurableNonterminal:
        catalog = compile_catalog(request.catalog_documents)
        if isinstance(catalog, CatalogRejected):
            return _rejected(resources, catalog.reasons, trace)
        planned = build_validation_plan(catalog.catalog, request.validation, request.policy)
        if isinstance(planned, PlanRejected):
            return _rejected(resources, planned.reasons, trace)
        expected = ExpectedDiagnostic(
            request.run_id.value,
            request.selection,
            request.image_identity,
            request.subject_identity,
            planned.plan.projection,
        )
        trace.append("domain-owned Validation Plan compiled")
        claim = resources.reserve_container(f"graphify-{request.run_id.value}")
        if not isinstance(claim, ContainerClaimed):
            return _rejected(resources, ("exact container name unavailable",), trace)
        outcome = run_validation(planned.plan, request.run_id, resources.fulfil)
        trace.append("application completed through one correlated fulfilment seam")
        return expected, outcome

    @staticmethod
    def _terminalize(
        resources: LeaseBackedFulfilment,
        request: RunRequest,
        expected: ExpectedDiagnostic,
        outcome: ApplicationOutcome,
        failures: tuple[DiagnosticFailure, ...],
        publication: PublicationFact,
        trace: list[str],
    ) -> RunDisposition:
        observed_exit = _observed_exit(request, outcome)
        facts = TerminalFacts(observed_exit, request.interrupt_signal, failures)
        publish_failure = _publish_terminal(resources, expected, facts, trace)
        if publish_failure is not None:
            return publish_failure
        return _reopen_and_classify(
            resources,
            expected,
            outcome,
            observed_exit,
            publication,
            trace,
        )

    @staticmethod
    def _persist_diagnostic_inputs(
        resources: LeaseBackedFulfilment,
        expected: ExpectedDiagnostic,
        outcome: ApplicationOutcome,
    ) -> tuple[DiagnosticFailure, ...]:
        failures: list[DiagnosticFailure] = []
        host_log = "\n".join(item.operation for item in resources.snapshot().chronology).encode()
        host_result = resources.persist_evidence("runner.log", host_log)
        if isinstance(host_result, PersistenceRejected):
            failures.append(PersistenceFailure("persist", "runner.log", host_result.detail))
        inventory = tuple(
            entry.reference
            for entry in resources.read_bundle().entries
            if str(entry.relative_path)
            not in {"run.json", "runner.log", "manifest.json", "report.md"}
        )
        manifest = build_manifest(expected, outcome, inventory)
        manifest_result = resources.persist_evidence(
            "manifest.json",
            encode_document(manifest),
        )
        if isinstance(manifest_result, PersistenceRejected):
            failures.append(PersistenceFailure("persist", "manifest.json", manifest_result.detail))
        return tuple(failures)


def _rejected(
    resources: LeaseBackedFulfilment,
    reasons: tuple[str, ...],
    trace: list[str],
) -> DurableNonterminal:
    return DurableNonterminal(resources.snapshot().bundle_path, reasons, tuple(trace))


def _publish_terminal(
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
        return _rejected(resources, (report_result.detail,), trace)
    trace.append("report persisted before terminal Run Record")
    with_report = assess_bundle(resources.read_bundle(), expected, facts)
    if not isinstance(with_report, ReadyToCommit):
        return _nonterminal(resources, with_report, trace)
    committed = resources.commit_terminal(
        resources.read_bundle(),
        encode_document(with_report.terminal_record),
    )
    if isinstance(committed, TerminalCommitRejected):
        return _rejected(resources, (committed.detail,), trace)
    trace.append("terminal Run Record committed last and exclusively")
    return None


def _reopen_and_classify(
    resources: LeaseBackedFulfilment,
    expected: ExpectedDiagnostic,
    outcome: ApplicationOutcome,
    observed_exit: int,
    publication: PublicationFact,
    trace: list[str],
) -> RunDisposition:
    reopened = assess_bundle(resources.read_bundle(), expected)
    if isinstance(reopened, InvalidBundle):
        trace.append("fresh terminal reassessment failed")
        return TerminalTrustFailure(
            resources.snapshot().bundle_path,
            reopened.failures,
            tuple(trace),
        )
    if not isinstance(reopened, CompletedAssessment):
        return _rejected(
            resources,
            ("fresh view did not prove terminal completion",),
            trace,
        )
    trace.append("fresh reopen and reassessment completed before CI")
    decision = classify_ci(CIClassificationInput(reopened, observed_exit, publication))
    trace.append("publication fact supplied before pure CI classification")
    return DurableTerminal(
        resources.snapshot().bundle_path,
        outcome,
        reopened,
        decision,
        tuple(trace),
    )


def _observed_exit(request: RunRequest, outcome: ApplicationOutcome) -> int:
    if request.observed_raw_exit is not None:
        return request.observed_raw_exit
    if isinstance(outcome, ValidationIncomplete):
        return 2
    if outcome.findings:
        return 1
    if request.interrupt_signal == "SIGINT":
        return 130
    if request.interrupt_signal == "SIGTERM":
        return 143
    return 0


def _nonterminal(
    resources: LeaseBackedFulfilment,
    assessment: object,
    trace: list[str],
) -> DurableNonterminal:
    failures = getattr(assessment, "failures", ())
    detail = tuple(str(item) for item in failures) or (
        f"unexpected assessment: {type(assessment).__name__}",
    )
    return DurableNonterminal(resources.snapshot().bundle_path, detail, tuple(trace))
