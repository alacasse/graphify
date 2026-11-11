"""Source-derived append expectations preserve all unrelated observed files."""

from dataclasses import replace
from typing import cast

import pytest

from tests.install_sandbox.component.contracts.reference_support import (
    reference_case,
    reference_sources,
)
from tools.install_sandbox.contracts.bound_mutation import BoundFileCreation
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import SnapshotEntry
from tools.install_sandbox.rules.effect_verifier import EffectVerifier
from tools.install_sandbox.rules.expectation_builder import (
    build_install_expectations,
    preservation_baseline,
)
from tools.install_sandbox.rules.repair_scenario import (
    PreparationBlocked,
    PreparationPlan,
    repair_scenario_from_case,
)


def _installed_skill(content: bytes):
    case = reference_case("preserve-skill-backup")
    sources = reference_sources()
    sources.contents[("subject", "skill.md")] = content
    first = FilesystemSnapshot(
        entries=[
            cast(
                SnapshotEntry,
                {"root": root, "path": ".", "kind": "directory", "listing_complete": True},
            )
            for root in ("home", "project")
        ]
    )
    installed = build_install_expectations(
        case, sources, first, {"home": "/home", "project": "/project"}
    )
    for item in installed.expectations:
        if item.kind == "absent":
            continue
        first.entries.append(
            cast(
                SnapshotEntry,
                {
                    "root": item.root,
                    "path": item.path,
                    "kind": item.kind,
                    **({"listing_complete": True} if item.kind == "directory" else {}),
                },
            )
        )
        if item.content is not None:
            first.contents[(item.root, item.path)] = item.content
    return case, sources, first, installed


@pytest.mark.parametrize("content", [b"", b"\x00\xff", b"\nSandbox previous backup witness.\n"])
def test_skill_plan_uses_source_plus_one_suffix_and_exact_restoration(content: bytes):
    case, sources, first, installed = _installed_skill(content)
    verdict = EffectVerifier().verify(installed, first)
    assert verdict.complete and not verdict.mismatches
    plan = repair_scenario_from_case(case, sources).bind(
        first, "steps/0/after.json", verdict, installed, case.to_json().encode()
    )
    assert isinstance(plan, PreparationPlan)
    assert isinstance(plan.operation, BoundFileCreation)
    key = ("project", "skill/SKILL.md.bak")
    assert plan.after_preparation_expectations.allowed_changes == (key,)
    assert not plan.after_preparation_expectations.allowed_removals
    prepared = replace(
        first,
        entries=[*first.entries, {"root": key[0], "path": key[1], "kind": "file"}],
        contents={**first.contents, key: plan.operation.content},
    )
    assert plan.operation.content == content + b"\nSandbox previous backup witness.\n"
    assert not plan.second_install_expectations.allowed_changes
    assert not plan.second_install_expectations.allowed_removals
    assert not EffectVerifier().verify(plan.after_preparation_expectations, prepared).mismatches
    for incorrect in (content, plan.operation.content + b"extra", b"wrong"):
        bad = replace(first, contents={**first.contents, key: incorrect})
        assert EffectVerifier().verify(plan.after_preparation_expectations, bad).mismatches
    effective = replace(
        plan.second_install_expectations, baseline=preservation_baseline(prepared, "reinstall")
    )
    assert not EffectVerifier().verify(effective, prepared).mismatches
    assert EffectVerifier().verify(plan.second_install_expectations, first).mismatches
    wrong_other = replace(
        prepared, contents={**prepared.contents, ("project", "skill/references/z.md"): b"wrong"}
    )
    assert EffectVerifier().verify(plan.after_preparation_expectations, wrong_other).mismatches

    for observation_ref, case_bytes, observation in (
        ("steps/1/after.json", case.to_json().encode(), first),
        ("steps/0/after.json", b"{}", first),
        ("steps/0/after.json", case.to_json().encode(), wrong_other),
    ):
        assert isinstance(
            repair_scenario_from_case(case, sources).bind(
                observation, observation_ref, verdict, installed, case_bytes
            ),
            PreparationBlocked,
        )
