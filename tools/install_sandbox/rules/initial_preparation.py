"""Pure initial preparation transitions and independent evidence admissibility."""

from dataclasses import dataclass, replace
from typing import Literal

from tools.install_sandbox.contracts.initial_preparation import (
    CHECKPOINTS,
    INITIAL_ARTIFACTS,
    OPERATIONS,
    REFERENCES,
    InitialPreparationFacts,
    InitialPreparationRetained,
    InitialPreparationState,
    InitialPreparationStop,
)

ARTIFACT_BY_OPERATION: dict[str, str] = dict(zip(OPERATIONS, INITIAL_ARTIFACTS[:6], strict=True))


def _validate_facts(facts: InitialPreparationFacts) -> int:
    count = len(facts.completed)
    if facts.completed != OPERATIONS[:count] or count > len(OPERATIONS):
        raise ValueError("Acquired operations must form an initial prefix")
    if facts.verification_passed is not None and type(facts.verification_passed) is not bool:
        raise ValueError("Invalid verification outcome")
    if (facts.verification_passed is not None) != (count >= 5):
        raise ValueError("Verification outcome contradicts acquired operations")
    return count


def _validate_retention(retained: InitialPreparationRetained, count: int) -> int:
    refs = [getattr(retained, ARTIFACT_BY_OPERATION[op]) for op in OPERATIONS]
    nretained = sum(ref is not None for ref in refs)
    if any(ref is None for ref in refs[:nretained]) or nretained > count:
        raise ValueError("Retention must follow acquired operations")
    for name in INITIAL_ARTIFACTS:
        ref = getattr(retained, name)
        if ref is not None and ref != REFERENCES[name]:
            raise ValueError("Initial evidence has a foreign reference")
    return nretained


def _validate_stop(state: InitialPreparationState, count: int, nretained: int) -> None:
    if state.previous_checkpoint not in CHECKPOINTS[:-1] or state.stop is None:
        raise ValueError("Stopped preparation requires its previous checkpoint")
    rank = CHECKPOINTS.index(state.previous_checkpoint)
    stop = state.stop
    if (
        stop.operation != OPERATIONS[rank]
        or stop.category not in {"io", "validation"}
        or not stop.reason.strip()
        or stop.facts != state.facts
    ):
        raise ValueError("Invalid operational stop")
    if count not in {rank, rank + 1} or nretained not in {rank, rank + 1}:
        raise ValueError("Stop crosses an unpublished checkpoint")
    if state.retained.failure != REFERENCES["failure"]:
        raise ValueError("Stopped preparation requires a retained diagnostic")


def _validate_checkpoint(state: InitialPreparationState, count: int, nretained: int) -> None:
    rank = 5 if state.checkpoint == "blocked" else CHECKPOINTS.index(state.checkpoint)
    if count != rank or nretained != rank or state.retained.failure is not None:
        raise ValueError("Initial checkpoint contradicts acquired or retained facts")
    if state.stop is not None or state.previous_checkpoint is not None:
        raise ValueError("Only operational stops carry a diagnostic")


def _validate_verification(state: InitialPreparationState, count: int) -> None:
    if count == 6 and state.facts.verification_passed is not True:
        raise ValueError("Install expectations require conformant initial verification")
    if state.checkpoint == "blocked" and state.facts.verification_passed is not False:
        raise ValueError("Blocked preparation requires a nonconformant verdict")
    verified = state.checkpoint in {"verified", "ready"} or state.previous_checkpoint == "verified"
    if verified and state.facts.verification_passed is not True:
        raise ValueError("Verified checkpoint requires conformant verification")


def validate(state: InitialPreparationState) -> None:
    if state.checkpoint not in (*CHECKPOINTS, "blocked", "stopped"):
        raise ValueError("Unknown initial checkpoint")
    count = _validate_facts(state.facts)
    nretained = _validate_retention(state.retained, count)
    if state.checkpoint == "stopped":
        _validate_stop(state, count, nretained)
    else:
        _validate_checkpoint(state, count, nretained)
    _validate_verification(state, count)


