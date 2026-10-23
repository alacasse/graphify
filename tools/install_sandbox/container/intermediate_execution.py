"""Apply an observation-bound byte range and retain the independent comparison."""

import hashlib
import os
from dataclasses import asdict

from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.container.effect_verifier import EffectVerifier
from tools.install_sandbox.container.environment import FilesystemSnapshot, same_observation
from tools.install_sandbox.container.evidence_writer import TestResultWriter
from tools.install_sandbox.container.intermediate_builder import (
    PreparationBlocked,
    PreparationPlan,
    prepare_intermediate,
)
from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.intermediate import PreparedByteRange
from tools.install_sandbox.contracts.results import EvidenceWriteError, InstallTestResult


def apply_prepared_range(
    environment: EffectEnvironment,
    operation: PreparedByteRange,
    case_bytes: bytes,
    first_after: FilesystemSnapshot,
) -> None:
    """Check identity and bounds, then apply bytes without interpreting Markdown."""
    preparation = environment.case.intermediate_preparation
    if preparation is None or operation.destination != preparation.destination:
        raise ValueError("Operation destination differs from the case")
    if operation.case_sha256 != hashlib.sha256(case_bytes).hexdigest():
        raise ValueError("Operation case digest differs from the retained case")
    if operation.observation_ref != "steps/0/after.json":
        raise ValueError("Operation must reference the validated first observation")
    key = (operation.destination.root, operation.destination.path)
    retained = first_after.contents[key]
    if operation.document_sha256 != hashlib.sha256(retained).hexdigest():
        raise ValueError("Operation document digest differs from the first observation")
    if not 0 <= operation.start < operation.end <= len(retained):
        raise ValueError("Operation byte bounds exceed the retained document")
    root = environment.project if key[0] == "project" else environment.home
    path = root / key[1]
    if path.resolve() != path or not path.is_file():
        raise ValueError("Operation requires the original regular document")
    with os.fdopen(os.open(path, os.O_RDWR | os.O_NOFOLLOW), "r+b") as stream:
        current = stream.read()
        if current != retained:
            raise ValueError("Document changed since its validated observation")
        stream.seek(0)
        stream.write(current[: operation.start] + current[operation.end :])
        stream.truncate()


def _archive_plan(
    plan: PreparationPlan, writer: TestResultWriter, result: InstallTestResult
) -> None:
    record = result.intermediate_preparation
    assert record is not None
    writer.write_metadata("intermediate/operation.json", plan.operation.to_data())
    record["operation_ref"] = "intermediate/operation.json"
    writer.write_result(result)
    writer.write_metadata(
        "expectations/intermediate.json", plan.after_removal_expectations.to_data()
    )
    record["expectations_ref"] = "expectations/intermediate.json"
    writer.write_result(result)
    writer.write_metadata("expectations/reinstall.json", plan.second_install_expectations.to_data())


def _remove_and_observe(
    plan: PreparationPlan,
    first_after: FilesystemSnapshot,
    environment: EffectEnvironment,
    writer: TestResultWriter,
    result: InstallTestResult,
) -> FilesystemSnapshot:
    record = result.intermediate_preparation
    assert record is not None
    before = environment.observe_intermediate(writer, "before")
    record["observations"]["before"] = "intermediate/before.json"
    writer.write_result(result)
    if not same_observation(first_after, before):
        raise ValueError("Environment changed since the validated first observation")
    apply_prepared_range(
        environment,
        plan.operation,
        (writer.output_directory / "case.json").read_bytes(),
        first_after,
    )
    after = environment.observe_intermediate(writer, "after")
    record["observations"]["after"] = "intermediate/after.json"
    writer.write_result(result)
    verdict = EffectVerifier().verify(plan.after_removal_expectations, after)
    writer.write_metadata("intermediate/verification.json", asdict(verdict))
    record["verification"] = verdict
    record["progress"] = "finished" if verdict.complete else "incomplete"
    return after


def conduct_intermediate(
    case: EffectInstallCase,
    sources: FilesystemSnapshot,
    installed: ExpectationSet,
    first_after: FilesystemSnapshot,
    environment: EffectEnvironment,
    writer: TestResultWriter,
    result: InstallTestResult,
) -> tuple[ExpectationSet, FilesystemSnapshot] | None:
    record = result.intermediate_preparation
    assert record is not None
    record["progress"], record["reason"] = "incomplete", None
    result.status = "incomplete"
    writer.write_result(result)
    try:
        verdict = result.steps[0]["verification"]
        assert verdict is not None
        plan = prepare_intermediate(
            case,
            sources,
            first_after,
            "steps/0/after.json",
            verdict,
            installed,
            (writer.output_directory / "case.json").read_bytes(),
        )
        if isinstance(plan, PreparationBlocked):
            raise ValueError(plan.reason)
        _archive_plan(plan, writer, result)
        after = _remove_and_observe(plan, first_after, environment, writer, result)
    except (OSError, ValueError, EvidenceWriteError) as error:
        record["reason"] = str(error)
        result.status = "incomplete"
    else:
        verified = record["verification"]
        assert verified is not None
        if verified.complete and not verified.mismatches and not verified.obstacles:
            writer.write_result(result)
            return plan.second_install_expectations, after
        result.status = "failed" if verified.complete else "incomplete"
        record["reason"] = "Intermediate preparation did not conform"
    result.steps[1]["skip_reason"] = "Intermediate preparation failed; repair not evaluated"
    writer.write_result(result)
    return None
