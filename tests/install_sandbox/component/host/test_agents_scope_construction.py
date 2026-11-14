"""Explicit cross-scope preparations belong to the executable transport."""

import json
from pathlib import Path

import pytest

from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.host.campaign_definition import CampaignDefinition, define_campaign


def definition(
    uninstall: bool = False, changes: dict[str, object] | None = None
) -> CampaignDefinition:
    context: dict[str, object] = {
        "identity": "test",
        "version_source": "version.py",
        "rules": {
            "skill_lock": "persistent",
            "json_backup": ".graphify-bak",
            "skill_backup": ".bak",
            "json_registry": False,
        },
        "invocations": {
            "agents:project": ["install", "--project"],
            "agents:user": ["install", "--user"],
        },
    }
    if uninstall:
        context["uninstall_invocations"] = {"agents:project": ["uninstall", "--project"]}
    context.update(changes or {})
    return define_campaign(
        {
            "format": "tool-campaign-v3",
            "spec": Path("tools/install_sandbox/specs/agents.yaml").read_text(),
            "context": context,
            "prepare_only": False,
            "operations": None,
            "request": None,
        },
        Path("."),
    )


def test_fourteen_cases_with_real_project_prerequisite() -> None:
    cases = definition().built.cases
    assert len(cases) == 14
    for case in cases:
        assert len(case.steps) == (3 if case.scope == "user" else 2)
        if case.scope == "user":
            assert [step.participant for step in case.steps] == [
                "agents:project",
                "agents:user",
                "agents:user",
            ]
            assert case.repair_after_index == 1
        assert EffectInstallCase.from_json(case.to_json()) == case


def test_uninstall_is_explicit_and_transport_rejects_changed_prerequisite() -> None:
    case = next(case for case in definition(True).built.cases if case.name == "uninstall")
    assert [(step.participant, step.action) for step in case.steps] == [
        ("agents:user", "install"),
        ("agents:project", "install"),
        ("agents:project", "uninstall"),
    ]
    assert EffectInstallCase.from_json(case.to_json()) == case
    data = json.loads(case.to_json())
    data["plan"][0]["argv"] = ["forged"]
    with pytest.raises(ValueError):
        EffectInstallCase.from_json(json.dumps(data))


def test_scope_prerequisite_cannot_be_overridden_by_the_context() -> None:
    with pytest.raises(ValueError, match="derived from declared scopes"):
        definition(changes={"prerequisites": {"agents:user": "other:project"}})


def test_historical_manifest_preserves_independent_installations() -> None:
    manifest = dict(definition().manifest, format="tool-campaign-v2")
    cases = define_campaign(manifest, Path("."), archived=True).built.cases
    assert all(case.prerequisite_effects is None for case in cases)
    assert all(len(case.steps) == 2 for case in cases)


def test_partial_user_request_retains_project_preparation_effects() -> None:
    original = definition()
    manifest = dict(original.manifest)
    manifest["request"] = {"scopes": ["user"]}
    selected = define_campaign(manifest, Path("."))
    assert {spec.scope for spec in selected.effects} == {"user", "project"}


def test_colliding_prerequisite_cannot_construct_user_cases() -> None:
    original = definition()
    manifest = dict(original.manifest)
    manifest["spec"] = str(manifest["spec"]).replace("root: HOME", "root: PROJECT")
    built = define_campaign(manifest, Path(".")).built
    assert not any(case.scope == "user" for case in built.cases)
    assert any("overlap" in entry.reason for entry in built.decisions)


def test_invalid_uninstall_prerequisite_preserves_project_install_cases() -> None:
    built = definition(True, changes={"invocations": {"agents:project": ["install"]}}).built
    assert len([case for case in built.cases if case.scope == "project"]) == 7
    assert any(
        entry.name == "uninstall" and entry.classification == "unconstructible"
        for entry in built.decisions
    )


def test_v3_derives_prerequisite_and_requires_project_invocation() -> None:
    built = definition(changes={"invocations": {"agents:user": ["install", "--user"]}}).built
    assert not any(case.scope == "user" for case in built.cases)
    assert any(
        entry.key.scope == "user" and entry.classification == "unconstructible"
        for entry in built.decisions
    )


@pytest.mark.parametrize("payload", ["[]", "null"])
def test_non_object_transport_is_rejected(payload: str) -> None:
    with pytest.raises(ValueError):
        EffectInstallCase.from_json(payload)


def test_project_fallback_is_preserved_when_binding_the_user_steps() -> None:
    campaign = definition(
        changes={
            "invocation": ["project-fallback"],
            "invocations": {"agents:user": ["install-user"]},
        }
    )
    case = next(case for case in campaign.built.cases if case.scope == "user")
    replayed = EffectInstallCase.from_json(case.to_json())
    assert [step.argv for step in replayed.steps] == [
        ("project-fallback",),
        ("install-user",),
        ("install-user",),
    ]
