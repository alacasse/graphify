"""Ordered skill operations retain independent payload and preservation constraints."""

import hashlib
from collections.abc import Iterable
from dataclasses import replace
from pathlib import PurePosixPath
from typing import cast

import pytest

from tests.install_sandbox.component.contracts.reference_support import (
    reference_case,
    reference_sources,
)
from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.effects import Destination, EffectSpec, SkillEffect
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import SnapshotEntry
from tools.install_sandbox.rules.effect_verifier import EffectVerifier
from tools.install_sandbox.rules.expectation_builder import (
    build_group_expectations,
    build_install_expectations,
)

ROOTS = {"home": "/home", "project": "/project"}


def snapshot(
    files: dict[tuple[str, str], bytes], directories: Iterable[tuple[str, str]] = ()
) -> FilesystemSnapshot:
    dirs = {("home", "."), ("project", "."), *directories}
    for root, path in files:
        dirs.update((root, str(parent)) for parent in PurePosixPath(path).parents)
    return FilesystemSnapshot(
        entries=[
            cast(
                SnapshotEntry, {"root": r, "path": p, "kind": "directory", "listing_complete": True}
            )
            for r, p in sorted(dirs)
        ]
        + [cast(SnapshotEntry, {"root": r, "path": p, "kind": "file"}) for r, p in files],
        contents=files,
    )


def group_install() -> tuple[EffectInstallCase, FilesystemSnapshot]:
    case = replace(
        reference_case(),
        name="group-uninstall-project",
        intermediate_preparation=None,
        subject=replace(
            reference_case().subject,
            group_lock_destinations=("other-project-skill",),
            group_install_invocations=(("install",), ("install",), ("install",)),
        ),
        effects=EffectSpec(
            tuple(
                SkillEffect("skill.md", "refs", Destination(root, path))
                for root, path in (("home", "user"), ("project", "agents"), ("project", "copilot"))
            )
        ),
    )
    before = snapshot(
        {
            ("home", "personal"): b"home",
            ("project", "agents/personal.txt"): b"neighbor",
            ("project", "copilot/personal.txt"): b"neighbor",
            ("project", "graphify-out/result"): b"graph",
        }
    )
    for index in range(3):
        expected = (
            build_install_expectations(case, reference_sources(), before, ROOTS)
            if index == 0
            else build_group_expectations(case, reference_sources(), before, ROOTS, index)
        )
        assert ExpectationSet.from_data(expected.to_data()) == expected
        assert EffectVerifier().verify(expected, before).mismatches
        files = dict(before.contents)
        dirs = {(e["root"], e["path"]) for e in before.entries if e["kind"] == "directory"}
        for item in expected.expectations:
            if item.kind == "file":
                assert item.content is not None
                files[(item.root, item.path)] = item.content
            elif item.kind == "directory":
                dirs.add((item.root, item.path))
        after = snapshot(files, dirs)
        assert not EffectVerifier().verify(expected, after).mismatches
        # A future install must not contaminate this phase.
        if index < 2:
            future = ("project", ("agents", "copilot")[index] + "/SKILL.md")
            assert (
                EffectVerifier()
                .verify(expected, snapshot({**files, future: b"skill"}, dirs))
                .mismatches
            )
        before = after
    return case, before


def test_group_uninstall_payloads_and_preservation() -> None:
    case, before = group_install()
    expected = build_group_expectations(case, reference_sources(), before, ROOTS, 3)
    assert ExpectationSet.from_data(expected.to_data()) == expected
    assert EffectVerifier().verify(expected, before).mismatches
    removed = set(expected.allowed_removals)
    files = {key: value for key, value in before.contents.items() if key not in removed}
    dirs = {
        (e["root"], e["path"])
        for e in before.entries
        if e["kind"] == "directory" and (e["root"], e["path"]) not in removed
    }
    after = snapshot(files, dirs)
    assert not EffectVerifier().verify(expected, after).mismatches
    for key in files:
        assert (
            EffectVerifier().verify(expected, snapshot({**files, key: b"changed"}, dirs)).mismatches
        )
        assert (
            EffectVerifier()
            .verify(expected, snapshot({k: v for k, v in files.items() if k != key}, dirs))
            .mismatches
        )


