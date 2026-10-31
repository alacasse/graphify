"""Immutable legal durable prefixes, distinct from facts held only in memory."""

from dataclasses import dataclass, replace
from typing import Literal, cast

from tools.install_sandbox.contracts.results import (
    IntermediateEvidence,
    ObservationObstacle,
    VerificationMismatch,
    VerificationResult,
)
from tools.install_sandbox.contracts.spec import fields, text

ProgressName = Literal["not_started", "incomplete", "finished"]
RetainedField = Literal["operation_ref", "expectations_ref", "before", "after"]


@dataclass(frozen=True)
class DurableArtifact:
    """A writer acknowledgement issued only after an artifact is retained."""

    reference: str


@dataclass(frozen=True)
class FrozenVerification:
    complete: bool
    mismatches: tuple[VerificationMismatch, ...]
    obstacles: tuple[tuple[str, str, str, str], ...]

    @classmethod
    def capture(cls, result: VerificationResult) -> "FrozenVerification":
        return cls(
            result.complete,
            tuple(result.mismatches),
            tuple(
                (item["operation"], item["root"], item["path"], item["reason"])
                for item in result.obstacles
            ),
        )

    def thaw(self) -> VerificationResult:
        return VerificationResult(
            self.complete,
            list(self.mismatches),
            [
                ObservationObstacle(operation=o[0], root=o[1], path=o[2], reason=o[3])
                for o in self.obstacles
            ],
        )


def _optional_text(value: object) -> str | None:
    return None if value is None else text(value)


@dataclass(frozen=True)
class RepairProgress:
    progress: ProgressName = "not_started"
    operation_ref: str | None = None
    expectations_ref: str | None = None
    before: str | None = None
    after: str | None = None
    verification: FrozenVerification | None = None
    reason: str | None = "First installation not completed"

    def __post_init__(self) -> None:
        self._validate_prefix()
        self._validate_completion()

    def _validate_prefix(self) -> None:
        references = (self.operation_ref, self.expectations_ref, self.before, self.after)
        canonical = (
            "intermediate/operation.json",
            "expectations/intermediate.json",
            "intermediate/before.json",
            "intermediate/after.json",
        )
        if any(
            actual is not None and actual != expected
            for actual, expected in zip(references, canonical, strict=True)
        ):
            raise ValueError("Preparation artifact uses a foreign reference")
        chain = (*references, self.verification)
        populated = [item is not None for item in chain]
        if populated != sorted(populated, reverse=True):
            raise ValueError("Preparation facts must form a legal durable prefix")
        if self.progress == "not_started" and any(populated):
            raise ValueError("Unstarted preparation cannot retain execution facts")

    def _validate_completion(self) -> None:
        if self.progress not in {"not_started", "incomplete", "finished"}:
            raise ValueError("Unknown preparation progress")
        if self.progress == "finished" and (
            self.verification is None or not self.verification.complete
        ):
            raise ValueError("Finished preparation requires complete durable verification")

    @classmethod
    def from_data(cls, value: object) -> "RepairProgress":
        data = fields(
            value, "progress operation_ref expectations_ref observations verification reason"
        )
        observations = fields(data["observations"], "before after")
        verdict = data["verification"]
        if verdict is not None and not isinstance(verdict, VerificationResult):
            raise ValueError("Progress requires a decoded verification result")
        progress = text(data["progress"])
        if progress not in {"not_started", "incomplete", "finished"}:
            raise ValueError("Unknown preparation progress")
        return cls(
            cast(ProgressName, progress),
            _optional_text(data["operation_ref"]),
            _optional_text(data["expectations_ref"]),
            _optional_text(observations["before"]),
            _optional_text(observations["after"]),
            None if verdict is None else FrozenVerification.capture(verdict),
            _optional_text(data["reason"]),
        )

    def to_data(self) -> IntermediateEvidence:
        return {
            "progress": self.progress,
            "operation_ref": self.operation_ref,
            "expectations_ref": self.expectations_ref,
            "observations": {"before": self.before, "after": self.after},
            "verification": None if self.verification is None else self.verification.thaw(),
            "reason": self.reason,
        }

    def begin(self) -> "RepairProgress":
        if self.progress != "not_started":
            raise ValueError("Preparation already started")
        return replace(self, progress="incomplete", reason=None)

    def _retain(
        self,
        receipt: DurableArtifact,
        field: RetainedField,
        expected: str,
        predecessor: str | bool | None,
    ) -> "RepairProgress":
        if self.progress != "incomplete" or getattr(self, field) is not None or not predecessor:
            raise ValueError("Artifact cannot advance this durable prefix")
        if receipt.reference != expected:
            raise ValueError("Transition requires matching persistence acknowledgement")
        return replace(self, **{field: receipt.reference})

    def retained_operation(self, receipt: DurableArtifact) -> "RepairProgress":
        return self._retain(receipt, "operation_ref", "intermediate/operation.json", True)

    def retained_expectations(self, receipt: DurableArtifact) -> "RepairProgress":
        return self._retain(
            receipt, "expectations_ref", "expectations/intermediate.json", self.operation_ref
        )

    def retained_before(self, receipt: DurableArtifact) -> "RepairProgress":
        return self._retain(receipt, "before", "intermediate/before.json", self.expectations_ref)

    def retained_after(self, receipt: DurableArtifact) -> "RepairProgress":
        return self._retain(receipt, "after", "intermediate/after.json", self.before)

    def verified(self, receipt: DurableArtifact, verdict: VerificationResult) -> "RepairProgress":
        if not self.after or self.verification is not None:
            raise ValueError("Verification follows retained after observation once")
        if receipt.reference != "intermediate/verification.json":
            raise ValueError("Verification requires its durable acknowledgement")
        return replace(
            self,
            verification=FrozenVerification.capture(verdict),
            progress="finished" if verdict.complete else "incomplete",
        )

    def permits_repair(self) -> bool:
        verdict = self.verification
        return (
            self.progress == "finished"
            and verdict is not None
            and verdict.complete
            and not verdict.mismatches
            and not verdict.obstacles
        )

    def interrupt(self, reason: object) -> "RepairProgress":
        return replace(self, reason=str(reason))
