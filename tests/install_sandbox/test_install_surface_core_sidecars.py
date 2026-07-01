from __future__ import annotations

from pathlib import Path

import pytest

from tools.install_sandbox.targets.reference_resolution import PackagedReferenceResolution
from tools.install_sandbox.surfaces import install_surface_generated
from tools.install_sandbox.surfaces import install_surface_models
from tools.install_sandbox.surfaces import install_surface_sidecars
from tools.install_sandbox.surfaces.install_surface_models import InstallSurface
from tools.install_sandbox.targets.install_target_models import Scenario


def resolution(status: str, names: tuple[str, ...] = (), detail: str = "test detail") -> PackagedReferenceResolution:
    return PackagedReferenceResolution(status, expected_names=names, detail=detail)


def scenario(platform: str, *expected: InstallSurface, scope: str = "project") -> Scenario:
    return Scenario(
        target_name=platform,
        scope=scope,
        install_command=("true",),
        uninstall_command=None,
        cwd_root="project" if scope == "project" else "user_cwd",
        expected=expected,
    )


def expected_skill(root: str, relative: str) -> InstallSurface:
    return InstallSurface(root, relative, skill_sidecar_expectation=install_surface_models.SkillSidecarExpectation())


def expected_skill_with_docs_sidecar(root: str, relative: str) -> InstallSurface:
    return InstallSurface(
        root,
        relative,
        skill_sidecar_expectation=install_surface_models.SkillSidecarExpectation(
            references_dir="docs",
            references_tmp_dir="docs.tmp",
            reference_pointer_pattern=r"docs/([A-Za-z0-9_.-]+\.md)\b",
        ),
    )


@pytest.mark.parametrize(
    ("status", "names", "expected_relatives"),
    [
        (
            "available",
            ("query.md", "update.md"),
            {
                ".unit/graphify/references",
                ".unit/graphify/references/query.md",
                ".unit/graphify/references/update.md",
            },
        ),
        ("empty", (), {".unit/graphify/references"}),
        ("missing", (), {".unit/graphify/references"}),
        ("not_directory", (), {".unit/graphify/references"}),
        ("intentionally_absent", (), set()),
        ("no_eligible_bundle", (), set()),
    ],
)
def test_reference_sidecar_expectation_owns_expected_relatives(status: str, names: tuple[str, ...], expected_relatives: set[str]) -> None:
    expectation = install_surface_sidecars.ReferenceSidecarExpectation.from_resolution(resolution(status, names))

    assert expectation.expected_relatives(Path(".unit/graphify"), install_surface_models.SkillSidecarExpectation()) == {
        Path(relative) for relative in expected_relatives
    }


def test_reference_sidecar_expectation_validates_installed_status_matrix() -> None:
    absent = install_surface_sidecars.ReferenceSidecarExpectation.from_resolution(resolution("intentionally_absent", detail="absent refs"))
    ok, detail = install_surface_sidecars.installed_reference_sidecar_status(
        absent,
        references_exists=False,
        references_is_dir=False,
        installed_names=(),
    )
    assert ok is True
    assert detail == "intentionally_absent; references_absent; absent refs"

    ok, detail = install_surface_sidecars.installed_reference_sidecar_status(
        absent,
        references_exists=True,
        references_is_dir=True,
        installed_names=(),
    )
    assert ok is False
    assert detail == "intentionally_absent; references_present; absent refs"

    source_error = install_surface_sidecars.ReferenceSidecarExpectation.from_resolution(resolution("missing", detail="missing /package/refs"))
    ok, detail = install_surface_sidecars.installed_reference_sidecar_status(
        source_error,
        references_exists=True,
        references_is_dir=True,
        installed_names=(),
    )
    assert ok is False
    assert detail == "missing; missing /package/refs"

    expected = install_surface_sidecars.ReferenceSidecarExpectation.from_resolution(resolution("available", ("query.md",), "available refs"))
    ok, detail = install_surface_sidecars.installed_reference_sidecar_status(
        expected,
        references_exists=True,
        references_is_dir=True,
        installed_names=(),
    )
    assert ok is False
    assert "missing=['query.md']" in detail

    ok, detail = install_surface_sidecars.installed_reference_sidecar_status(
        expected,
        references_exists=True,
        references_is_dir=True,
        installed_names=("query.md",),
    )
    assert ok is True
    assert "status=available" in detail


def test_install_surface_sidecars_evaluates_skill_sidecar_status_decisions() -> None:
    sidecar = install_surface_models.SkillSidecarExpectation()

    assert install_surface_sidecars.skill_version_status(None, "9.9.9") == (False, "missing; expected=9.9.9")
    assert install_surface_sidecars.skill_version_status("9.9.9\n", "9.9.9") == (True, "actual=9.9.9; expected=9.9.9")
    assert install_surface_sidecars.references_tmp_absence_status(False) == (True, "absent")
    assert install_surface_sidecars.references_tmp_absence_status(True) == (False, "present")
    assert install_surface_sidecars.skill_reference_pointer_status(
        sidecar,
        "See references/query.md and references/update.md",
        references_is_dir=True,
        installed_names=("query.md",),
    ) == (False, "pointers=['query.md', 'update.md']; missing=['update.md']")
    assert install_surface_sidecars.skill_reference_pointer_status(
        sidecar,
        "See references/query.md",
        references_is_dir=False,
        installed_names=(),
    ) == (False, "references_missing; skill_mentions_references=true; pointers=['query.md']")
    assert install_surface_sidecars.skill_reference_pointer_status(sidecar, "No pointers here", references_is_dir=False, installed_names=()) == (
        True,
        "no_reference_pointers",
    )
    assert install_surface_sidecars.uninstalled_skill_sidecar_status(False) == (True, "removed")
    assert install_surface_sidecars.uninstalled_skill_sidecar_status(True) == (False, "sidecar_still_exists")


