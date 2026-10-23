"""Replay the preparation transition from independent retained inputs."""

import hashlib
from collections.abc import Callable
from pathlib import Path

from tools.install_sandbox.container.effect_verifier import EffectVerifier
from tools.install_sandbox.container.environment import FilesystemSnapshot
from tools.install_sandbox.container.intermediate_builder import (
    PreparationBlocked,
    PreparationPlan,
    prepare_intermediate,
)
from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.intermediate import PreparedByteRange
from tools.install_sandbox.contracts.results import (
    InstallTestResult,
    IntermediateEvidence,
    VerificationResult,
)
from tools.install_sandbox.host.evidence_reader import (
    read_json_evidence,
    safe_evidence_path,
    verification,
)


def replay_intermediate(
    result: InstallTestResult,
    case: EffectInstallCase,
    output: Path,
    sources: FilesystemSnapshot,
    installed: ExpectationSet,
    first: FilesystemSnapshot,
    verdict: VerificationResult,
    snapshot: Callable[[Path, str], FilesystemSnapshot],
    same: Callable[[FilesystemSnapshot, FilesystemSnapshot], bool],
    expectations: Callable[[Path, ExpectationSet], None],
) -> tuple[ExpectationSet, FilesystemSnapshot] | None:
    """Validate preparation links and continuity; return its repair inputs when complete."""
    evidence = result.intermediate_preparation
    assert evidence is not None
    _check_references(evidence, output)
    if evidence["progress"] == "not_started":
        return None
    plan = prepare_intermediate(
        case,
        sources,
        first,
        "steps/0/after.json",
        verdict,
        installed,
        safe_evidence_path(output, "case.json").read_bytes(),
    )
    if isinstance(plan, PreparationBlocked):
        _blocked(evidence, output)
        return None
    operation_ref = _available(output, evidence["operation_ref"], "intermediate/operation.json")
    if operation_ref is None:
        _require_no_later(evidence, "operation")
        return None
    operation = PreparedByteRange.from_data(read_json_evidence(output, operation_ref))
    document = _bound_document(output, operation, plan.operation, first)
    _check_expectations(output, evidence, plan, expectations)
    return _observations(output, evidence, plan, operation, document, first, snapshot, same)


def _bound_document(
    output: Path,
    operation: PreparedByteRange,
    expected_operation: PreparedByteRange,
    first: FilesystemSnapshot,
) -> bytes:
    # Bounds may be wrong yet valid: the independent oracle must expose that failure.
    if (
        operation.case_sha256,
        operation.observation_ref,
        operation.destination,
        operation.document_sha256,
    ) != (
        expected_operation.case_sha256,
        expected_operation.observation_ref,
        expected_operation.destination,
        expected_operation.document_sha256,
    ):
        raise ValueError(
            "Prepared operation contradicts its retained case or validated observation"
        )
    safe_evidence_path(output, operation.observation_ref)
    key = operation.destination.root, operation.destination.path
    document = first.contents.get(key)
    if (
        document is None
        or hashlib.sha256(document).hexdigest() != operation.document_sha256
        or operation.end > len(document)
    ):
        raise ValueError("Prepared operation has invalid document binding or bounds")
    return document


def _check_expectations(
    output: Path,
    evidence: IntermediateEvidence,
    plan: PreparationPlan,
    expectations: Callable[[Path, ExpectationSet], None],
) -> None:
    if (
        _available(output, evidence["expectations_ref"], "expectations/intermediate.json")
        is not None
    ):
        expectations(output, plan.after_removal_expectations)
        if (output / "expectations/reinstall.json").exists():
            expectations(output, plan.second_install_expectations)
        elif evidence["progress"] == "finished" or any(evidence["observations"].values()):
            raise ValueError("Mutation requires retained repair expectations")
    elif evidence["progress"] == "finished" or any(evidence["observations"].values()):
        raise ValueError("Intermediate execution requires independent expectations")


