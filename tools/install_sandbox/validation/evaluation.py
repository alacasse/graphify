"""Pure lifecycle-state evaluation of correlated Raw Facts."""

from __future__ import annotations

from dataclasses import replace

from .filesystem_evaluation import evaluate_filesystem
from .plan_types import (
    AggregatePlan,
    LifecyclePlan,
    NotApplicablePhasePlan,
    PhasePlan,
    UnsupportedPlan,
    ValidationPlan,
)
from .protocol import (
    ActionFailureFact,
    ActionId,
    CommandFact,
    ObservationFact,
    PhaseKind,
    RawFact,
)
from .results import (
    AggregateResult,
    DetailedScenarioResult,
    LifecycleResult,
    PhaseResult,
    PhaseStatus,
    ProductFinding,
    ScenarioStatus,
    UnsupportedResult,
)


def evaluate_phase(phase: PhasePlan, facts: dict[ActionId, RawFact]) -> PhaseResult:
    """Derive one closed phase result from already validated correlated facts."""

    command = facts.get(phase.command.action_id)
    observation = facts.get(phase.observation.action_id)
    if isinstance(command, ActionFailureFact):
        return PhaseResult(
            phase.kind,
            PhaseStatus.INCOMPLETE,
            None,
            None,
            reason=command.detail,
            failure=command,
        )
    if not isinstance(command, CommandFact):
        return PhaseResult(
            phase.kind,
            PhaseStatus.INCOMPLETE,
            None,
            observation if isinstance(observation, ObservationFact) else None,
            reason="required raw phase evidence is missing",
        )
    if command.argv != phase.command.argv:
        return PhaseResult(
            phase.kind,
            PhaseStatus.INCOMPLETE,
            command,
            observation if isinstance(observation, ObservationFact) else None,
            reason="command evidence disagrees with the plan",
        )
    capture_errors = tuple(
        f"{name} capture failed: {capture.error}"
        for name, capture in (("stdout", command.stdout), ("stderr", command.stderr))
        if capture.error is not None
    )
    if capture_errors:
        return PhaseResult(
            phase.kind,
            PhaseStatus.INCOMPLETE,
            command,
            observation if isinstance(observation, ObservationFact) else None,
            reason="; ".join(capture_errors),
        )
    if not isinstance(observation, ObservationFact):
        failure = observation if isinstance(observation, ActionFailureFact) else None
        return PhaseResult(
            phase.kind,
            PhaseStatus.INCOMPLETE,
            command,
            None,
            reason=(
                failure.detail if failure is not None else "required filesystem evidence is missing"
            ),
            failure=failure,
        )
    findings, problems = evaluate_filesystem(phase, command, observation)
    if problems:
        return PhaseResult(
            phase.kind,
            PhaseStatus.INCOMPLETE,
            command,
            observation,
            reason="; ".join(problems),
        )
    if command.timed_out or command.exit_code != 0:
        command_finding = ProductFinding(
            "product command",
            "command timed out" if command.timed_out else f"command exited {command.exit_code}",
        )
        findings = (command_finding, *findings)
    return PhaseResult(
        phase.kind,
        PhaseStatus.FINDING if findings else PhaseStatus.PASS,
        command,
        observation,
        findings,
    )


def _roll_up(phases: tuple[PhaseResult, ...]) -> ScenarioStatus:
    if any(phase.status is PhaseStatus.INCOMPLETE for phase in phases):
        return ScenarioStatus.INCOMPLETE
    if any(phase.status in {PhaseStatus.FINDING, PhaseStatus.BLOCKED} for phase in phases):
        return ScenarioStatus.FINDING
    return ScenarioStatus.PASS


