"""Perform only the actions authorized by the published repair protocol."""

from tools.install_sandbox.container.case_publication import CasePublisher
from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.container.evidence_writer import TestResultWriter
from tools.install_sandbox.container.file_mutation import (
    apply_mutation,
    capture_performed_mutation,
)
from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import (
    EvidenceWriteError,
)
from tools.install_sandbox.rules.repair_actions import (
    ApplyMutation,
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
    action: RetainEvidence | ObserveSnapshot | ApplyMutation,
    inputs: RepairInputs,
    environment: EffectEnvironment,
) -> Completion:
    if isinstance(action, RetainEvidence):
        return action.completion
    if isinstance(action, ObserveSnapshot):
        return action.complete(environment.observe_intermediate(action.phase))
    operation = action.operation
    apply_mutation(operation, environment, inputs.case_bytes, inputs.first_after, inputs.sources)
    return action.complete(capture_performed_mutation(operation, environment))


def _advance(
    session: RepairSession,
    inputs: RepairInputs,
    environment: EffectEnvironment,
    writer: TestResultWriter,
    publisher: CasePublisher,
) -> Ready | Stop:
    try:
        pending = session.pending
        if pending is not None:
            publisher.publish_repair(session)
        while True:
            action = session.next_action()
            if isinstance(action, (Ready, Stop)):
                return action
            completion = _perform(action, inputs, environment)
            artifact = session.prepare(completion)
            receipt = writer.retain(artifact)
            session.record(completion, receipt)
            publisher.publish_repair(session)
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
    publisher: CasePublisher,
) -> tuple[ExpectationSet, FilesystemSnapshot] | None:
    case_bytes = (writer.output_directory / "case.json").read_bytes()
    if EffectInstallCase.from_json(case_bytes.decode("utf-8")) != case:
        raise ValueError("Archived case differs from execution case")
    inputs = RepairInputs(case_bytes, sources, installed, first_after, publisher.facts.steps[0])
    session = begin(inputs)
    try:
        outcome = _advance(session, inputs, environment, writer, publisher)
    except (OSError, ValueError, EvidenceWriteError):
        # Keep the last published prefix. No publication retry or dependent effect.
        writer.halted = True
        return None
    if isinstance(outcome, Ready):
        return outcome.expectations, outcome.baseline
    return None
