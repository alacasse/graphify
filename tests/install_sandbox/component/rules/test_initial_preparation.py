"""Publication barriers and independent initial evidence admissibility."""

from dataclasses import replace

import pytest

from tools.install_sandbox.contracts.initial_preparation import (
    INITIAL_ARTIFACTS,
    OPERATIONS,
    REFERENCES,
    InitialPreparationState,
)
from tools.install_sandbox.rules.initial_preparation import (
    ARTIFACT_BY_OPERATION,
    InitialPreparationInventory,
    InitialPreparationLifecycle,
    inspect,
)


def publish(lifecycle: InitialPreparationLifecycle) -> InitialPreparationState:
    candidate = lifecycle.publication_candidate()
    lifecycle.acknowledge(candidate)
    return candidate


def complete(
    lifecycle: InitialPreparationLifecycle, operation: str, passed: bool = True
) -> InitialPreparationState:
    lifecycle.acquire(
        operation, **({"verification_passed": passed} if operation == "verification" else {})
    )
    assert lifecycle.next_operation() is None
    with pytest.raises(ValueError):
        lifecycle.publication_candidate()
    lifecycle.retain(operation, REFERENCES[ARTIFACT_BY_OPERATION[operation]])
    assert lifecycle.next_operation() is None
    return publish(lifecycle)


def test_every_group_requires_initial_publication_acquisition_retention_and_acknowledgement():
    lifecycle = InitialPreparationLifecycle()
    assert lifecycle.next_operation() is None
    with pytest.raises(ValueError):
        lifecycle.acquire("environment")
    state = publish(lifecycle)
    for operation in OPERATIONS:
        assert lifecycle.next_operation() == operation
        state = complete(lifecycle, operation)
        assert InitialPreparationState.from_data(state.to_data()) == state
    assert lifecycle.next_operation() is None
    assert (
        inspect(state, InitialPreparationInventory(frozenset(INITIAL_ARTIFACTS[:6]), True)).status
        == "incomplete"
    )


@pytest.mark.parametrize("count", range(7))
def test_only_the_next_operation_may_have_unpublished_artifacts(count: int) -> None:
    lifecycle = InitialPreparationLifecycle()
    state = publish(lifecycle)
    for operation in OPERATIONS[:count]:
        state = complete(lifecycle, operation)
    present = frozenset(INITIAL_ARTIFACTS[: min(count + 1, 6)])
    inventory = InitialPreparationInventory(present, True if "verification" in present else None)
    assert inspect(state, inventory).checkpoint == state.checkpoint
    if count < 5:
        excessive = present | {INITIAL_ARTIFACTS[count + 1]}
        with pytest.raises(ValueError):
            inspect(state, replace(inventory, present=excessive))
    if count < 6:
        inspect(state, replace(inventory, staged=(frozenset({INITIAL_ARTIFACTS[count]}),)))
    if count < 5:
        with pytest.raises(ValueError):
            inspect(state, replace(inventory, staged=(frozenset({INITIAL_ARTIFACTS[count + 1]}),)))


def test_diagnostic_retained_before_publication_preserves_old_checkpoint():
    lifecycle = InitialPreparationLifecycle()
    state = publish(lifecycle)
    lifecycle.acquire("environment")
    lifecycle.stop("environment", "io", "Root retention failed")
    diagnostic = lifecycle.failure_candidate()
    assert lifecycle.next_operation() is None
    assert lifecycle.published == state
    with pytest.raises(ValueError):
        lifecycle.publication_candidate()
    lifecycle.retain_failure(REFERENCES["failure"])
    inventory = InitialPreparationInventory(frozenset({"failure"}), stopped_state=diagnostic)
    assert inspect(state, inventory).status == "incomplete"
    stopped = publish(lifecycle)
    assert inspect(stopped, inventory).status == "not_run"
    assert stopped.facts.completed == ("environment",)


def test_failed_initial_verification_blocks_installation_and_is_independently_checked():
    lifecycle = InitialPreparationLifecycle()
    publish(lifecycle)
    for operation in OPERATIONS[:4]:
        complete(lifecycle, operation)
    state = complete(lifecycle, "verification", passed=False)
    assert state.checkpoint == "blocked"
    assert lifecycle.next_operation() is None
    inventory = InitialPreparationInventory(frozenset(INITIAL_ARTIFACTS[:5]), False)
    assert inspect(state, inventory).status == "not_run"
    with pytest.raises(ValueError):
        inspect(state, replace(inventory, verification_passed=True))
    with pytest.raises(ValueError):
        inspect(state, replace(inventory, present=inventory.present | {"install_expectations"}))


def test_forged_and_missing_evidence_and_wrong_publication_receipts_are_rejected():
    lifecycle = InitialPreparationLifecycle()
    with pytest.raises(ValueError):
        lifecycle.acknowledge(replace(lifecycle.publication_candidate()))
    publish(lifecycle)
    state = complete(lifecycle, "environment")
    with pytest.raises(ValueError):
        inspect(state, InitialPreparationInventory())
    with pytest.raises(ValueError):
        inspect(
            replace(state, retained=replace(state.retained, environment="foreign.json")),
            InitialPreparationInventory(frozenset({"environment"})),
        )


def test_diagnostic_cannot_claim_it_passed_an_unpublished_checkpoint():
    lifecycle = InitialPreparationLifecycle()
    started = publish(lifecycle)
    complete(lifecycle, "environment")
    lifecycle.stop("sources", "validation", "Source rejected")
    diagnostic = lifecycle.failure_candidate()
    with pytest.raises(ValueError):
        inspect(
            started,
            InitialPreparationInventory(
                frozenset({"environment", "failure"}), stopped_state=diagnostic
            ),
        )


def test_old_operation_staging_cannot_reappear_after_its_checkpoint():
    lifecycle = InitialPreparationLifecycle()
    publish(lifecycle)
    state = complete(lifecycle, "environment")
    inventory = InitialPreparationInventory(
        frozenset({"environment"}), staged=(frozenset({"environment"}),)
    )
    with pytest.raises(ValueError):
        inspect(state, inventory)


def test_unpublished_observation_verdict_is_inspection_information_only():
    lifecycle = InitialPreparationLifecycle()
    state = publish(lifecycle)
    for operation in OPERATIONS[:4]:
        state = complete(lifecycle, operation)
    outcome = inspect(state, InitialPreparationInventory(frozenset(INITIAL_ARTIFACTS[:4]), True))
    assert outcome.status == "incomplete"
    assert outcome.checkpoint == "observed"
    assert lifecycle.next_operation() == "verification"


def test_install_expectations_stop_cannot_claim_a_failed_verified_predecessor() -> None:
    lifecycle = InitialPreparationLifecycle()
    publish(lifecycle)
    for operation in OPERATIONS[:5]:
        complete(lifecycle, operation)
    lifecycle.stop("install_expectations", "io", "Builder input unavailable")
    diagnostic = lifecycle.failure_candidate()
    assert diagnostic.stop is not None
    forged_facts = replace(diagnostic.facts, verification_passed=False)
    forged = replace(
        diagnostic, facts=forged_facts, stop=replace(diagnostic.stop, facts=forged_facts)
    )
    with pytest.raises(ValueError, match="conformant verification"):
        inspect(
            forged,
            InitialPreparationInventory(
                frozenset((*INITIAL_ARTIFACTS[:5], "failure")), False, forged
            ),
        )