class InitialPreparationLifecycle:
    """Keep acquired, retained and successfully published statements separate."""

    def __init__(self) -> None:
        self.published: InitialPreparationState | None = None
        self.facts = InitialPreparationFacts()
        self._retained = InitialPreparationRetained()
        self._candidate: InitialPreparationState | None = InitialPreparationState()
        self._stop: InitialPreparationStop | None = None

    def next_operation(self) -> str | None:
        if self._candidate is not None or self._stop is not None or self.published is None:
            return None
        if self.published.checkpoint not in CHECKPOINTS[:-1]:
            return None
        if len(self.facts.completed) != CHECKPOINTS.index(self.published.checkpoint):
            return None
        return OPERATIONS[len(self.facts.completed)]

    def acquire(self, operation: str, *, verification_passed: bool | None = None) -> None:
        if self.next_operation() != operation:
            raise ValueError("Operation is not authorized by the published checkpoint")
        if (operation == "verification") != (type(verification_passed) is bool):
            raise ValueError("Only verification acquires a boolean outcome")
        self.facts = InitialPreparationFacts(
            (*self.facts.completed, operation),
            verification_passed if operation == "verification" else self.facts.verification_passed,
        )

    def retain(self, operation: str, reference: str) -> None:
        if (
            self._candidate is not None
            or self._stop is not None
            or not self.facts.completed
            or self.facts.completed[-1] != operation
        ):
            raise ValueError("Retention requires the authorized acquired operation")
        name = ARTIFACT_BY_OPERATION[operation]
        if reference != REFERENCES[name] or getattr(self._retained, name) is not None:
            raise ValueError("Invalid initial retention receipt")
        self._retained = replace(self._retained, **{name: reference})
        checkpoint = CHECKPOINTS[len(self.facts.completed)]
        if operation == "verification" and not self.facts.verification_passed:
            checkpoint = "blocked"
        self._candidate = InitialPreparationState(checkpoint, self.facts, self._retained)
        validate(self._candidate)

    def stop(self, operation: str, category: str, reason: str) -> None:
        if self._candidate is not None or self._stop is not None or self.published is None:
            raise ValueError("Cannot stop outside an authorized operation")
        rank = CHECKPOINTS.index(self.published.checkpoint)
        if rank >= len(OPERATIONS) or operation != OPERATIONS[rank]:
            raise ValueError("Stop operation is not authorized")
        if category not in {"io", "validation"} or not reason.strip():
            raise ValueError("Invalid stop explanation")
        self._stop = InitialPreparationStop(operation, category, reason, self.facts)

    def failure_candidate(self) -> InitialPreparationState:
        """Document to retain; its retention claim becomes authoritative only on receipt."""
        if self._stop is None or self.published is None:
            raise ValueError("No operational stop is acquired")
        candidate = InitialPreparationState(
            "stopped",
            self.facts,
            replace(self._retained, failure=REFERENCES["failure"]),
            self._stop,
            self.published.checkpoint,
        )
        validate(candidate)
        return candidate

    def retain_failure(self, reference: str) -> None:
        if self._stop is None or reference != REFERENCES["failure"] or self._candidate is not None:
            raise ValueError("Failure retention requires an acquired operational stop")
        assert self.published is not None
        self._retained = replace(self._retained, failure=reference)
        self._candidate = InitialPreparationState(
            "stopped",
            self.facts,
            self._retained,
            self._stop,
            self.published.checkpoint,
        )
        validate(self._candidate)

    def publication_candidate(self) -> InitialPreparationState:
        if self._candidate is None:
            raise ValueError("No retained checkpoint is ready for publication")
        return self._candidate

    def acknowledge(self, candidate: InitialPreparationState) -> None:
        if candidate is not self._candidate:
            raise ValueError("Publication acknowledgement does not identify the candidate")
        self.published = candidate
        self._candidate = None


@dataclass(frozen=True)
class InitialPreparationInventory:
    present: frozenset[str] = frozenset()
    verification_passed: bool | None = None
    stopped_state: InitialPreparationState | None = None
    staged: tuple[frozenset[str], ...] = ()


@dataclass(frozen=True)
class InitialPreparationInspection:
    status: Literal["incomplete", "not_run"]
    checkpoint: str
    stop: InitialPreparationStop | None
    reason: str | None = None


def _published_rank(state: InitialPreparationState) -> int:
    if state.checkpoint == "stopped":
        assert state.previous_checkpoint is not None
        return CHECKPOINTS.index(state.previous_checkpoint)
    return 5 if state.checkpoint == "blocked" else CHECKPOINTS.index(state.checkpoint)


