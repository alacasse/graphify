"""Pure family inspection and grouped removal assessment over retained observations."""

from dataclasses import asdict, dataclass, replace

from tools.install_sandbox.contracts.effects import (
    JSON_BACKUP_SUFFIX,
    Effect,
    EffectSpec,
    FileEffect,
    JsonHooksEffect,
    physical_destinations,
)
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import (
    ObservationObstacle,
    VerificationMismatch,
    VerificationResult,
)
from tools.install_sandbox.contracts.spec import HookExpectation
from tools.install_sandbox.rules import comparison as checks


@dataclass(frozen=True)
class ElementState:
    effect_id: str
    member: str
    root: str
    path: str
    presence: str
    conformity: str


@dataclass(frozen=True)
class Diagnostic:
    root: str
    path: str
    member: str
    reason: str


@dataclass(frozen=True)
class FamilyInspection:
    items: tuple[ElementState, ...]
    preservation: str
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class ParticipantAssessment:
    role: str
    summary: str
    preservation: str
    items: tuple[ElementState, ...]
    diagnostics: tuple[Diagnostic, ...]
    complete: bool


def _presence(snapshot: FilesystemSnapshot, root: str, path: str) -> str:
    entry = snapshot.entry(root, path)
    if entry is not None:
        return "indeterminate" if entry["kind"] == "unknown" else "present"
    return "absent" if snapshot.absent(root, path) else "indeterminate"


def _identity_hooks(effect: JsonHooksEffect) -> tuple[HookExpectation, ...]:
    return tuple(
        replace(hook, content={k: hook.content[k] for k in ("type", "command")})
        for hook in effect.hooks
    )


def _element(effect: Effect, member: str, presence: str, conformity: str) -> ElementState:
    return ElementState(
        effect.effect_id,
        member,
        effect.destination.root,
        effect.destination.path,
        presence,
        conformity,
    )


def _json_items(effect: JsonHooksEffect, document: dict[str, object]) -> tuple[ElementState, ...]:
    items: list[ElementState] = []
    for hook, identity in zip(effect.hooks, _identity_hooks(effect), strict=True):
        try:
            count = len(
                checks.hook_positions(
                    document, hook.event, hook.matcher, identity.content, exact=False
                )
            )
            valid = len(
                checks.hook_positions(document, hook.event, hook.matcher, hook.content, exact=False)
            )
            conformity = (
                "not_applicable" if not count else "valid" if count == valid == 1 else "invalid"
            )
            items.append(_element(effect, hook.id, "present" if count else "absent", conformity))
        except (ValueError, UnicodeError):
            items.append(_element(effect, hook.id, "indeterminate", "indeterminate"))
    return tuple(items)


def _personal_preservation(
    effect: JsonHooksEffect,
    initial: FilesystemSnapshot,
    document: dict[str, object] | None,
    presence: str,
) -> str:
    root, path = effect.destination.root, effect.destination.path
    baseline = initial.contents.get((root, path))
    if baseline is None:
        return "not_applicable" if initial.absent(root, path) else "indeterminate"
    identities = _identity_hooks(effect)
    try:
        personal = checks.personal_json(identities, checks.read_json(baseline))
        if document is not None:
            current = checks.personal_json(identities, document)
            return "preserved" if checks.json_equal(personal, current) else "violated"
        if presence == "absent":
            return "preserved" if checks.json_equal(personal, {}) else "violated"
    except (ValueError, UnicodeError):
        pass
    return "indeterminate"