def _prevented_result(
    phase: PhasePlan,
    prevented_by: PhaseKind,
    cause: PhaseStatus,
) -> PhaseResult:
    if cause is PhaseStatus.INCOMPLETE:
        return PhaseResult(
            phase.kind,
            PhaseStatus.INCOMPLETE,
            None,
            None,
            reason=f"{prevented_by.value} diagnostic evidence is incomplete",
            blocked_by=prevented_by,
        )
    return PhaseResult(
        phase.kind,
        PhaseStatus.BLOCKED,
        None,
        None,
        reason="a required earlier command did not establish state",
        blocked_by=prevented_by,
    )


def _evaluated_phases(
    phases: tuple[PhasePlan | NotApplicablePhasePlan, ...],
    facts: dict[ActionId, RawFact],
) -> tuple[PhaseResult, ...]:
    results: list[PhaseResult] = []
    prevented: tuple[PhaseKind, PhaseStatus] | None = None
    stable_installed = None
    for phase in phases:
        if isinstance(phase, NotApplicablePhasePlan):
            results.append(
                PhaseResult(
                    phase.kind,
                    PhaseStatus.NOT_APPLICABLE,
                    None,
                    None,
                    reason=phase.reason,
                )
            )
            continue
        if prevented is not None:
            results.append(_prevented_result(phase, *prevented))
            continue
        result = evaluate_phase(phase, facts)
        if (
            phase.kind in {PhaseKind.REINSTALL, PhaseKind.REPAIR}
            and stable_installed is not None
            and result.command is not None
            and result.status in {PhaseStatus.PASS, PhaseStatus.FINDING}
            and result.command.after_snapshot != stable_installed
        ):
            label = (
                "idempotent filesystem state"
                if phase.kind is PhaseKind.REINSTALL
                else "repaired stable filesystem state"
            )
            detail = (
                "reinstall post-state differs from the stable installed state"
                if phase.kind is PhaseKind.REINSTALL
                else "repair post-state differs from the stable installed state"
            )
            result = replace(
                result,
                status=PhaseStatus.FINDING,
                findings=(*result.findings, ProductFinding(label, detail)),
            )
        results.append(result)
        if phase.kind is PhaseKind.INSTALL and result.status is PhaseStatus.PASS:
            assert result.command is not None
            stable_installed = result.command.after_snapshot
        if result.status is PhaseStatus.INCOMPLETE or (
            result.status is PhaseStatus.FINDING
            and result.command is not None
            and (result.command.timed_out or result.command.exit_code != 0)
        ):
            prevented = (phase.kind, result.status)
    return tuple(results)


def _lifecycle_result(
    plan: LifecyclePlan,
    facts: dict[ActionId, RawFact],
) -> LifecycleResult:
    phases = _evaluated_phases(plan.phases, facts)
    return LifecycleResult(
        plan.target,
        plan.scope,
        _roll_up(phases),
        phases,
        plan.runtime_limitations,
    )


def _aggregate_result(
    plan: AggregatePlan,
    facts: dict[ActionId, RawFact],
) -> AggregateResult:
    phases = _evaluated_phases((*plan.preparations, plan.uninstall), facts)
    return AggregateResult(plan.scope, _roll_up(phases), phases, plan.runtime_limitations)


def derive_results(
    plan: ValidationPlan,
    raw_facts: tuple[RawFact, ...],
) -> tuple[DetailedScenarioResult, ...]:
    """Derive closed scenario results without mutating or reinterpreting Raw Facts."""

    facts = {fact.action_id: fact for fact in raw_facts}
    results: list[DetailedScenarioResult] = []
    for scenario in plan.scenarios:
        if isinstance(scenario, LifecyclePlan):
            results.append(_lifecycle_result(scenario, facts))
        elif isinstance(scenario, AggregatePlan):
            results.append(_aggregate_result(scenario, facts))
        else:
            assert isinstance(scenario, UnsupportedPlan)
            results.append(
                UnsupportedResult(
                    scenario.target,
                    scenario.scope,
                    ScenarioStatus.UNSUPPORTED,
                    scenario.reason,
                    scenario.runtime_limitations,
                )
            )
    return tuple(results)
