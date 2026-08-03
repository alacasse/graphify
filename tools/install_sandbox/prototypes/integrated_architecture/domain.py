"""PROTOTYPE ONLY: pure catalog, planning, and validation application logic."""

# pyright: strict

from __future__ import annotations

import hashlib
import itertools
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import NoReturn, cast

from .model import (
    AbsentRule,
    ActionId,
    ActionRequest,
    ActionUnavailable,
    AggregatePreparation,
    AggregatePreparationResult,
    AggregateScenario,
    AggregateScenarioRecord,
    AggregateUninstallFinding,
    AggregateUninstallIncomplete,
    AggregateUninstallNotApplicable,
    AggregateUninstallPassed,
    AggregateUninstallResult,
    AggregateValidation,
    ApplicationOutcome,
    CatalogCompilation,
    CatalogReady,
    CatalogRejected,
    CommandFact,
    CommandRequest,
    CompletedValidation,
    CompleteValidation,
    ContainsTextRule,
    ExactTextRule,
    Exited,
    HarnessPolicy,
    InstallationEstablished,
    InstallationWitness,
    InstallEffect,
    InstallTargetCatalog,
    IsolationScenario,
    LifecycleScenario,
    LifecycleValidation,
    ObservationFact,
    ObservationReadFailure,
    ObservationRequest,
    ObservationRule,
    ObservationSpecification,
    ObservedAbsent,
    ObservedContent,
    OwnedFileEffect,
    PhaseBlocked,
    PhaseFinding,
    PhaseIncomplete,
    PhaseKind,
    PhasePassed,
    PhasePlan,
    PhaseResult,
    PhaseScenarioRecord,
    PlanCompilation,
    PlanId,
    PlanProjection,
    PlanReady,
    PlanRejected,
    PreparationFinding,
    PreparationIncomplete,
    PreparationPassed,
    ProductFinding,
    PurgeFinding,
    PurgeIncomplete,
    PurgePassed,
    PurgePlan,
    PurgeResult,
    RawCatalogDocument,
    RawFact,
    RunId,
    ScenarioFinding,
    ScenarioIncomplete,
    ScenarioKind,
    ScenarioPassed,
    ScenarioPlan,
    ScenarioProjection,
    ScenarioRecord,
    ScenarioResult,
    ScenarioUnsupported,
    Scope,
    ScopeFacts,
    StableInstallationEstablished,
    StreamCaptureFailure,
    SupportedScopeFacts,
    TargetFacts,
    TargetScope,
    TextEntryEffect,
    UnsupportedScenario,
    UnsupportedScenarioRecord,
    UnsupportedScopeFacts,
    UnsupportedValidation,
    ValidationIncomplete,
    ValidationPlan,
    ValidationRequest,
)

type Fulfil = Callable[[ActionRequest], RawFact]
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")


def _fail(message: str) -> NoReturn:
    raise ValueError(message)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        _fail(f"{label} must be a mapping")
    return cast(Mapping[str, object], value)


def _exact_keys(data: Mapping[str, object], expected: set[str], label: str) -> None:
    actual = set(data)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        _fail(f"{label} keys differ: missing={missing!r}, unknown={unknown!r}")


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{label} must be a non-empty string")
    return value


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        _fail(f"{label} must be a list of non-empty strings")
    values = cast(list[object], value)
    if not all(isinstance(item, str) and item for item in values):
        _fail(f"{label} must be a list of non-empty strings")
    return tuple(cast(str, item) for item in values)


def _safe_leaf(source: object, name: str) -> str:
    value = _string(source, "catalog source")
    path = PurePosixPath(value)
    if path.is_absolute() or len(path.parts) != 1 or path.name != value:
        _fail(f"catalog source must be one safe leaf: {value}")
    if path.suffix != ".yaml" or path.stem != name or value in {".", ".."}:
        _fail(f"catalog source must be exactly {name}.yaml: {value}")
    return value


def _safe_location(value: object) -> str:
    location = _string(value, "effect location")
    path = PurePosixPath(location)
    if path.is_absolute() or not path.parts or any(part in {".", ".."} for part in path.parts):
        _fail(f"unsafe effect location: {location}")
    if (
        "//" in location
        or "/./" in location
        or location.startswith("./")
        or location.endswith("/")
        or "\\" in location
    ):
        _fail(f"non-canonical effect location: {location}")
    return location


def _decode_effect(raw: object) -> InstallEffect:
    data = _mapping(raw, "effect")
    kind = _string(data.get("kind"), "effect kind")
    if kind == "owned_file":
        _exact_keys(data, {"kind", "location", "expected_text"}, "owned_file effect")
        return OwnedFileEffect(
            _safe_location(data["location"]), _string(data["expected_text"], "expected_text")
        )
    if kind == "text_entry":
        _exact_keys(data, {"kind", "location", "entry", "required_text"}, "text_entry effect")
        return TextEntryEffect(
            _safe_location(data["location"]),
            _string(data["entry"], "entry"),
            _string(data["required_text"], "required_text"),
        )
    _fail(f"unknown effect kind: {kind}")


