"""Verify sandbox behavior at its owning boundary."""

import json
from pathlib import Path

import pytest

from tools.install_sandbox.contracts.case import InstallTestCase
from tools.install_sandbox.contracts.spec import InstallTestSpec


@pytest.mark.parametrize(
    "hooks",
    [
        None,
        {},
        [None],
        [{"event": "", "matcher": "Any", "content": {"x": 1}}],
        [{"event": "Any", "matcher": "", "content": {"x": 1}}],
        [{"event": "Any", "matcher": "Any", "content": {}}],
        [{"event": "Any", "matcher": "Any", "content": {"x": float("nan")}}],
        [{"event": "Any", "matcher": "Any", "content": {"x": {1: "bad"}}}],
        [{"event": "Any", "matcher": "Any", "content": {"x": (1, 2)}}],
    ],
)
def test_hook_spec_rejects_non_transportable_or_incomplete_facts(hooks: object) -> None:
    data = json.loads(
        (Path(__file__).resolve().parents[1] / "fixtures/first-install.json").read_text()
    )["spec"]
    data["json"]["hooks"] = hooks
    with pytest.raises(ValueError):
        InstallTestSpec.from_data(data)


def test_hook_spec_requires_explicit_list_and_preserves_structured_values() -> None:
    data = json.loads(
        (Path(__file__).resolve().parents[1] / "fixtures/first-install.json").read_text()
    )["spec"]
    del data["json"]["hooks"]
    with pytest.raises(ValueError):
        InstallTestSpec.from_data(data)
    data["json"]["hooks"] = []
    assert InstallTestSpec.from_data(data).to_data() == data
    data["json"]["hooks"] = [
        {"event": "E", "matcher": "M", "content": {"x": [None, {"enabled": True}]}}
    ]
    assert InstallTestSpec.from_data(data).to_data() == data


def test_case_witness_survives_transport() -> None:
    case = InstallTestCase.from_json(
        (Path(__file__).resolve().parents[1] / "fixtures/first-install.json").read_text()
    )
    assert InstallTestCase.from_json(case.to_json()) == case
    assert json.loads(case.initial_files[1]["content"])["hooks"]["PreToolUse"][0]["hooks"] == [
        {"type": "command", "command": "python personal_graphify_audit.py", "timeout": 17}
    ]
