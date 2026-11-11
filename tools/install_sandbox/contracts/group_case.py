"""Compile explicit ordered participant commands without inventing product syntax."""

import json
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import Any, cast

from tools.install_sandbox.contracts.effect_case import (
    CaseKey,
    EffectInstallCase,
    StepInvocation,
    SubjectContext,
    effect_initial_files,
    validate_effect_rules,
)
from tools.install_sandbox.contracts.effects import (
    Destination,
    EffectSpec,
    FileEffect,
    JsonHooksEffect,
    physical_destinations,
)
from tools.install_sandbox.contracts.spec import fields, text


class GroupNotConstructible(ValueError):
    """A valid request cannot be operated with the declared subject/effects."""


@dataclass(frozen=True)
class GroupPlan:
    participants: dict[str, EffectSpec]
    prepare: tuple[str, ...]
    remove: tuple[str, ...]


def _validate_destinations(participants: dict[str, EffectSpec], prepare: tuple[str, ...]) -> None:
    reserved: list[Destination] = []
    for participant in prepare:
        parts = participant.split(":")
        if len(parts) != 2 or not all(parts) or participants[participant].scope != parts[1]:
            raise ValueError("Participant scope does not match effect declaration")
        for effect in participants[participant].effects:
            if not isinstance(effect, (FileEffect, JsonHooksEffect)):
                raise GroupNotConstructible(
                    "Group verifier supports only literal file and JSON hooks effects"
                )
            for destination in physical_destinations(effect):
                path = PurePosixPath(destination.path)
                for previous in reserved:
                    other = PurePosixPath(previous.path)
                    if destination.root == previous.root and (
                        path == other or path in other.parents or other in path.parents
                    ):
                        raise GroupNotConstructible(
                            "Group effect destinations overlap, including auxiliary files"
                        )
                reserved.append(destination)


def build_group_case(
    participants: dict[str, EffectSpec],
    prepare: tuple[str, ...],
    remove: tuple[str, ...],
    subject: SubjectContext,
    selected_tool: str,
) -> EffectInstallCase:
    if (
        not prepare
        or not remove
        or len(set(prepare)) != len(prepare)
        or len(set(remove)) != len(remove)
    ):
        raise ValueError("Group participants must be nonempty and distinct")
    if set(participants) != set(prepare) or not set(remove) <= set(prepare):
        raise ValueError("Removed participants must have been prepared")
    if not any(p.rsplit(":", 1)[0] == selected_tool for p in prepare):
        raise ValueError("Selected tool must participate in group preparation")
    _validate_destinations(participants, prepare)
    for spec in participants.values():
        validate_effect_rules(spec, subject)
    if any(p not in subject.invocations for p in prepare):
        raise GroupNotConstructible("Group preparation requires explicit participant invocations")
    installs = tuple(StepInvocation("install", (p,), subject.invocations[p]) for p in prepare)
    removals = [step for step in subject.removals if step.participants == remove]
    if len(removals) != 1 or removals[0].action != "uninstall":
        raise GroupNotConstructible("Missing unique invocation for ordered removal participants")
    effects = EffectSpec(
        tuple(
            replace(effect, effect_id=f"{index}:{effect.effect_id}")
            for index, p in enumerate(prepare)
            for effect in participants[p].effects
        ),
        "group",
    )
    initial = effect_initial_files(effects)
    plan = (*installs, removals[0])
    return EffectInstallCase(
        "group-uninstall",
        CaseKey(selected_tool, "group", "group-uninstall", prepare=prepare, remove=remove),
        subject.identity,
        "group",
        effects,
        subject,
        initial,
        [step.action for step in plan],
        participants=tuple(participants.items()),
        plan=plan,
    )


def group_from_data(data: dict[str, Any]) -> EffectInstallCase:
    key = CaseKey.from_data(data["key"])
    if not isinstance(data["participants"], list):
        raise ValueError("Invalid group participant transport")
    raw = cast(list[object], data["participants"])
    participants: dict[str, EffectSpec] = {}
    for value in raw:
        item = fields(value, "participant effects")
        participant = text(item["participant"])
        if participant in participants:
            raise ValueError("Duplicate participant transport")
        participants[participant] = EffectSpec.from_data(item["effects"])
    case = build_group_case(
        participants, key.prepare, key.remove, SubjectContext.from_data(data["subject"]), key.tool
    )

    checks = {
        "key": case.key.to_data(),
        "name": case.name,
        "target": case.target,
        "scope": case.scope,
        "effects": case.effects.to_data(),
        "initial_files": case.initial_files,
        "operations": case.operations,
        "intermediate_preparation": None,
        "plan": [step.to_data() for step in case.steps],
    }
    stored = {name: data[name] for name in checks}
    if json.dumps(stored, sort_keys=True) != json.dumps(checks, sort_keys=True):
        raise ValueError("Group transport does not match compiled definition")
    return case
