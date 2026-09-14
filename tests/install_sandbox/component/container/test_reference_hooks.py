"""Hook comparisons through the verifier's observation boundary."""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tests.install_sandbox.component.container.observations_verifier_support import (
    assert_passed,
    scenario,
)
from tools.install_sandbox.contracts.spec import HookExpectation

GRAPHIFY = {"type": "command", "command": "graphify hook-guard search"}
PERSONAL = {"type": "command", "command": "python personal_graphify_audit.py", "timeout": 17}


def _document() -> dict[str, Any]:
    return {
        "theme": "dark",
        "instructions": ["my-instructions.md", "skills/graphify/SKILL.md"],
        "hooks": {
            "PreToolUse": [{"matcher": "Bash|Grep", "hooks": [PERSONAL.copy(), GRAPHIFY.copy()]}]
        },
    }


def _damage_graphify(document: dict[str, Any], defect: str) -> None:
    group = document["hooks"]["PreToolUse"][0]
    hooks = group["hooks"]
    if defect == "absent":
        hooks.pop()
    elif defect == "duplicate":
        hooks.append(GRAPHIFY.copy())
    elif defect == "split_duplicate":
        document["hooks"]["PreToolUse"].append(
            {"matcher": "Bash|Grep", "hooks": [GRAPHIFY | {"extra": 2}]}
        )
    elif defect in {"command", "type"}:
        hooks[1][defect] = "different"
    elif defect == "invalid_groups":
        document["hooks"]["PreToolUse"] = {}
    elif defect == "invalid_hooks":
        group["hooks"] = {}


def _damage_personal(document: dict[str, Any], defect: str) -> None:
    hooks = document["hooks"]["PreToolUse"][0]["hooks"]
    if defect == "personal_absent":
        hooks.pop(0)
    elif defect == "personal_duplicate":
        hooks.append(PERSONAL.copy())
    elif defect == "personal_added":
        hooks[0]["extra"] = True
    elif defect == "personal_removed":
        hooks[0].pop("timeout")
    elif defect == "personal_changed":
        hooks[0]["timeout"] = 18


def _move_hook(document: dict[str, Any], defect: str) -> None:
    hooks = document["hooks"]["PreToolUse"][0]["hooks"]
    hook = hooks.pop(0 if defect.startswith("personal") else -1)
    if defect.endswith("event"):
        document["hooks"]["OtherEvent"] = [{"matcher": "Bash|Grep", "hooks": [hook]}]
    else:
        document["hooks"]["PreToolUse"].append({"matcher": "Grep|Bash", "hooks": [hook]})


@pytest.mark.parametrize(
    "defect",
    [
        "absent",
        "duplicate",
        "split_duplicate",
        "event",
        "matcher",
        "command",
        "type",
        "personal_absent",
        "personal_duplicate",
        "personal_event",
        "personal_matcher",
        "personal_added",
        "personal_removed",
        "personal_changed",
        "invalid_groups",
        "invalid_hooks",
    ],
)
def test_hook_defects_have_factual_diagnostics(tmp_path: Path, defect: str) -> None:
    run = scenario(tmp_path)
    run.effects()
    document = _document()
    if defect.endswith(("event", "matcher")):
        _move_hook(document, defect)
    elif defect.startswith("personal"):
        _damage_personal(document, defect)
    else:
        _damage_graphify(document, defect)
    run.path("json").write_text(json.dumps(document))
    result = run.verify()
    kind = "personal_hook_count" if defect.startswith("personal") else "hook_count"
    if defect.startswith("invalid"):
        kind = "invalid_json_hooks"
    mismatch = next(m for m in result.mismatches if m.type == kind)
    expected = json.loads(mismatch.expected)
    assert expected["event"] == "PreToolUse" and expected["matcher"] == "Bash|Grep"
    assert expected["count"] == 1 and "content" in expected
    assert mismatch.path.endswith("settings.json")
    if not defect.startswith("invalid"):
        observed = json.loads(mismatch.observed)
        count = 2 if "duplicate" in defect else 0
        assert observed["count"] == count
        assert len(observed["positions"]) == count
        if defect == "split_duplicate":
            assert observed["positions"] == [
                "hooks.PreToolUse[0].hooks[1]",
                "hooks.PreToolUse[1].hooks[0]",
            ]


