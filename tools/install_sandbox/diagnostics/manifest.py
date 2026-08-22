"""Produce one versioned Diagnostic Manifest and content-bound evidence set."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from tools.install_sandbox.diagnostics.evidence import (
    EvidenceReference,
    EvidenceWriter,
    write_raw_facts,
    write_subject_evidence,
)
from tools.install_sandbox.sandbox_runtime.subject_types import SubjectRejected, SubjectVerified
from tools.install_sandbox.validation.completion import ValidationCompleted
from tools.install_sandbox.validation.plan_types import (
    AggregatePlan,
    LifecyclePlan,
    PurgePlan,
    ScopeIsolationPlan,
    UnsupportedPlan,
    ValidationRequest,
)
from tools.install_sandbox.validation.protocol import (
    ActionId,
)
from tools.install_sandbox.validation.results import (
    AggregateResult,
    DetailedScenarioResult,
    LifecycleResult,
    PhaseResult,
    PurgeResult,
    PurgeStatus,
    ScenarioStatus,
    ScopeIsolationResult,
    UnsupportedResult,
)

_MANIFEST_KIND = "graphify.install-sandbox.diagnostic-manifest"
_SCENARIO_KIND = "graphify.install-sandbox.scenario-result"
_PURGE_KIND = "graphify.install-sandbox.purge-result"


@dataclass(frozen=True, slots=True)
class ManifestContext:
    """Container-observed identities and selection bound into one manifest."""

    run_id: str
    image_identity: str
    harness_runtime_limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.run_id or not self.image_identity:
            raise ValueError("manifest context requires run and image identities")


@dataclass(frozen=True, slots=True)
class DiagnosticInput:
    """One coherent verified subject and completed Validation Plan result."""

    validation: ValidationCompleted
    subject: SubjectVerified

    def __post_init__(self) -> None:
        if self.validation.request.targets != self.subject.target_names:
            raise ValueError("verified subject target selection disagrees with validation")


@dataclass(frozen=True, slots=True)
class ProducedManifest:
    path: Path
    sha256: str
    complete: bool
    has_findings: bool


def _schema(kind: str) -> dict[str, object]:
    return {"kind": kind, "version": 1}


def _prepare_output(output: Path) -> None:
    if output.is_symlink():
        raise ValueError("diagnostic output cannot be a symlink")
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise ValueError("diagnostic output must be an absent or empty real directory")
        return
    output.mkdir(parents=True)


def _phase_result(phase: PhaseResult, fact_paths: dict[ActionId, str]) -> dict[str, object]:
    body: dict[str, object] = {
        "kind": phase.kind.value,
        "status": phase.status.value,
        "findings": [
            {"check": finding.check, "detail": finding.detail} for finding in phase.findings
        ],
    }
    if phase.reason is not None:
        body["reason"] = phase.reason
    if phase.blocked_by is not None:
        body["blocked_by"] = phase.blocked_by.value
    if phase.command is not None:
        body["command"] = fact_paths[phase.command.action_id]
    if phase.observation is not None:
        body["observation"] = fact_paths[phase.observation.action_id]
    if phase.failure is not None:
        body["failure"] = fact_paths[phase.failure.action_id]
    return body


def _scenario_identity(result: DetailedScenarioResult, index: int) -> str:
    if isinstance(result, LifecycleResult):
        return f"{index:03d}-target-{result.target}-{result.scope.value}"
    if isinstance(result, AggregateResult):
        return f"{index:03d}-aggregate-{result.scope.value}"
    if isinstance(result, ScopeIsolationResult):
        return (
            f"{index:03d}-isolation-{result.selected_scope.value}"
            f"-preserves-{result.preserved_scope.value}"
        )
    assert isinstance(result, UnsupportedResult)
    return f"{index:03d}-unsupported-{result.target}-{result.scope.value}"


def _scenario_body(
    result: DetailedScenarioResult,
    fact_paths: dict[ActionId, str],
) -> dict[str, object]:
    body: dict[str, object] = {
        "status": result.status.value,
        "runtime_limitations": list(result.runtime_limitations),
    }
    if isinstance(result, LifecycleResult):
        body.update({"kind": "target-lifecycle", "target": result.target, "scope": result.scope})
    elif isinstance(result, AggregateResult):
        body.update({"kind": "aggregate-uninstall", "scope": result.scope})
        if result.preparation is not None:
            body["preparation"] = fact_paths[result.preparation.action_id]
    elif isinstance(result, ScopeIsolationResult):
        body.update(
            {
                "kind": "scope-isolation",
                "selected_scope": result.selected_scope,
                "preserved_scope": result.preserved_scope,
            }
        )
    else:
        assert isinstance(result, UnsupportedResult)
        body.update(
            {
                "kind": "unsupported-target",
                "target": result.target,
                "scope": result.scope,
                "reason": result.reason,
                "phases": [],
            }
        )
        return body
    body["phases"] = [_phase_result(phase, fact_paths) for phase in result.phases]
    return body


def _write_scenarios(
    writer: EvidenceWriter,
    results: tuple[DetailedScenarioResult, ...],
    fact_paths: dict[ActionId, str],
) -> list[dict[str, object]]:
    manifest_results: list[dict[str, object]] = []
    for index, result in enumerate(results):
        identity = _scenario_identity(result, index)
        path = writer.write_document(
            f"scenarios/{identity}/result.json",
            _SCENARIO_KIND,
            _scenario_body(result, fact_paths),
        )
        manifest_results.append({"id": identity, "status": result.status.value, "result": path})
    return manifest_results


def _write_purge(
    writer: EvidenceWriter,
    result: PurgeResult,
    fact_paths: dict[ActionId, str],
) -> str:
    body: dict[str, object] = {
        "status": result.status.value,
        "runtime_limitations": list(result.runtime_limitations),
        "phases": [_phase_result(phase, fact_paths) for phase in result.phases],
    }
    if result.preparation is not None:
        body["preparation"] = fact_paths[result.preparation.action_id]
    return writer.write_document("purge/result.json", _PURGE_KIND, body)


def _plan_scenario(plan: object) -> dict[str, object]:
    if isinstance(plan, LifecyclePlan):
        return {
            "kind": "target-lifecycle",
            "target": plan.target,
            "scope": plan.scope.value,
            "phases": [phase.kind.value for phase in plan.phases],
        }
    if isinstance(plan, AggregatePlan):
        return {"kind": "aggregate-uninstall", "scope": plan.scope.value}
    if isinstance(plan, ScopeIsolationPlan):
        return {
            "kind": "scope-isolation",
            "selected_scope": plan.selected_scope.value,
            "preserved_scope": plan.preserved_scope.value,
        }
    assert isinstance(plan, UnsupportedPlan)
    return {
        "kind": "unsupported-target",
        "target": plan.target,
        "scope": plan.scope.value,
    }


def _plan_projection(validation: ValidationCompleted) -> dict[str, object]:
    plan = validation.plan
    assert isinstance(plan.purge, PurgePlan)
    return {
        "id": plan.plan_id,
        "scenarios": [_plan_scenario(scenario) for scenario in plan.scenarios],
        "purge": {"kind": "purge", "phase": plan.purge.purge.kind.value},
    }


def _runtime_limitations(
    context: ManifestContext,
    validation: ValidationCompleted,
) -> list[str]:
    values = [*context.harness_runtime_limitations]
    for result in (*validation.scenario_results, validation.purge_result):
        values.extend(result.runtime_limitations)
    return list(dict.fromkeys(values))


def _manifest_body(
    context: ManifestContext,
    diagnostic: DiagnosticInput,
    scenarios: list[dict[str, object]],
    purge_path: str,
    subject_evidence: dict[str, object],
    references: tuple[EvidenceReference, ...],
) -> dict[str, object]:
    validation = diagnostic.validation
    subject = diagnostic.subject
    summary = Counter(result.status.value for result in validation.scenario_results)
    return {
        "run": {
            "id": context.run_id,
            "image_identity": context.image_identity,
            "subject_identity": subject.identity,
        },
        "selection": {
            "targets": list(validation.request.targets),
            "scopes": [scope.value for scope in validation.request.scopes],
        },
        "validation_plan": _plan_projection(validation),
        "subject": {
            "identity": subject.identity,
            "version": subject.version,
            "executable": str(subject.executable),
            "prepared_source": str(subject.prepared_source),
            "built_artifact": str(subject.built_artifact),
            "published_targets": list(subject.target_names),
            **subject_evidence,
        },
        "summary": dict(sorted(summary.items())),
        "scenarios": scenarios,
        "purge": {"status": validation.purge_result.status.value, "result": purge_path},
        "runtime_limitations": _runtime_limitations(context, validation),
        "evidence": [reference.as_dict() for reference in references],
    }


def produce_manifest(
    output: Path,
    context: ManifestContext,
    diagnostic: DiagnosticInput,
) -> ProducedManifest:
    """Write subordinate evidence first and publish one content-bound manifest last."""

    _prepare_output(output)
    writer = EvidenceWriter(output)
    validation = diagnostic.validation
    subject_evidence = write_subject_evidence(writer, diagnostic.subject)
    fact_paths = write_raw_facts(writer, validation.raw_facts)
    scenarios = _write_scenarios(writer, validation.scenario_results, fact_paths)
    purge_path = _write_purge(writer, validation.purge_result, fact_paths)
    body = _manifest_body(
        context,
        diagnostic,
        scenarios,
        purge_path,
        subject_evidence,
        writer.references,
    )
    document = {"schema": _schema(_MANIFEST_KIND), **body}
    payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
    temporary = output / ".manifest.json.tmp"
    with temporary.open("xb") as handle:
        handle.write(payload)
    manifest_path = output / "manifest.json"
    temporary.replace(manifest_path)
    incomplete = (
        any(result.status is ScenarioStatus.INCOMPLETE for result in validation.scenario_results)
        or validation.purge_result.status is PurgeStatus.INCOMPLETE
    )
    findings = (
        any(result.status is ScenarioStatus.FINDING for result in validation.scenario_results)
        or validation.purge_result.status is PurgeStatus.FINDING
    )
    return ProducedManifest(
        manifest_path,
        hashlib.sha256(payload).hexdigest(),
        not incomplete,
        findings,
    )


def produce_preflight_manifest(
    output: Path,
    context: ManifestContext,
    request: ValidationRequest,
    rejection: SubjectRejected,
) -> ProducedManifest:
    """Publish structured incomplete evidence when the subject cannot be verified."""

    _prepare_output(output)
    writer = EvidenceWriter(output)
    subject_evidence = write_subject_evidence(writer, rejection)
    document = {
        "schema": _schema(_MANIFEST_KIND),
        "run": {
            "id": context.run_id,
            "image_identity": context.image_identity,
            "subject_identity": None,
        },
        "selection": {
            "targets": list(request.targets),
            "scopes": [scope.value for scope in request.scopes],
        },
        "validation_plan": None,
        "summary": {"INCOMPLETE": 1},
        "subject": {
            "status": "INCOMPLETE",
            "failed_stage": rejection.stage,
            "diagnostic_failure": rejection.detail,
            **subject_evidence,
        },
        "scenarios": [],
        "purge": {"status": "INCOMPLETE", "result": None},
        "runtime_limitations": list(context.harness_runtime_limitations),
        "evidence": [reference.as_dict() for reference in writer.references],
    }
    payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
    temporary = output / ".manifest.json.tmp"
    with temporary.open("xb") as handle:
        handle.write(payload)
    manifest_path = output / "manifest.json"
    temporary.replace(manifest_path)
    return ProducedManifest(
        manifest_path,
        hashlib.sha256(payload).hexdigest(),
        False,
        False,
    )