def _inspect_json(
    effect: JsonHooksEffect, initial: FilesystemSnapshot, observed: FilesystemSnapshot
) -> FamilyInspection:
    root, path = effect.destination.root, effect.destination.path
    presence = _presence(observed, root, path)
    content = observed.contents.get((root, path))
    document = None
    diagnostics: list[Diagnostic] = []
    items: tuple[ElementState, ...] = ()
    entry = observed.entry(root, path)
    if entry is not None and entry["kind"] == "file" and content is not None:
        try:
            document = checks.read_json(content)
            items = _json_items(effect, document)
        except (ValueError, UnicodeError):
            document = None
            diagnostics.append(Diagnostic(root, path, "*", "Invalid JSON content"))
    if not items:
        items = tuple(
            _element(
                effect,
                hook.id,
                "absent" if presence == "absent" else "indeterminate",
                "not_applicable" if presence == "absent" else "indeterminate",
            )
            for hook in effect.hooks
        )
    diagnostics.extend(
        Diagnostic(root, path, item.member, "Hook duplicated or content differs")
        for item in items
        if item.conformity == "invalid"
    )
    diagnostics.extend(
        Diagnostic(root, path, item.member, "Hook observation unavailable")
        for item in items
        if item.presence == "indeterminate"
    )
    preservation = _personal_preservation(effect, initial, document, presence)
    if preservation == "violated":
        diagnostics.append(Diagnostic(root, path, "*", "Personal JSON changed"))
    return FamilyInspection(items, preservation, tuple(diagnostics))


def inspect(
    effect: Effect, initial: FilesystemSnapshot, observed: FilesystemSnapshot
) -> FamilyInspection:
    """Keep lstat presence distinct from readable bytes and semantic conformity."""
    if isinstance(effect, JsonHooksEffect):
        return _inspect_json(effect, initial, observed)
    if not isinstance(effect, FileEffect):
        raise ValueError("Grouped inspection supports file and json-hooks families only")
    root, path = effect.destination.root, effect.destination.path
    presence = _presence(observed, root, path)
    content = observed.contents.get((root, path))
    conformity = "not_applicable" if presence == "absent" else "indeterminate"
    entry = observed.entry(root, path)
    if presence == "present" and entry is not None:
        if entry["kind"] != "file":
            conformity = "invalid"
        elif content is not None:
            conformity = "valid" if content == effect.content.encode("utf-8") else "invalid"
    diagnostics = (
        (Diagnostic(root, path, effect.effect_id, "Declared content differs"),)
        if conformity == "invalid"
        else ()
    )
    return FamilyInspection(
        (_element(effect, effect.effect_id, presence, conformity),), "not_applicable", diagnostics
    )


def _aggregate(states: list[str]) -> str:
    if "violated" in states:
        return "violated"
    if "indeterminate" in states:
        return "indeterminate"
    return "preserved" if "preserved" in states else "not_applicable"


def _owned(effect: Effect, root: str, path: str) -> bool:
    return any(
        d.root == root and (path == d.path or path.startswith(d.path + "/"))
        for d in physical_destinations(effect)
    )


def _path_preservation(
    before: FilesystemSnapshot, after: FilesystemSnapshot, root: str, path: str
) -> str:
    left_presence, right_presence = _presence(before, root, path), _presence(after, root, path)
    if "indeterminate" in (left_presence, right_presence):
        return "indeterminate"
    if left_presence != right_presence:
        return "violated"
    if left_presence == "absent":
        return "preserved"
    prior, current = before.entry(root, path), after.entry(root, path)
    assert prior is not None and current is not None
    if prior["kind"] != current["kind"]:
        return "violated"
    if prior["kind"] == "file":
        left, right = before.contents.get((root, path)), after.contents.get((root, path))
        return (
            "indeterminate"
            if left is None or right is None
            else ("preserved" if left == right else "violated")
        )
    if prior["kind"] == "directory":
        return (
            "preserved"
            if prior.get("listing_complete") and current.get("listing_complete")
            else "indeterminate"
        )
    return "indeterminate"


