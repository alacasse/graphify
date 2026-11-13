"""Declarations retain tool, participant and member identities independently of paths."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from tests.install_sandbox.component.contracts.test_effect_contracts import context
from tools.install_sandbox.contracts.effect_case import (
    CaseKey,
    EffectInstallCase,
    build_effect_cases,
)
from tools.install_sandbox.contracts.effects import ToolDeclaration
from tools.install_sandbox.contracts.intermediate import JsonHookPreparation
from tools.install_sandbox.host.effect_reader import EffectSpecReader

FIXTURE = Path(__file__).parents[2] / "fixtures" / "generic-effects.yaml"

SKILL_OPERATIONS = (
    "missing-reference",
    "altered-reference",
    "altered-skill",
    "preserve-skill-backup",
    "stale-version",
    "stale-reference",
)
MARKDOWN_OPERATIONS = ("missing-section", "altered-section")
HOOK_OPERATIONS = ("missing-json-hook",)


@pytest.mark.parametrize(
    ("effect_ids", "absent_operations"),
    [
        (("skill",), (*MARKDOWN_OPERATIONS, *HOOK_OPERATIONS)),
        (("skill", "markdown-section"), HOOK_OPERATIONS),
        (("skill", "markdown-section", "json-hooks"), ()),
    ],
    ids=["skill", "skill-markdown", "skill-markdown-hooks"],
)
@pytest.mark.parametrize("scope", ["project", "user"])
def test_synthetic_compositions_build_operations_for_their_declared_targets(
    effect_ids: tuple[str, ...], absent_operations: tuple[str, ...], scope: str
) -> None:
    declaration = EffectSpecReader().read(FIXTURE)
    complete = declaration.scopes[0].effects
    assert complete is not None
    spec = replace(
        complete,
        scope=scope,
        effects=tuple(effect for effect in complete.effects if effect.effect_id in effect_ids),
    )
    subject = replace(
        context(), invocation=(), invocations={f"synthetic:{scope}": ("install", scope)}
    )
    built = build_effect_cases(spec, subject, declaration.tool)
    operations_by_effect = {
        "skill": tuple((operation, None) for operation in SKILL_OPERATIONS),
        "markdown-section": tuple((operation, None) for operation in MARKDOWN_OPERATIONS),
        "json-hooks": tuple(
            ("missing-json-hook", member) for member in ("PreToolUse-search", "PreToolUse-read")
        ),
    }
    expected = {
        CaseKey("synthetic", scope, operation, effect.effect_id, member): effect.destination
        for effect in spec.effects
        for operation, member in operations_by_effect[effect.effect_id]
    }
    keys = [case.key for case in built.cases]
    assert len(keys) == len(set(keys))
    assert set(keys) == {CaseKey("synthetic", scope, "reinstall"), *expected}
    assert sorted((entry.name, entry.classification) for entry in built.decisions) == sorted(
        (operation, "not_applicable") for operation in absent_operations
    )
    for case in built.cases:
        assert case.operations == ["install", "install"]
        assert case.subject.invocation == ("install", scope)
        preparation = case.intermediate_preparation
        if case.name == "reinstall":
            assert preparation is None
            continue
        assert preparation is not None
        assert preparation.destination == expected[case.key]
        if isinstance(preparation, JsonHookPreparation):
            assert preparation.member == case.key.member
            assert preparation.effect_id == case.key.effect_id


def two_hooks() -> str:
    return """tool: birch
scopes:
  project:
    - effect_id: editor-hooks
      family: json-hooks
      root: PROJECT
      path: .editor/settings.json
      hooks:
        - id: run
          event: SessionStart
          matcher: '*'
          content: {type: command, command: 'birch run', timeout: 10}
    - effect_id: assistant-hooks
      family: json-hooks
      root: HOME
      path: .assistant/settings.json
      hooks:
        - id: run
          event: SessionStart
          matcher: '*'
          content: {type: command, command: 'birch run', timeout: 10}
