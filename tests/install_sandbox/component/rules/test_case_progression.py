"""Independent case decision tables built from valid local lifecycle states."""

from dataclasses import FrozenInstanceError, replace
from typing import Literal

import pytest

from tools.install_sandbox.contracts.initial_preparation import (
    OPERATIONS,
    REFERENCES,
    InitialPreparationState,
)
from tools.install_sandbox.contracts.results import (
    RepairCheckpoint,
    RepairProgress,
    StepState,
    VerificationResult,
)
from tools.install_sandbox.rules import initial_preparation as initial
from tools.install_sandbox.rules import step_lifecycle as step
from tools.install_sandbox.rules.case_progression import (
    CaseDecision,
    CaseFacts,
    CaseShape,
    evaluate,
)


def prepared(
    count: int = 6, *, blocked: bool = False, stopped: bool = False
) -> InitialPreparationState:
    lifecycle = initial.InitialPreparationLifecycle()
    state = lifecycle.publication_candidate()
    lifecycle.acknowledge(state)
    for operation in OPERATIONS[:count]:
        lifecycle.acquire(
            operation,
            **({"verification_passed": not blocked} if operation == "verification" else {}),
        )
        lifecycle.retain(operation, REFERENCES[initial.ARTIFACT_BY_OPERATION[operation]])
        state = lifecycle.publication_candidate()
        lifecycle.acknowledge(state)
    if stopped:
        lifecycle.stop(OPERATIONS[count], "io", "Unavailable storage")
        lifecycle.retain_failure(REFERENCES["failure"])
        state = lifecycle.publication_candidate()
        lifecycle.acknowledge(state)
    return state


def installation(count: int = 9, *, code: int = 0, stopped: bool = False) -> StepState:
    state = step.start("install")
    events = (
        step.PreparationObserved("before"),
        step.Prepared(),
        step.ExpectationsRetained("expectations"),
        step.CommandReturned(
            {
                "args": ["install"],
                "cwd": "/project",
                "state": "completed",
                "exit_code": code,
                "reason": None,
                "stdout_file": None,
                "stderr_file": None,
            }
        ),
        step.CommandRetained("stdout", "stderr"),
        step.ObservationRetained("after"),
        step.VerificationComputed(VerificationResult()),
        step.VerificationRetained("verification"),
        step.Terminate(),
    )
    for event in events[:count]:
        state = step.advance(state, event)
    return step.advance(state, step.StopStep("Storage unavailable")) if stopped else state


def repair(
    stage: str = "started", outcome: Literal["incomplete", "ready", "failed"] = "incomplete"
) -> RepairProgress:
    # These are published protocol facts, not a recomputation of the case decision.
    generations = {"not_started": 0, "started": 1, "verification_retained": 8, "ready": 9}
    return RepairProgress(RepairCheckpoint(stage, generations[stage], None), outcome)


IDLE = StepState.idle("install")
PASSED = installation()
READY = prepared()


@pytest.mark.parametrize("count", range(6))
def test_initial_publication_prefixes_authorize_only_preparation(count: int) -> None:
    assert evaluate(
        CaseShape(("install", "install"), False), CaseFacts(prepared(count), (IDLE, IDLE))
    ) == CaseDecision("incomplete", "initial_preparation")


@pytest.mark.parametrize("state", [prepared(5, blocked=True), prepared(0, stopped=True)])
def test_initial_terminal_results_end_the_invocation(state: InitialPreparationState) -> None:
    assert evaluate(
        CaseShape(("install", "install"), False), CaseFacts(state, (IDLE, IDLE))
    ) == CaseDecision("not_run", None)


@pytest.mark.parametrize(
    "first,second,expected",
    [
        (IDLE, IDLE, CaseDecision("incomplete", "installation")),
        (installation(3), IDLE, CaseDecision("incomplete", "installation")),
        (installation(3, stopped=True), IDLE, CaseDecision("incomplete", None)),
        (installation(code=1), IDLE, CaseDecision("failed", None)),
        (PASSED, IDLE, CaseDecision("incomplete", "reinstallation")),
        (PASSED, installation(5), CaseDecision("incomplete", "reinstallation")),
        (PASSED, installation(5, stopped=True), CaseDecision("incomplete", None)),
        (PASSED, installation(code=1), CaseDecision("failed", None)),
        (PASSED, PASSED, CaseDecision("passed", None)),
    ],
)
def test_reinstall_table(first: StepState, second: StepState, expected: CaseDecision) -> None:
    assert (
        evaluate(CaseShape(("install", "install"), False), CaseFacts(READY, (first, second)))
        == expected
    )


@pytest.mark.parametrize("count", range(9))
def test_first_step_publication_prefixes(count: int) -> None:
    assert evaluate(
        CaseShape(("install", "install"), False), CaseFacts(READY, (installation(count), IDLE))
    ) == CaseDecision("incomplete", "installation")


def test_records_are_frozen() -> None:
    decision = evaluate(
        CaseShape(("install", "install"), False), CaseFacts(READY, (PASSED, PASSED))
    )
    with pytest.raises(FrozenInstanceError):
        decision.status = "failed"  # pyright: ignore[reportAttributeAccessIssue]


