"""Replay the preparation transition from independent retained inputs."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from tools.install_sandbox.container.effect_verifier import EffectVerifier
from tools.install_sandbox.container.environment import FilesystemSnapshot
from tools.install_sandbox.container.expectation_builder import preservation_baseline
from tools.install_sandbox.container.repair_scenario import (
    MarkdownRepairScenario,
    PreparationBlocked,
    PreparationPlan,
)
from tools.install_sandbox.contracts.bound_mutation import BoundMarkdownMutation, PerformedMutation
from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.repair_progress import RepairProgress
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
    RepairProgress.from_data(evidence)
    _check_artifact_sequence(output)
    if evidence["progress"] == "not_started":
        _check_unstarted(evidence, output)
    if evidence["progress"] == "not_started":
        return None
    plan = MarkdownRepairScenario.from_case(case, sources).bind(
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
        _forbid_later_files(
            output,
            (
                "expectations/intermediate.json",
                "expectations/reinstall.json",
                "intermediate/before.json",
                "intermediate/performed.json",
                "intermediate/after.json",
                "intermediate/verification.json",
            ),
        )
        return None
    operation = BoundMarkdownMutation.from_data(read_json_evidence(output, operation_ref))
    if operation.destination != plan.operation.destination:
        raise ValueError("Mutation destination contradicts retained case")
    operation.verify_binding(safe_evidence_path(output, "case.json").read_bytes(), first)
    if (output / "intermediate/performed.json").exists():
        performed = PerformedMutation.from_data(
            read_json_evidence(output, "intermediate/performed.json")
        )
        if performed.operation != operation:
            raise ValueError("Retained byte operation contradicts performed mutation")
    _check_expectations(output, evidence, plan, expectations)
    return _observations(output, evidence, plan, operation, first, snapshot, same)


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
        expectations(output, plan.after_preparation_expectations)
        if (output / "expectations/reinstall.json").exists():
            pass  # Checked against the prepared physical baseline when repair starts.
        elif evidence["progress"] == "finished" or any(evidence["observations"].values()):
            raise ValueError("Mutation requires retained repair expectations")
    elif evidence["progress"] == "finished" or any(evidence["observations"].values()):
        raise ValueError("Intermediate execution requires independent expectations")


def _observations(
    output: Path,
    evidence: IntermediateEvidence,
    plan: PreparationPlan,
    operation: BoundMarkdownMutation,
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
    performed = PerformedMutation.from_data(
        read_json_evidence(output, "intermediate/performed.json")
    )
    performed.verify(operation, after)
    return _after(output, evidence, plan, after)


def _after(
    output: Path,
    evidence: IntermediateEvidence,
    plan: PreparationPlan,
    after: FilesystemSnapshot,
) -> tuple[ExpectationSet, FilesystemSnapshot] | None:
    computed = EffectVerifier().verify(plan.after_preparation_expectations, after)
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
    if not RepairProgress.from_data(evidence).permits_repair():
        return None
    return replace(
        plan.second_install_expectations, baseline=preservation_baseline(after, "reinstall")
    ), after


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


def _forbid_later_files(output: Path, relatives: tuple[str, ...]) -> None:
    for relative in relatives:
        path = safe_evidence_path(output, relative)
        if path.exists() or path.is_symlink():
            raise ValueError("Forbidden later preparation artifact without retained predecessor")


def _check_artifact_sequence(output: Path) -> None:
    """Raw blobs may precede metadata; future metadata requires its predecessor."""
    names = (
        "intermediate/operation.json",
        "expectations/intermediate.json",
        "expectations/reinstall.json",
        "intermediate/before.json",
        "intermediate/performed.json",
        "intermediate/after.json",
        "intermediate/verification.json",
    )
    retained = [safe_evidence_path(output, name).exists() for name in names]
    if retained != sorted(retained, reverse=True):
        raise ValueError("Forbidden later preparation metadata without retained predecessor")