@pytest.mark.parametrize("variation", ["position", "groups", "extra", "format", "unknown"])
def test_allowed_hook_variations(tmp_path: Path, variation: str) -> None:
    run = scenario(tmp_path)
    run.effects()
    document = _document()
    hooks = document["hooks"]["PreToolUse"][0]["hooks"]
    if variation == "position":
        hooks.reverse()
    elif variation == "groups":
        document["hooks"]["PreToolUse"].append({"matcher": "Bash|Grep", "hooks": [hooks.pop()]})
    elif variation == "extra":
        hooks[1]["arbitrary"] = {"values": [False, None, 3]}
    elif variation == "unknown":
        hooks[0]["type"] = "unknown-personal-type"
        initial = deepcopy(run.case.initial_files)
        data = json.loads(initial[1]["content"])
        data["hooks"]["PreToolUse"][0]["hooks"][0]["type"] = "unknown-personal-type"
        initial[1]["content"] = json.dumps(data)
        run.case = replace(run.case, initial_files=initial)
    run.path("json").write_text(json.dumps(document, indent=4, sort_keys=True))
    assert_passed(run.verify())


@pytest.mark.parametrize(
    "observed,passed",
    [
        ({"mode": "strict", "values": [1, 2]}, True),
        ({"values": [1, 2], "mode": "strict"}, True),
        ({"mode": "strict", "values": [2, 1]}, False),
        ({"mode": "strict", "values": [True, 2]}, False),
        ({"mode": "strict", "values": [1.0, 2]}, False),
        ({"mode": "strict", "values": [1, 2], "extra": 0}, False),
    ],
)
def test_structured_fields_are_compared_in_full(
    tmp_path: Path, observed: object, passed: bool
) -> None:
    run = scenario(tmp_path)
    run.effects()
    content: dict[str, object] = {
        "type": "another-type",
        "options": {"mode": "strict", "values": [1, 2]},
    }
    spec = replace(run.case.spec, json_hooks=(HookExpectation("BeforeTool", "Any", content),))
    run.case = replace(run.case, spec=spec)
    document = _document()
    document["hooks"]["BeforeTool"] = [
        {
            "matcher": "Any",
            "hooks": [{"type": "another-type", "options": observed, "extra": "allowed"}],
        }
    ]
    run.path("json").write_text(json.dumps(document))
    result = run.verify()
    assert (not result.mismatches) == passed


def test_reinstall_cannot_adopt_a_damaged_personal_baseline(tmp_path: Path) -> None:
    run = scenario(tmp_path)
    run.effects()
    document = _document()
    document["hooks"]["PreToolUse"][0]["hooks"].pop(0)
    content = json.dumps(document).encode()
    run.before.contents[("project", ".sandbox-reference/settings.json")] = content
    run.path("json").write_bytes(content)
    run.case = replace(run.case, name="reinstall", operations=["install", "install"])
    assert any(m.type == "personal_hook_count" for m in run.verify().mismatches)


@pytest.mark.parametrize("change", ["none", "list_order", "count"])
def test_personal_structured_content_and_original_count(tmp_path: Path, change: str) -> None:
    run = scenario(tmp_path)
    run.effects()
    personal = {**PERSONAL, "unknown": {"items": ["first", "second"]}}
    initial = deepcopy(run.case.initial_files)
    data = json.loads(initial[1]["content"])
    data["hooks"]["PreToolUse"] = [
        {"matcher": "Bash|Grep", "hooks": [personal]},
        {"matcher": "Bash|Grep", "hooks": [personal]},
    ]
    initial[1]["content"] = json.dumps(data)
    run.case = replace(run.case, initial_files=initial)
    document = _document()
    document["hooks"]["PreToolUse"][0]["hooks"] = [GRAPHIFY, deepcopy(personal), deepcopy(personal)]
    if change == "list_order":
        document["hooks"]["PreToolUse"][0]["hooks"][1]["unknown"]["items"].reverse()
    elif change == "count":
        document["hooks"]["PreToolUse"][0]["hooks"].pop()
    run.path("json").write_text(json.dumps(document))
    result = run.verify()
    if change == "none":
        assert_passed(result)
    else:
        mismatch = next(m for m in result.mismatches if m.type == "personal_hook_count")
        assert json.loads(mismatch.expected)["count"] == 2
        assert json.loads(mismatch.observed)["count"] == 1