@pytest.mark.parametrize(
    "shape,facts",
    [
        (CaseShape(("install", "other"), False), CaseFacts(READY, (PASSED, IDLE))),
        (
            CaseShape(("install", "install"), False),
            CaseFacts(prepared(), (replace(IDLE, phase="terminal"), IDLE)),
        ),
        (CaseShape(("install", "install"), False), CaseFacts(prepared(0), (installation(0), IDLE))),
        (
            CaseShape(("install", "install"), False),
            CaseFacts(prepared(5, blocked=True), (IDLE, installation(0))),
        ),
        (
            CaseShape(("install", "install"), False),
            CaseFacts(READY, (installation(code=1), installation(0))),
        ),
        (
            CaseShape(("install", "install"), False),
            CaseFacts(READY, (installation(0, stopped=True), installation(0))),
        ),
        (CaseShape(("install", "install"), True), CaseFacts(READY, (PASSED, installation(0)))),
    ],
)
def test_invalid_local_facts_and_dependencies_are_never_hidden(
    shape: CaseShape, facts: CaseFacts
) -> None:
    with pytest.raises(ValueError):
        evaluate(shape, facts)


@pytest.mark.parametrize(
    "progress,second,expected",
    [
        (None, IDLE, CaseDecision("incomplete", "repair")),
        (repair("not_started"), IDLE, CaseDecision("incomplete", "repair")),
        (repair(), IDLE, CaseDecision("incomplete", "repair")),
        (repair("verification_retained", "failed"), IDLE, CaseDecision("failed", None)),
        (repair("ready", "ready"), IDLE, CaseDecision("incomplete", "reinstallation")),
        (repair("ready", "ready"), PASSED, CaseDecision("passed", None)),
    ],
)
def test_repair_table(
    progress: RepairProgress | None, second: StepState, expected: CaseDecision
) -> None:
    assert (
        evaluate(
            CaseShape(("install", "install"), True), CaseFacts(READY, (PASSED, second), progress)
        )
        == expected
    )


@pytest.mark.parametrize(
    "shape,facts",
    [
        (CaseShape(("install", "install"), False), CaseFacts(READY, (PASSED, IDLE), repair())),
        (CaseShape(("install", "install"), True), CaseFacts(READY, (IDLE, IDLE), repair())),
        (
            CaseShape(("install", "install"), True),
            CaseFacts(READY, (installation(code=1), IDLE), repair()),
        ),
        (
            CaseShape(("install", "install"), True),
            CaseFacts(prepared(5, blocked=True), (IDLE, IDLE), repair()),
        ),
        (
            CaseShape(("install", "install"), True),
            CaseFacts(READY, (PASSED, installation(0)), repair()),
        ),
        (
            CaseShape(("install", "install"), True),
            CaseFacts(READY, (PASSED, installation(0)), repair("verification_retained", "failed")),
        ),
    ],
)
def test_repair_dependencies(shape: CaseShape, facts: CaseFacts) -> None:
    with pytest.raises(ValueError):
        evaluate(shape, facts)


GROUP_OPERATIONS = ("install", "install-group-1", "install-group-2", "uninstall")


@pytest.mark.parametrize("completed", range(5))
def test_group_authorizes_only_next_operation(completed: int) -> None:
    states = tuple(
        replace(PASSED if index < completed else IDLE, operation=operation)
        for index, operation in enumerate(GROUP_OPERATIONS)
    )
    expected = (
        CaseDecision("passed", None)
        if completed == 4
        else CaseDecision(
            "incomplete",
            "installation"
            if completed == 0
            else "uninstallation"
            if completed == 3
            else "installation",
            completed,
        )
    )
    assert evaluate(CaseShape(GROUP_OPERATIONS, False), CaseFacts(READY, states)) == expected


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("stopped", [False, True])
def test_group_stops_at_unsuccessful_operation(index: int, stopped: bool) -> None:
    states = tuple(
        replace(
            PASSED
            if position < index
            else installation(5, stopped=True)
            if position == index and stopped
            else installation(code=1)
            if position == index
            else IDLE,
            operation=operation,
        )
        for position, operation in enumerate(GROUP_OPERATIONS)
    )
    decision = evaluate(CaseShape(GROUP_OPERATIONS, False), CaseFacts(READY, states))
    assert decision.segment is None
    assert decision.status == ("incomplete" if stopped else "failed")


@pytest.mark.parametrize("index", [1, 2, 3])
def test_group_rejects_out_of_order_operation(index: int) -> None:
    states = tuple(
        replace(PASSED if position == index else IDLE, operation=operation)
        for position, operation in enumerate(GROUP_OPERATIONS)
    )
    with pytest.raises(ValueError, match="preceding"):
        evaluate(CaseShape(GROUP_OPERATIONS, False), CaseFacts(READY, states))


@pytest.mark.parametrize("count", [1, 23, 31])
def test_dynamic_group_progression(count: int) -> None:
    operations = ("install", *(f"install-group-{index}" for index in range(1, count)), "uninstall")
    for completed in range(len(operations) + 1):
        states = tuple(
            replace(PASSED if index < completed else IDLE, operation=operation)
            for index, operation in enumerate(operations)
        )
        decision = evaluate(CaseShape(operations, False), CaseFacts(READY, states))
        assert decision.status == ("passed" if completed == len(operations) else "incomplete")
        if completed < len(operations):
            assert decision.segment == ("uninstallation" if completed == count else "installation")
