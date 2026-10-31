"""Orchestrate domain transitions only after their evidence is retained."""

from dataclasses import asdict, replace

from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.container.effect_verifier import EffectVerifier
from tools.install_sandbox.container.environment import FilesystemSnapshot, same_observation
from tools.install_sandbox.container.evidence_writer import TestResultWriter
from tools.install_sandbox.container.expectation_builder import preservation_baseline
from tools.install_sandbox.container.repair_scenario import (
    MarkdownRepairScenario,
    PreparationBlocked,
    PreparationPlan,
)
from tools.install_sandbox.contracts.bound_mutation import PerformedMutation
from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.repair_progress import RepairProgress
from tools.install_sandbox.contracts.results import EvidenceWriteError, InstallTestResult


def _publish(progress: RepairProgress, writer: TestResultWriter, result: InstallTestResult) -> None:
    result.intermediate_preparation = progress.to_data()
    writer.write_result(result)


def _archive_plan(
    plan: PreparationPlan, writer: TestResultWriter, result: InstallTestResult
) -> None:
    progress = RepairProgress.from_data(result.intermediate_preparation)
    writer.write_metadata("intermediate/operation.json", plan.operation.to_data())
    progress = progress.retained_operation(writer.acknowledge("intermediate/operation.json"))
    _publish(progress, writer, result)
    writer.write_metadata(
        "expectations/intermediate.json", plan.after_preparation_expectations.to_data()
    )
    progress = progress.retained_expectations(writer.acknowledge("expectations/intermediate.json"))
    _publish(progress, writer, result)
    writer.write_metadata("expectations/reinstall.json", plan.second_install_expectations.to_data())


def _prepare_and_observe(
    plan: PreparationPlan,
    first_after: FilesystemSnapshot,
    environment: EffectEnvironment,
    writer: TestResultWriter,
    result: InstallTestResult,
) -> FilesystemSnapshot:
    progress = RepairProgress.from_data(result.intermediate_preparation)
    before = environment.observe_intermediate(writer, "before")
    progress = progress.retained_before(writer.acknowledge("intermediate/before.json"))
    _publish(progress, writer, result)
    if not same_observation(first_after, before):
        raise ValueError("Environment changed since validated first observation")
    plan.operation.apply(
        environment, (writer.output_directory / "case.json").read_bytes(), first_after
    )
    performed = PerformedMutation.capture(plan.operation, environment)
    writer.write_metadata("intermediate/performed.json", performed.to_data())
    after = environment.observe_intermediate(writer, "after")
    progress = progress.retained_after(writer.acknowledge("intermediate/after.json"))
    _publish(progress, writer, result)
    verdict = EffectVerifier().verify(plan.after_preparation_expectations, after)
    writer.write_metadata("intermediate/verification.json", asdict(verdict))
    progress = progress.verified(writer.acknowledge("intermediate/verification.json"), verdict)
    _publish(progress, writer, result)
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
    progress = RepairProgress.from_data(result.intermediate_preparation).begin()
    result.status = "incomplete"
    _publish(progress, writer, result)
    try:
        verdict = result.steps[0]["verification"]
        assert verdict is not None
        plan = MarkdownRepairScenario.from_case(case, sources).bind(
            first_after,
            "steps/0/after.json",
            verdict,
            installed,
            (writer.output_directory / "case.json").read_bytes(),
        )
        if isinstance(plan, PreparationBlocked):
            raise ValueError(plan.reason)
        _archive_plan(plan, writer, result)
        after = _prepare_and_observe(plan, first_after, environment, writer, result)
        progress = RepairProgress.from_data(result.intermediate_preparation)
        if progress.permits_repair():
            repaired = replace(
                plan.second_install_expectations, baseline=preservation_baseline(after, "reinstall")
            )
            writer.write_metadata("expectations/reinstall.json", repaired.to_data())
            return repaired, after
        result.status = (
            "failed" if progress.verification and progress.verification.complete else "incomplete"
        )
        progress = progress.interrupt("Intermediate preparation did not conform")
    except (OSError, ValueError, EvidenceWriteError) as error:
        progress = RepairProgress.from_data(result.intermediate_preparation).interrupt(error)
        result.status = "incomplete"
    result.steps[1]["skip_reason"] = "Intermediate preparation failed; repair not evaluated"
    _publish(progress, writer, result)
    return None
