"""Group compilation binds ordered commands and rejects unsafe compositions."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from tools.install_sandbox.contracts.effect_case import (
    EffectInstallCase,
    EffectRules,
    GroupCaseKey,
    StepInvocation,
    SubjectContext,
)
from tools.install_sandbox.contracts.effects import (
    Destination,
    EffectSpec,
    FileEffect,
    JsonHooksEffect,
)
from tools.install_sandbox.contracts.group_case import build_group_case
from tools.install_sandbox.contracts.spec import HookExpectation


def composition() -> tuple[dict[str, EffectSpec], tuple[str, ...], tuple[str, ...], SubjectContext]:
    prepare = ("cedar:user", "cedar:project", "birch:project")
    remove = ("birch:project", "cedar:project")
    specs = {
        p: EffectSpec(
            (
                FileEffect(
                    "managed",
                    Destination(
                        "home" if p.endswith(":user") else "project", p.split(":")[0] + ".txt"
                    ),
                ),
            ),
            p.split(":")[1],
        )
        for p in prepare
    }
    context = SubjectContext(
        "fixture",
        (),
        "METADATA",
        EffectRules("persistent", ".graphify-bak", ".bak", False),
        invocations={p: ("install", p) for p in prepare},
        removals=(StepInvocation("uninstall", remove, ("uninstall", *remove)),),
    )
    return specs, prepare, remove, context


def test_ordered_group_roundtrip_and_command_binding() -> None:
    specs, prepare, remove, context = composition()
    case = build_group_case(specs, prepare, remove, context, "cedar")
    assert EffectInstallCase.from_json(case.to_json()) == case
    assert [s.argv for s in case.steps] == [("install", p) for p in prepare] + [
        ("uninstall", *remove)
    ]
    assert case.group is not None
    assert case.group.prepare == prepare and case.group.remove == remove
    changed = json.loads(case.to_json())
    changed["plan"][-1]["participants"].reverse()
    with pytest.raises(ValueError):
        EffectInstallCase.from_json(json.dumps(changed))
    other = build_group_case(specs, tuple(reversed(prepare)), remove, context, "cedar")
    assert case.key.storage_id != other.key.storage_id


def test_group_rejects_missing_exact_commands_and_physical_overlap() -> None:
    specs, prepare, remove, context = composition()
    with pytest.raises(ValueError, match="ordered removal"):
        build_group_case(specs, prepare, tuple(reversed(remove)), context, "cedar")
    with pytest.raises(ValueError, match="explicit participant"):
        build_group_case(specs, prepare, remove, replace(context, invocations={}), "cedar")
    specs["birch:project"] = EffectSpec(
        (FileEffect("other", Destination("project", "cedar.txt/child")),)
    )
    with pytest.raises(ValueError, match="overlap"):
        build_group_case(specs, prepare, remove, context, "cedar")


def test_archived_campaign_rebuilds_group_without_catalog_files(tmp_path: Path) -> None:
    from dataclasses import asdict

    import yaml

    from tools.install_sandbox.host.campaign_definition import define_campaign
    from tools.install_sandbox.host.coordinator import CampaignResult

    specs, prepare, remove, context = composition()

    def source(tool: str) -> str:
        return yaml.safe_dump(
            {
                "tool": tool,
                "scopes": {
                    p.split(":")[1]: [
                        {
                            "effect_id": "literal",
                            "family": "file",
                            "root": e.destination.root.upper(),
                            "path": e.destination.path,
                            "content": cast(FileEffect, e).content,
                        }
                        for e in spec.effects
                    ]
                    for p, spec in specs.items()
                    if p.split(":")[0] == tool
                },
            }
        )

    manifest = {
        "format": "tool-campaign-v2",
        "spec": source("cedar"),
        "catalog": {"birch": source("birch")},
        "context": json.loads(json.dumps(asdict(context))),
        "prepare_only": False,
        "operations": None,
        "request": {
            "operation": "group-uninstall",
            "prepare": list(prepare),
            "remove": list(remove),
        },
    }
    definition = define_campaign(manifest, tmp_path)
    rebuilt = define_campaign(json.loads(json.dumps(definition.manifest)), tmp_path / "moved")
    assert rebuilt.transports == definition.transports
    assert rebuilt.partial and len(rebuilt.effects) == 3
    result = CampaignResult.from_definition(rebuilt, tmp_path / "output")
    assert result.scope == "partial"
    assert "group" in result.declared_scopes
    assert isinstance(result.cases[0].key, GroupCaseKey)
    assert result.cases[0].key.prepare == prepare


@pytest.mark.parametrize(
    "fault",
    ["missing-install", "missing-remove", "absent-scope", "unconstructible-scope", "overlap"],
)
def test_valid_group_without_required_capability_is_unconstructible(
    tmp_path: Path, fault: str
) -> None:
    from dataclasses import asdict

    import yaml

    from tools.install_sandbox.host.campaign_definition import define_campaign

    specs, prepare, remove, context = composition()
    scopes: dict[str, object] = {}
    for participant, spec in specs.items():
        if participant.startswith("cedar:"):
            effect = spec.effects[0]
            scopes[spec.scope] = [
                {
                    "effect_id": "literal",
                    "family": "file",
                    "root": effect.destination.root.upper(),
                    "path": effect.destination.path,
                    "content": "managed",
                }
            ]
    birch_path = "cedar.txt" if fault == "overlap" else "birch.txt"
    other: dict[str, Any] = {
        "tool": "birch",
        "scopes": {
            "project": [
                {
                    "effect_id": "literal",
                    "family": "file",
                    "root": "PROJECT",
                    "path": birch_path,
                    "content": "managed",
                }
            ]
        },
    }
    if fault == "absent-scope":
        other["scopes"] = {
            "user": [
                {
                    "effect_id": "literal",
                    "family": "file",
                    "root": "HOME",
                    "path": "birch.txt",
                    "content": "managed",
                }
            ]
        }
    elif fault == "unconstructible-scope":
        other["scopes"] = {"project": {"state": "unconstructible", "reason": "Pending conversion"}}
    if fault == "missing-install":
        context = replace(
            context,
            invocations={p: argv for p, argv in context.invocations.items() if p != "cedar:user"},
        )
    elif fault == "missing-remove":
        context = replace(context, removals=())
    manifest = {
        "format": "tool-campaign-v2",
        "spec": yaml.safe_dump({"tool": "cedar", "scopes": scopes}),
        "catalog": {"birch": yaml.safe_dump(other)},
        "context": json.loads(json.dumps(asdict(context))),
        "prepare_only": False,
        "operations": None,
        "request": {
            "operation": "group-uninstall",
            "prepare": list(prepare),
            "remove": list(remove),
        },
    }
    definition = define_campaign(manifest, tmp_path)
    assert not definition.built.cases
    assert len(definition.built.decisions) == 1
    assert definition.built.decisions[0].classification == "unconstructible"
    assert isinstance(definition.built.decisions[0].key, GroupCaseKey)
    assert definition.built.decisions[0].key.prepare == prepare


def test_invalid_group_request_is_rejected_before_catalog_lookup(tmp_path: Path) -> None:
    from dataclasses import asdict

    from tools.install_sandbox.host.campaign_definition import load_campaign_definition

    _, _, _, context = composition()
    spec_file = tmp_path / "cedar.yaml"
    spec_file.write_text(
        "tool: cedar\nscopes:\n  project:\n    state: unconstructible\n    reason: pending\n"
    )
    context_file = tmp_path / "context.json"
    context_file.write_text(json.dumps(asdict(context)))
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "operation": "group-uninstall",
                "prepare": ["cedar:project", "missing:project"],
                "remove": [],
            }
        )
    )
    with pytest.raises(ValueError, match="non-empty"):
        load_campaign_definition(
            spec_file=spec_file,
            subject_context_file=context_file,
            subject_checkout=tmp_path,
            request_file=request,
        )


def test_chosen_spec_is_read_once_and_archived_from_same_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import asdict

    from tools.install_sandbox.host.campaign_definition import load_campaign_definition

    _, _, _, context = composition()
    spec_file = tmp_path / "cedar.yaml"
    original = "tool: cedar\nscopes:\n  project:\n    state: unconstructible\n    reason: pending\n"
    spec_file.write_text(original)
    context_file = tmp_path / "context.json"
    context_file.write_text(json.dumps(asdict(context)))
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "operation": "group-uninstall",
                "prepare": ["cedar:project"],
                "remove": ["cedar:project"],
            }
        )
    )
    read_text = Path.read_text
    reads: list[Path] = []

    def read(path: Path, *args: Any, **kwargs: Any) -> str:
        if path == spec_file:
            reads.append(path)
            if len(reads) > 1:
                raise AssertionError("chosen spec was reread")
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    definition = load_campaign_definition(
        spec_file=spec_file,
        subject_context_file=context_file,
        subject_checkout=tmp_path,
        request_file=request,
    )
    assert reads == [spec_file]
    assert definition.manifest["spec"] == original


def test_redundant_group_effect_facts_preserve_json_types() -> None:
    specs, prepare, remove, context = composition()
    hook = HookExpectation(
        "run", "Start", "*", {"type": "command", "command": "run", "timeout": 10}
    )
    specs["birch:project"] = EffectSpec(
        (JsonHooksEffect(Destination("project", "hooks.json"), (hook,)),)
    )
    case = build_group_case(specs, prepare, remove, context, "cedar")
    transport = json.loads(case.to_json())
    transport["effects"]["effects"][-1]["hooks"][0]["content"]["timeout"] = 10.0
    with pytest.raises(ValueError, match="Group transport"):
        EffectInstallCase.from_json(json.dumps(transport))


def test_ordinary_and_group_keys_keep_distinct_serialized_fields() -> None:
    from dataclasses import asdict

    from tools.install_sandbox.contracts.effect_case import CaseKey

    ordinary = CaseKey("cedar", "project", "reinstall")
    assert set(asdict(ordinary)) == {"tool", "scope", "operation", "effect_id", "member"}
    assert CaseKey.from_data(ordinary.to_data()) == ordinary
    grouped = GroupCaseKey(
        "cedar",
        "group",
        "group-uninstall",
        prepare=("cedar:project", "birch:project"),
        remove=("birch:project",),
    )
    assert set(asdict(grouped)) == set(asdict(ordinary)) | {"prepare", "remove"}
    assert CaseKey.from_data(grouped.to_data()) == grouped
