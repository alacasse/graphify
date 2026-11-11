"""Skill repair definitions retain explicit destination and canonical append bytes."""

import json
from dataclasses import replace

import pytest

from tests.install_sandbox.component.contracts.reference_support import reference_case
from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.effects import Destination
from tools.install_sandbox.contracts.intermediate import AlteredSkillPreparation


@pytest.mark.parametrize("change", ["suffix", "destination", "version", "selection"])
def test_altered_skill_case_rejects_tampered_definition(change: str) -> None:
    case = replace(
        reference_case(),
        name="altered-skill",
        key=replace(reference_case().key, operation="altered-skill"),
        intermediate_preparation=AlteredSkillPreparation(Destination("project", "skill")),
    )
    assert EffectInstallCase.from_json(case.to_json()) == case
    raw = json.loads(case.to_json())
    if change == "version":
        raw["format"] = "explicit-expectations-v7"
    elif change == "destination":
        raw["intermediate_preparation"][change]["root"] = "home"
    else:
        raw["intermediate_preparation"][change] = "YQ==" if change == "suffix" else "first"
    with pytest.raises(ValueError):
        EffectInstallCase.from_json(json.dumps(raw))