def test_install_surface_sidecars_derives_skill_sidecar_relative_paths_from_declared_names() -> None:
    default_entry = expected_skill("project", ".aider/graphify/SKILL.md")
    custom_entry = expected_skill_with_docs_sidecar("project", ".custom/graphify/SKILL.md")

    assert install_surface_sidecars.skill_relative_dir(default_entry) == Path(".aider/graphify")
    assert install_surface_sidecars.skill_version_relative(default_entry) == Path(".aider/graphify/.graphify_version")
    assert install_surface_sidecars.skill_references_relative(default_entry) == Path(".aider/graphify/references")
    assert install_surface_sidecars.skill_references_tmp_relative(default_entry) == Path(".aider/graphify/references.tmp")

    assert install_surface_sidecars.skill_relative_dir(custom_entry) == Path(".custom/graphify")
    assert install_surface_sidecars.skill_version_relative(custom_entry) == Path(".custom/graphify/.graphify_version")
    assert install_surface_sidecars.skill_references_relative(custom_entry) == Path(".custom/graphify/docs")
    assert install_surface_sidecars.skill_references_tmp_relative(custom_entry) == Path(".custom/graphify/docs.tmp")


def test_install_surface_sidecars_derives_expected_skill_sidecar_relatives_from_resolved_references() -> None:
    entry = expected_skill("project", ".claude/skills/graphify/SKILL.md")

    assert install_surface_sidecars.expected_skill_sidecar_relatives(entry, resolution("available", ("query.md", "update.md"))) == {
        Path(".claude/skills/graphify/.graphify_version"),
        Path(".claude/skills/graphify/references.tmp"),
        Path(".claude/skills/graphify/references"),
        Path(".claude/skills/graphify/references/query.md"),
        Path(".claude/skills/graphify/references/update.md"),
    }

    with pytest.raises(AssertionError, match="expected path has no skill sidecar expectation: project/notes.md"):
        install_surface_sidecars.skill_sidecar_expectation(InstallSurface("project", "notes.md"))


@pytest.mark.parametrize(
    ("platform", "expected_relatives"),
    [
        (
            "claude",
            {
                ".claude/skills/graphify/.graphify_version",
                ".claude/skills/graphify/references.tmp",
                ".claude/skills/graphify/references",
                ".claude/skills/graphify/references/query.md",
                ".claude/skills/graphify/references/update.md",
            },
        ),
        (
            "empty",
            {
                ".empty/graphify/.graphify_version",
                ".empty/graphify/references.tmp",
                ".empty/graphify/references",
            },
        ),
        (
            "aider",
            {
                ".aider/graphify/.graphify_version",
                ".aider/graphify/references.tmp",
            },
        ),
        (
            "no_eligible",
            {
                ".no_eligible/graphify/.graphify_version",
                ".no_eligible/graphify/references.tmp",
            },
        ),
        (
            "missing",
            {
                ".missing/graphify/.graphify_version",
                ".missing/graphify/references.tmp",
                ".missing/graphify/references",
            },
        ),
        (
            "not_directory",
            {
                ".not_directory/graphify/.graphify_version",
                ".not_directory/graphify/references.tmp",
                ".not_directory/graphify/references",
            },
        ),
    ],
)
def test_expected_skill_sidecar_relatives_follow_packaged_reference_status(
    platform: str,
    expected_relatives: set[str],
) -> None:
    relative = ".claude/skills/graphify/SKILL.md" if platform == "claude" else f".{platform}/graphify/SKILL.md"
    entry = expected_skill("project", relative)
    resolutions = {
        "claude": resolution("available", ("query.md", "update.md"), "claude refs"),
        "empty": resolution("empty", detail="empty refs"),
        "aider": resolution("intentionally_absent", detail="absent refs"),
        "no_eligible": resolution("no_eligible_bundle", detail="no eligible refs"),
        "missing": resolution("missing", detail="missing /package/refs"),
        "not_directory": resolution("not_directory", detail="not_directory /package/refs"),
    }

    assert install_surface_sidecars.expected_skill_sidecar_relatives(entry, resolutions[platform]) == {Path(relative) for relative in expected_relatives}


def test_install_surface_sidecars_match_skill_sidecar_version_and_nested_reference_paths() -> None:
    test_scenario = scenario("aider", expected_skill("project", ".aider/graphify/SKILL.md"))

    assert install_surface_generated.is_skill_sidecar_relative(test_scenario.expected, "project", Path(".aider/graphify/.graphify_version")) is True
    assert install_surface_generated.is_skill_sidecar_relative(test_scenario.expected, "project", Path(".aider/graphify/references/query.md")) is True
    assert install_surface_generated.is_skill_sidecar_relative(test_scenario.expected, "project", Path(".aider/graphify/references/nested/query.md")) is True
    assert install_surface_generated.is_skill_sidecar_relative(test_scenario.expected, "project", Path(".aider/graphify/references.tmp/partial.md")) is True
    assert install_surface_generated.is_skill_sidecar_relative(test_scenario.expected, "project", Path(".aider/graphify/references.tmp/nested/partial.md")) is True
    assert install_surface_generated.is_skill_sidecar_relative(test_scenario.expected, "project", Path(".aider/graphify/notes.md")) is False
    assert install_surface_generated.is_skill_sidecar_relative(test_scenario.expected, "home", Path(".aider/graphify/.graphify_version")) is False