def _decode_scope(raw: object, scope: Scope) -> ScopeFacts:
    data = _mapping(raw, f"{scope.value} scope")
    supported = data.get("supported")
    if supported is True:
        _exact_keys(data, {"supported", "effects"}, f"{scope.value} supported scope")
        raw_effects = data["effects"]
        if not isinstance(raw_effects, list) or not raw_effects:
            _fail(f"{scope.value} supported scope requires effects")
        effects = tuple(_decode_effect(item) for item in cast(list[object], raw_effects))
        if len(set(surface_key((effect,)) for effect in effects)) != len(effects):
            _fail(f"{scope.value} supported scope contains duplicate effect surfaces")
        return SupportedScopeFacts(effects)
    if supported is False:
        _exact_keys(
            data, {"supported", "reason", "limitations"}, f"{scope.value} unsupported scope"
        )
        return UnsupportedScopeFacts(
            _string(data["reason"], f"{scope.value} unsupported reason"),
            _strings(data["limitations"], f"{scope.value} limitations"),
        )
    _fail(f"{scope.value} scope supported must be boolean")


def _decode_document(document: RawCatalogDocument) -> TargetFacts:
    _exact_keys(document, {"source", "name", "scopes"}, "catalog document")
    name = _string(document["name"], "target name")
    if _NAME.fullmatch(name) is None:
        _fail(f"unsafe target name: {name}")
    _safe_leaf(document["source"], name)
    scopes = _mapping(document["scopes"], "scopes")
    _exact_keys(scopes, {scope.value for scope in Scope}, f"{name} scopes")
    return TargetFacts(
        name,
        tuple(TargetScope(scope, _decode_scope(scopes[scope.value], scope)) for scope in Scope),
    )


def compile_catalog(documents: Sequence[RawCatalogDocument]) -> CatalogCompilation:
    """Validate the raw edge once and return a deeply immutable catalog."""

    targets: list[TargetFacts] = []
    reasons: list[str] = []
    seen: set[str] = set()
    for document in documents:
        try:
            target = _decode_document(document)
            if target.name in seen:
                _fail(f"duplicate target identity: {target.name}")
            seen.add(target.name)
            targets.append(target)
        except ValueError as error:
            reasons.append(str(error))
    if reasons or not targets:
        return CatalogRejected(tuple(reasons or ("catalog is empty",)))
    return CatalogReady(InstallTargetCatalog(tuple(sorted(targets, key=lambda item: item.name))))


def surface_key(effects: tuple[InstallEffect, ...]) -> tuple[tuple[str, ...], ...]:
    keys: list[tuple[str, ...]] = []
    for effect in effects:
        if isinstance(effect, OwnedFileEffect):
            keys.append(("owned-file", effect.location))
        else:
            keys.append(("text-entry", effect.location, effect.entry))
    return tuple(sorted(keys))


def _installed_rule(effect: InstallEffect, scope: Scope) -> ObservationRule:
    if isinstance(effect, OwnedFileEffect):
        return ExactTextRule(
            f"{scope.value}:file:{effect.location}", effect.location, effect.expected_text
        )
    return ContainsTextRule(
        f"{scope.value}:entry:{effect.location}:{effect.entry}",
        effect.location,
        effect.required_text,
    )


def _installed_spec(effects: tuple[InstallEffect, ...], scope: Scope) -> ObservationSpecification:
    return ObservationSpecification(tuple(_installed_rule(effect, scope) for effect in effects))


def _absent_spec(effects: tuple[InstallEffect, ...], scope: Scope) -> ObservationSpecification:
    indexed = {
        installed.key: AbsentRule(installed.key, installed.location)
        for effect in effects
        for installed in (_installed_rule(effect, scope),)
    }
    return ObservationSpecification(tuple(indexed[key] for key in sorted(indexed)))


def _aggregate_candidates(
    catalog: InstallTargetCatalog, scope: Scope
) -> tuple[tuple[TargetFacts, frozenset[tuple[str, ...]]], ...]:
    candidates: list[tuple[TargetFacts, frozenset[tuple[str, ...]]]] = []
    for target in catalog.targets:
        facts = target.facts_for(scope)
        if isinstance(facts, SupportedScopeFacts):
            candidates.append((target, frozenset(surface_key(facts.effects))))
    return tuple(candidates)


def _minimum_cover(
    candidates: tuple[tuple[TargetFacts, frozenset[tuple[str, ...]]], ...],
) -> tuple[TargetFacts, ...]:
    universe: frozenset[tuple[str, ...]] = frozenset(
        item for _, surfaces in candidates for item in surfaces
    )
    ordered = tuple(sorted(candidates, key=lambda item: item[0].name))
    for size in range(1, len(ordered) + 1):
        for combination in itertools.combinations(ordered, size):
            if frozenset().union(*(surface for _, surface in combination)) == universe:
                return tuple(target for target, _ in combination)
    return ()


