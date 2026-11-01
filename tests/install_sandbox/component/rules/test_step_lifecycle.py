"""Transitions and retained prefixes are independent from runner and physical paths."""

from dataclasses import replace
from typing import cast

import pytest

from tools.install_sandbox.contracts.results import (
    StepFacts,
    StepState,
    VerificationMismatch,
    VerificationResult,
)
from tools.install_sandbox.rules import step_lifecycle as life


def events(verdict: VerificationResult | None = None, code: int = 0) -> tuple[life.Event, ...]:
    return (
        life.PreparationObserved("before"),
        life.Prepared(),
        life.ExpectationsRetained("expectations"),
        life.CommandReturned(
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
        life.CommandRetained("stdout", "stderr"),
        life.ObservationRetained("after"),
        life.VerificationComputed(verdict or VerificationResult()),
        life.VerificationRetained("verdict"),
        life.Terminate(),
    )


def through(count: int, verdict: VerificationResult | None = None, code: int = 0) -> StepState:
    state = life.start("install")
    for event in events(verdict, code)[:count]:
        state = life.advance(state, event)
    return state


@pytest.mark.parametrize(
    "code,verdict,expected",
    [
        (0, VerificationResult(), "passed"),
        (1, VerificationResult(), "failed"),
        (0, VerificationResult(False), "incomplete"),
        (
            0,
            VerificationResult(True, [VerificationMismatch("content", "home", "x", "a", "b")]),
            "failed",
        ),
    ],
)
def test_terminal_status_requires_publication(
    code: int, verdict: VerificationResult, expected: life.Status
) -> None:
    assert life.status(through(8, verdict, code)) == "incomplete"
    terminal = through(9, verdict, code)
    assert life.status(terminal) == expected
    assert StepState.from_data(terminal.to_data()) == terminal


def test_order_is_closed_and_cannot_repeat_command():
    for count in range(9):
        state = through(count)
        for event in (
            life.Terminate(),
            life.CommandReturned(cast(life.CommandReturned, events()[3]).command),
        ):
            if (
                count == 3
                and isinstance(event, life.CommandReturned)
                or count == 8
                and isinstance(event, life.Terminate)
            ):
                continue
            with pytest.raises(ValueError):
                life.advance(state, event)
    with pytest.raises(ValueError):
        life.advance(through(0), cast(life.Event, object()))
    with pytest.raises(ValueError):
        life.status(replace(through(0), phase="terminal"))
    with pytest.raises(ValueError):
        life.advance(replace(through(3), facts=StepFacts()), events()[3])


def test_caller_mutations_are_detached():
    command_event = cast(life.CommandReturned, events()[3])
    state = through(3)
    state = life.advance(state, command_event)
    command_event.command["args"].append("forged")
    command = state.command
    assert command is not None
    assert command["args"] == ["install"]
    command["args"].append("also-forged")
    verdict = VerificationResult()
    state = life.advance(state, life.CommandRetained("stdout", "stderr"))
    state = life.advance(state, life.ObservationRetained("after"))
    state = life.advance(state, life.VerificationComputed(verdict))
    verdict.complete = False
    captured = state.verification
    assert captured is not None
    captured.complete = False
    assert state.verification is not None and state.verification.complete


def test_beginning_allows_command_write_prefix_but_no_future_observation():
    state = through(0)
    for facts in (
        life.RetainedFacts(before=True),
        life.RetainedFacts(before=True, expectations=True, environment=True),
        life.RetainedFacts(
            before=True, expectations=True, environment=True, stdout=True, stderr=True
        ),
    ):
        assert life.inspect(state, facts).status == "incomplete"
    for facts in (
        life.RetainedFacts(stdout=True),
        life.RetainedFacts(after=True),
        life.RetainedFacts(staged=(frozenset({"after"}),)),
        life.RetainedFacts(verification=VerificationResult()),
    ):
        with pytest.raises(ValueError):
            life.inspect(state, facts)


def test_command_publication_allows_after_and_verdict_without_promotion():
    state = through(5)
    facts = life.RetainedFacts(
        before=True,
        expectations=True,
        environment=True,
        stdout=True,
        stderr=True,
        after=True,
        verification=VerificationResult(),
    )
    assert life.inspect(state, facts).status == "incomplete"
    assert (
        life.inspect(
            state, replace(facts, after=False, verification=None, staged=(frozenset({"after"}),))
        ).status
        == "incomplete"
    )
    assert life.inspect(through(9), facts).status == "passed"
    with pytest.raises(ValueError):
        life.inspect(through(9), replace(facts, staged=(frozenset({"after"}),)))


def test_unusable_before_is_inspectable_and_prevents_command():
    state = life.advance(life.start("reinstall"), life.PreparationObserved("before1", False))
    with pytest.raises(ValueError):
        life.advance(state, life.Prepared())
    stopped = life.advance(state, life.StopStep("observation obstructed"))
    facts = life.RetainedFacts(
        before=True, before_usable=False, stop=stopped.stop, stopped_state=stopped
    )
    assert life.inspect(life.start("reinstall"), facts).status == "incomplete"
    assert life.inspect(stopped, facts).status == "incomplete"
    with pytest.raises(ValueError):
        life.inspect(stopped, replace(facts, environment=True))


def test_stop_ahead_requires_coherent_acquired_facts_and_bounds_staging():
    state = through(5)
    stopped = life.advance(state, life.StopStep("observation unavailable"))
    facts = life.RetainedFacts(
        before=True,
        expectations=True,
        environment=True,
        stdout=True,
        stderr=True,
        stop=stopped.stop,
        stopped_state=stopped,
        staged=(frozenset({"after"}),),
    )
    assert life.inspect(state, facts).status == "incomplete"
    with pytest.raises(ValueError):
        life.inspect(through(0), facts)
    with pytest.raises(ValueError):
        life.inspect(state, replace(facts, stopped_state=None))
    with pytest.raises(ValueError):
        life.inspect(through(0), replace(facts, staged=(frozenset({"verification"}),)))


def test_external_expectations_allow_command_prefix_without_claiming_local_acquisition() -> None:
    state = through(0)
    facts = life.RetainedFacts(
        before=True, external_expectations=True, environment=True, stdout=True
    )
    assert life.inspect(state, facts).status == "incomplete"
    stopped = life.advance(life.start("install"), life.StopStep("preparation failed"))
    facts = replace(
        facts, environment=False, stdout=False, stop=stopped.stop, stopped_state=stopped
    )
    assert life.inspect(life.start("install"), facts).status == "incomplete"
    assert life.inspect(stopped, facts).status == "incomplete"


def test_ambiguous_structural_directory_needs_one_eligible_owner() -> None:
    facts = life.RetainedFacts(staged=(frozenset({"before", "after", "environment"}),))
    assert life.inspect(life.start("install"), facts).status == "incomplete"
    with pytest.raises(ValueError):
        life.inspect(
            life.start("install"), replace(facts, staged=(frozenset({"after", "environment"}),))
        )