"""


def test_each_member_has_a_distinct_key_and_path_independent_storage_identity() -> None:
    reader = EffectSpecReader()
    declaration = reader.from_yaml(two_hooks())
    spec = declaration.scopes[0].effects
    assert spec is not None
    cases = build_effect_cases(spec, context(), declaration.tool).cases
    members = [case for case in cases if case.name == "missing-json-hook"]
    assert [case.key for case in members] == [
        CaseKey("birch", "project", "missing-json-hook", "editor-hooks", "run"),
        CaseKey("birch", "project", "missing-json-hook", "assistant-hooks", "run"),
    ]
    assert len({case.key.storage_id for case in members}) == 2
    moved = reader.from_yaml(two_hooks().replace(".assistant/settings.json", "elsewhere.json"))
    assert moved.scopes[0].effects is not None
    assert [
        c.key for c in build_effect_cases(moved.scopes[0].effects, context(), "birch").cases
    ] == [c.key for c in cases]
    for case in members:
        assert EffectInstallCase.from_json(case.to_json()) == case


def test_member_and_effect_ids_are_unique_within_their_owning_scope() -> None:
    reader = EffectSpecReader()
    with pytest.raises(ValueError, match="Duplicate effect ID"):
        reader.from_yaml(two_hooks().replace("assistant-hooks", "editor-hooks"))
    declaration = reader.from_yaml(two_hooks())
    spec = declaration.scopes[0].effects
    assert spec is not None
    raw = cast(dict[str, Any], declaration.to_data())
    raw["scopes"][0]["effects"]["effects"][0]["hooks"].append(
        raw["scopes"][0]["effects"]["effects"][0]["hooks"][0]
    )
    with pytest.raises(ValueError, match="member ID"):
        ToolDeclaration.from_data(raw)


def test_missing_scope_invocation_retains_applicable_keys_as_unconstructible() -> None:
    declaration = EffectSpecReader().from_yaml(two_hooks().replace("  project:", "  user:"))
    spec = declaration.scopes[0].effects
    assert spec is not None
    built = build_effect_cases(spec, context(), "birch")
    assert not built.cases
    assert len([d for d in built.decisions if d.classification == "unconstructible"]) == 3
    bound = replace(context(), invocations={"birch:user": ("install", "--user")})
    assert all(
        c.subject.invocation == ("install", "--user")
        for c in build_effect_cases(spec, bound, "birch").cases
    )


def test_historical_specs_have_an_explicit_not_converted_diagnostic() -> None:
    with pytest.raises(ValueError, match="not been converted"):
        EffectSpecReader().from_yaml("scopes: {project: {effects: []}}")


def test_transport_rejects_substituted_participant_invocation_and_member() -> None:
    declaration = EffectSpecReader().from_yaml(two_hooks())
    spec = declaration.scopes[0].effects
    assert spec is not None
    subject = replace(
        context(), invocation=(), invocations={"birch:project": ("install", "project")}
    )
    case = next(
        c for c in build_effect_cases(spec, subject, "birch").cases if c.name == "missing-json-hook"
    )
    data = json.loads(case.to_json())
    data["subject"]["invocation"] = ["install", "other-participant"]
    with pytest.raises(ValueError, match="do not match"):
        EffectInstallCase.from_json(json.dumps(data))
    data = json.loads(case.to_json())
    data["intermediate_preparation"]["member"] = "other"
    with pytest.raises(ValueError, match="do not match"):
        EffectInstallCase.from_json(json.dumps(data))


def test_hook_disk_identity_ignores_timeout_and_allows_different_commands() -> None:
    declaration = EffectSpecReader().from_yaml(two_hooks())
    data = cast(dict[str, Any], declaration.to_data())
    first = data["scopes"][0]["effects"]["effects"][0]["hooks"][0]
    second: dict[str, Any] = {
        **first,
        "id": "other",
        "content": {**first["content"], "timeout": 20},
    }
    data["scopes"][0]["effects"]["effects"][0]["hooks"].append(second)
    with pytest.raises(ValueError, match="Duplicate hook destination"):
        ToolDeclaration.from_data(data)
    second["content"]["command"] = "birch other"
    assert ToolDeclaration.from_data(data).tool == "birch"


def test_contract_example_without_timeout_retains_missing_repairs() -> None:
    declaration = EffectSpecReader().from_yaml(two_hooks().replace(", timeout: 10", ""))
    spec = declaration.scopes[0].effects
    assert spec is not None
    built = build_effect_cases(spec, context(), "birch")
    assert [c.name for c in built.cases] == [
        "reinstall",
        "missing-json-hook",
        "missing-json-hook",
    ]
    for case in built.cases:
        assert EffectInstallCase.from_json(case.to_json()) == case


def test_explicit_timeout_is_owned_by_the_declaration() -> None:
    declaration = EffectSpecReader().from_yaml(two_hooks().replace("timeout: 10", "timeout: 37"))
    spec = declaration.scopes[0].effects
    assert spec is not None
    assert len(build_effect_cases(spec, context(), "birch").cases) == 3
