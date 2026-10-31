"""Perform only the actions authorized by the published repair protocol."""

from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.container.evidence_writer import TestResultWriter
from tools.install_sandbox.container.markdown_mutation import (
    apply_markdown_mutation,
    capture_performed_mutation,
)
from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import (
    EvidenceWriteError,
    InstallTestResult,
)
from tools.install_sandbox.rules.repair_actions import (
    ApplyMarkdownMutation,
    Completion,
    ObserveSnapshot,
    RetainEvidence,
)
from tools.install_sandbox.rules.repair_protocol import (
    Ready,
    RepairInputs,
    RepairSession,
    Stop,
    begin,
)


def _perform(
    action: RetainEvidence | ObserveSnapshot | ApplyMarkdownMutation,
    inputs: RepairInputs,
    environment: EffectEnvironment,
) -> Completion:
    if isinstance(action, RetainEvidence):
        return action.completion
    if isinstance(action, ObserveSnapshot):
        return action.complete(environment.observe_intermediate(action.phase))
    operation = action.operation
    apply_markdown_mutation(operation, environment, inputs.case_bytes, inputs.first_after)
    return action.complete(capture_performed_mutation(operation, environment))


def _advance(
    session: RepairSession,
    inputs: RepairInputs,
    environment: EffectEnvironment,
    writer: TestResultWriter,
    result: InstallTestResult,
) -> Ready | Stop:
    try:
        pending = session.pending
        if pending is not None:
            session.confirm_checkpoint(writer.write_checkpoint(result, pending))
        while True:
            action = session.next_action()
            if isinstance(action, (Ready, Stop)):
                return action
            completion = _perform(action, inputs, environment)
            artifact = session.prepare(completion)
            receipt = writer.retain(artifact)
            pending = session.record(completion, receipt)
            session.confirm_checkpoint(writer.write_checkpoint(result, pending))
    except BaseException:
        session.abort()
        writer.halted = True
        raise


def conduct_intermediate(
    case: EffectInstallCase,
    sources: FilesystemSnapshot,
    installed: ExpectationSet,
    first_after: FilesystemSnapshot,
    environment: EffectEnvironment,
    writer: TestResultWriter,
    result: InstallTestResult,
) -> tuple[ExpectationSet, FilesystemSnapshot] | None:
    case_bytes = (writer.output_directory / "case.json").read_bytes()
    if EffectInstallCase.from_json(case_bytes.decode("utf-8")) != case:
        raise ValueError("Archived case differs from execution case")
    inputs = RepairInputs(case_bytes, sources, installed, first_after, result.steps[0])
    session = begin(inputs)
    result.status = "incomplete"
    try:
        outcome = _advance(session, inputs, environment, writer, result)
    except (OSError, ValueError, EvidenceWriteError):
        # Keep the last published prefix. No publication retry or dependent effect.
        writer.halted = True
        return None
    if isinstance(outcome, Ready):
        return outcome.expectations, outcome.baseline
    result.status = outcome.diagnostic
    result.steps[1]["skip_reason"] = outcome.reason
    writer.write_result(result)
    return None
