"""Temporary reference witnesses permit exact additions and removals only."""

from dataclasses import replace
from typing import cast

import pytest

from tests.install_sandbox.component.contracts.reference_support import (
    reference_case,
    reference_sources,
)
from tools.install_sandbox.contracts.bound_mutation import BoundStaleReferencesTmpCreation
from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.effects import Destination
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.intermediate import StaleReferencesTmpPreparation
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import SnapshotEntry
from tools.install_sandbox.rules.effect_verifier import EffectVerifier
from tools.install_sandbox.rules.expectation_builder import build_install_expectations
from tools.install_sandbox.rules.repair_scenario import PreparationPlan, repair_scenario_from_case


def tmp_first_install(
    empty: bool,
) -> tuple[EffectInstallCase, FilesystemSnapshot, FilesystemSnapshot, ExpectationSet]:
    case = replace(
        reference_case(),
        name="stale-references-tmp",
        intermediate_preparation=StaleReferencesTmpPreparation(Destination("project", "skill")),
    )
    sources = reference_sources()
    if empty:
        sources.entries = [e for e in sources.entries if not e["path"].startswith("refs/")]
        sources.contents = {
            k: v for k, v in sources.contents.items() if not k[1].startswith("refs/")
        }
    else:
        sources.entries.append(
            cast(SnapshotEntry, {"root": "subject", "path": "refs/stale.md", "kind": "file"})
        )
        sources.contents[("subject", "refs/stale.md")] = b"Independent retained reference\x00\xff"
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


@pytest.mark.parametrize("empty", [False, True])
def test_tmp_plan_preserves_sources_and_all_other_entries(empty: bool):
    case, sources, first, installed = tmp_first_install(empty)
    verdict = EffectVerifier().verify(installed, first)
    assert verdict.complete and not verdict.mismatches
    plan = repair_scenario_from_case(case, sources).bind(
        first,
        "steps/0/after.json",
        verdict,
        installed,
        case.to_json().encode(),
    )
    assert isinstance(plan, PreparationPlan)
    assert isinstance(plan.operation, BoundStaleReferencesTmpCreation)
    directory = ("project", "skill/references.tmp")
    child = ("project", "skill/references.tmp/stale.md")
    assert plan.after_preparation_expectations.allowed_changes == (directory, child)
    assert plan.second_install_expectations.allowed_removals == (directory, child)
    assert not plan.second_install_expectations.allowed_changes
    prepared = replace(
        first,
        entries=[
            *first.entries,
            {
                "root": directory[0],
                "path": directory[1],
                "kind": "directory",
                "listing_complete": True,
            },
            {"root": child[0], "path": child[1], "kind": "file"},
        ],
        contents={**first.contents, child: plan.operation.content},
    )
    verifier = EffectVerifier()
    assert not verifier.verify(plan.after_preparation_expectations, prepared).mismatches
    assert not verifier.verify(plan.second_install_expectations, first).mismatches
    assert verifier.verify(plan.second_install_expectations, prepared).mismatches
    directory_only = replace(first, entries=[*first.entries, prepared.entries[-2]])
    assert verifier.verify(plan.second_install_expectations, directory_only).mismatches
    wrong = replace(first, contents={**first.contents, ("project", "skill/SKILL.md"): b"damaged"})
    assert verifier.verify(plan.second_install_expectations, wrong).mismatches
    assert (
        ExpectationSet.from_data(plan.second_install_expectations.to_data())
        == plan.second_install_expectations
    )
    with pytest.raises(ValueError, match="descendant"):
        replace(plan.second_install_expectations, allowed_removals=(directory,))
