"""The pure owner of step progression and admissible retained evidence."""

from dataclasses import dataclass, replace
from typing import Literal

from tools.install_sandbox.contracts.results import (
    CommandEvidence,
    CommandFacts,
    StepRetained,
    StepState,
    StepStop,
    VerificationFacts,
    VerificationResult,
)

PHASES = (
    "idle",
    "preparation",
    "expectations",
    "command",
    "command_evidence",
    "observation",
    "verification",
    "verification_evidence",
    "termination",
    "terminal",
)
Artifact = Literal[
    "before", "expectations", "environment", "stdout", "stderr", "after", "verification", "failure"
]
Status = Literal["not_run", "incomplete", "passed", "failed"]


@dataclass(frozen=True)
class PreparationObserved:
    reference: str
    usable: bool = True


@dataclass(frozen=True)
class Prepared:
    pass


@dataclass(frozen=True)
class ExpectationsRetained:
    reference: str


@dataclass(frozen=True)
class CommandReturned:
    command: CommandEvidence


@dataclass(frozen=True)
class CommandRetained:
    stdout_file: str
    stderr_file: str


@dataclass(frozen=True)
class ObservationRetained:
    reference: str


@dataclass(frozen=True)
class VerificationComputed:
    verification: VerificationResult


@dataclass(frozen=True)
class VerificationRetained:
    reference: str


@dataclass(frozen=True)
class Terminate:
    pass


@dataclass(frozen=True)
class StopStep:
    reason: str


Event = (
    PreparationObserved
    | Prepared
    | ExpectationsRetained
    | CommandReturned
    | CommandRetained
    | ObservationRetained
    | VerificationComputed
    | VerificationRetained
    | Terminate
    | StopStep
)


def start(operation: str) -> StepState:
    return replace(StepState.idle(operation), phase="preparation")