def _protected(
    effects: tuple[Effect, ...], before: FilesystemSnapshot, after: FilesystemSnapshot
) -> tuple[str, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    states: list[str] = []
    keys = {
        (e["root"], e["path"])
        for s in (before, after)
        for e in s.entries
        if any(_owned(effect, e["root"], e["path"]) for effect in effects)
    }
    keys.update((e.destination.root, e.destination.path) for e in effects)
    for root, path in sorted(keys):
        state = _path_preservation(before, after, root, path)
        states.append(state)
        if state != "preserved":
            diagnostics.append(Diagnostic(root, path, "*", "Protected path " + state))
    return _aggregate(states), diagnostics


def _participant_obstacles(effects: tuple[Effect, ...], snapshot: FilesystemSnapshot) -> bool:
    return any(
        obstacle["root"] == destination.root
        and (
            obstacle["path"] == "."
            or obstacle["path"] == destination.path
            or obstacle["path"].startswith(destination.path + "/")
            or destination.path.startswith(obstacle["path"] + "/")
        )
        for obstacle in snapshot.obstacles
        for effect in effects
        for destination in physical_destinations(effect)
    )


def assess_participant(
    effects: EffectSpec,
    initial: FilesystemSnapshot,
    before: FilesystemSnapshot,
    after: FilesystemSnapshot,
    role: str,
) -> ParticipantAssessment:
    inspections = [inspect(e, initial, after) for e in effects.effects]
    items = tuple(item for inspection in inspections for item in inspection.items)
    diagnostics = [d for inspection in inspections for d in inspection.diagnostics]
    presences = {item.presence for item in items}
    summary = (
        "all_removed"
        if presences == {"absent"}
        else "none_removed"
        if presences == {"present"}
        else "partially_removed"
        if {"present", "absent"} <= presences
        else "indeterminate"
    )
    preservation = _aggregate([i.preservation for i in inspections])
    if role == "protected":
        preservation, protected_diagnostics = _protected(effects.effects, before, after)
        diagnostics.extend(protected_diagnostics)
    complete = (
        not _participant_obstacles(effects.effects, after)
        and all(i.presence != "indeterminate" and i.conformity != "indeterminate" for i in items)
        and preservation != "indeterminate"
    )
    return ParticipantAssessment(role, summary, preservation, items, tuple(diagnostics), complete)


def _collateral(
    targeted: tuple[Effect, ...],
    before: FilesystemSnapshot,
    after: FilesystemSnapshot,
    removing: bool,
    result: VerificationResult,
) -> None:
    keys = {(e["root"], e["path"]) for snapshot in (before, after) for e in snapshot.entries}
    for root, path in sorted(keys):
        if any(
            e.destination.root == root
            and (
                path == e.destination.path
                or (
                    not removing
                    and isinstance(e, JsonHooksEffect)
                    and path == e.destination.path + JSON_BACKUP_SUFFIX
                )
            )
            for e in targeted
        ):
            continue
        prior, current = before.entry(root, path), after.entry(root, path)
        if (
            not removing
            and prior is None
            and current is not None
            and current["kind"] == "directory"
            and any(
                e.destination.root == root and e.destination.path.startswith(path + "/")
                for e in targeted
            )
        ):
            continue
        if _path_preservation(before, after, root, path) != "violated":
            continue
        result.mismatches.append(
            VerificationMismatch(
                "unexpected_change", root, path, "entry preserved", "entry changed"
            )
        )


def _verify_json_auxiliaries(
    effects: tuple[Effect, ...],
    before: FilesystemSnapshot,
    after: FilesystemSnapshot,
    after_obstacles: list[ObservationObstacle],
    result: VerificationResult,
) -> None:
    from tools.install_sandbox.rules.effect_verifier import verify_constraints
    from tools.install_sandbox.rules.expectation_builder import (
        json_auxiliary_expectations,
        json_forbidden_expectations,
    )

    for effect in effects:
        if not isinstance(effect, JsonHooksEffect):
            continue
        try:
            constraints = json_auxiliary_expectations(effect, before)
        except ValueError:
            result.obstacles.append(
                ObservationObstacle(
                    operation="verify_json_auxiliary",
                    root=effect.destination.root,
                    path=effect.destination.path,
                    reason="Retained backup baseline unavailable",
                )
            )
            constraints = json_forbidden_expectations(effect)
        verdict = verify_constraints(constraints, after)
        result.mismatches.extend(verdict.mismatches)
        result.obstacles.extend(verdict.obstacles)
        auxiliary_paths = {(item.root, item.path) for item in constraints}
        result.obstacles.extend(
            obstacle
            for obstacle in after_obstacles
            if (obstacle["root"], obstacle["path"]) in auxiliary_paths
        )


def _apply_auxiliaries(
    assessments: dict[str, ParticipantAssessment],
    participants: dict[str, EffectSpec],
    active: tuple[str, ...],
    before: FilesystemSnapshot,
    after: FilesystemSnapshot,
    after_obstacles: list[ObservationObstacle],
    result: VerificationResult,
) -> None:
    for key in active:
        verdict = VerificationResult()
        _verify_json_auxiliaries(participants[key].effects, before, after, after_obstacles, verdict)
        prior = assessments[key]
        diagnostics = (
            *(Diagnostic(m.root, m.path, "*", m.type) for m in verdict.mismatches),
            *(Diagnostic(o["root"], o["path"], "*", o["reason"]) for o in verdict.obstacles),
        )
        auxiliary_preservation = "not_applicable"
        if verdict.mismatches:
            auxiliary_preservation = "violated"
        elif verdict.obstacles:
            auxiliary_preservation = "indeterminate"
        preservation = _aggregate([prior.preservation, auxiliary_preservation])
        assessments[key] = replace(
            prior,
            preservation=preservation,
            diagnostics=(*prior.diagnostics, *diagnostics),
            complete=prior.complete and not verdict.obstacles,
        )
        result.mismatches.extend(verdict.mismatches)
        result.obstacles.extend(verdict.obstacles)


def assess_group_step(
    participants: dict[str, EffectSpec],
    prepared: tuple[str, ...],
    active: tuple[str, ...],
    removing: bool,
    initial: FilesystemSnapshot,
    before: FilesystemSnapshot,
    after: FilesystemSnapshot,
) -> tuple[dict[str, object], VerificationResult]:
    """Project one preparation or removal independently of the process status."""
    from tools.install_sandbox.rules.effect_verifier import observation_obstacles

    selected = {key: participants[key] for key in dict.fromkeys((*prepared, *active))}
    assessments = {
        key: assess_participant(
            spec,
            initial,
            before,
            after,
            ("targeted" if removing else "preparing") if key in active else "protected",
        )
        for key, spec in selected.items()
    }
    result = VerificationResult()
    after_obstacles = observation_obstacles(after)
    _apply_auxiliaries(assessments, participants, active, before, after, after_obstacles, result)
    for key, assessment in assessments.items():
        if key not in active:
            valid = assessment.preservation == "preserved"
        elif removing:
            valid = assessment.summary == "all_removed"
        else:
            valid = all(
                i.presence == "present" and i.conformity == "valid" for i in assessment.items
            )
        if not valid or assessment.preservation == "violated":
            result.mismatches.append(
                VerificationMismatch(
                    "group_contract",
                    "project",
                    ".",
                    key,
                    assessment.summary + ":" + assessment.preservation,
                )
            )
    _collateral(
        tuple(e for key in active for e in participants[key].effects),
        before,
        after,
        removing,
        result,
    )
    # Completeness obstacles do not discard the facts that could be read elsewhere.
    collected = (*result.obstacles, *observation_obstacles(before), *after_obstacles)
    result.obstacles = []
    for obstacle in collected:
        if obstacle not in result.obstacles:
            result.obstacles.append(obstacle)
    result.complete = not result.obstacles and all(a.complete for a in assessments.values())
    return {
        key: {
            **asdict(value),
            "items": [asdict(i) for i in value.items],
            "diagnostics": [asdict(d) for d in value.diagnostics],
        }
        for key, value in assessments.items()
    }, result