@pytest.mark.parametrize(
    ("path", "content", "valid"),
    [
        ("declared", b"", True),
        (".cache/graphify/skill-locks/0123456789abcdef.lock", b"", False),
        ("declared", b"nonempty", False),
        (".cache/graphify/skill-locks/INVALID.lock", b"", False),
        (".cache/graphify/other/0123456789abcdef.lock", b"", False),
    ],
)
def test_group_uninstall_narrow_new_lock_policy(path: str, content: bytes, valid: bool) -> None:
    case, before = group_install()
    expected = build_group_expectations(case, reference_sources(), before, ROOTS, 3)
    removed = set(expected.allowed_removals)
    files = {k: v for k, v in before.contents.items() if k not in removed}
    dirs = {
        (e["root"], e["path"])
        for e in before.entries
        if e["kind"] == "directory" and (e["root"], e["path"]) not in removed
    }
    if path == "declared":
        digest = hashlib.sha256(b"/project/other-project-skill").hexdigest()[:16]
        path = f".cache/graphify/skill-locks/{digest}.lock"
        assert expected.new_skill_locks == (path,)
    observed = snapshot({**files, ("home", path): content}, dirs)
    assert bool(EffectVerifier().verify(expected, observed).mismatches) is not valid


def test_old_expectation_transport_omits_optional_lock_policy() -> None:
    expected = ExpectationSet("install", ())
    assert "new_skill_locks" not in expected.to_data()
    assert ExpectationSet.from_data(expected.to_data()) == expected


@pytest.mark.parametrize("purge", [False, True])
def test_global_uninstall_removes_both_home_payloads_and_exact_output_tree(purge: bool) -> None:
    case = replace(
        reference_case(),
        name="global-uninstall-purge" if purge else "global-uninstall",
        intermediate_preparation=None,
        operations=["install-group-0", "install-group-1", "purge" if purge else "uninstall"],
        subject=replace(
            reference_case().subject,
            group_install_invocations=(("install",), ("install",)),
            home_lock_destinations=("other",),
            config_lock_destinations=("claude_config_dir/skills/graphify",),
        ),
        effects=EffectSpec(
            tuple(
                SkillEffect("skill.md", "refs", Destination("home", path))
                for path in ("first", "second")
            )
        ),
    )
    before = snapshot(
        {
            ("home", "first/personal.txt"): b"first neighbor",
            ("home", "second/personal.txt"): b"second neighbor",
            ("project", "graphify-out/nested/output"): b"output",
            ("project", "nested/graphify-out/personal"): b"preserve",
        },
        (("project", "graphify-out/empty"),),
    )
    for index in range(2):
        expected = build_group_expectations(case, reference_sources(), before, ROOTS, index)
        assert EffectVerifier().verify(expected, before).mismatches
        files = dict(before.contents)
        dirs = {(e["root"], e["path"]) for e in before.entries if e["kind"] == "directory"}
        for item in expected.expectations:
            if item.kind == "file":
                assert item.content is not None
                files[(item.root, item.path)] = item.content
            elif item.kind == "directory":
                dirs.add((item.root, item.path))
        after = snapshot(files, dirs)
        assert not EffectVerifier().verify(expected, after).mismatches
        if index == 0:
            with pytest.raises(ValueError, match="conforming prior"):
                build_group_expectations(case, reference_sources(), before, ROOTS, 1)
            early = snapshot(
                {k: v for k, v in files.items() if not k[1].startswith("graphify-out/")}, dirs
            )
            assert EffectVerifier().verify(expected, early).mismatches
        before = after
    expected = build_group_expectations(case, reference_sources(), before, ROOTS, 2)
    assert ExpectationSet.from_data(expected.to_data()) == expected
    assert EffectVerifier().verify(expected, before).mismatches
    removed = set(expected.allowed_removals)
    files = {k: v for k, v in before.contents.items() if k not in removed}
    dirs = {
        (e["root"], e["path"])
        for e in before.entries
        if e["kind"] == "directory" and (e["root"], e["path"]) not in removed
    }
    assert not EffectVerifier().verify(expected, snapshot(files, dirs)).mismatches
    assert (("project", "graphify-out") in removed) is purge
    for absolute in ("/home/other", "/command-tmp/configuration/claude_config_dir/skills/graphify"):
        digest = hashlib.sha256(absolute.encode()).hexdigest()[:16]
        path = f".cache/graphify/skill-locks/{digest}.lock"
        assert path in expected.new_skill_locks
        assert (
            not EffectVerifier()
            .verify(expected, snapshot({**files, ("home", path): b""}, dirs))
            .mismatches
        )
        assert (
            EffectVerifier()
            .verify(expected, snapshot({**files, ("home", path): b"bad"}, dirs))
            .mismatches
        )
    for key in files:
        assert (
            EffectVerifier().verify(expected, snapshot({**files, key: b"changed"}, dirs)).mismatches
        )
    for key in removed:
        original = before.entry(*key)
        assert original is not None
        residual = (
            snapshot({**files, key: before.contents[key]}, dirs)
            if original["kind"] == "file"
            else snapshot(files, dirs | {key})
        )
        assert EffectVerifier().verify(expected, residual).mismatches