def _reference(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Retained evidence requires a reference")
    return value


def validate(state: object) -> None:
    """Validate untrusted decoded states as well as values constructed in process."""
    if not isinstance(state, StepState) or not state.operation:
        raise ValueError("Expected a named step")
    phase = state.stop.phase if state.phase == "stopped" and state.stop else state.phase
    if phase not in PHASES or (state.phase == "stopped") != (state.stop is not None):
        raise ValueError("Invalid stop or phase")
    if state.stop is not None and (phase in {"idle", "terminal"} or not state.stop.reason):
        raise ValueError("Invalid stopped phase")
    rank = PHASES.index(phase)
    facts, retained = state.facts, state.retained
    flags = (facts.prepared, retained.before_usable, retained.command)
    if any(type(value) is not bool for value in flags):
        raise ValueError("Step facts require boolean flags")
    if facts.prepared != (rank >= 2):
        raise ValueError("Preparation facts contradict phase")
    if (retained.expectations is not None) != (rank >= 3):
        raise ValueError("Expectations contradict phase")
    if (facts.command is not None) != (rank >= 4) or retained.command != (rank >= 5):
        raise ValueError("Command facts contradict phase")
    if (retained.after is not None) != (rank >= 6):
        raise ValueError("Observation contradicts phase")
    if (facts.verification is not None) != (rank >= 7):
        raise ValueError("Verification contradicts phase")
    if (retained.verification is not None) != (rank >= 8):
        raise ValueError("Retained verification contradicts phase")
    if rank == 0 and retained != StepRetained():
        raise ValueError("Idle step has retained evidence")
    if rank >= 2 and retained.before is None:
        raise ValueError("Prepared step requires a retained prior observation")
    if not retained.before_usable and (retained.before is None or rank > 1):
        raise ValueError("Unusable preparation cannot authorize a command")
    for value in (retained.before, retained.expectations, retained.after, retained.verification):
        if value is not None:
            _reference(value)
    if facts.command is not None:
        decoded = CommandFacts.from_data(facts.command.to_data())
        if decoded != facts.command:
            raise ValueError("Malformed command facts")
        if (
            bool(decoded.stdout_file) != retained.command
            or bool(decoded.stderr_file) != retained.command
        ):
            raise ValueError("Command output references contradict retention")
    if facts.verification is not None:
        verdict = facts.verification.result()
        if (
            VerificationFacts.capture(VerificationResult.from_data(_verdict_data(verdict)))
            != facts.verification
        ):
            raise ValueError("Malformed verification facts")


def _verdict_data(verdict: VerificationResult) -> dict[str, object]:
    from dataclasses import asdict

    return asdict(verdict)


def advance(state: StepState, event: Event) -> StepState:
    validate(state)
    if state.phase in {"idle", "terminal", "stopped"}:
        raise ValueError("Step cannot advance from an inactive phase")
    facts, retained = state.facts, state.retained
    if type(event) is StopStep:
        candidate = replace(
            state, phase="stopped", stop=StepStop(state.phase, _reference(event.reason))
        )
    elif (
        type(event) is PreparationObserved
        and state.phase == "preparation"
        and retained.before is None
    ):
        candidate = replace(
            state,
            retained=replace(
                retained, before=_reference(event.reference), before_usable=event.usable
            ),
        )
    elif type(event) is Prepared and state.phase == "preparation" and retained.before_usable:
        candidate = replace(state, phase="expectations", facts=replace(facts, prepared=True))
    elif type(event) is ExpectationsRetained and state.phase == "expectations":
        candidate = replace(
            state,
            phase="command",
            retained=replace(retained, expectations=_reference(event.reference)),
        )
    elif type(event) is CommandReturned and state.phase == "command":
        command = CommandFacts.from_data(event.command)
        candidate = replace(state, phase="command_evidence", facts=replace(facts, command=command))
    elif type(event) is CommandRetained and state.phase == "command_evidence":
        assert facts.command is not None
        command = replace(
            facts.command,
            stdout_file=_reference(event.stdout_file),
            stderr_file=_reference(event.stderr_file),
        )
        candidate = replace(
            state,
            phase="observation",
            facts=replace(facts, command=command),
            retained=replace(retained, command=True),
        )
    elif type(event) is ObservationRetained and state.phase == "observation":
        candidate = replace(
            state,
            phase="verification",
            retained=replace(retained, after=_reference(event.reference)),
        )
    elif type(event) is VerificationComputed and state.phase == "verification":
        verdict = VerificationResult.from_data(_verdict_data(event.verification))
        candidate = replace(
            state,
            phase="verification_evidence",
            facts=replace(facts, verification=VerificationFacts.capture(verdict)),
        )
    elif type(event) is VerificationRetained and state.phase == "verification_evidence":
        candidate = replace(
            state,
            phase="termination",
            retained=replace(retained, verification=_reference(event.reference)),
        )
    elif type(event) is Terminate and state.phase == "termination":
        candidate = replace(state, phase="terminal")
    else:
        raise ValueError("Event does not follow the step phase")
    validate(candidate)
    return candidate


def status(state: StepState) -> Status:
    validate(state)
    if state.phase == "idle":
        return "not_run"
    if state.phase != "terminal":
        return "incomplete"
    command, verdict = state.facts.command, state.facts.verification
    assert command is not None and verdict is not None
    if command.state != "completed" or not verdict.complete or verdict.obstacles:
        return "incomplete"
    return "passed" if command.exit_code == 0 and not verdict.mismatches else "failed"


@dataclass(frozen=True)
class RetainedFacts:
    expectations: bool = False
    external_expectations: bool = False
    before: bool = False
    before_usable: bool = True
    environment: bool = False
    stdout: bool = False
    stderr: bool = False
    after: bool = False
    verification: VerificationResult | None = None
    stop: StepStop | None = None
    stopped_state: StepState | None = None
    staged: tuple[frozenset[Artifact], ...] = ()


@dataclass(frozen=True)
class StepInspection:
    status: Status
    published_phase: str
    stop: StepStop | None


def inspect(published_state: StepState, retained_facts: RetainedFacts) -> StepInspection:
    """Check all physical facts without promoting the last published statement."""
    validate(published_state)
    state, present = published_state, retained_facts
    if state.phase not in {"idle", "preparation", "observation", "terminal", "stopped"}:
        raise ValueError("Step was not published at a publication boundary")
    diagnostic = present.stopped_state
    if diagnostic is not None:
        validate(diagnostic)
        if (
            diagnostic.phase != "stopped"
            or diagnostic.operation != state.operation
            or diagnostic.stop != present.stop
        ):
            raise ValueError("Malformed diagnostic state")
        if state.phase == "stopped" and state != diagnostic:
            raise ValueError("Diagnostic state contradicts published stop")
        if state.phase == "idle" or state.phase == "terminal":
            raise ValueError("Diagnostic cannot follow an inactive step")
        for name in ("before", "expectations", "command", "after", "verification"):
            value = getattr(state.retained, name)
            if value and value != getattr(diagnostic.retained, name):
                raise ValueError("Diagnostic contradicts published retained facts")
        if state.facts.command is not None and diagnostic.facts.command != state.facts.command:
            raise ValueError("Diagnostic contradicts published command")
        if (
            state.facts.verification is not None
            and diagnostic.facts.verification != state.facts.verification
        ):
            raise ValueError("Diagnostic contradicts published verification")
        inspect(diagnostic, replace(present, stopped_state=None))
    elif present.stop is not None and state.stop is None:
        raise ValueError("Unpublished diagnostic requires its acquired facts")
    declared, fact = state.retained, state.facts
    required = (
        (declared.before is not None, present.before),
        (declared.expectations is not None, present.expectations),
        (declared.command, present.environment and present.stdout and present.stderr),
        (declared.after is not None, present.after),
        (declared.verification is not None, present.verification is not None),
    )
    if any(expected and not actual for expected, actual in required):
        raise ValueError("Published facts are missing retained evidence")
    if declared.before is not None and declared.before_usable != present.before_usable:
        raise ValueError("Preparation observation contradicts declaration")
    if declared.verification is not None:
        assert present.verification is not None
        if fact.verification != VerificationFacts.capture(present.verification):
            raise ValueError("Retained verdict contradicts declaration")
    command_evidence = present.environment or present.stdout or present.stderr
    if command_evidence and (
        not (present.expectations or present.external_expectations)
        or not present.before
        or not present.before_usable
    ):
        raise ValueError("Command evidence requires usable preparation and expectations")
    if present.stdout and not present.environment or present.stderr and not present.stdout:
        raise ValueError("Command evidence must form environment/stdout/stderr prefix")
    if present.verification is not None and not present.after:
        raise ValueError("Verdict requires a retained observation")
    stop = present.stop or state.stop
    if state.stop is not None and present.stop != state.stop:
        raise ValueError("Stop diagnostic contradicts declaration")
    phase = state.stop.phase if state.stop else state.phase
    if stop is not None:
        if (
            stop.phase not in PHASES[1:-1]
            or not stop.reason
            or PHASES.index(stop.phase) < PHASES.index(phase)
        ):
            raise ValueError("Stop diagnostic is unreachable from declaration")
        if state.phase == "terminal":
            raise ValueError("Terminal step cannot have a stop diagnostic")
        if state.phase == "preparation" and PHASES.index(stop.phase) >= 5:
            raise ValueError("Stop crossed an unpublished command checkpoint")
        phase = stop.phase
    if state.phase == "idle":
        allowed: set[Artifact] = set()
    elif state.phase == "terminal":
        allowed = {
            "before",
            "expectations",
            "environment",
            "stdout",
            "stderr",
            "after",
            "verification",
        }
    else:
        rank = PHASES.index(phase)
        allowed = {"before", "failure"}
        if stop is None or rank >= 2:
            allowed.add("expectations")
        if stop is None or rank >= 4:
            allowed |= {"environment", "stdout", "stderr"}
        if rank >= 5:
            allowed.add("after")
        if rank >= 7 or (stop is None and rank >= 5):
            allowed.add("verification")
    actual = {
        kind
        for kind, exists in (
            ("before", present.before),
            ("expectations", present.expectations),
            ("environment", present.environment),
            ("stdout", present.stdout),
            ("stderr", present.stderr),
            ("after", present.after),
            ("verification", present.verification is not None),
            ("failure", present.stop is not None),
        )
        if exists
    }
    staging_allowed = allowed.copy()
    if (
        not (present.expectations or present.external_expectations)
        or not present.before
        or not present.before_usable
    ):
        staging_allowed -= {"environment", "stdout", "stderr"}
    if not present.after:
        staging_allowed.discard("verification")
    if not present.before_usable:
        staging_allowed -= {"after", "verification"}
    if actual - allowed or any(not owners & staging_allowed for owners in present.staged):
        raise ValueError("Evidence exceeds the published step or stop phase")
    if state.phase == "terminal" and present.staged:
        raise ValueError("Terminal step retains staging")
    if not present.before_usable and (
        command_evidence or present.after or present.verification is not None
    ):
        raise ValueError("Unusable preparation cannot have command evidence")
    return StepInspection(status(state), state.phase, stop)
