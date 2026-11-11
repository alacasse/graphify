"""Source-derived append expectations preserve all unrelated observed files."""

from dataclasses import replace
from typing import cast

import pytest

from tests.install_sandbox.component.contracts.reference_support import (
    reference_case,
    reference_sources,
)
from tools.install_sandbox.contracts.bound_mutation import BoundFileAppend
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import SnapshotEntry
from tools.install_sandbox.rules.effect_verifier import EffectVerifier
from tools.install_sandbox.rules.expectation_builder import build_install_expectations
from tools.install_sandbox.rules.repair_scenario import (
    PreparationBlocked,
    PreparationPlan,
    repair_scenario_from_case,
)


@pytest.mark.parametrize("content", [b"", b"\x00\xff", b"\nSandbox skill repair witness.\n"])
def test_skill_plan_uses_source_plus_one_suffix_and_exact_restoration(content: bytes):
    case = reference_case("altered-skill")
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
    verdict = EffectVerifier().verify(installed, first)
    assert verdict.complete and not verdict.mismatches
    plan = repair_scenario_from_case(case, sources).bind(
        first, "steps/0/after.json", verdict, installed, case.to_json().encode()
    )
    assert isinstance(plan, PreparationPlan)
    assert isinstance(plan.operation, BoundFileAppend)
    key = ("project", "skill/SKILL.md")
    assert plan.after_preparation_expectations.allowed_changes == (key,)
    assert not plan.after_preparation_expectations.allowed_removals
    prepared = replace(first, contents={**first.contents, key: content + plan.operation.suffix})
    assert not EffectVerifier().verify(plan.after_preparation_expectations, prepared).mismatches
    for incorrect in (content, content + plan.operation.suffix * 2, b"wrong"):
        bad = replace(first, contents={**first.contents, key: incorrect})
        assert EffectVerifier().verify(plan.after_preparation_expectations, bad).mismatches
    backup = ("project", "skill/SKILL.md.bak")
    repaired = replace(
        first,
        entries=[*first.entries, {"root": "project", "path": backup[1], "kind": "file"}],
        contents={**first.contents, backup: content + plan.operation.suffix},
    )
    assert not EffectVerifier().verify(plan.second_install_expectations, repaired).mismatches
    assert EffectVerifier().verify(plan.second_install_expectations, first).mismatches
    assert EffectVerifier().verify(plan.second_install_expectations, prepared).mismatches
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