def _inspect_ownership(
    state: InitialPreparationState, inventory: InitialPreparationInventory, rank: int
) -> None:
    if inventory.present - set(INITIAL_ARTIFACTS):
        raise ValueError("Unknown initial evidence")
    required = {name for name in INITIAL_ARTIFACTS if getattr(state.retained, name) is not None}
    if not required <= inventory.present:
        raise ValueError("Published initial evidence is missing")
    terminal = state.checkpoint in {"blocked", "stopped", "ready"}
    allowed: set[str] = set(INITIAL_ARTIFACTS[:rank])
    staging_allowed: set[str] = {"failure"} if state.checkpoint == "stopped" else set()
    if not terminal:
        next_artifacts = {ARTIFACT_BY_OPERATION[OPERATIONS[rank]], "failure"}
        allowed |= next_artifacts
        staging_allowed |= next_artifacts
    elif state.checkpoint == "stopped":
        allowed |= required
    if inventory.present - allowed:
        raise ValueError("Initial evidence crosses an unpublished checkpoint")
    if any(not owners or not owners & staging_allowed for owners in inventory.staged):
        raise ValueError("Initial staging crosses an unpublished checkpoint")


def _inspect_prerequisites(
    state: InitialPreparationState, inventory: InitialPreparationInventory
) -> None:
    for index, name in enumerate(INITIAL_ARTIFACTS[:6]):
        if name in inventory.present and not set(INITIAL_ARTIFACTS[:index]) <= inventory.present:
            raise ValueError("Initial evidence is missing its prerequisites")
    if "verification" in inventory.present and type(inventory.verification_passed) is not bool:
        raise ValueError("Validated verdict and evidence contradict each other")
    if (
        state.facts.verification_passed is not None
        and state.facts.verification_passed != inventory.verification_passed
    ):
        raise ValueError("Initial verdict contradicts independently recomputed verdict")
    if "install_expectations" in inventory.present and inventory.verification_passed is not True:
        raise ValueError("Install expectations require a conformant verdict")


def _inspect_diagnostic_identity(
    state: InitialPreparationState, diagnostic: InitialPreparationState, rank: int
) -> None:
    validate(diagnostic)
    if diagnostic.checkpoint != "stopped":
        raise ValueError("Diagnostic does not describe an operational stop")
    if state.checkpoint == "stopped":
        if diagnostic != state:
            raise ValueError("Diagnostic contradicts published stop")
    elif diagnostic.previous_checkpoint != state.checkpoint:
        raise ValueError("Diagnostic crosses an unpublished checkpoint")
    if diagnostic.facts.completed[:rank] != state.facts.completed[:rank]:
        raise ValueError("Diagnostic contradicts published acquired facts")
    for name in INITIAL_ARTIFACTS[:rank]:
        if getattr(diagnostic.retained, name) != getattr(state.retained, name):
            raise ValueError("Diagnostic contradicts published retained facts")


def _inspect_diagnostic(
    state: InitialPreparationState, inventory: InitialPreparationInventory, rank: int
) -> None:
    diagnostic = inventory.stopped_state
    if ("failure" in inventory.present) != (diagnostic is not None):
        raise ValueError("Initial diagnostic requires its validated stopped state")
    if diagnostic is None:
        return
    _inspect_diagnostic_identity(state, diagnostic, rank)
    if state.checkpoint != "stopped":
        inspect(diagnostic, inventory)


def inspect(
    state: InitialPreparationState, inventory: InitialPreparationInventory
) -> InitialPreparationInspection:
    """Check independently validated physical evidence without promoting publication."""
    validate(state)
    rank = _published_rank(state)
    _inspect_ownership(state, inventory, rank)
    _inspect_prerequisites(state, inventory)
    _inspect_diagnostic(state, inventory, rank)
    diagnostic = inventory.stopped_state
    return InitialPreparationInspection(
        status(state),
        state.checkpoint,
        diagnostic.stop if diagnostic else state.stop,
        "Initial state is nonconformant or incomplete" if state.checkpoint == "blocked" else None,
    )


def status(state: InitialPreparationState) -> Literal["incomplete", "not_run"]:
    validate(state)
    return "not_run" if state.checkpoint in {"blocked", "stopped"} else "incomplete"
