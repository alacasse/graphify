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
from tools.install_sandbox.host.effect_reader import EffectSpecReader

ROOT = Path(__file__).resolve().parents[4]


def test_active_specs_preserve_project_facts_and_unconverted_user_obligation() -> None:
    expected = {
        "agents": ("project", ".agents/skills/graphify", 8),
        "copilot": ("project", ".copilot/skills/graphify", 8),
        "kimi": ("project", ".kimi/skills/graphify", 8),
        "pi": ("project", ".pi/agent/skills/graphify", 8),
        "amp": ("project", ".agents/skills/graphify", 10),
        "codebuddy": ("home", ".codebuddy/skills/graphify", 16),
    }
    for tool, (root, path, count) in expected.items():
        declaration = EffectSpecReader().read(ROOT / f"tools/install_sandbox/specs/{tool}.yaml")
        assert declaration.tool == tool
        assert ToolDeclaration.from_data(declaration.to_data()) == declaration
        project, user = declaration.scopes
        assert project.scope == "project" and project.effects is not None
        assert project.effects.effects[0].destination.root == root
        assert project.effects.effects[0].destination.path == path
        assert len(build_effect_cases(project.effects, context(), tool).cases) == count
        assert user.scope == "user" and user.effects is None
        assert user.classification == "unconstructible" and user.reason


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
    duplicates = [case for case in cases if case.name == "duplicate-json-hook"]
    assert [case.key for case in duplicates] == [
        CaseKey("birch", "project", "duplicate-json-hook", "editor-hooks", "run"),
        CaseKey("birch", "project", "duplicate-json-hook", "assistant-hooks", "run"),
    ]
    assert len({case.key.storage_id for case in duplicates}) == 2
    moved = reader.from_yaml(two_hooks().replace(".assistant/settings.json", "elsewhere.json"))
    assert moved.scopes[0].effects is not None
    assert [
        c.key for c in build_effect_cases(moved.scopes[0].effects, context(), "birch").cases
    ] == [c.key for c in cases]
    for case in duplicates:
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
    assert len([d for d in built.decisions if d.classification == "unconstructible"]) == 7
    bound = replace(context(), invocations={"birch:user": ("install", "--user")})
    assert all(
        c.subject.invocation == ("install", "--user")
        for c in build_effect_cases(spec, bound, "birch").cases
    )


def test_historical_specs_have_an_explicit_not_converted_diagnostic() -> None:
    with pytest.raises(ValueError, match="not been converted"):
        EffectSpecReader().read(ROOT / "tools/install_sandbox/specs/claude.yaml")


def test_transport_rejects_substituted_participant_invocation_and_member() -> None:
    declaration = EffectSpecReader().from_yaml(two_hooks())
    spec = declaration.scopes[0].effects
    assert spec is not None
    subject = replace(
        context(), invocation=(), invocations={"birch:project": ("install", "project")}
    )
    case = next(
        c
        for c in build_effect_cases(spec, subject, "birch").cases
        if c.name == "duplicate-json-hook"
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
    second: dict[str, Any] = {**first, "id": "other", "content": {**first["content"], "timeout": 20}}
    data["scopes"][0]["effects"]["effects"][0]["hooks"].append(second)
    with pytest.raises(ValueError, match="Duplicate hook destination"):
        ToolDeclaration.from_data(data)
    second["content"]["command"] = "birch other"
    assert ToolDeclaration.from_data(data).tool == "birch"


def test_contract_example_without_timeout_retains_missing_and_duplicate_repairs() -> None:
    declaration = EffectSpecReader().from_yaml(two_hooks().replace(", timeout: 10", ""))
    spec = declaration.scopes[0].effects
    assert spec is not None
    built = build_effect_cases(spec, context(), "birch")
    assert [c.name for c in built.cases] == [
        "reinstall",
        "missing-json-hook",
        "missing-json-hook",
        "duplicate-json-hook",
        "duplicate-json-hook",
    ]
    altered = [d for d in built.decisions if d.name == "altered-json-hook"]
    assert [d.key for d in altered] == [
        CaseKey("birch", "project", "altered-json-hook", "editor-hooks", "run"),
        CaseKey("birch", "project", "altered-json-hook", "assistant-hooks", "run"),
    ]
    assert all(d.classification == "not_applicable" for d in altered)
    for case in built.cases:
        assert EffectInstallCase.from_json(case.to_json()) == case


def test_explicit_timeout_is_owned_by_the_declaration() -> None:
    declaration = EffectSpecReader().from_yaml(two_hooks().replace("timeout: 10", "timeout: 37"))
    spec = declaration.scopes[0].effects
    assert spec is not None
    assert len(build_effect_cases(spec, context(), "birch").cases) == 7
