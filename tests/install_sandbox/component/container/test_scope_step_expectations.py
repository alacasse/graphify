"""Scope transitions preserve independent installations and personal witnesses."""

import hashlib

import pytest

from tools.install_sandbox.contracts.effect_case import (
    CaseKey,
    EffectInstallCase,
    EffectRules,
    SubjectContext,
)
from tools.install_sandbox.contracts.effects import Destination, EffectSpec, SkillEffect
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import SnapshotEntry
from tools.install_sandbox.rules.effect_verifier import EffectVerifier
from tools.install_sandbox.rules.expectation_builder import (
    build_install_expectations,
    build_step_expectations,
    preservation_baseline,
)

ROOTS = {"home": "/sandbox/home", "project": "/sandbox/project"}


def snapshot(files: dict[tuple[str, str], bytes]) -> FilesystemSnapshot:
    directories = {(root, ".") for root in ("home", "project")}
    from pathlib import PurePosixPath

    for root, path in files:
        directories.update((root, str(parent)) for parent in PurePosixPath(path).parents)
    entries: list[SnapshotEntry] = [
        {"root": root, "path": path, "kind": "directory", "listing_complete": True}
        for root, path in sorted(directories)
    ]
    entries.extend({"root": root, "path": path, "kind": "file"} for root, path in files)
    return FilesystemSnapshot(entries=entries, contents=dict(files))


def case_definition(prerequisite: bool = False, uninstall: bool = False) -> EffectInstallCase:
    def skill(root: str) -> EffectSpec:
        return EffectSpec(
            (SkillEffect("skill.md", "references", Destination(root, "skills/graphify")),)
        )

    return EffectInstallCase(
        "scope",
        CaseKey("synthetic", "project", "uninstall" if uninstall else "reinstall"),
        "synthetic",
        "project",
        skill("project"),
        SubjectContext(
            "synthetic",
            ("install",),
            "VERSION",
            EffectRules("persistent", ".graphify-bak", ".bak", False),
            invocations={"synthetic:user": ("install-user",)},
            uninstall_invocations={"synthetic:project": ("remove",)},
        ),
        [],
        ["install", "uninstall" if uninstall else "install"],
        prerequisite_effects=skill("home") if prerequisite else None,
        prerequisite_participant="synthetic:user" if prerequisite else None,
    )


def sources() -> FilesystemSnapshot:
    return snapshot(
        {
            ("subject", "skill.md"): b"Skill\n",
            ("subject", "VERSION"): b"Version: 4.2\n",
            ("subject", "references/nested/guide.md"): b"Guide\n",
        }
    )


def lock_path(root: str) -> str:
    digest = hashlib.sha256(f"{ROOTS[root]}/skills/graphify".encode()).hexdigest()[:16]
    return f".cache/graphify/skill-locks/{digest}.lock"


def installed_files(root: str) -> dict[tuple[str, str], bytes]:
    return {
        (root, "skills/graphify/SKILL.md"): b"Skill\n",
        (root, "skills/graphify/.graphify_version"): b"4.2",
        (root, "skills/graphify/references/nested/guide.md"): b"Guide\n",
        ("home", lock_path(root)): b"",
    }


def test_prerequisite_install_uses_distinct_lock_and_preserves_the_other_scope() -> None:
    case = case_definition(prerequisite=True)
    first = build_install_expectations(case, sources(), snapshot({}), ROOTS)
    observed = snapshot(installed_files("home"))
    verdict = EffectVerifier().verify(first, observed)
    assert verdict.complete and not verdict.mismatches
    second = build_step_expectations(case, sources(), observed, ROOTS, 1, first, verdict)
    assert first.lock_destination == Destination("home", "skills/graphify")
    assert lock_path("home") != lock_path("project")
    assert ("home", lock_path("home")) not in second.allowed_changes
    files = {**installed_files("home"), **installed_files("project")}
    assert not EffectVerifier().verify(second, snapshot(files)).mismatches
    del files[("home", lock_path("home"))]
    assert EffectVerifier().verify(second, snapshot(files)).mismatches


def test_step_refuses_unvalidated_predecessor() -> None:
    with pytest.raises(ValueError, match="previous expectations"):
        build_step_expectations(case_definition(), sources(), snapshot({}), ROOTS, 1)


def test_reinstall_has_no_write_permission() -> None:
    case = case_definition()
    first = build_install_expectations(case, sources(), snapshot({}), ROOTS)
    observed = snapshot(installed_files("project"))
    verdict = EffectVerifier().verify(first, observed)
    second = build_step_expectations(case, sources(), observed, ROOTS, 1, first, verdict)
    assert second.phase == "reinstall"
    assert second.allowed_changes == ()
    assert second.expectations == first.in_phase("reinstall").expectations


def test_uninstall_removes_reference_tree_and_preserves_personal_witnesses() -> None:
    case = case_definition(uninstall=True)
    files = installed_files("project")
    files.update(
        {
            ("project", "skills/graphify/personal.txt"): b"personal",
            ("project", "skills/graphify/SKILL.md.bak"): b"backup",
            ("project", "skills/personal/SKILL.md"): b"neighbor",
            ("project", "graphify-out/personal.txt"): b"graph",
        }
    )
    installed = snapshot(files)
    prior = ExpectationSet(
        "install", (), baseline=preservation_baseline(installed, "install"), roots=ROOTS
    )
    verdict = EffectVerifier().verify(prior, installed)
    expected = build_step_expectations(case, sources(), installed, ROOTS, 1, prior, verdict)
    assert expected.phase == "uninstall"
    removed = set(expected.allowed_removals)
    after_files = {key: value for key, value in files.items() if key not in removed}
    assert not EffectVerifier().verify(expected, snapshot(after_files)).mismatches
    for witness in (
        "skills/graphify/SKILL.md.bak",
        "skills/graphify/personal.txt",
        "skills/personal/SKILL.md",
        "graphify-out/personal.txt",
    ):
        assert (
            EffectVerifier()
            .verify(
                expected,
                snapshot(
                    {
                        key: value
                        for key, value in after_files.items()
                        if key != ("project", witness)
                    }
                ),
            )
            .mismatches
        )
    assert ("project", "skills/graphify/references") in removed
    assert ("project", "skills/graphify/references/nested/guide.md") in removed


def test_initial_lock_must_be_absent_and_aliases_are_rejected() -> None:
    with pytest.raises(ValueError, match="observably absent"):
        build_install_expectations(
            case_definition(), sources(), snapshot({("home", lock_path("project")): b""}), ROOTS
        )
    roots = {"home": "/same", "project": "/same"}
    with pytest.raises(ValueError, match="collide"):
        build_install_expectations(
            case_definition(prerequisite=True), sources(), snapshot({}), roots
        )