def _observations(
    output: Path,
    evidence: IntermediateEvidence,
    plan: PreparationPlan,
    operation: PreparedByteRange,
    document: bytes,
    first: FilesystemSnapshot,
    snapshot: Callable[[Path, str], FilesystemSnapshot],
    same: Callable[[FilesystemSnapshot, FilesystemSnapshot], bool],
) -> tuple[ExpectationSet, FilesystemSnapshot] | None:
    refs = {
        key: _available(output, ref, f"intermediate/{key}.json")
        for key, ref in evidence["observations"].items()
    }
    if refs["before"] is None:
        if refs["after"] or evidence["verification"] or evidence["progress"] == "finished":
            raise ValueError("Intermediate execution requires its before observation")
        return None
    before = snapshot(output, refs["before"])
    if not same(first, before):
        if refs["after"] or evidence["verification"] or evidence["progress"] == "finished":
            raise ValueError("Changed validated document cannot be mutated")
        return None
    if refs["after"] is None:
        if evidence["verification"] or evidence["progress"] == "finished":
            raise ValueError("Intermediate verdict requires its after observation")
        return None
    after = snapshot(output, refs["after"])
    return _after(output, evidence, plan, operation, document, after)


def _after(
    output: Path,
    evidence: IntermediateEvidence,
    plan: PreparationPlan,
    operation: PreparedByteRange,
    document: bytes,
    after: FilesystemSnapshot,
) -> tuple[ExpectationSet, FilesystemSnapshot] | None:
    key = operation.destination.root, operation.destination.path
    actual_document = after.contents.get(key)
    if (
        actual_document is not None
        and actual_document != document[: operation.start] + document[operation.end :]
    ):
        raise ValueError("Intermediate observation contradicts the applied byte operation")
    computed = EffectVerifier().verify(plan.after_removal_expectations, after)
    stored = _available(output, None, "intermediate/verification.json")
    if stored is not None:
        saved = verification(read_json_evidence(output, stored))
        if computed != saved:
            raise ValueError("Intermediate verification contradicts independent expectations")
    else:
        saved = None
    if evidence["verification"] is None:
        if evidence["progress"] == "finished":
            raise ValueError("Finished intermediate preparation requires verification")
        return None
    if saved != evidence["verification"]:
        raise ValueError("Intermediate verification contradicts independent expectations")
    assert saved is not None
    if (
        evidence["progress"] != "finished"
        or not saved.complete
        or saved.mismatches
        or saved.obstacles
    ):
        return None
    return plan.second_install_expectations, after


def _available(output: Path, ref: str | None, canonical: str) -> str | None:
    if ref is not None:
        safe_evidence_path(output, ref).read_bytes()
        return ref
    return canonical if safe_evidence_path(output, canonical).exists() else None


def _require_no_later(evidence: IntermediateEvidence, missing: str) -> None:
    if (
        evidence["progress"] == "finished"
        or any(evidence["observations"].values())
        or evidence["verification"]
    ):
        raise ValueError(f"Intermediate execution requires retained {missing}")


def _blocked(evidence: IntermediateEvidence, output: Path) -> None:
    _require_no_later(evidence, "plan")
    if (
        evidence["operation_ref"]
        or evidence["expectations_ref"]
        or (output / "intermediate").exists()
    ):
        raise ValueError("Blocked preparation contradicts execution evidence")


def _check_references(evidence: IntermediateEvidence, output: Path) -> None:
    refs = evidence["observations"]
    canonical = {"before": "intermediate/before.json", "after": "intermediate/after.json"}
    for key, ref in refs.items():
        if ref is not None and ref != canonical[key]:
            raise ValueError("Intermediate observation must use its own reference")
    for key, expected in (
        ("operation_ref", "intermediate/operation.json"),
        ("expectations_ref", "expectations/intermediate.json"),
    ):
        if evidence[key] is not None and evidence[key] != expected:
            raise ValueError("Intermediate evidence must use its own reference")
    if evidence["progress"] == "not_started":
        _check_unstarted(evidence, output)


def _check_unstarted(evidence: IntermediateEvidence, output: Path) -> None:
    if (
        any(evidence["observations"].values())
        or evidence["operation_ref"]
        or evidence["expectations_ref"]
        or evidence["verification"]
    ):
        raise ValueError("Unstarted intermediate preparation has execution evidence")
    if (output / "intermediate").exists() or (output / "expectations/intermediate.json").exists():
        raise ValueError("Unstarted intermediate preparation has retained artifacts")