def independent_aggregate_cover_oracle(
    catalog: InstallTargetCatalog, scope: Scope
) -> tuple[str, ...]:
    """Brute-force demonstration oracle, intentionally separate from plan construction."""

    named: list[tuple[str, frozenset[tuple[str, ...]]]] = []
    required: set[tuple[str, ...]] = set()
    for target in catalog.targets:
        facts = target.facts_for(scope)
        if isinstance(facts, SupportedScopeFacts):
            surfaces = frozenset(surface_key(facts.effects))
            required.update(surfaces)
            named.append((target.name, surfaces))
    winners: list[tuple[str, ...]] = []
    for mask in range(1, 1 << len(named)):
        selected = tuple(named[index] for index in range(len(named)) if mask & (1 << index))
        covered: set[tuple[str, ...]] = {item for _, surfaces in selected for item in surfaces}
        if covered == required:
            winners.append(tuple(name for name, _ in selected))
    return min(winners, key=lambda item: (len(item), item), default=())


def _lifecycle(
    target: TargetFacts, scope: Scope, policy: HarnessPolicy
) -> ScenarioPlan | PlanRejected:
    facts = target.facts_for(scope)
    if isinstance(facts, UnsupportedScopeFacts):
        return UnsupportedScenario(
            f"{target.name}:{scope.value}", target.name, scope, facts.reason, facts.limitations
        )
    phases = [
        PhasePlan(
            PhaseKind.INSTALL,
            target.name,
            scope,
            (*policy.install_argv, target.name, "--scope", scope.value),
            _installed_spec(facts.effects, scope),
        )
    ]
    if policy.reinstall:
        phases.append(replace(phases[0], kind=PhaseKind.REINSTALL))
    if policy.repair:
        phases.append(replace(phases[0], kind=PhaseKind.REPAIR))
    phases.append(
        PhasePlan(
            PhaseKind.TARGET_UNINSTALL,
            target.name,
            scope,
            (*policy.uninstall_argv, target.name, "--scope", scope.value),
            _absent_spec(facts.effects, scope),
        )
    )
    return LifecycleScenario(f"{target.name}:{scope.value}", scope, tuple(phases))


def _aggregate(
    catalog: InstallTargetCatalog, scope: Scope, policy: HarnessPolicy
) -> ScenarioPlan | PlanRejected:
    candidates = _aggregate_candidates(catalog, scope)
    selected = _minimum_cover(candidates)
    if not selected:
        return PlanRejected((f"aggregate {scope.value} has no supported targets",))
    preparations: list[AggregatePreparation] = []
    all_effects: list[InstallEffect] = []
    for target in selected:
        facts = target.facts_for(scope)
        if not isinstance(facts, SupportedScopeFacts):
            raise AssertionError("minimum cover selected an unsupported target")
        all_effects.extend(facts.effects)
        preparations.append(
            AggregatePreparation(
                target.name,
                scope,
                facts.effects,
                (*policy.install_argv, target.name, "--scope", scope.value),
                _installed_spec(facts.effects, scope),
            )
        )
    return AggregateScenario(
        f"aggregate:{scope.value}",
        scope,
        tuple(preparations),
        (*policy.aggregate_uninstall_argv, "--scope", scope.value),
        _absent_spec(tuple(all_effects), scope),
    )


def _isolation(
    catalog: InstallTargetCatalog, selected: Scope, preserved: Scope, policy: HarnessPolicy
) -> IsolationScenario | None:
    rules: list[ObservationRule] = []
    targets: list[str] = []
    preparations: list[PhasePlan] = []
    for target in catalog.targets:
        selected_facts = target.facts_for(selected)
        preserved_facts = target.facts_for(preserved)
        if isinstance(selected_facts, SupportedScopeFacts) and isinstance(
            preserved_facts, SupportedScopeFacts
        ):
            targets.append(target.name)
            preparations.extend(
                (
                    PhasePlan(
                        PhaseKind.INSTALL,
                        target.name,
                        selected,
                        (*policy.install_argv, target.name, "--scope", selected.value),
                        _installed_spec(selected_facts.effects, selected),
                    ),
                    PhasePlan(
                        PhaseKind.INSTALL,
                        target.name,
                        preserved,
                        (*policy.install_argv, target.name, "--scope", preserved.value),
                        _installed_spec(preserved_facts.effects, preserved),
                    ),
                )
            )
            rules.extend(_absent_spec(selected_facts.effects, selected).rules)
            rules.extend(_installed_spec(preserved_facts.effects, preserved).rules)
    if not targets:
        return None
    name = f"isolation:{selected.value}-preserves-{preserved.value}"
    phase = PhasePlan(
        PhaseKind.CROSS_SCOPE_PRESERVATION,
        ",".join(targets),
        selected,
        (*policy.aggregate_uninstall_argv, "--scope", selected.value),
        ObservationSpecification(tuple(rules)),
    )
    return IsolationScenario(name, selected, phase, preserved, tuple(preparations))


