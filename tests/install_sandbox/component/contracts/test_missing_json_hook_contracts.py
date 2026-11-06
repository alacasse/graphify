"""JSON hook repair construction is effect-driven and validates retained witnesses."""

import json
from dataclasses import replace

import pytest

from tests.install_sandbox.component.contracts.test_effect_contracts import context, structured_spec
from tools.install_sandbox.contracts.effect_case import EffectInstallCase, build_effect_cases
from tools.install_sandbox.contracts.effects import Destination, EffectSpec, JsonHooksEffect
from tools.install_sandbox.contracts.intermediate import JsonHookPreparation


@pytest.mark.parametrize("kind", ["missing-json-hook", "altered-json-hook", "duplicate-json-hook"])
def test_hook_selection_ignores_markdown_and_skill_cardinality(kind: str) -> None:
    original = structured_spec().effects[-1]
    assert isinstance(original, JsonHooksEffect)
    first = replace(original, destination=Destination("home", "first.json"))
    second = replace(original, destination=Destination("project", "second.json"))
    built = build_effect_cases(EffectSpec((first, second)), context())
    case = next(case for case in built.cases if case.name == kind)
    assert case.intermediate_preparation == JsonHookPreparation(first.destination, kind)
    assert EffectInstallCase.from_json(case.to_json()) == case
    initial = next(item for item in case.initial_files if item["path"] == "first.json")
    groups = json.loads(initial["content"])["hooks"][first.hooks[0].event]
    assert groups[0] == {
        "matcher": first.hooks[0].matcher,
        "sandbox_personal": "preserve",
        "hooks": [
            first.hooks[0].content,
            {"type": "command", "command": "python personal_graphify_audit.py", "timeout": 17},
        ],
    }
    assert groups[-1]["sandbox_neighbor"] is True
    if kind == "duplicate-json-hook":
        assert groups[1] == {
            "matcher": first.hooks[0].matcher,
            "sandbox_personal": "duplicate-destination",
            "hooks": [
                {"type": "command", "command": "python personal_duplicate_a.py", "timeout": 19},
                {"type": "command", "command": "python personal_duplicate_b.py", "timeout": 29},
            ],
        }
        assert len(groups) == 3
    else:
        assert len(groups) == 2
    assert first.hooks[1].content not in groups[0]["hooks"]
    reinstall = built.cases[0]
    assert reinstall.initial_files != case.initial_files


@pytest.mark.parametrize("kind", ["missing-json-hook", "altered-json-hook", "duplicate-json-hook"])
@pytest.mark.parametrize(
    "change", ["witness", "destination", "kind", "invalid-kind", "extra", "missing"]
)
def test_retained_hook_case_rejects_modified_contract(change: str, kind: str) -> None:
    built = build_effect_cases(structured_spec(), context())
    case = next(case for case in built.cases if case.name == kind)
    raw = json.loads(case.to_json())
    preparation = raw["intermediate_preparation"]
    if change == "witness":
        item = next(item for item in raw["initial_files"] if item["path"].endswith("config.json"))
        item["content"] = item["content"].replace('"timeout": 17', '"timeout": 18')
    elif change == "destination":
        preparation["destination"]["root"] = "home"
    elif change == "kind":
        preparation["kind"] = "unsupported-hook-operation"
    elif change == "invalid-kind":
        preparation["kind"] = []
    elif change == "missing":
        del preparation["destination"]
    else:
        preparation["selection"] = "first"
    with pytest.raises(ValueError):
        EffectInstallCase.from_json(json.dumps(raw))


def test_duplicate_case_rejects_changed_destination_group_witness() -> None:
    built = build_effect_cases(structured_spec(), context())
    case = next(case for case in built.cases if case.name == "duplicate-json-hook")
    raw = json.loads(case.to_json())
    item = next(item for item in raw["initial_files"] if item["path"].endswith("config.json"))
    settings = json.loads(item["content"])
    groups = settings["hooks"]["PreToolUse"]
    groups[1]["hooks"].reverse()
    item["content"] = json.dumps(settings, indent=2) + "\n"
    with pytest.raises(ValueError, match="do not match definition"):
        EffectInstallCase.from_json(json.dumps(raw))
