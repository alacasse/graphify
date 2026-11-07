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
from tools.install_sandbox.contracts.effect_case import EffectInstallCase, GroupInstall
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


def member(destination: Destination) -> GroupInstall:
    command = ("install", "--platform", destination.path)
    if destination.root == "project":
        command += ("--project",)
    return GroupInstall(command, destination)


def group_install() -> tuple[EffectInstallCase, FilesystemSnapshot]:
    case = replace(
        reference_case(),
        name="group-uninstall-project",
        intermediate_preparation=None,
        subject=replace(
            reference_case().subject,
            group_lock_destinations=("other-project-skill",),
            uninstall_invocation=("uninstall", "--project"),
            group_installs=tuple(
                member(Destination(root, path))
                for root, path in (("home", "user"), ("project", "agents"), ("project", "copilot"))
            ),
        ),
        operations=["install", "install-group-1", "install-group-2", "uninstall"],
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
        operations=["install", "install-group-1", "purge" if purge else "uninstall"],
        subject=replace(
            reference_case().subject,
            uninstall_invocation=("uninstall",),
            group_installs=tuple(member(Destination("home", path)) for path in ("first", "second")),
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


def observed_group(
    destinations: tuple[Destination, ...], installed: int, removed: set[Destination]
) -> FilesystemSnapshot:
    files = {(d.root, d.path + "/personal.txt"): b"neighbor" for d in destinations}
    for destination in destinations[:installed]:
        root, skill = destination.root, destination.path
        digest = hashlib.sha256(f"{ROOTS[root]}/{skill}".encode()).hexdigest()[:16]
        files[("home", f".cache/graphify/skill-locks/{digest}.lock")] = b""
        if destination not in removed:
            for suffix, value in {
                "SKILL.md": b"skill",
                ".graphify_version": b"1",
                "references/a/nested.md": b"a",
                "references/z.md": b"z",
            }.items():
                files[(root, f"{skill}/{suffix}")] = value
    return snapshot(files)


@pytest.mark.parametrize(("count", "project_removal"), [(1, False), (23, False), (23, True)])
def test_dynamic_group_order_preserves_pending_prior_locks_and_neighbors(
    count: int, project_removal: bool
) -> None:
    destinations = tuple(
        Destination("project" if project_removal and index % 2 else "home", f"skill-{index}")
        for index in range(count)
    )
    effects = tuple(SkillEffect("skill.md", "refs", destination) for destination in destinations)
    case = replace(
        reference_case(),
        name="arbitrary-name",
        intermediate_preparation=None,
        operations=[
            "install",
            *(f"install-group-{index}" for index in range(1, count)),
            "uninstall",
        ],
        subject=replace(
            reference_case().subject,
            group_installs=tuple(member(destination) for destination in destinations),
            uninstall_invocation=("uninstall", "--project") if project_removal else ("uninstall",),
        ),
        # Effect declaration order must not become invocation order.
        effects=EffectSpec(tuple(reversed(effects))),
    )
    before = observed_group(destinations, 0, set())
    for index, current in enumerate(destinations):
        expected = build_group_expectations(case, reference_sources(), before, ROOTS, index)
        assert ExpectationSet.from_data(expected.to_data()) == expected
        assert expected.lock_destination == current
        assert EffectVerifier().verify(expected, before).mismatches
        if index < count - 1:
            with pytest.raises(ValueError, match="conforming prior"):
                build_group_expectations(case, reference_sources(), before, ROOTS, index + 1)
        after = observed_group(destinations, index + 1, set())
        assert not EffectVerifier().verify(expected, after).mismatches
        before = after

    final = build_group_expectations(case, reference_sources(), before, ROOTS, count)
    removed = {d for d in destinations if not project_removal or d.root == "project"}
    after = observed_group(destinations, count, removed)
    assert not EffectVerifier().verify(final, after).mismatches
    for destination in destinations:
        wrong_scope = observed_group(destinations, count, removed ^ {destination})
        assert EffectVerifier().verify(final, wrong_scope).mismatches
        damaged = dict(after.contents)
        damaged[(destination.root, destination.path + "/personal.txt")] = b"changed"
        assert EffectVerifier().verify(final, snapshot(damaged)).mismatches


@pytest.mark.parametrize(
    "phase",
    [
        "install-group-0",
        "install-group-01",
        "install-group--1",
        "install-group-1x",
        "install-group-",
        "install-project-1",
    ],
)
def test_noncanonical_group_expectation_phase_is_rejected(phase: str) -> None:
    with pytest.raises(ValueError, match="phase"):
        ExpectationSet(phase, ())