def _selected(
    catalog: InstallTargetCatalog, names: tuple[str, ...]
) -> tuple[TargetFacts, ...] | PlanRejected:
    if not names or len(set(names)) != len(names):
        return PlanRejected(("target selection must be non-empty and unique",))
    targets = tuple(catalog.target(name) for name in names)
    missing = tuple(name for name, target in zip(names, targets, strict=True) if target is None)
    if missing:
        return PlanRejected(tuple(f"unknown target: {name}" for name in missing))
    return cast(tuple[TargetFacts, ...], targets)


def _complete(
    catalog: InstallTargetCatalog, request: CompleteValidation, policy: HarnessPolicy
) -> tuple[ScenarioPlan, ...] | PlanRejected:
    targets = _selected(catalog, request.targets)
    if isinstance(targets, PlanRejected):
        return targets
    if not request.scopes or len(set(request.scopes)) != len(request.scopes):
        return PlanRejected(("scope selection must be non-empty and unique",))
    subset = InstallTargetCatalog(targets)
    pairs = _pair_scenarios(targets, request.scopes, policy)
    if isinstance(pairs, PlanRejected):
        return pairs
    return (
        *pairs,
        *_aggregate_scenarios(subset, request.scopes, policy),
        *_isolations(subset, request.scopes, policy),
    )


def _pair_scenarios(
    targets: tuple[TargetFacts, ...], scopes: tuple[Scope, ...], policy: HarnessPolicy
) -> tuple[ScenarioPlan, ...] | PlanRejected:
    scenarios: list[ScenarioPlan] = []
    for target in targets:
        for scope in scopes:
            scenario = _lifecycle(target, scope, policy)
            if isinstance(scenario, PlanRejected):
                return scenario
            scenarios.append(scenario)
    return tuple(scenarios)


def _aggregate_scenarios(
    catalog: InstallTargetCatalog, scopes: tuple[Scope, ...], policy: HarnessPolicy
) -> tuple[ScenarioPlan, ...]:
    candidates = tuple(_aggregate(catalog, scope, policy) for scope in scopes)
    return tuple(item for item in candidates if not isinstance(item, PlanRejected))


def _isolations(
    catalog: InstallTargetCatalog, scopes: tuple[Scope, ...], policy: HarnessPolicy
) -> tuple[ScenarioPlan, ...]:
    if set(scopes) != set(Scope):
        return ()
    candidates = (
        _isolation(catalog, Scope.USER, Scope.PROJECT, policy),
        _isolation(catalog, Scope.PROJECT, Scope.USER, policy),
    )
    return tuple(item for item in candidates if item is not None)


def _planned(
    catalog: InstallTargetCatalog, request: ValidationRequest, policy: HarnessPolicy
) -> tuple[ScenarioPlan, ...] | PlanRejected:
    if isinstance(request, CompleteValidation):
        return _complete(catalog, request, policy)
    if isinstance(request, AggregateValidation):
        scenario = _aggregate(catalog, request.scope, policy)
    else:
        target = catalog.target(request.target)
        if target is None:
            return PlanRejected((f"unknown target: {request.target}",))
        scenario = _lifecycle(target, request.scope, policy)
        if isinstance(request, UnsupportedValidation) and not isinstance(
            scenario, UnsupportedScenario
        ):
            return PlanRejected((f"{request.target}:{request.scope.value} is supported",))
        if isinstance(request, LifecycleValidation) and isinstance(scenario, UnsupportedScenario):
            return PlanRejected((f"{request.target}:{request.scope.value} is unsupported",))
    return scenario if isinstance(scenario, PlanRejected) else (scenario,)


def _projection(scenarios: tuple[ScenarioPlan, ...], plan_id: PlanId) -> PlanProjection:
    projections: list[ScenarioProjection] = []
    for scenario in scenarios:
        if isinstance(scenario, LifecycleScenario):
            kind, targets, phases = (
                ScenarioKind.LIFECYCLE,
                (scenario.phases[0].target,),
                tuple(phase.kind for phase in scenario.phases),
            )
        elif isinstance(scenario, UnsupportedScenario):
            kind, targets, phases = ScenarioKind.UNSUPPORTED, (scenario.target,), ()
        elif isinstance(scenario, AggregateScenario):
            kind = ScenarioKind.AGGREGATE
            targets = tuple(item.target for item in scenario.preparations)
            phases = (
                *((PhaseKind.AGGREGATE_PREPARE,) * len(targets)),
                PhaseKind.AGGREGATE_UNINSTALL,
            )
        else:
            kind, targets, phases = (
                ScenarioKind.ISOLATION,
                tuple(scenario.phase.target.split(",")),
                (
                    *(phase.kind for phase in scenario.preparations),
                    PhaseKind.CROSS_SCOPE_PRESERVATION,
                ),
            )
        projections.append(ScenarioProjection(scenario.name, kind, scenario.scope, targets, phases))
    return PlanProjection(plan_id, tuple(projections), True)


