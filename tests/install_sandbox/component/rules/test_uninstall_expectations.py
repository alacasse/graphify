"""Uninstall removes declared payload while preserving every other entry."""

from dataclasses import replace
from typing import cast

import pytest

from tests.install_sandbox.component.contracts.reference_support import (
    reference_case,
    reference_sources,
)
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import SnapshotEntry, VerificationResult
from tools.install_sandbox.rules.effect_verifier import EffectVerifier
from tools.install_sandbox.rules.expectation_builder import (
    build_initial_expectations,
    build_install_expectations,
    build_uninstall_expectations,
)


def installed_skill():
    seeds = (
        {"root": "project", "path": "skill/SKILL.md.bak", "content": "prior backup"},
        {"root": "project", "path": "skill/neighbor.txt", "content": "neighbor"},
        {"root": "project", "path": "graphify-out/result", "content": "graph"},
        {"root": "home", "path": "personal", "content": "home"},
    )
    case = replace(reference_case(), initial_files=seeds)
    sources = reference_sources()
    initial = build_initial_expectations(case, sources)
    assert next(e for e in initial.expectations if e.path == "skill").kind == "directory"
    before = FilesystemSnapshot()
    for root, path in (
        ("home", "."),
        ("project", "."),
        ("project", "skill"),
        ("project", "graphify-out"),
    ):
        before.entries.append(
            cast(
                SnapshotEntry,
                {"root": root, "path": path, "kind": "directory", "listing_complete": True},
            )
        )
    for seed in seeds:
        key = (seed["root"], seed["path"])
        before.entries.append(cast(SnapshotEntry, {"root": key[0], "path": key[1], "kind": "file"}))
        before.contents[key] = seed["content"].encode()
    installed = build_install_expectations(
        case, sources, before, {"home": "/home", "project": "/project"}
    )
    after = replace(before, entries=list(before.entries), contents=dict(before.contents))
    keys = {(e["root"], e["path"]) for e in after.entries}
    for root, path in installed.allowed_changes:
        if (root, path) not in keys:
            after.entries.append(
                cast(
                    SnapshotEntry,
                    {"root": root, "path": path, "kind": "directory", "listing_complete": True},
                )
            )
            keys.add((root, path))
    for item in installed.expectations:
        if item.kind == "absent":
            continue
        after.entries = [
            e for e in after.entries if (e["root"], e["path"]) != (item.root, item.path)
        ]
        after.entries.append(
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
            after.contents[(item.root, item.path)] = item.content
    verdict = EffectVerifier().verify(installed, after)
    assert verdict.complete and not verdict.mismatches and not verdict.obstacles
    return installed, after, verdict


def test_uninstall_exact_preservation_and_transport():
    installed, after, verdict = installed_skill()
    expected = build_uninstall_expectations(installed, after, verdict)
    assert ExpectationSet.from_data(expected.to_data()) == expected
    assert ("project", "skill/SKILL.md") in expected.allowed_removals
    assert ("project", "skill/references/a/nested.md") in expected.allowed_removals
    removed = set(expected.allowed_removals)
    uninstalled = replace(
        after,
        entries=[e for e in after.entries if (e["root"], e["path"]) not in removed],
        contents={k: v for k, v in after.contents.items() if k not in removed},
    )
    assert not EffectVerifier().verify(expected, uninstalled).mismatches
    assert EffectVerifier().verify(expected, after).mismatches
    for key in uninstalled.contents:
        changed = replace(uninstalled, contents={**uninstalled.contents, key: b"changed"})
        assert EffectVerifier().verify(expected, changed).mismatches, key
        deleted = replace(
            uninstalled,
            entries=[e for e in uninstalled.entries if (e["root"], e["path"]) != key],
            contents={k: v for k, v in uninstalled.contents.items() if k != key},
        )
        assert EffectVerifier().verify(expected, deleted).mismatches, key


@pytest.mark.parametrize(
    "verdict",
    [
        VerificationResult(complete=False),
        VerificationResult(
            obstacles=[
                {"operation": "observe", "root": "project", "path": ".", "reason": "incomplete"}
            ]
        ),
    ],
)
def test_uninstall_requires_passed_first_install(verdict: VerificationResult) -> None:
    installed, after, _ = installed_skill()
    with pytest.raises(ValueError, match="conforming complete"):
        build_uninstall_expectations(installed, after, verdict)


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("skill/SKILL.md", "file"),
        ("skill/.graphify_version", "file"),
        ("skill/references", "directory"),
    ],
)
def test_initial_seeded_skill_rejects_preinstalled_payload(path: str, kind: str) -> None:
    seeds = [
        {"root": "project", "path": "skill/SKILL.md.bak", "content": "prior backup"},
        {"root": "project", "path": "skill/neighbor.txt", "content": "neighbor"},
    ]
    case = replace(reference_case(), initial_files=seeds)
    expected = build_initial_expectations(case, reference_sources())
    observed = FilesystemSnapshot(
        entries=[
            cast(
                SnapshotEntry,
                {"root": root, "path": directory, "kind": "directory", "listing_complete": True},
            )
            for root, directory in (("home", "."), ("project", "."), ("project", "skill"))
        ]
        + [
            cast(SnapshotEntry, {"root": seed["root"], "path": seed["path"], "kind": "file"})
            for seed in seeds
        ],
        contents={(seed["root"], seed["path"]): seed["content"].encode() for seed in seeds},
    )
    assert not EffectVerifier().verify(expected, observed).mismatches
    observed.entries.append(
        cast(
            SnapshotEntry,
            {
                "root": "project",
                "path": path,
                "kind": kind,
                **({"listing_complete": True} if kind == "directory" else {}),
            },
        )
    )
    if kind == "file":
        observed.contents[("project", path)] = b"preinstalled payload"
    verdict = EffectVerifier().verify(expected, observed)
    assert verdict.mismatches
    assert any(item.path == path for item in verdict.mismatches)
