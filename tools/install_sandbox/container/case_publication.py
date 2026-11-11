"""Publish a detached case decision before acknowledging any local progress."""

import copy
import json
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import replace

from tools.install_sandbox.container.evidence_writer import TestResultWriter, result_document
from tools.install_sandbox.contracts.effect_case import EffectInstallCase, unique_object
from tools.install_sandbox.contracts.initial_preparation import InitialPreparationState
from tools.install_sandbox.contracts.results import (
    CheckpointReceipt,
    EvidenceWriteError,
    InstallTestResult,
    RepairCheckpoint,
    RepairProgress,
    StepState,
)
from tools.install_sandbox.rules.case_progression import (
    CaseDecision,
    CaseFacts,
    CaseShape,
    evaluate,
)
from tools.install_sandbox.rules.initial_preparation import InitialPreparationLifecycle
from tools.install_sandbox.rules.repair_actions import artifact_digest
from tools.install_sandbox.rules.repair_protocol import RepairSession


class CasePublisher:
    """Own the last acknowledged facts and the complete published case document."""

    def __init__(self, case: EffectInstallCase, writer: TestResultWriter) -> None:
        self.shape = CaseShape.from_case(case)
        self.writer = writer
        self.facts = CaseFacts(
            InitialPreparationState(),
            (StepState.idle(self.shape.operations[0]), StepState.idle(self.shape.operations[1])),
            RepairProgress(RepairCheckpoint("not_started", 0, None), "incomplete")
            if self.shape.requires_repair
            else None,
        )
        self.result = InstallTestResult(
            {
                "name": case.name,
                "target": case.target,
                "scope": case.scope,
                "key": case.key.to_data(),
            },
            self.facts.initial,
            list(self.facts.steps),
            self.decision.status,
            {"journal": "journal.log"},
            self.facts.repair.checkpoint.to_data() if self.facts.repair else None,
        )

    @property
    def decision(self) -> CaseDecision:
        return evaluate(self.shape, self.facts)

    def publish_initial(self, lifecycle: InitialPreparationLifecycle) -> None:
        checkpoint = lifecycle.publication_candidate()
        self._publish(
            replace(self.facts, initial=checkpoint), lambda: lifecycle.acknowledge(checkpoint)
        )

    def publish_step(self, index: int, state: StepState) -> None:
        if index not in (0, 1):
            raise ValueError("Case publication requires one of its two steps")
        steps = (state, self.facts.steps[1]) if index == 0 else (self.facts.steps[0], state)
        self._publish(replace(self.facts, steps=steps))

    def publish_repair(self, session: RepairSession) -> None:
        pending = session.pending
        if pending is None or session.progress != self.facts.repair:
            raise EvidenceWriteError("Repair publication does not follow confirmed case facts")
        receipt = CheckpointReceipt(pending.session_id, pending.generation, pending.sha256)
        self._publish(
            replace(self.facts, repair=pending.progress),
            lambda: session.confirm_checkpoint(receipt),
        )

    def _publish(self, facts: CaseFacts, acknowledge: Callable[[], None] | None = None) -> None:
        try:
            if self.writer.halted:
                raise EvidenceWriteError("Case publisher has halted")
            decision = evaluate(self.shape, facts)
            candidate = copy.deepcopy(
                replace(
                    self.result,
                    preparation=facts.initial,
                    steps=list(facts.steps),
                    intermediate_preparation=(
                        facts.repair.checkpoint.to_data() if facts.repair else None
                    ),
                    status=decision.status,
                )
            )
            expected = result_document(candidate)
            timing = self.writer.measure("finalize") if decision.segment is None else nullcontext()
            with timing:
                self.writer.write_result(copy.deepcopy(candidate))
                self._verify(expected)
                if acknowledge is not None:
                    acknowledge()
            self.facts, self.result = facts, candidate
        except BaseException as error:
            self.writer.halted = True
            if isinstance(error, Exception) and not isinstance(error, EvidenceWriteError):
                raise EvidenceWriteError(f"Case publication failed: {error}") from error
            raise

    def _verify(self, expected: dict[str, object]) -> None:
        path = self.writer.output_directory / "result.json"
        if path.is_symlink() or not path.is_file():
            raise EvidenceWriteError("Case document has not been retained")
        published = json.loads(path.read_bytes(), object_pairs_hook=unique_object)
        if artifact_digest(published) != artifact_digest(expected):
            raise EvidenceWriteError("Published case document differs from its candidate")