def _canonical_plan_payload(scenarios: tuple[ScenarioPlan, ...], purge: PurgePlan) -> str:
    def rule(rule: ObservationRule) -> tuple[str, ...]:
        if isinstance(rule, ExactTextRule):
            return ("exact", rule.key, rule.location, rule.expected_text)
        if isinstance(rule, ContainsTextRule):
            return ("contains", rule.key, rule.location, rule.required_text)
        return ("absent", rule.key, rule.location)

    payload = {
        "scenarios": [
            {
                "name": scenario.name,
                "scope": scenario.scope.value,
                "repr": repr(scenario),
            }
            for scenario in scenarios
        ],
        "purge": {
            "command": purge.command,
            "rules": [rule(item) for item in purge.observation.rules],
        },
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def build_validation_plan(
    catalog: InstallTargetCatalog, request: ValidationRequest, policy: HarnessPolicy
) -> PlanCompilation:
    """Derive one deterministic plan and its diagnostics-safe projection."""

    if not policy.reinstall:
        return PlanRejected(("reinstall is required to establish a stable installation witness",))
    scenarios = _planned(catalog, request, policy)
    if isinstance(scenarios, PlanRejected):
        return scenarios
    names = tuple(scenario.name for scenario in scenarios)
    if not names or len(set(names)) != len(names):
        return PlanRejected(("validation plan requires unique scenarios",))
    purge = PurgePlan(
        policy.purge_argv,
        ObservationSpecification(
            (
                AbsentRule("purge:installations", "installations"),
                AbsentRule("purge:graphify-out", "graphify-out"),
            )
        ),
    )
    canonical = _canonical_plan_payload(scenarios, purge).encode()
    plan_id = PlanId("plan-" + hashlib.sha256(canonical).hexdigest()[:16])
    return PlanReady(ValidationPlan(plan_id, scenarios, purge, _projection(scenarios, plan_id)))


def roll_up_phases(
    scenario: LifecycleScenario | IsolationScenario, results: tuple[PhaseResult, ...]
) -> ScenarioResult:
    expected = (
        tuple(phase.kind for phase in scenario.phases)
        if isinstance(scenario, LifecycleScenario)
        else (*(phase.kind for phase in scenario.preparations), scenario.phase.kind)
    )
    actual = tuple(result.phase for result in results)
    if actual != expected:
        return ScenarioIncomplete(
            scenario.name,
            (f"phase detail mismatch: expected={expected!r}, actual={actual!r}",),
        )
    reasons = tuple(result.reason for result in results if isinstance(result, PhaseIncomplete))
    if reasons:
        return ScenarioIncomplete(scenario.name, reasons)
    findings = tuple(result.finding for result in results if isinstance(result, PhaseFinding))
    return ScenarioFinding(scenario.name, findings) if findings else ScenarioPassed(scenario.name)


def _judge_observation(
    specification: ObservationSpecification, fact: ObservationFact
) -> tuple[bool, bool, bool, str]:
    indexed = {item.rule_key: item for item in fact.items}
    if len(indexed) != len(fact.items):
        return False, True, False, "observation contains duplicate rule keys"
    expected = {rule.key for rule in specification.rules}
    if set(indexed) != expected:
        return False, True, False, "observation does not exactly cover requested rules"
    failures = tuple(item.detail for item in fact.items if isinstance(item, ObservationReadFailure))
    if failures:
        return False, True, False, "; ".join(failures)
    established = bool(specification.rules) and all(
        not isinstance(rule, AbsentRule) and isinstance(indexed[rule.key], ObservedContent)
        for rule in specification.rules
    )
    violations: list[str] = []
    for rule in specification.rules:
        item = indexed[rule.key]
        if isinstance(rule, AbsentRule):
            passed = isinstance(item, ObservedAbsent)
        elif isinstance(rule, ExactTextRule):
            passed = (
                isinstance(item, ObservedContent)
                and item.content.decode(errors="replace") == rule.expected_text
            )
        else:
            passed = isinstance(
                item, ObservedContent
            ) and rule.required_text in item.content.decode(errors="replace")
        if not passed:
            violations.append(rule.location)
    return (
        not violations,
        False,
        established,
        "semantic rule violation at " + ", ".join(violations),
    )


def _request_pair(
    run_id: RunId,
    plan_id: PlanId,
    ordinal: int,
    scenario: str,
    phase: str,
    argv: tuple[str, ...],
    observation: ObservationSpecification,
) -> tuple[CommandRequest, ObservationRequest]:
    command_id = ActionId(run_id, plan_id, ordinal)
    observation_id = ActionId(run_id, plan_id, ordinal + 1)
    return (
        CommandRequest(command_id, scenario, phase, argv, "."),
        ObservationRequest(observation_id, scenario, phase, observation),
    )


@dataclass(frozen=True, slots=True)
class _RunLedger:
    plan: ValidationPlan
    run_id: RunId
    next_ordinal: int = 0
    facts: tuple[RawFact, ...] = ()
    findings: tuple[ProductFinding, ...] = ()
    chronology: tuple[ActionId, ...] = ()

    def request_pair(
        self,
        scenario: str,
        phase: str,
        argv: tuple[str, ...],
        observation: ObservationSpecification,
    ) -> tuple[CommandRequest, ObservationRequest]:
        return _request_pair(
            self.run_id,
            self.plan.plan_id,
            self.next_ordinal,
            scenario,
            phase,
            argv,
            observation,
        )

    def receive(self, request: ActionRequest, fact: RawFact) -> _RunLedger:
        if fact.action_id != request.action_id:
            raise ValueError(
                f"mismatched fact: expected {request.action_id!r}, got {fact.action_id!r}"
            )
        if fact.action_id in self.chronology:
            raise ValueError(f"duplicate or late fact: {fact.action_id!r}")
        expected = self.next_ordinal
        if fact.action_id.ordinal != expected:
            raise ValueError(f"out-of-order fact: expected ordinal {expected}")
        if isinstance(request, CommandRequest) != isinstance(
            fact, (CommandFact, ActionUnavailable)
        ):
            raise ValueError("fact family does not match command request")
        if isinstance(request, ObservationRequest) != isinstance(
            fact, (ObservationFact, ActionUnavailable)
        ):
            raise ValueError("fact family does not match observation request")
        return replace(
            self,
            next_ordinal=expected + 1,
            facts=(*self.facts, fact),
            chronology=(*self.chronology, fact.action_id),
        )


def _command_verdict(fact: RawFact) -> tuple[bool, bool, str]:
    if isinstance(fact, ActionUnavailable):
        return False, True, fact.detail
    if not isinstance(fact, CommandFact):
        raise TypeError("command verdict requires a command fact")
    if fact.finished_ns < fact.started_ns:
        return False, True, "command finish precedes start"
    if fact.argv == () or not fact.reaped:
        return False, True, "command evidence is incomplete"
    if isinstance(fact.stdout, StreamCaptureFailure) or isinstance(
        fact.stderr, StreamCaptureFailure
    ):
        return False, True, "command stream capture is incomplete"
    if isinstance(fact.termination, Exited):
        if not 0 <= fact.termination.code <= 255:
            return False, True, f"invalid raw exit code {fact.termination.code}"
        return fact.termination.code == 0, False, f"command exited {fact.termination.code}"
    return False, True, f"command did not exit normally: {fact.termination!r}"


def _fulfil(
    ledger: _RunLedger, request: ActionRequest, fulfil: Fulfil
) -> tuple[_RunLedger, RawFact]:
    fact = fulfil(request)
    updated = ledger.receive(request, fact)
    if (
        isinstance(fact, CommandFact)
        and isinstance(request, CommandRequest)
        and (fact.argv != request.argv or fact.cwd != request.cwd)
    ):
        raise ValueError("command fact does not preserve the requested argv/cwd")
    return updated, fact


def _witness_after_observation(
    phase: PhasePlan,
    witness: InstallationWitness | None,
) -> InstallationWitness | None:
    surfaces = tuple((rule.key,) for rule in phase.observation.rules)
    if phase.kind in (PhaseKind.INSTALL, PhaseKind.AGGREGATE_PREPARE):
        return InstallationEstablished(phase.target, phase.scope, surfaces)
    if phase.kind in (PhaseKind.REINSTALL, PhaseKind.REPAIR):
        return StableInstallationEstablished(phase.target, phase.scope, surfaces)
    if phase.kind is PhaseKind.TARGET_UNINSTALL:
        return None
    return witness


def _phase_observation_result(
    ledger: _RunLedger,
    phase: PhasePlan,
    request: ObservationRequest,
    fact: RawFact,
    witness: InstallationWitness | None,
) -> tuple[_RunLedger, PhaseResult, InstallationWitness | None]:
    if isinstance(fact, ActionUnavailable):
        return ledger, PhaseIncomplete(phase.kind, fact.detail), witness
    if not isinstance(fact, ObservationFact):
        raise TypeError("observation request returned a non-observation fact")
    passed, incomplete, established, detail = _judge_observation(phase.observation, fact)
    if incomplete:
        return ledger, PhaseIncomplete(phase.kind, detail), witness
    next_witness = _witness_after_observation(phase, witness)
    if passed:
        return ledger, PhasePassed(phase.kind), next_witness
    if not established and phase.kind in (
        PhaseKind.INSTALL,
        PhaseKind.REINSTALL,
        PhaseKind.REPAIR,
        PhaseKind.AGGREGATE_PREPARE,
    ):
        next_witness = None
    finding_witness = next_witness if established else None
    finding = ProductFinding(request.action_id, detail, finding_witness)
    return (
        replace(ledger, findings=(*ledger.findings, finding)),
        PhaseFinding(phase.kind, finding),
        next_witness,
    )


def _run_phase(
    ledger: _RunLedger,
    scenario: str,
    phase: PhasePlan,
    witness: InstallationWitness | None,
    fulfil: Fulfil,
) -> tuple[_RunLedger, PhaseResult, InstallationWitness | None]:
    command, observation = ledger.request_pair(
        scenario, phase.kind.value, phase.command, phase.observation
    )
    ledger, command_fact = _fulfil(ledger, command, fulfil)
    passed, incomplete, detail = _command_verdict(command_fact)
    if incomplete:
        return ledger, PhaseIncomplete(phase.kind, detail), witness
    if not passed:
        finding = ProductFinding(command.action_id, detail, witness)
        return (
            replace(ledger, findings=(*ledger.findings, finding)),
            PhaseFinding(phase.kind, finding),
            witness,
        )
    ledger, observed = _fulfil(ledger, observation, fulfil)
    return _phase_observation_result(ledger, phase, observation, observed, witness)


def _blocked(
    phases: tuple[PhasePlan, ...], witness: InstallationWitness | None
) -> tuple[PhaseBlocked, ...]:
    blocked: list[PhaseBlocked] = []
    for phase in phases:
        if phase.kind is PhaseKind.REINSTALL and not isinstance(witness, InstallationEstablished):
            blocked.append(PhaseBlocked(phase.kind, "InstallationEstablished"))
        elif phase.kind in (PhaseKind.REPAIR, PhaseKind.TARGET_UNINSTALL) and not isinstance(
            witness, StableInstallationEstablished
        ):
            blocked.append(PhaseBlocked(phase.kind, "StableInstallationEstablished"))
    return tuple(blocked)


def _run_lifecycle(
    ledger: _RunLedger, scenario: LifecycleScenario | IsolationScenario, fulfil: Fulfil
) -> tuple[_RunLedger, PhaseScenarioRecord]:
    phases = (
        scenario.phases
        if isinstance(scenario, LifecycleScenario)
        else (*scenario.preparations, scenario.phase)
    )
    witness: InstallationWitness | None = None
    results: list[PhaseResult] = []
    for index, phase in enumerate(phases):
        ledger, result, witness = _run_phase(ledger, scenario.name, phase, witness, fulfil)
        results.append(result)
        if isinstance(result, PhaseIncomplete):
            blocked = _blocked(phases[index + 1 :], witness)
            projected = tuple(results)
            return ledger, PhaseScenarioRecord(
                ScenarioIncomplete(scenario.name, (result.reason,)), projected, blocked
            )
        if isinstance(result, PhaseFinding) and result.finding.witness is None:
            blocked = _blocked(phases[index + 1 :], witness)
            projected = tuple(results)
            return ledger, PhaseScenarioRecord(
                ScenarioFinding(scenario.name, (result.finding,)), projected, blocked
            )
    projected = tuple(results)
    return ledger, PhaseScenarioRecord(roll_up_phases(scenario, projected), projected, ())


def _run_preparation(
    ledger: _RunLedger,
    scenario: AggregateScenario,
    preparation: AggregatePreparation,
    fulfil: Fulfil,
) -> tuple[_RunLedger, AggregatePreparationResult, InstallationEstablished | None]:
    phase = PhasePlan(
        PhaseKind.AGGREGATE_PREPARE,
        preparation.target,
        preparation.scope,
        preparation.command,
        preparation.observation,
    )
    ledger, result, witness = _run_phase(ledger, scenario.name, phase, None, fulfil)
    established = witness if isinstance(witness, InstallationEstablished) else None
    if isinstance(result, PhaseIncomplete):
        return ledger, PreparationIncomplete(preparation.target, result.reason), None
    if isinstance(result, PhaseFinding):
        return ledger, PreparationFinding(preparation.target, result.finding), established
    return (
        ledger,
        PreparationPassed(preparation.target, cast(InstallationEstablished, established)),
        established,
    )


def _aggregate_rollup(
    name: str,
    preparations: tuple[AggregatePreparationResult, ...],
    removal: AggregateUninstallResult,
) -> ScenarioResult:
    reasons = tuple(item.reason for item in preparations if isinstance(item, PreparationIncomplete))
    if isinstance(removal, AggregateUninstallIncomplete):
        reasons = (*reasons, removal.reason)
    if reasons:
        return ScenarioIncomplete(name, reasons)
    findings = tuple(item.finding for item in preparations if isinstance(item, PreparationFinding))
    if isinstance(removal, AggregateUninstallFinding):
        findings = (*findings, removal.finding)
    return ScenarioFinding(name, findings) if findings else ScenarioPassed(name)


def _aggregate_observation_result(
    ledger: _RunLedger,
    scenario: AggregateScenario,
    installations: tuple[str, ...],
    request: ObservationRequest,
    fact: RawFact,
) -> tuple[_RunLedger, AggregateUninstallResult]:
    if isinstance(fact, ActionUnavailable):
        return ledger, AggregateUninstallIncomplete(installations, fact.detail)
    if not isinstance(fact, ObservationFact):
        raise TypeError("aggregate observation returned wrong fact family")
    passed, incomplete, _, detail = _judge_observation(scenario.removal_observation, fact)
    if incomplete:
        return ledger, AggregateUninstallIncomplete(installations, detail)
    if passed:
        return ledger, AggregateUninstallPassed(installations)
    finding = ProductFinding(request.action_id, detail)
    return (
        replace(ledger, findings=(*ledger.findings, finding)),
        AggregateUninstallFinding(installations, finding),
    )


def _run_aggregate_removal(
    ledger: _RunLedger,
    scenario: AggregateScenario,
    installations: tuple[str, ...],
    fulfil: Fulfil,
) -> tuple[_RunLedger, AggregateUninstallResult]:
    if not installations:
        return ledger, AggregateUninstallNotApplicable(
            "no aggregate preparation established an installation"
        )
    command, observation = ledger.request_pair(
        scenario.name,
        PhaseKind.AGGREGATE_UNINSTALL.value,
        scenario.uninstall_command,
        scenario.removal_observation,
    )
    ledger, command_fact = _fulfil(ledger, command, fulfil)
    passed, incomplete, detail = _command_verdict(command_fact)
    if incomplete:
        return ledger, AggregateUninstallIncomplete(installations, detail)
    if not passed:
        finding = ProductFinding(command.action_id, detail)
        return (
            replace(ledger, findings=(*ledger.findings, finding)),
            AggregateUninstallFinding(installations, finding),
        )
    ledger, observed = _fulfil(ledger, observation, fulfil)
    return _aggregate_observation_result(ledger, scenario, installations, observation, observed)


def _run_aggregate(
    ledger: _RunLedger, scenario: AggregateScenario, fulfil: Fulfil
) -> tuple[_RunLedger, AggregateScenarioRecord]:
    results: list[AggregatePreparationResult] = []
    established: list[str] = []
    for preparation in scenario.preparations:
        ledger, result, witness = _run_preparation(ledger, scenario, preparation, fulfil)
        results.append(result)
        if witness is not None:
            established.append(preparation.target)
    preparations = tuple(results)
    ledger, removal = _run_aggregate_removal(ledger, scenario, tuple(established), fulfil)
    record = AggregateScenarioRecord(
        _aggregate_rollup(scenario.name, preparations, removal),
        preparations,
        removal,
        tuple(established),
    )
    return ledger, record


def _run_purge(ledger: _RunLedger, fulfil: Fulfil) -> tuple[_RunLedger, PurgeResult]:
    command, observation = ledger.request_pair(
        "purge", PhaseKind.PURGE.value, ledger.plan.purge.command, ledger.plan.purge.observation
    )
    ledger, command_fact = _fulfil(ledger, command, fulfil)
    passed, incomplete, detail = _command_verdict(command_fact)
    if incomplete:
        return ledger, PurgeIncomplete(detail)
    if not passed:
        finding = ProductFinding(command.action_id, detail)
        return replace(ledger, findings=(*ledger.findings, finding)), PurgeFinding(finding)
    ledger, observed = _fulfil(ledger, observation, fulfil)
    if isinstance(observed, ActionUnavailable):
        return ledger, PurgeIncomplete(observed.detail)
    if not isinstance(observed, ObservationFact):
        raise TypeError("purge observation returned wrong fact family")
    ok, is_incomplete, _, observation_detail = _judge_observation(
        ledger.plan.purge.observation, observed
    )
    if is_incomplete:
        return ledger, PurgeIncomplete(observation_detail)
    if not ok:
        finding = ProductFinding(observation.action_id, observation_detail)
        return replace(ledger, findings=(*ledger.findings, finding)), PurgeFinding(finding)
    return ledger, PurgePassed()


def run_validation(plan: ValidationPlan, run_id: RunId, fulfil: Fulfil) -> ApplicationOutcome:
    """Execute the whole plan through one typed request/fact seam and return all records."""

    ledger = _RunLedger(plan, run_id)
    records: list[ScenarioRecord] = []
    try:
        for scenario in plan.scenarios:
            if isinstance(scenario, UnsupportedScenario):
                unsupported = ScenarioUnsupported(
                    scenario.name, scenario.reason, scenario.limitations
                )
                records.append(UnsupportedScenarioRecord(unsupported))
            elif isinstance(scenario, (LifecycleScenario, IsolationScenario)):
                ledger, record = _run_lifecycle(ledger, scenario, fulfil)
                records.append(record)
            else:
                ledger, record = _run_aggregate(ledger, scenario, fulfil)
                records.append(record)
        ledger, purge_result = _run_purge(ledger, fulfil)
    except (TypeError, ValueError) as error:
        return ValidationIncomplete(
            plan.projection,
            str(error),
            tuple(records),
            ledger.facts,
            ledger.findings,
            ledger.chronology,
        )
    return CompletedValidation(
        plan.projection,
        tuple(records),
        purge_result,
        ledger.facts,
        ledger.findings,
        ledger.chronology,
    )
