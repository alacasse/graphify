from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.install_sandbox import file_effects
from tools.install_sandbox import install_surface_core
from tools.install_sandbox import platform_specs
from tools.install_sandbox.platform_specs import ExpectedPath, InstallSurface, Scenario
from tools.install_sandbox.reference_resolution import PackagedReferenceResolution


@pytest.fixture
def roots(tmp_path) -> dict[str, Path]:
    paths = {"home": tmp_path / "home", "project": tmp_path / "project", "user_cwd": tmp_path / "user-cwd"}
    for path in paths.values():
        path.mkdir(parents=True)
    return paths


def resolution(status: str, names: tuple[str, ...] = (), detail: str = "test detail") -> PackagedReferenceResolution:
    return PackagedReferenceResolution(status, expected_names=names, detail=detail)


@pytest.fixture
def oracle(roots) -> file_effects.FileEffectOracle:
    def packaged_reference_resolution(platform: str) -> PackagedReferenceResolution:
        if platform == "claude":
            return resolution("available", ("query.md", "update.md"), "claude refs")
        if platform == "empty":
            return resolution("empty", detail="empty refs")
        if platform == "no_eligible":
            return resolution("no_eligible_bundle", detail="no eligible refs")
        if platform == "missing":
            return resolution("missing", detail="missing /package/refs")
        if platform == "not_directory":
            return resolution("not_directory", detail="not_directory /package/refs")
        return resolution("intentionally_absent", detail="absent refs")

    return file_effects.FileEffectOracle(
        roots=roots,
        packaged_reference_resolution=packaged_reference_resolution,
        expected_graphify_version=lambda: "9.9.9",
        manifest_prune_dirs=set(file_effects.GENERATED_COPY_EXCLUDES),
    )


def scenario(platform: str, *expected: InstallSurface, scope: str = "project") -> Scenario:
    return Scenario(
        platform=platform,
        scope=scope,
        install_command=("true",),
        uninstall_command=None,
        cwd_root="project" if scope == "project" else "user_cwd",
        expected=expected,
    )


def expected_skill(root: str, relative: str) -> InstallSurface:
    return InstallSurface(root, relative, skill_sidecar_expectation=platform_specs.SkillSidecarExpectation())


def expected_skill_with_docs_sidecar(root: str, relative: str) -> InstallSurface:
    return InstallSurface(
        root,
        relative,
        skill_sidecar_expectation=platform_specs.SkillSidecarExpectation(
            references_dir="docs",
            references_tmp_dir="docs.tmp",
            reference_pointer_pattern=r"docs/([A-Za-z0-9_.-]+\.md)\b",
        ),
    )


def section(root: str, relative: str, marker: str = platform_specs.GRAPHIFY_MARKER, *, preserve_user_content: bool = False) -> InstallSurface:
    return InstallSurface(
        root,
        relative,
        marker=marker,
        text_expectation=platform_specs.TextExpectation(
            preserve_user_content=preserve_user_content,
            repair_stale_graphify_section=True,
            require_user_content_on_uninstall=preserve_user_content,
        ),
    )


def write_skill(root: Path, relative: str, *, body: str = "# graphify skill\n", version: str | None = None) -> Path:
    skill = root / relative
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(body, encoding="utf-8")
    if version is not None:
        (skill.parent / ".graphify_version").write_text(version, encoding="utf-8")
    return skill


def check_by_relative(checks: list[dict[str, object]], relative: str) -> dict[str, object]:
    return next(check for check in checks if check.get("relative") == relative)


def json_shape_check(oracle: file_effects.FileEffectOracle, roots: dict[str, Path], relative: str, data: object) -> dict[str, object]:
    test_scenario = scenario("unit", ExpectedPath("project", relative, content_kind="json", marker="graphify"))
    path = roots["project"] / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return oracle.assert_expected_files(test_scenario)[0]


def registered_json_shape_check(oracle: file_effects.FileEffectOracle, roots: dict[str, Path], platform: str, scope: str, relative: str, data: object) -> dict[str, object]:
    test_scenario = platform_specs.DEFAULT_SCENARIO_REGISTRY.make_scenario(platform, scope)
    assert test_scenario is not None
    entry = next(item for item in test_scenario.expected if item.relative == relative)
    root = roots[entry.root]
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return oracle.assert_expected_files(scenario(platform, entry, scope=scope))[0]


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
    expectation = install_surface_core.ReferenceSidecarExpectation.from_resolution(resolution(status, names))

    assert expectation.expected_relatives(Path(".unit/graphify"), platform_specs.SkillSidecarExpectation()) == {Path(relative) for relative in expected_relatives}


def test_reference_sidecar_expectation_validates_installed_status_matrix(tmp_path: Path) -> None:
    def installed_reference_names(refs_dir: Path) -> list[str]:
        return sorted(path.name for path in refs_dir.glob("*.md") if path.is_file())

    refs_dir = tmp_path / "references"
    absent = install_surface_core.ReferenceSidecarExpectation.from_resolution(resolution("intentionally_absent", detail="absent refs"))
    ok, detail = install_surface_core.installed_reference_sidecar_status(
        absent,
        references_exists=refs_dir.exists(),
        references_is_dir=refs_dir.is_dir(),
        installed_names=installed_reference_names(refs_dir),
    )
    assert ok is True
    assert detail == "intentionally_absent; references_absent; absent refs"

    refs_dir.mkdir()
    ok, detail = install_surface_core.installed_reference_sidecar_status(
        absent,
        references_exists=refs_dir.exists(),
        references_is_dir=refs_dir.is_dir(),
        installed_names=installed_reference_names(refs_dir),
    )
    assert ok is False
    assert detail == "intentionally_absent; references_present; absent refs"

    source_error = install_surface_core.ReferenceSidecarExpectation.from_resolution(resolution("missing", detail="missing /package/refs"))
    ok, detail = install_surface_core.installed_reference_sidecar_status(
        source_error,
        references_exists=refs_dir.exists(),
        references_is_dir=refs_dir.is_dir(),
        installed_names=installed_reference_names(refs_dir),
    )
    assert ok is False
    assert detail == "missing; missing /package/refs"

    expected = install_surface_core.ReferenceSidecarExpectation.from_resolution(resolution("available", ("query.md",), "available refs"))
    ok, detail = install_surface_core.installed_reference_sidecar_status(
        expected,
        references_exists=refs_dir.exists(),
        references_is_dir=refs_dir.is_dir(),
        installed_names=installed_reference_names(refs_dir),
    )
    assert ok is False
    assert "missing=['query.md']" in detail

    (refs_dir / "query.md").write_text("query\n", encoding="utf-8")
    ok, detail = install_surface_core.installed_reference_sidecar_status(
        expected,
        references_exists=refs_dir.exists(),
        references_is_dir=refs_dir.is_dir(),
        installed_names=installed_reference_names(refs_dir),
    )
    assert ok is True
    assert "status=available" in detail


def test_install_surface_core_evaluates_skill_sidecar_status_decisions() -> None:
    sidecar = platform_specs.SkillSidecarExpectation()

    assert install_surface_core.skill_version_status(None, "9.9.9") == (False, "missing; expected=9.9.9")
    assert install_surface_core.skill_version_status("9.9.9\n", "9.9.9") == (True, "actual=9.9.9; expected=9.9.9")
    assert install_surface_core.references_tmp_absence_status(False) == (True, "absent")
    assert install_surface_core.references_tmp_absence_status(True) == (False, "present")
    assert install_surface_core.skill_reference_pointer_status(
        sidecar,
        "See references/query.md and references/update.md",
        references_is_dir=True,
        installed_names=("query.md",),
    ) == (False, "pointers=['query.md', 'update.md']; missing=['update.md']")
    assert install_surface_core.skill_reference_pointer_status(
        sidecar,
        "See references/query.md",
        references_is_dir=False,
        installed_names=(),
    ) == (False, "references_missing; skill_mentions_references=true; pointers=['query.md']")
    assert install_surface_core.skill_reference_pointer_status(sidecar, "No pointers here", references_is_dir=False, installed_names=()) == (
        True,
        "no_reference_pointers",
    )
    assert install_surface_core.uninstalled_skill_sidecar_status(False) == (True, "removed")
    assert install_surface_core.uninstalled_skill_sidecar_status(True) == (False, "sidecar_still_exists")


def test_install_surface_core_classifies_generated_file_relevance_decisions() -> None:
    skill_entry = expected_skill("home", ".codex/skills/graphify/SKILL.md")
    ordinary_entry = InstallSurface("project", "AGENTS.md")
    expected = (skill_entry, ordinary_entry)
    expectation = platform_specs.GeneratedFileExpectation(
        relative_substrings=("graphify",),
        text_suffixes=(".md",),
        content_markers=("Graphify",),
        include_user_content_sentinel=True,
        max_text_bytes=12,
    )

    assert install_surface_core.expected_generated_relative_keys(expected, resolution("available", ("query.md",))) == {
        ("home", ".codex/skills/graphify/SKILL.md"),
        ("home", ".codex/skills/graphify/.graphify_version"),
        ("home", ".codex/skills/graphify/references.tmp"),
        ("home", ".codex/skills/graphify/references"),
        ("home", ".codex/skills/graphify/references/query.md"),
        ("project", "AGENTS.md"),
    }
    assert install_surface_core.is_excluded_generated_path(Path(".local/lib/example.py"), file_effects.GENERATED_COPY_EXCLUDES) is True
    assert install_surface_core.is_expected_generated_key(expected, "project", Path("AGENTS.md")) is True
    assert install_surface_core.is_skill_sidecar_relative(expected, "home", Path(".codex/skills/graphify/references/nested/query.md")) is True
    assert install_surface_core.is_small_text_candidate(expectation, file_size=12, suffix=".md") is True
    assert install_surface_core.is_small_text_candidate(expectation, file_size=13, suffix=".md") is False
    assert install_surface_core.is_small_text_candidate(expectation, file_size=12, suffix=".bin") is False
    assert install_surface_core.text_mentions_expected_generated_marker(expectation, "generated by graphify") is True
    assert install_surface_core.text_mentions_expected_generated_marker(expectation, file_effects.USER_SENTINEL) is True

    candidate = install_surface_core.generated_file_observation(
        expectation,
        expected,
        "project",
        Path("notes.md"),
        file_size=12,
        mentions_expected_marker=False,
        excluded_path=False,
    )
    assert candidate.root_name == "project"
    assert candidate.relative == Path("notes.md")
    assert candidate.suffix == ".md"
    assert candidate.file_size == 12
    assert candidate.expected_key is False
    assert candidate.skill_sidecar_relative is False
    assert candidate.excluded_path is False
    assert candidate.relative_substring_match is False
    assert candidate.small_text_candidate is True
    assert candidate.needs_text_marker_match is True
    assert install_surface_core.decide_generated_file_observation(candidate).should_include is False

    marker_match = install_surface_core.generated_file_observation(
        expectation,
        expected,
        "project",
        Path("notes.md"),
        file_size=12,
        mentions_expected_marker=True,
        excluded_path=False,
    )
    marker_decision = install_surface_core.decide_generated_file_observation(marker_match)
    assert marker_decision.is_relevant is True
    assert marker_decision.is_ignored is False
    assert marker_decision.should_include is True

    excluded = install_surface_core.generated_file_observation(
        expectation,
        expected,
        "project",
        Path(".cache/graphify.txt"),
        file_size=12,
        mentions_expected_marker=True,
        excluded_path=True,
    )
    excluded_decision = install_surface_core.decide_generated_file_observation(excluded)
    assert excluded.path_relevant is True
    assert excluded.needs_text_marker_match is False
    assert excluded_decision.is_relevant is True
    assert excluded_decision.is_ignored is True
    assert excluded_decision.should_include is False

    assert (
        install_surface_core.is_relevant_generated_file(
            expectation,
            expected,
            "project",
            Path("AGENTS.md"),
            small_text_candidate=False,
            mentions_expected_marker=False,
        )
        is True
    )
    assert (
        install_surface_core.is_relevant_generated_file(
            expectation,
            expected,
            "home",
            Path(".codex/skills/graphify/.graphify_version"),
            small_text_candidate=False,
            mentions_expected_marker=False,
        )
        is True
    )
    assert (
        install_surface_core.is_relevant_generated_file(
            expectation,
            expected,
            "project",
            Path("notes/graphify-log.bin"),
            small_text_candidate=False,
            mentions_expected_marker=False,
        )
        is True
    )
    assert (
        install_surface_core.is_relevant_generated_file(
            expectation,
            expected,
            "project",
            Path("notes.md"),
            small_text_candidate=True,
            mentions_expected_marker=True,
        )
        is True
    )
    assert (
        install_surface_core.is_relevant_generated_file(
            expectation,
            expected,
            "project",
            Path("notes.md"),
            small_text_candidate=True,
            mentions_expected_marker=False,
        )
        is False
    )
    assert (
        install_surface_core.is_relevant_generated_file(
            expectation,
            expected,
            "project",
            Path("notes.md"),
            small_text_candidate=False,
            mentions_expected_marker=True,
        )
        is False
    )


def test_install_surface_core_derives_generated_artifact_copy_destination() -> None:
    plan = install_surface_core.generated_artifact_copy_plan(
        "project",
        Path("nested/graphify-output.txt"),
    )

    assert plan == install_surface_core.GeneratedArtifactCopyPlan(
        root_name="project",
        source_relative=Path("nested/graphify-output.txt"),
        destination_relative=Path("project/nested/graphify-output.txt"),
    )


def test_install_surface_core_calculates_idempotency_fingerprints(tmp_path: Path) -> None:
    missing = tmp_path / "missing.md"
    directory = tmp_path / "dir"
    directory.mkdir()
    notes = tmp_path / "notes.md"
    notes_text = f"# Notes\n\n{file_effects.USER_SENTINEL}\n\n## graphify\n{file_effects.STALE_GRAPHIFY_SENTINEL}\n"
    notes.write_text(notes_text, encoding="utf-8")

    assert install_surface_core.file_fingerprint(missing) == {"exists": False}
    assert install_surface_core.file_fingerprint(directory) == {"exists": True, "kind": "dir"}

    fingerprint = install_surface_core.file_fingerprint(
        notes,
        "## graphify",
        platform_specs.TextExpectation(preserve_user_content=True, repair_stale_graphify_section=True),
    )

    assert fingerprint["exists"] is True
    assert fingerprint["kind"] == "file"
    assert fingerprint["size"] == len(notes_text.encode("utf-8"))
    assert fingerprint["marker_count"] == 1
    assert fingerprint["user_content_preserved"] is True
    assert fingerprint["stale_graphify_present"] is True
    assert isinstance(fingerprint["sha256"], str)


def test_install_surface_core_derives_ordered_idempotency_state_plan() -> None:
    notes = section("project", "notes.md", preserve_user_content=True)
    skill = expected_skill("home", ".codex/skills/graphify/SKILL.md")

    plan = install_surface_core.planned_state_entries(
        (notes, skill),
        resolution("available", ("query.md",)),
        installed_skill_reference_relatives={
            ("home", ".codex/skills/graphify/SKILL.md"): {
                Path(".codex/skills/graphify/references/local.md"),
            },
        },
    )

    assert [entry.key for entry in plan] == [
        "project/notes.md",
        "home/.codex/skills/graphify/SKILL.md",
        "home/.codex/skills/graphify/.graphify_version",
        "home/.codex/skills/graphify/references",
        "home/.codex/skills/graphify/references.tmp",
        "home/.codex/skills/graphify/references/local.md",
        "home/.codex/skills/graphify/references/query.md",
    ]
    assert plan[0].root_name == "project"
    assert plan[0].relative == Path("notes.md")
    assert plan[0].marker == platform_specs.GRAPHIFY_MARKER
    assert plan[0].text_expectation is not None
    assert plan[0].text_expectation.preserve_user_content is True
    assert plan[1].root_name == "home"
    assert plan[1].relative == Path(".codex/skills/graphify/SKILL.md")
    assert plan[2].marker is None
    assert plan[2].text_expectation is None


def test_install_surface_core_derives_ordered_idempotency_state_changes() -> None:
    before = {
        "project/changed.md": {"exists": True, "sha256": "before"},
        "project/removed.md": {"exists": True, "sha256": "removed"},
        "project/stable.md": {"exists": True, "sha256": "same"},
    }
    after = {
        "project/added.md": {"exists": True, "sha256": "added"},
        "project/changed.md": {"exists": True, "sha256": "after"},
        "project/stable.md": {"exists": True, "sha256": "same"},
    }

    changes = install_surface_core.idempotency_state_changes(before, after)

    assert changes == (
        install_surface_core.IdempotencyStateChange("project/added.md", stable=False),
        install_surface_core.IdempotencyStateChange("project/changed.md", stable=False),
        install_surface_core.IdempotencyStateChange("project/removed.md", stable=False),
        install_surface_core.IdempotencyStateChange("project/stable.md", stable=True),
    )


def test_install_surface_core_derives_user_content_seed_plans() -> None:
    stale_section = section("project", "stale-notes.md", preserve_user_content=True)
    legacy_text_policy = ExpectedPath(
        "home",
        "legacy-notes.txt",
        text_expectation=platform_specs.TextExpectation(preserve_user_content=True),
    )
    no_preserve_text_section = section("project", "no-preserve.md")
    plain_surface = ExpectedPath("project", "plain.txt")
    json_surface = ExpectedPath("project", "settings.json", content_kind="json", marker="graphify")

    plans = install_surface_core.user_content_seed_plans(
        (
            stale_section,
            legacy_text_policy,
            no_preserve_text_section,
            plain_surface,
            json_surface,
        )
    )

    assert plans == (
        install_surface_core.UserContentSeedPlan(
            root_name="project",
            relative=Path("stale-notes.md"),
            text=(
                f"# User Notes\n\n{file_effects.USER_SENTINEL}\n\n"
                f"{platform_specs.GRAPHIFY_MARKER}\n{file_effects.STALE_GRAPHIFY_SENTINEL}\n\n"
                "## User Section\nThis section should survive Graphify install and uninstall.\n"
            ),
        ),
        install_surface_core.UserContentSeedPlan(
            root_name="home",
            relative=Path("legacy-notes.txt"),
            text=f"# User Notes\n\n{file_effects.USER_SENTINEL}\n",
        ),
    )


def test_install_surface_core_derives_stale_sidecar_seed_plans() -> None:
    skill = expected_skill("home", ".codex/skills/graphify/SKILL.md")
    plain_surface = ExpectedPath("project", "AGENTS.md")

    plans = install_surface_core.stale_sidecar_seed_plans(
        (plain_surface, skill),
        resolution("available", ("query.md",)),
    )

    assert plans == (
        install_surface_core.StaleSidecarSeedPlan(
            root_name="home",
            relative=Path(".codex/skills/graphify/references/stale-sandbox-fragment.md"),
            text="stale sandbox reference fragment\n",
            kind="stale_reference_fragment",
        ),
        install_surface_core.StaleSidecarSeedPlan(
            root_name="home",
            relative=Path(".codex/skills/graphify/references.tmp/partial.md"),
            text="partial staged reference fragment\n",
            kind="staged_reference_fragment",
        ),
    )
    assert install_surface_core.stale_sidecar_seed_plans((skill,), resolution("empty")) == plans
    assert install_surface_core.stale_sidecar_seed_plans((skill,), resolution("missing")) == plans
    assert install_surface_core.stale_sidecar_seed_plans((skill,), resolution("not_directory")) == plans
    assert install_surface_core.stale_sidecar_seed_plans((skill,), resolution("intentionally_absent")) == ()
    assert install_surface_core.stale_sidecar_seed_plans((skill,), resolution("no_eligible_bundle")) == ()
    assert install_surface_core.stale_sidecar_seed_plans((plain_surface,), resolution("available", ("query.md",))) == ()


def test_expected_generated_keys_reuse_generated_state_plan() -> None:
    notes = section("project", "notes.md", preserve_user_content=True)
    skill = expected_skill("home", ".codex/skills/graphify/SKILL.md")

    plan = install_surface_core.planned_state_entries(
        (notes, skill),
        resolution("available", ("query.md",)),
    )

    assert install_surface_core.expected_generated_relative_keys((notes, skill), resolution("available", ("query.md",))) == {
        (entry.root_name, entry.relative.as_posix()) for entry in plan
    }


def test_skill_sidecar_relative_derivation_uses_declared_sidecar_names(oracle) -> None:
    default_entry = expected_skill("project", ".aider/graphify/SKILL.md")
    custom_entry = expected_skill_with_docs_sidecar("project", ".custom/graphify/SKILL.md")

    assert install_surface_core.skill_relative_dir(default_entry) == Path(".aider/graphify")
    assert install_surface_core.skill_version_relative(default_entry) == Path(".aider/graphify/.graphify_version")
    assert install_surface_core.skill_references_relative(default_entry) == Path(".aider/graphify/references")
    assert install_surface_core.skill_references_tmp_relative(default_entry) == Path(".aider/graphify/references.tmp")

    assert install_surface_core.skill_relative_dir(custom_entry) == Path(".custom/graphify")
    assert install_surface_core.skill_version_relative(custom_entry) == Path(".custom/graphify/.graphify_version")
    assert install_surface_core.skill_references_relative(custom_entry) == Path(".custom/graphify/docs")
    assert install_surface_core.skill_references_tmp_relative(custom_entry) == Path(".custom/graphify/docs.tmp")

    assert oracle.skill_relative_dir(default_entry) == Path(".aider/graphify")
    assert oracle.skill_version_relative(default_entry) == Path(".aider/graphify/.graphify_version")
    assert oracle.skill_references_relative(default_entry) == Path(".aider/graphify/references")
    assert oracle.skill_references_tmp_relative(default_entry) == Path(".aider/graphify/references.tmp")

    assert oracle.skill_relative_dir(custom_entry) == Path(".custom/graphify")
    assert oracle.skill_version_relative(custom_entry) == Path(".custom/graphify/.graphify_version")
    assert oracle.skill_references_relative(custom_entry) == Path(".custom/graphify/docs")
    assert oracle.skill_references_tmp_relative(custom_entry) == Path(".custom/graphify/docs.tmp")


def test_install_surface_core_derives_expected_skill_sidecar_relatives_from_resolved_references() -> None:
    entry = expected_skill("project", ".claude/skills/graphify/SKILL.md")

    assert install_surface_core.expected_skill_sidecar_relatives(entry, resolution("available", ("query.md", "update.md"))) == {
        Path(".claude/skills/graphify/.graphify_version"),
        Path(".claude/skills/graphify/references.tmp"),
        Path(".claude/skills/graphify/references"),
        Path(".claude/skills/graphify/references/query.md"),
        Path(".claude/skills/graphify/references/update.md"),
    }

    with pytest.raises(AssertionError, match="expected path has no skill sidecar expectation: project/notes.md"):
        install_surface_core.skill_sidecar_expectation(InstallSurface("project", "notes.md"))


def test_install_surface_core_derives_expected_manifest_relatives_for_root() -> None:
    project_notes = InstallSurface("project", "AGENTS.md")
    project_skill = expected_skill("project", ".claude/skills/graphify/SKILL.md")
    home_skill = expected_skill("home", ".codex/skills/graphify/SKILL.md")

    assert install_surface_core.expected_manifest_relatives(
        (project_notes, project_skill, home_skill),
        resolution("available", ("query.md", "update.md")),
        "project",
    ) == {
        Path("AGENTS.md"),
        Path(".claude/skills/graphify/SKILL.md"),
        Path(".claude/skills/graphify/.graphify_version"),
        Path(".claude/skills/graphify/references.tmp"),
        Path(".claude/skills/graphify/references"),
        Path(".claude/skills/graphify/references/query.md"),
        Path(".claude/skills/graphify/references/update.md"),
    }
    assert install_surface_core.expected_manifest_relatives(
        (project_notes, project_skill, home_skill),
        resolution("intentionally_absent"),
        "home",
    ) == {
        Path(".codex/skills/graphify/SKILL.md"),
        Path(".codex/skills/graphify/.graphify_version"),
        Path(".codex/skills/graphify/references.tmp"),
    }


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
    oracle: file_effects.FileEffectOracle,
    platform: str,
    expected_relatives: set[str],
) -> None:
    relative = ".claude/skills/graphify/SKILL.md" if platform == "claude" else f".{platform}/graphify/SKILL.md"
    entry = expected_skill("project", relative)
    test_scenario = scenario(platform, entry)

    assert oracle.expected_skill_sidecar_relatives(test_scenario, entry) == {Path(relative) for relative in expected_relatives}


def test_assertion_detects_missing_file(oracle) -> None:
    checks = oracle.assert_expected_files(scenario("unit", ExpectedPath("project", "missing.txt")))

    assert len(checks) == 1
    assert checks[0]["ok"] is False
    assert checks[0]["detail"] == "missing"


def test_install_surface_alias_is_accepted_by_scenario_and_oracle(oracle, roots) -> None:
    assert platform_specs.ExpectedPath is platform_specs.InstallSurface

    surface = platform_specs.InstallSurface("project", "surface.txt")
    (roots["project"] / "surface.txt").write_text("installed\n", encoding="utf-8")
    test_scenario = Scenario(
        platform="unit",
        scope="project",
        install_command=("true",),
        uninstall_command=None,
        cwd_root="project",
        expected=(surface,),
    )

    checks = oracle.assert_expected_files(test_scenario)

    assert test_scenario.expected == (surface,)
    assert checks == [
        {
            "path": str(roots["project"] / "surface.txt"),
            "ok": True,
            "detail": "file",
            "root": "project",
            "relative": "surface.txt",
        }
    ]


def test_install_surface_path_uses_declared_root_and_relative(oracle, roots) -> None:
    surface = InstallSurface("project", "nested/surface.txt")

    assert oracle.expected_path(surface) == roots["project"] / "nested/surface.txt"

    with pytest.raises(AssertionError, match="unknown root: missing"):
        oracle.expected_path(InstallSurface("missing", "surface.txt"))


def test_install_surface_kind_status_contracts(oracle, roots) -> None:
    file_surface = InstallSurface("project", "installed.txt")
    dir_surface = InstallSurface("project", "installed-dir", kind="dir")
    generic_surface = InstallSurface("project", "socketish", kind="exists")
    wrong_dir_surface = InstallSurface("project", "wrong-dir", kind="dir")

    (roots["project"] / "installed.txt").write_text("installed\n", encoding="utf-8")
    (roots["project"] / "installed-dir").mkdir()
    (roots["project"] / "socketish").write_text("installed\n", encoding="utf-8")
    (roots["project"] / "wrong-dir").write_text("not a directory\n", encoding="utf-8")

    assert oracle.expected_entry_status(file_surface) == (True, "file")
    assert oracle.expected_entry_status(dir_surface) == (True, "directory")
    assert oracle.expected_entry_status(generic_surface) == (True, "exists")
    assert oracle.expected_entry_status(wrong_dir_surface) == (False, "expected_directory_but_not_directory")
    assert oracle.expected_entry_status(InstallSurface("project", "missing-dir", kind="dir")) == (False, "missing")


def test_install_surface_core_resolves_kind_status_from_declared_roots(roots) -> None:
    surface = InstallSurface("project", "installed.txt")
    (roots["project"] / "installed.txt").write_text("installed\n", encoding="utf-8")

    status = install_surface_core.install_surface_kind_status(surface, roots)

    assert status.path == roots["project"] / "installed.txt"
    assert status.ok is True
    assert status.detail == "file"


def test_install_surface_core_resolves_installed_marker_status(roots) -> None:
    text_surface = section("project", "notes.md", preserve_user_content=True)
    text_path = roots["project"] / "notes.md"
    text_path.write_text(
        f"# Notes\n\n{file_effects.USER_SENTINEL}\n\n{platform_specs.GRAPHIFY_MARKER}\nnew section\n",
        encoding="utf-8",
    )

    text_status = install_surface_core.installed_surface_status(text_surface, roots)

    assert text_status.path == text_path
    assert text_status.ok is True
    assert text_status.detail == "marker_count=1; user_content_preserved; stale_replaced=True"

    json_surface = InstallSurface("project", "settings.json", content_kind="json", marker="graphify")
    json_path = roots["project"] / "settings.json"
    json_path.write_text(json.dumps({"hooks": [{"command": "graphify query"}]}), encoding="utf-8")

    json_status = install_surface_core.installed_surface_status(json_surface, roots)

    assert json_status.path == json_path
    assert json_status.ok is True
    assert json_status.detail == "valid_json=true; schema=generic_marker; marker_present=True"


def test_text_marker_status_preserves_user_content_and_replaces_stale_section(oracle, roots) -> None:
    surface = section("project", "notes.md", preserve_user_content=True)
    path = roots["project"] / "notes.md"

    path.write_text(
        f"# Notes\n\n{file_effects.USER_SENTINEL}\n\n{platform_specs.GRAPHIFY_MARKER}\nnew section\n",
        encoding="utf-8",
    )
    assert oracle.expected_entry_status(surface) == (True, "marker_count=1; user_content_preserved; stale_replaced=True")

    path.write_text(
        f"# Notes\n\n{platform_specs.GRAPHIFY_MARKER}\nfirst\n\n{platform_specs.GRAPHIFY_MARKER}\nsecond\n",
        encoding="utf-8",
    )
    assert oracle.expected_entry_status(surface) == (False, "marker_count=2; user_content_missing; stale_replaced=True")

    path.write_text(
        f"# Notes\n\n{file_effects.USER_SENTINEL}\n\n{platform_specs.GRAPHIFY_MARKER}\n{file_effects.STALE_GRAPHIFY_SENTINEL}\n",
        encoding="utf-8",
    )
    assert oracle.expected_entry_status(surface) == (False, "marker_count=1; user_content_preserved; stale_replaced=False")


def test_json_surface_marker_status_contracts(oracle, roots) -> None:
    generic = InstallSurface("project", "generic.json", content_kind="json", marker="graphify")
    generic_path = roots["project"] / "generic.json"
    generic_path.write_text(json.dumps({"hooks": [{"command": "graphify query"}]}), encoding="utf-8")

    assert oracle.expected_entry_status(generic) == (True, "valid_json=true; schema=generic_marker; marker_present=True")

    generic_path.write_text(json.dumps({"hooks": [{"command": "other"}]}), encoding="utf-8")
    assert oracle.expected_entry_status(generic) == (False, "valid_json=true; schema=generic_marker; marker_present=False")

    registered = InstallSurface(
        "project",
        "hooks.json",
        content_kind="json",
        marker="graphify",
        json_expectation=platform_specs.JsonExpectation(
            schema_name="unit_hooks",
            hooks=(platform_specs.JsonHookExpectation("PreToolUse", "Bash", "bash_hook_present"),),
        ),
    )
    registered_path = roots["project"] / "hooks.json"
    registered_path.write_text(
        json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "graphify hook-check"}]}]}}),
        encoding="utf-8",
    )

    assert oracle.expected_entry_status(registered) == (True, "valid_json=true; schema=unit_hooks; bash_hook_present=True")

    registered_path.write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": []}]}}), encoding="utf-8")
    assert oracle.expected_entry_status(registered) == (False, "valid_json=true; schema=unit_hooks; bash_hook_present=False")


def test_uninstall_surface_status_contracts(oracle, roots) -> None:
    plain = InstallSurface("project", "plain.txt")
    plain_path = roots["project"] / "plain.txt"

    assert oracle.uninstalled_entry_status(plain) == (True, "removed")

    plain_path.write_text("still here\n", encoding="utf-8")
    assert oracle.uninstalled_entry_status(plain) == (False, "still_exists")

    text_section = section("project", "notes.md", preserve_user_content=True)
    notes_path = roots["project"] / "notes.md"
    notes_path.write_text(f"# Notes\n\n{file_effects.USER_SENTINEL}\n\n## User Section\n", encoding="utf-8")
    assert oracle.uninstalled_entry_status(text_section) == (True, "graphify_removed=True; user_content_preserved=True")

    notes_path.write_text(
        f"# Notes\n\n{file_effects.USER_SENTINEL}\n\n{platform_specs.GRAPHIFY_MARKER}\n{file_effects.STALE_GRAPHIFY_SENTINEL}\n",
        encoding="utf-8",
    )
    assert oracle.uninstalled_entry_status(text_section) == (False, "graphify_removed=False; user_content_preserved=True")


def test_install_surface_core_resolves_uninstalled_surface_status(roots) -> None:
    plain = InstallSurface("project", "plain.txt")
    plain_status = install_surface_core.uninstalled_surface_status(plain, roots)

    assert plain_status.path == roots["project"] / "plain.txt"
    assert plain_status.ok is True
    assert plain_status.detail == "removed"

    text_section = section("project", "notes.md", preserve_user_content=True)
    notes_path = roots["project"] / "notes.md"
    notes_path.write_text(f"# Notes\n\n{file_effects.USER_SENTINEL}\n\n## User Section\n", encoding="utf-8")

    text_status = install_surface_core.uninstalled_surface_status(text_section, roots)

    assert text_status.path == notes_path
    assert text_status.ok is True
    assert text_status.detail == "graphify_removed=True; user_content_preserved=True"

    notes_path.write_text(
        f"# Notes\n\n{file_effects.USER_SENTINEL}\n\n{platform_specs.GRAPHIFY_MARKER}\n{file_effects.STALE_GRAPHIFY_SENTINEL}\n",
        encoding="utf-8",
    )

    stale_status = install_surface_core.uninstalled_surface_status(text_section, roots)

    assert stale_status.ok is False
    assert stale_status.detail == "graphify_removed=False; user_content_preserved=True"


def test_oracle_dispatches_named_effect_types(oracle, roots) -> None:
    skill = platform_specs.SkillEffect("project", ".unit/graphify/SKILL.md")
    hooks = platform_specs.JsonHooksEffect(
        "project",
        ".unit/hooks.json",
        json_expectation=platform_specs.JsonExpectation(
            schema_name="unit_hooks",
            hooks=(platform_specs.JsonHookExpectation("PreToolUse", "Bash", "bash_hook_present"),),
        ),
    )
    write_skill(roots["project"], ".unit/graphify/SKILL.md", version="9.9.9")
    hooks_path = roots["project"] / ".unit/hooks.json"
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [{"type": "command", "command": "graphify hook-check"}],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    checks = oracle.assert_expected_files(scenario("unit", skill, hooks))

    assert all(check["ok"] for check in checks)
    assert check_by_relative(checks, ".unit/graphify/.graphify_version")["ok"] is True
    assert check_by_relative(checks, ".unit/hooks.json")["detail"] == "valid_json=true; schema=unit_hooks; bash_hook_present=True"


def test_skill_assertion_detects_missing_and_wrong_version_stamp(oracle, roots) -> None:
    missing_version = scenario("aider", expected_skill("project", ".aider/graphify/SKILL.md"))
    write_skill(roots["project"], ".aider/graphify/SKILL.md")

    version = check_by_relative(oracle.assert_expected_files(missing_version), ".aider/graphify/.graphify_version")
    assert version["ok"] is False
    assert "missing" in str(version["detail"])

    write_skill(roots["project"], ".aider/graphify/SKILL.md", version="0.0.0")
    version = check_by_relative(oracle.assert_expected_files(missing_version), ".aider/graphify/.graphify_version")
    assert version["ok"] is False
    assert "actual=0.0.0" in str(version["detail"])
    assert "expected=9.9.9" in str(version["detail"])


def test_installed_skill_sidecar_records_render_sandbox_check_shape(oracle, roots) -> None:
    test_scenario = scenario("claude", expected_skill("project", ".claude/skills/graphify/SKILL.md"))
    skill = write_skill(
        roots["project"],
        ".claude/skills/graphify/SKILL.md",
        body="See references/query.md and references/update.md for details.\n",
        version="9.9.9",
    )
    refs = skill.parent / "references"
    refs.mkdir()
    (refs / "query.md").write_text("# query\n", encoding="utf-8")
    (refs / "update.md").write_text("# update\n", encoding="utf-8")

    checks = oracle.assert_expected_files(test_scenario)

    version = check_by_relative(checks, ".claude/skills/graphify/.graphify_version")
    assert version == {
        "path": str(roots["project"] / ".claude/skills/graphify/.graphify_version"),
        "ok": True,
        "detail": "actual=9.9.9; expected=9.9.9",
        "root": "project",
        "relative": ".claude/skills/graphify/.graphify_version",
    }

    refs_tmp = check_by_relative(checks, ".claude/skills/graphify/references.tmp")
    assert refs_tmp == {
        "path": str(roots["project"] / ".claude/skills/graphify/references.tmp"),
        "ok": True,
        "detail": "absent",
        "root": "project",
        "relative": ".claude/skills/graphify/references.tmp",
    }

    packaged_refs = check_by_relative(checks, ".claude/skills/graphify/references")
    assert packaged_refs["path"] == str(roots["project"] / ".claude/skills/graphify/references")
    assert packaged_refs["ok"] is True
    assert packaged_refs["root"] == "project"
    assert packaged_refs["relative"] == ".claude/skills/graphify/references"
    assert packaged_refs["detail"] == (
        "status=available; actual_names=['query.md', 'update.md']; "
        "expected_names=['query.md', 'update.md']; missing=[]; extra=[]"
    )

    pointer_check = next(
        check
        for check in checks
        if check.get("relative") == ".claude/skills/graphify/SKILL.md" and str(check.get("detail")).startswith("pointers=")
    )
    assert pointer_check == {
        "path": str(roots["project"] / ".claude/skills/graphify/SKILL.md"),
        "ok": True,
        "detail": "pointers=['query.md', 'update.md']; missing=[]",
        "root": "project",
        "relative": ".claude/skills/graphify/SKILL.md",
    }


def test_skill_assertion_detects_missing_references_sidecar_from_body_pointer(oracle, roots) -> None:
    test_scenario = scenario("aider", expected_skill("project", ".aider/graphify/SKILL.md"))
    write_skill(
        roots["project"],
        ".aider/graphify/SKILL.md",
        body="See references/query.md for details.\n",
        version="9.9.9",
    )

    pointer_check = next(
        check
        for check in oracle.assert_expected_files(test_scenario)
        if check.get("relative") == ".aider/graphify/SKILL.md" and "references_missing" in str(check.get("detail"))
    )
    assert pointer_check["ok"] is False
    assert "references_missing" in str(pointer_check["detail"])


def test_skill_reference_pointer_detection_uses_declared_sidecar_pattern(oracle, roots) -> None:
    test_scenario = scenario("aider", expected_skill_with_docs_sidecar("project", ".custom/graphify/SKILL.md"))
    write_skill(
        roots["project"],
        ".custom/graphify/SKILL.md",
        body="See docs/query.md for details. references/query.md is unrelated legacy text.\n",
        version="9.9.9",
    )

    pointer_check = next(
        check
        for check in oracle.assert_expected_files(test_scenario)
        if check.get("relative") == ".custom/graphify/SKILL.md" and "docs_missing" in str(check.get("detail"))
    )
    assert pointer_check["ok"] is False
    assert "pointers=['query.md']" in str(pointer_check["detail"])


def test_skill_reference_pointer_detection_ignores_undeclared_references_directory(oracle, roots) -> None:
    test_scenario = scenario("aider", expected_skill_with_docs_sidecar("project", ".custom/graphify/SKILL.md"))
    write_skill(
        roots["project"],
        ".custom/graphify/SKILL.md",
        body="See references/query.md for details.\n",
        version="9.9.9",
    )

    pointer_check = next(
        check
        for check in oracle.assert_expected_files(test_scenario)
        if check.get("relative") == ".custom/graphify/SKILL.md" and check.get("detail") == "no_reference_pointers"
    )

    assert pointer_check["ok"] is True
    assert pointer_check["detail"] == "no_reference_pointers"


def test_skill_assertion_detects_references_tmp(oracle, roots) -> None:
    test_scenario = scenario("aider", expected_skill("project", ".aider/graphify/SKILL.md"))
    skill = write_skill(roots["project"], ".aider/graphify/SKILL.md", version="9.9.9")
    (skill.parent / "references.tmp").mkdir()

    tmp_check = check_by_relative(oracle.assert_expected_files(test_scenario), ".aider/graphify/references.tmp")
    assert tmp_check["ok"] is False
    assert tmp_check["detail"] == "present"


def test_skill_assertion_detects_extra_and_missing_packaged_reference_fragments(oracle, roots) -> None:
    test_scenario = scenario("claude", expected_skill("project", ".claude/skills/graphify/SKILL.md"))
    skill = write_skill(roots["project"], ".claude/skills/graphify/SKILL.md", version="9.9.9")
    refs = skill.parent / "references"
    refs.mkdir()
    (refs / "query.md").write_text("# query\n", encoding="utf-8")
    (refs / "update.md").write_text("# update\n", encoding="utf-8")
    (refs / "stale-sandbox-fragment.md").write_text("stale\n", encoding="utf-8")

    refs_check = check_by_relative(oracle.assert_expected_files(test_scenario), ".claude/skills/graphify/references")
    assert refs_check["ok"] is False
    assert "stale-sandbox-fragment.md" in str(refs_check["detail"])

    (refs / "stale-sandbox-fragment.md").unlink()
    (refs / "query.md").unlink()
    refs_check = check_by_relative(oracle.assert_expected_files(test_scenario), ".claude/skills/graphify/references")
    assert refs_check["ok"] is False
    assert "query.md" in str(refs_check["detail"])


def test_skill_assertion_rejects_monolith_sidecar(oracle, roots) -> None:
    test_scenario = scenario("aider", expected_skill("project", ".aider/graphify/SKILL.md"))
    skill = write_skill(roots["project"], ".aider/graphify/SKILL.md", version="9.9.9")
    refs = skill.parent / "references"
    refs.mkdir()
    (refs / "leftover.md").write_text("leftover\n", encoding="utf-8")

    refs_check = check_by_relative(oracle.assert_expected_files(test_scenario), ".aider/graphify/references")
    assert refs_check["ok"] is False
    assert "intentionally_absent" in str(refs_check["detail"])


def test_absent_packaged_reference_statuses_pass_when_references_absent(oracle, roots) -> None:
    for platform in ("aider", "no_eligible"):
        test_scenario = scenario(platform, expected_skill("project", f".{platform}/graphify/SKILL.md"))
        write_skill(roots["project"], f".{platform}/graphify/SKILL.md", version="9.9.9")

        refs_check = check_by_relative(oracle.assert_expected_files(test_scenario), f".{platform}/graphify/references")

        expected_status = "intentionally_absent" if platform == "aider" else "no_eligible_bundle"
        assert refs_check["ok"] is True
        assert expected_status in str(refs_check["detail"])


def test_no_eligible_bundle_fails_when_references_present(oracle, roots) -> None:
    test_scenario = scenario("no_eligible", expected_skill("project", ".no_eligible/graphify/SKILL.md"))
    skill = write_skill(roots["project"], ".no_eligible/graphify/SKILL.md", version="9.9.9")
    refs = skill.parent / "references"
    refs.mkdir()
    (refs / "leftover.md").write_text("leftover\n", encoding="utf-8")

    refs_check = check_by_relative(oracle.assert_expected_files(test_scenario), ".no_eligible/graphify/references")

    assert refs_check["ok"] is False
    assert "no_eligible_bundle" in str(refs_check["detail"])


def test_empty_packaged_references_requires_empty_installed_directory(oracle, roots) -> None:
    test_scenario = scenario("empty", expected_skill("project", ".empty/graphify/SKILL.md"))
    skill = write_skill(roots["project"], ".empty/graphify/SKILL.md", version="9.9.9")
    refs = skill.parent / "references"
    refs.mkdir()

    refs_check = check_by_relative(oracle.assert_expected_files(test_scenario), ".empty/graphify/references")
    assert refs_check["ok"] is True
    assert "status=empty" in str(refs_check["detail"])

    (refs / "unexpected.md").write_text("unexpected\n", encoding="utf-8")
    refs_check = check_by_relative(oracle.assert_expected_files(test_scenario), ".empty/graphify/references")
    assert refs_check["ok"] is False
    assert "extra=['unexpected.md']" in str(refs_check["detail"])


def test_malformed_packaged_reference_statuses_fail_with_resolver_detail(oracle, roots) -> None:
    for platform in ("missing", "not_directory"):
        test_scenario = scenario(platform, expected_skill("project", f".{platform}/graphify/SKILL.md"))
        write_skill(roots["project"], f".{platform}/graphify/SKILL.md", version="9.9.9")

        refs_check = check_by_relative(oracle.assert_expected_files(test_scenario), f".{platform}/graphify/references")

        assert refs_check["ok"] is False
        assert platform in str(refs_check["detail"])
        assert "/package/refs" in str(refs_check["detail"])


def test_reference_resolution_status_controls_manifest_generated_keys_and_state(oracle, roots) -> None:
    skill_entry = expected_skill("project", ".claude/skills/graphify/SKILL.md")
    ordinary_entry = InstallSurface("project", "AGENTS.md")
    available = scenario("claude", skill_entry)
    empty = scenario("empty", expected_skill("project", ".empty/graphify/SKILL.md"))
    absent = scenario("aider", expected_skill("project", ".aider/graphify/SKILL.md"))
    ordinary = scenario("unit", ordinary_entry)

    available_manifest = oracle.expected_manifest_relatives(available, "project")
    ordinary_manifest = oracle.expected_manifest_relatives(ordinary, "project")
    assert ordinary_manifest == {Path("AGENTS.md")}
    assert oracle.expected_manifest_relatives(ordinary, "home") == set()
    assert oracle.skill_version_relative(skill_entry) == Path(".claude/skills/graphify/.graphify_version")
    assert oracle.skill_references_relative(skill_entry) == Path(".claude/skills/graphify/references")
    assert oracle.skill_references_tmp_relative(skill_entry) == Path(".claude/skills/graphify/references.tmp")
    assert oracle.expected_skill_sidecar_relatives(available, skill_entry) == {
        Path(".claude/skills/graphify/.graphify_version"),
        Path(".claude/skills/graphify/references.tmp"),
        Path(".claude/skills/graphify/references"),
        Path(".claude/skills/graphify/references/query.md"),
        Path(".claude/skills/graphify/references/update.md"),
    }
    assert Path(".claude/skills/graphify/references") in available_manifest
    assert Path(".claude/skills/graphify/references/query.md") in available_manifest
    assert ("project", ".claude/skills/graphify/references/update.md") in oracle.expected_generated_relative_keys(available)
    assert "project/.claude/skills/graphify/references/query.md" in oracle.scenario_file_state(available)

    empty_manifest = oracle.expected_manifest_relatives(empty, "project")
    empty_entry = empty.expected[0]
    assert oracle.expected_skill_sidecar_relatives(empty, empty_entry) == {
        Path(".empty/graphify/.graphify_version"),
        Path(".empty/graphify/references.tmp"),
        Path(".empty/graphify/references"),
    }
    assert Path(".empty/graphify/references") in empty_manifest
    assert not any(path.name.endswith(".md") and "references" in path.parts for path in empty_manifest)
    assert ("project", ".empty/graphify/references") in oracle.expected_generated_relative_keys(empty)
    assert "project/.empty/graphify/references" in oracle.scenario_file_state(empty)

    absent_manifest = oracle.expected_manifest_relatives(absent, "project")
    absent_generated_keys = oracle.expected_generated_relative_keys(absent)
    absent_entry = absent.expected[0]
    assert oracle.expected_skill_sidecar_relatives(absent, absent_entry) == {
        Path(".aider/graphify/.graphify_version"),
        Path(".aider/graphify/references.tmp"),
    }
    assert Path(".aider/graphify/references") not in absent_manifest
    assert ("project", ".aider/graphify/references") not in absent_generated_keys
    assert not any(key[1].startswith(".aider/graphify/references/") for key in absent_generated_keys)
    assert "project/.aider/graphify/references" not in oracle.scenario_file_state(absent)


@pytest.mark.parametrize(
    ("platform", "skill_relative", "generated_relatives", "state_relatives"),
    [
        (
            "claude",
            ".claude/skills/graphify/SKILL.md",
            {
                ".claude/skills/graphify/SKILL.md",
                ".claude/skills/graphify/.graphify_version",
                ".claude/skills/graphify/references.tmp",
                ".claude/skills/graphify/references",
                ".claude/skills/graphify/references/query.md",
                ".claude/skills/graphify/references/update.md",
            },
            {
                ".claude/skills/graphify/SKILL.md",
                ".claude/skills/graphify/.graphify_version",
                ".claude/skills/graphify/references.tmp",
                ".claude/skills/graphify/references",
                ".claude/skills/graphify/references/query.md",
                ".claude/skills/graphify/references/update.md",
            },
        ),
        (
            "empty",
            ".empty/graphify/SKILL.md",
            {
                ".empty/graphify/SKILL.md",
                ".empty/graphify/.graphify_version",
                ".empty/graphify/references.tmp",
                ".empty/graphify/references",
            },
            {
                ".empty/graphify/SKILL.md",
                ".empty/graphify/.graphify_version",
                ".empty/graphify/references.tmp",
                ".empty/graphify/references",
            },
        ),
        (
            "aider",
            ".aider/graphify/SKILL.md",
            {
                ".aider/graphify/SKILL.md",
                ".aider/graphify/.graphify_version",
                ".aider/graphify/references.tmp",
            },
            {
                ".aider/graphify/SKILL.md",
                ".aider/graphify/.graphify_version",
                ".aider/graphify/references.tmp",
            },
        ),
        (
            "no_eligible",
            ".no_eligible/graphify/SKILL.md",
            {
                ".no_eligible/graphify/SKILL.md",
                ".no_eligible/graphify/.graphify_version",
                ".no_eligible/graphify/references.tmp",
            },
            {
                ".no_eligible/graphify/SKILL.md",
                ".no_eligible/graphify/.graphify_version",
                ".no_eligible/graphify/references.tmp",
            },
        ),
        (
            "missing",
            ".missing/graphify/SKILL.md",
            {
                ".missing/graphify/SKILL.md",
                ".missing/graphify/.graphify_version",
                ".missing/graphify/references.tmp",
                ".missing/graphify/references",
            },
            {
                ".missing/graphify/SKILL.md",
                ".missing/graphify/.graphify_version",
                ".missing/graphify/references.tmp",
                ".missing/graphify/references",
            },
        ),
        (
            "not_directory",
            ".not_directory/graphify/SKILL.md",
            {
                ".not_directory/graphify/SKILL.md",
                ".not_directory/graphify/.graphify_version",
                ".not_directory/graphify/references.tmp",
                ".not_directory/graphify/references",
            },
            {
                ".not_directory/graphify/SKILL.md",
                ".not_directory/graphify/.graphify_version",
                ".not_directory/graphify/references.tmp",
                ".not_directory/graphify/references",
            },
        ),
    ],
)
def test_sidecar_generated_keys_and_idempotency_state_follow_packaged_reference_status(
    oracle: file_effects.FileEffectOracle,
    roots: dict[str, Path],
    platform: str,
    skill_relative: str,
    generated_relatives: set[str],
    state_relatives: set[str],
) -> None:
    test_scenario = scenario(platform, expected_skill("project", skill_relative))
    skill = write_skill(roots["project"], skill_relative, version="9.9.9")
    if platform in {"claude", "empty"}:
        refs = skill.parent / "references"
        refs.mkdir()
        if platform == "claude":
            (refs / "query.md").write_text("# query\n", encoding="utf-8")
            (refs / "update.md").write_text("# update\n", encoding="utf-8")

    assert oracle.expected_generated_relative_keys(test_scenario) == {("project", relative) for relative in generated_relatives}
    assert set(oracle.scenario_file_state(test_scenario)) == {f"project/{relative}" for relative in state_relatives}


def test_scenario_file_state_pins_expected_surface_and_tracked_sidecar_fingerprints(oracle, roots) -> None:
    def assert_fingerprint(entry: dict[str, object], content: str) -> None:
        payload = content.encode("utf-8")
        assert entry["exists"] is True
        assert entry["kind"] == "file"
        assert entry["size"] == len(payload)
        assert entry["sha256"] == hashlib.sha256(payload).hexdigest()

    expected_notes = section("project", "notes.md", preserve_user_content=True)
    skill_entry = expected_skill("home", ".codex/skills/graphify/SKILL.md")
    test_scenario = scenario("claude", expected_notes, skill_entry)
    notes_text = f"# Notes\n\n{file_effects.USER_SENTINEL}\n\n{platform_specs.GRAPHIFY_MARKER}\ninstalled\n"
    skill_text = "See references/query.md.\n"
    version_text = "9.9.9"
    query_text = "# query\n"
    update_text = "# update\n"
    notes = roots["project"] / "notes.md"
    notes.write_text(notes_text, encoding="utf-8")
    skill = write_skill(
        roots["home"],
        ".codex/skills/graphify/SKILL.md",
        body=skill_text,
        version=version_text,
    )
    refs = skill.parent / "references"
    refs.mkdir()
    (refs / "query.md").write_text(query_text, encoding="utf-8")
    (refs / "update.md").write_text(update_text, encoding="utf-8")

    state = oracle.scenario_file_state(test_scenario)

    assert list(state) == [
        "project/notes.md",
        "home/.codex/skills/graphify/SKILL.md",
        "home/.codex/skills/graphify/.graphify_version",
        "home/.codex/skills/graphify/references",
        "home/.codex/skills/graphify/references.tmp",
        "home/.codex/skills/graphify/references/query.md",
        "home/.codex/skills/graphify/references/update.md",
    ]
    assert state["project/notes.md"]["kind"] == "file"
    assert state["project/notes.md"]["size"] == len(notes_text.encode("utf-8"))
    assert state["project/notes.md"]["marker_count"] == 1
    assert state["project/notes.md"]["user_content_preserved"] is True
    assert state["project/notes.md"]["sha256"] == hashlib.sha256(notes_text.encode("utf-8")).hexdigest()
    assert state["home/.codex/skills/graphify/references"]["kind"] == "dir"
    assert state["home/.codex/skills/graphify/references.tmp"] == {"exists": False}
    assert_fingerprint(state["home/.codex/skills/graphify/SKILL.md"], skill_text)
    assert_fingerprint(state["home/.codex/skills/graphify/.graphify_version"], version_text)
    assert_fingerprint(state["home/.codex/skills/graphify/references/query.md"], query_text)
    assert_fingerprint(state["home/.codex/skills/graphify/references/update.md"], update_text)


def test_uninstall_skill_sidecar_checks_require_version_references_and_tmp_removal(oracle, roots) -> None:
    test_scenario = scenario("claude", expected_skill("project", ".claude/skills/graphify/SKILL.md"))
    skill = write_skill(roots["project"], ".claude/skills/graphify/SKILL.md", version="9.9.9")
    refs = skill.parent / "references"
    refs.mkdir()
    (refs / "query.md").write_text("# query\n", encoding="utf-8")
    refs_tmp = skill.parent / "references.tmp"
    refs_tmp.mkdir()
    (refs_tmp / "partial.md").write_text("partial\n", encoding="utf-8")

    checks = oracle.assert_uninstalled(test_scenario)

    version = check_by_relative(checks, ".claude/skills/graphify/.graphify_version")
    assert version == {
        "path": str(roots["project"] / ".claude/skills/graphify/.graphify_version"),
        "ok": False,
        "detail": "sidecar_still_exists",
        "root": "project",
        "relative": ".claude/skills/graphify/.graphify_version",
    }
    assert check_by_relative(checks, ".claude/skills/graphify/references")["detail"] == "sidecar_still_exists"
    assert check_by_relative(checks, ".claude/skills/graphify/references.tmp")["detail"] == "sidecar_still_exists"

    (skill.parent / ".graphify_version").unlink()
    (refs / "query.md").unlink()
    refs.rmdir()
    (refs_tmp / "partial.md").unlink()
    refs_tmp.rmdir()

    checks = oracle.assert_uninstalled(test_scenario)

    assert check_by_relative(checks, ".claude/skills/graphify/.graphify_version") == {
        "path": str(roots["project"] / ".claude/skills/graphify/.graphify_version"),
        "ok": True,
        "detail": "removed",
        "root": "project",
        "relative": ".claude/skills/graphify/.graphify_version",
    }
    assert check_by_relative(checks, ".claude/skills/graphify/references") == {
        "path": str(roots["project"] / ".claude/skills/graphify/references"),
        "ok": True,
        "detail": "removed",
        "root": "project",
        "relative": ".claude/skills/graphify/references",
    }
    assert check_by_relative(checks, ".claude/skills/graphify/references.tmp") == {
        "path": str(roots["project"] / ".claude/skills/graphify/references.tmp"),
        "ok": True,
        "detail": "removed",
        "root": "project",
        "relative": ".claude/skills/graphify/references.tmp",
    }


def test_is_skill_sidecar_relative_matches_version_and_nested_reference_paths(oracle) -> None:
    test_scenario = scenario("aider", expected_skill("project", ".aider/graphify/SKILL.md"))

    assert oracle.is_skill_sidecar_relative(test_scenario, "project", Path(".aider/graphify/.graphify_version")) is True
    assert oracle.is_skill_sidecar_relative(test_scenario, "project", Path(".aider/graphify/references/query.md")) is True
    assert oracle.is_skill_sidecar_relative(test_scenario, "project", Path(".aider/graphify/references/nested/query.md")) is True
    assert oracle.is_skill_sidecar_relative(test_scenario, "project", Path(".aider/graphify/references.tmp/partial.md")) is True
    assert oracle.is_skill_sidecar_relative(test_scenario, "project", Path(".aider/graphify/references.tmp/nested/partial.md")) is True
    assert oracle.is_skill_sidecar_relative(test_scenario, "project", Path(".aider/graphify/notes.md")) is False
    assert oracle.is_skill_sidecar_relative(test_scenario, "home", Path(".aider/graphify/.graphify_version")) is False


def test_stale_sidecar_seed_only_targets_progressive_skills(oracle, roots) -> None:
    progressive = scenario("claude", expected_skill("project", ".claude/skills/graphify/SKILL.md"))
    monolith = scenario("aider", expected_skill("project", ".aider/graphify/SKILL.md"))

    progressive_seeded = oracle.seed_stale_skill_sidecars(progressive)
    monolith_seeded = oracle.seed_stale_skill_sidecars(monolith)

    assert progressive_seeded
    assert (roots["project"] / ".claude/skills/graphify/references/stale-sandbox-fragment.md").exists()
    assert (roots["project"] / ".claude/skills/graphify/references.tmp/partial.md").exists()
    assert monolith_seeded == []
    assert not (roots["project"] / ".aider/graphify/references").exists()


@pytest.mark.parametrize("platform", ["claude", "empty", "missing", "not_directory"])
def test_stale_sidecar_seed_targets_reference_directory_expectations(
    oracle: file_effects.FileEffectOracle,
    roots: dict[str, Path],
    platform: str,
) -> None:
    skill_relative = (
        ".claude/skills/graphify/SKILL.md"
        if platform == "claude"
        else f".{platform}/graphify/SKILL.md"
    )
    skill_dir = Path(skill_relative).parent
    entry = expected_skill("project", skill_relative)

    seeded = oracle.seed_stale_skill_sidecars(scenario(platform, entry))

    assert seeded == [
        {
            "path": str(roots["project"] / skill_dir / "references/stale-sandbox-fragment.md"),
            "ok": True,
            "detail": "seeded_stale_reference_fragment",
            "root": "project",
            "relative": (skill_dir / "references/stale-sandbox-fragment.md").as_posix(),
        },
        {
            "path": str(roots["project"] / skill_dir / "references.tmp/partial.md"),
            "ok": True,
            "detail": "seeded_staged_reference_fragment",
            "root": "project",
            "relative": (skill_dir / "references.tmp/partial.md").as_posix(),
        },
    ]
    assert (
        (roots["project"] / skill_dir / "references/stale-sandbox-fragment.md").read_text(
            encoding="utf-8"
        )
        == "stale sandbox reference fragment\n"
    )
    assert (
        (roots["project"] / skill_dir / "references.tmp/partial.md").read_text(
            encoding="utf-8"
        )
        == "partial staged reference fragment\n"
    )


@pytest.mark.parametrize("platform", ["aider", "no_eligible"])
def test_stale_sidecar_seed_skips_absent_reference_expectations(
    oracle: file_effects.FileEffectOracle,
    roots: dict[str, Path],
    platform: str,
) -> None:
    skill_relative = f".{platform}/graphify/SKILL.md"
    skill_dir = Path(skill_relative).parent

    seeded = oracle.seed_stale_skill_sidecars(
        scenario(platform, expected_skill("project", skill_relative))
    )

    assert seeded == []
    assert not (roots["project"] / skill_dir / "references").exists()
    assert not (roots["project"] / skill_dir / "references.tmp").exists()


def test_seeded_stale_section_must_be_replaced(oracle, roots) -> None:
    test_scenario = scenario("unit", section("project", "random-notes.txt", preserve_user_content=True))

    oracle.seed_user_owned_content(test_scenario)
    seeded = roots["project"] / "random-notes.txt"
    assert file_effects.USER_SENTINEL in seeded.read_text(encoding="utf-8")
    assert file_effects.STALE_GRAPHIFY_SENTINEL in seeded.read_text(encoding="utf-8")
    assert oracle.assert_expected_files(test_scenario)[0]["ok"] is False

    seeded.write_text(f"# User Notes\n\n{file_effects.USER_SENTINEL}\n\n{platform_specs.GRAPHIFY_MARKER}\nnew section\n", encoding="utf-8")
    assert oracle.assert_expected_files(test_scenario)[0]["ok"] is True


def test_text_policy_is_declared_not_inferred_from_known_file_names(oracle, roots) -> None:
    known_without_policy = ExpectedPath("project", "AGENTS.md", marker=platform_specs.GRAPHIFY_MARKER)
    declared_random_path = section("project", "not-a-platform-file.txt", preserve_user_content=True)
    test_scenario = scenario("unit", known_without_policy, declared_random_path)

    oracle.seed_user_owned_content(test_scenario)

    assert not (roots["project"] / "AGENTS.md").exists()
    assert (roots["project"] / "not-a-platform-file.txt").exists()

    (roots["project"] / "AGENTS.md").write_text(
        f"# Notes\n\n{platform_specs.GRAPHIFY_MARKER}\n{file_effects.STALE_GRAPHIFY_SENTINEL}\n",
        encoding="utf-8",
    )
    (roots["project"] / "not-a-platform-file.txt").write_text(
        f"# Notes\n\n{platform_specs.GRAPHIFY_MARKER}\n{file_effects.STALE_GRAPHIFY_SENTINEL}\n",
        encoding="utf-8",
    )

    known_check, declared_check = oracle.assert_expected_files(test_scenario)
    assert known_check["ok"] is True
    assert "stale_replaced" not in str(known_check["detail"])
    assert declared_check["ok"] is False
    assert "stale_replaced=False" in str(declared_check["detail"])


def test_legacy_expected_path_with_text_policy_dispatches_as_text_section(oracle, roots) -> None:
    legacy_text_policy = ExpectedPath(
        "project",
        "notes.txt",
        text_expectation=platform_specs.TextExpectation(preserve_user_content=True, require_user_content_on_uninstall=True),
    )
    test_scenario = scenario("unit", legacy_text_policy)

    oracle.seed_user_owned_content(test_scenario)

    assert (roots["project"] / "notes.txt").read_text(encoding="utf-8") == f"# User Notes\n\n{file_effects.USER_SENTINEL}\n"


def test_seed_user_owned_content_writes_only_declared_preserved_text_surfaces(oracle, roots) -> None:
    stale_section = section("project", "stale-notes.md", preserve_user_content=True)
    legacy_text_policy = ExpectedPath(
        "project",
        "legacy-notes.txt",
        text_expectation=platform_specs.TextExpectation(preserve_user_content=True),
    )
    no_preserve_text_section = section("project", "no-preserve.md")
    plain_surface = ExpectedPath("project", "plain.txt")
    json_surface = ExpectedPath("project", "settings.json", content_kind="json", marker="graphify")
    skill_surface = expected_skill("project", ".unit/graphify/SKILL.md")
    test_scenario = scenario(
        "unit",
        stale_section,
        legacy_text_policy,
        no_preserve_text_section,
        plain_surface,
        json_surface,
        skill_surface,
    )

    oracle.seed_user_owned_content(test_scenario)

    assert (roots["project"] / "stale-notes.md").read_text(encoding="utf-8") == (
        f"# User Notes\n\n{file_effects.USER_SENTINEL}\n\n"
        f"{platform_specs.GRAPHIFY_MARKER}\n{file_effects.STALE_GRAPHIFY_SENTINEL}\n\n"
        "## User Section\nThis section should survive Graphify install and uninstall.\n"
    )
    assert (roots["project"] / "legacy-notes.txt").read_text(encoding="utf-8") == (
        f"# User Notes\n\n{file_effects.USER_SENTINEL}\n"
    )
    assert not (roots["project"] / "no-preserve.md").exists()
    assert not (roots["project"] / "plain.txt").exists()
    assert not (roots["project"] / "settings.json").exists()
    assert not (roots["project"] / ".unit/graphify/SKILL.md").exists()


def test_uninstall_requires_seeded_user_content_to_survive(oracle, roots) -> None:
    test_scenario = scenario("unit", section("project", "random-notes.txt", preserve_user_content=True))
    oracle.seed_user_owned_content(test_scenario)
    (roots["project"] / "random-notes.txt").unlink()

    check = oracle.assert_uninstalled(test_scenario)[0]
    assert check["ok"] is False
    assert check["detail"] == "user_content_file_missing"

    (roots["project"] / "random-notes.txt").write_text("# User Notes\n", encoding="utf-8")
    check = oracle.assert_uninstalled(test_scenario)[0]
    assert check["ok"] is False
    assert "user_content_preserved=False" in str(check["detail"])


def test_json_marker_assertion_rejects_invalid_json(oracle, roots) -> None:
    test_scenario = scenario("unit", ExpectedPath("project", ".codebuddy/settings.json", content_kind="json", marker="graphify"))
    path = roots["project"] / ".codebuddy/settings.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"hooks": ["graphify",}', encoding="utf-8")

    check = oracle.assert_expected_files(test_scenario)[0]
    assert check["ok"] is False
    assert "invalid_json" in str(check["detail"])


def test_json_marker_assertion_recurses_into_valid_json(oracle, roots) -> None:
    check = json_shape_check(oracle, roots, "custom/settings.json", {"hooks": {"PreToolUse": [{"command": "graphify query"}]}})

    assert check["ok"] is True
    assert "valid_json=true" in str(check["detail"])


def test_platform_specific_json_shape_validation(oracle, roots) -> None:
    claude_valid = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo graphify context"}]},
                {"matcher": "Read|Glob", "hooks": [{"type": "command", "command": "echo graphify context"}]},
            ]
        }
    }
    assert registered_json_shape_check(oracle, roots, "claude", "project", ".claude/settings.json", claude_valid)["ok"] is True
    assert registered_json_shape_check(oracle, roots, "codebuddy", "project", ".codebuddy/settings.json", {"note": "graphify in wrong location"})["ok"] is False

    codex_valid = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "/tmp/bin/graphify hook-check"}]}]}}
    assert registered_json_shape_check(oracle, roots, "codex", "project", ".codex/hooks.json", codex_valid)["ok"] is True
    assert registered_json_shape_check(oracle, roots, "codex", "project", ".codex/hooks.json", {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "graphify query"}]}]}})["ok"] is False

    gemini_valid = {"hooks": {"BeforeTool": [{"matcher": "read_file|list_directory", "hooks": [{"type": "command", "command": "python -c 'print(\"graphify\")'"}]}]}}
    assert registered_json_shape_check(oracle, roots, "gemini", "project", ".gemini/settings.json", gemini_valid)["ok"] is True
    assert registered_json_shape_check(oracle, roots, "gemini", "project", ".gemini/settings.json", {"hooks": {"PreToolUse": [{"matcher": "read_file|list_directory", "hooks": [{"type": "command", "command": "graphify"}]}]}})["ok"] is False

    assert registered_json_shape_check(oracle, roots, "kilo", "project", ".kilo/kilo.json", {"plugin": ["file:///tmp/project/.kilo/plugins/graphify.js"]})["ok"] is True
    assert registered_json_shape_check(oracle, roots, "kilo", "project", ".kilo/kilo.json", {"plugin": ["graphify"]})["ok"] is False
    assert registered_json_shape_check(oracle, roots, "opencode", "project", ".opencode/opencode.json", {"plugin": [".opencode/plugins/graphify.js"]})["ok"] is True
    assert registered_json_shape_check(oracle, roots, "opencode", "project", ".opencode/opencode.json", {"plugin": ["file:///tmp/project/.opencode/plugins/graphify.js"]})["ok"] is False


def test_expected_path_kind_is_enforced(oracle, roots) -> None:
    test_scenario = scenario("unit", ExpectedPath("project", "AGENTS.md"))
    (roots["project"] / "AGENTS.md").mkdir()

    check = oracle.assert_expected_files(test_scenario)[0]
    assert check["ok"] is False
    assert check["detail"] == "expected_file_but_not_file"


def test_idempotency_state_detects_content_change() -> None:
    before = {
        "project/AGENTS.md": {"exists": True, "sha256": "a"},
        "project/notes.md": {"exists": True, "sha256": "same"},
    }
    after = {
        "project/AGENTS.md": {"exists": True, "sha256": "b"},
        "project/notes.md": {"exists": True, "sha256": "same"},
    }

    checks = file_effects.assert_idempotent_state(before, after)
    assert checks == [
        {"path": "project/AGENTS.md", "ok": False, "detail": "changed_after_repeat_install"},
        {"path": "project/notes.md", "ok": True, "detail": "unchanged_after_repeat_install"},
    ]
    assert file_effects.assert_idempotent_state(before, before)[0]["ok"] is True


def test_unexpected_graphify_files_render_success_and_failure_records(oracle, roots) -> None:
    expected = roots["project"] / "AGENTS.md"
    expected.write_text("## graphify\n", encoding="utf-8")
    excluded = roots["home"] / ".local/lib/python3.12/site-packages/graphify_noise.py"
    excluded.parent.mkdir(parents=True)
    excluded.write_text("graphify dependency noise\n", encoding="utf-8")
    unexpected_path = roots["project"] / "notes/graphify.md"
    unexpected_path.parent.mkdir(parents=True)
    unexpected_path.write_text("generated by graphify\n", encoding="utf-8")
    marker_only = roots["user_cwd"] / "notes.md"
    marker_only.write_text("Generated by Graphify\n", encoding="utf-8")
    test_scenario = scenario("unit", ExpectedPath("project", "AGENTS.md"))

    checks = oracle.assert_no_unexpected_graphify_files(
        test_scenario,
        phase="install",
        expected_keys={("project", "AGENTS.md"), ("user_cwd", "notes.md")},
    )

    assert checks == [
        {
            "path": str(unexpected_path),
            "ok": False,
            "detail": "unexpected_graphify_related_file_after_install",
            "root": "project",
            "relative": "notes/graphify.md",
        }
    ]

    unexpected_path.unlink()
    success = oracle.assert_no_unexpected_graphify_files(
        test_scenario,
        phase="repeat_install",
        expected_keys={("project", "AGENTS.md"), ("user_cwd", "notes.md")},
    )

    assert success == [{"path": "unexpected-graphify-files", "ok": True, "detail": "none_after_repeat_install"}]


def test_copy_generated_files_filters_relevance_and_preserves_root_relative_layout(oracle, roots, tmp_path) -> None:
    skill = roots["home"] / ".codex/skills/graphify/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# graphify skill\n", encoding="utf-8")
    (skill.parent / ".graphify_version").write_text("1.2.3", encoding="utf-8")
    refs = skill.parent / "references"
    refs.mkdir()
    (refs / "query.md").write_text("# query\n", encoding="utf-8")
    dependency = roots["home"] / ".local/lib/python3.12/site-packages/example.py"
    dependency.parent.mkdir(parents=True)
    dependency.write_text("graphify dependency noise\n", encoding="utf-8")
    shared = roots["project"] / "AGENTS.md"
    shared.write_text("## graphify\n", encoding="utf-8")
    nested = roots["project"] / "nested/graphify-output.txt"
    nested.parent.mkdir(parents=True)
    nested.write_text("generated by graphify\n", encoding="utf-8")
    unrelated = roots["project"] / "notes.md"
    unrelated.write_text("user notes\n", encoding="utf-8")
    excluded_project = roots["project"] / ".cache/graphify/cache.txt"
    excluded_project.parent.mkdir(parents=True)
    excluded_project.write_text("graphify cache\n", encoding="utf-8")
    test_scenario = Scenario(
        platform="claude",
        scope="user",
        install_command=("true",),
        uninstall_command=None,
        cwd_root="user_cwd",
        expected=(expected_skill("home", ".codex/skills/graphify/SKILL.md"),),
    )

    artifact_dir = tmp_path / "artifact"
    stale_archive = artifact_dir / "generated-files/project/stale.txt"
    stale_archive.parent.mkdir(parents=True)
    stale_archive.write_text("old archive\n", encoding="utf-8")

    oracle.copy_generated_files(test_scenario, artifact_dir)

    generated = artifact_dir / "generated-files"
    assert not stale_archive.exists()
    assert (generated / "home/.codex/skills/graphify/SKILL.md").exists()
    assert (generated / "home/.codex/skills/graphify/.graphify_version").exists()
    assert (generated / "home/.codex/skills/graphify/references/query.md").exists()
    assert (generated / "project/AGENTS.md").exists()
    assert (generated / "project/nested/graphify-output.txt").exists()
    assert not (generated / "home/.local/lib/python3.12/site-packages/example.py").exists()
    assert not (generated / "project/.cache/graphify/cache.txt").exists()
    assert not (generated / "project/notes.md").exists()


def test_copy_generated_files_keeps_walking_decisions_and_copying_in_oracle(oracle, roots, tmp_path, monkeypatch) -> None:
    included = roots["project"] / "nested/keep.txt"
    included.parent.mkdir(parents=True)
    included.write_text("generated by graphify\n", encoding="utf-8")
    skipped = roots["project"] / "nested/skip.txt"
    skipped.write_text("generated by graphify but ignored by decision\n", encoding="utf-8")
    copied: list[tuple[Path, Path]] = []

    def copy2(source, destination) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        copied.append((source_path, destination_path))
        destination_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.setattr(file_effects.shutil, "copy2", copy2)

    class RecordingCopyOracle(file_effects.FileEffectOracle):
        def __init__(self, wrapped: file_effects.FileEffectOracle) -> None:
            super().__init__(
                roots=wrapped.roots,
                packaged_reference_resolution=wrapped.packaged_reference_resolution,
                expected_graphify_version=wrapped.expected_graphify_version,
                manifest_prune_dirs=wrapped.manifest_prune_dirs,
            )
            object.__setattr__(self, "walked_roots", [])
            object.__setattr__(self, "decisions", [])

        def pruned_file_walk(self, base: Path):
            self.walked_roots.append(base)
            if base == roots["project"]:
                yield included
                yield skipped

        def generated_file_decision(
            self,
            scenario_arg,
            root_name,
            relative,
            path,
            *,
            apply_excludes,
            expected_keys=None,
        ):
            self.decisions.append(
                {
                    "scenario": scenario_arg.platform,
                    "root": root_name,
                    "relative": relative.as_posix(),
                    "path": path,
                    "apply_excludes": apply_excludes,
                    "expected_keys": expected_keys,
                }
            )
            observation = install_surface_core.GeneratedFileObservation(
                root_name=root_name,
                relative=relative,
                suffix=path.suffix,
                file_size=path.stat().st_size,
                mentions_expected_marker=False,
                expected_key=False,
                skill_sidecar_relative=False,
                excluded_path=False,
                relative_substring_match=False,
                small_text_candidate=False,
            )
            return install_surface_core.GeneratedFileDecision(
                observation,
                is_relevant=relative == Path("nested/keep.txt"),
                is_ignored=False,
            )

    recording_oracle = RecordingCopyOracle(oracle)
    archive_scenario = scenario("unit", ExpectedPath("project", "declared.txt"))
    artifact_dir = tmp_path / "artifact"

    recording_oracle.copy_generated_files(archive_scenario, artifact_dir)

    assert recording_oracle.walked_roots == [roots["home"], roots["project"], roots["user_cwd"]]
    assert recording_oracle.decisions == [
        {
            "scenario": "unit",
            "root": "project",
            "relative": "nested/keep.txt",
            "path": included,
            "apply_excludes": True,
            "expected_keys": {("project", "declared.txt")},
        },
        {
            "scenario": "unit",
            "root": "project",
            "relative": "nested/skip.txt",
            "path": skipped,
            "apply_excludes": True,
            "expected_keys": {("project", "declared.txt")},
        },
    ]
    assert copied == [
        (
            included,
            artifact_dir / "generated-files/project/nested/keep.txt",
        )
    ]
    assert (artifact_dir / "generated-files/project/nested/keep.txt").read_text(encoding="utf-8") == "generated by graphify\n"
    assert not (artifact_dir / "generated-files/project/nested/skip.txt").exists()


def test_scenario_file_effects_adapter_preserves_repeat_install_and_universal_uninstall_shapes(oracle, roots) -> None:
    def write_manifest(*args, **kwargs) -> None:
        raise AssertionError("not used")

    def equivalence_check(scenario_arg, env, artifact_dir):
        raise AssertionError("not used")

    adapter = file_effects.ScenarioFileEffectsAdapter(oracle, write_manifest, equivalence_check)
    repeat_scenario = scenario("unit", ExpectedPath("project", "AGENTS.md"))
    before = {
        "project/AGENTS.md": {"exists": True, "sha256": "a"},
        "project/notes.md": {"exists": True, "sha256": "same"},
    }
    after = {
        "project/AGENTS.md": {"exists": True, "sha256": "b"},
        "project/notes.md": {"exists": True, "sha256": "same"},
    }

    repeat_checks = adapter.repeat_install_checks(repeat_scenario, before, after, phase="repeat_install")

    assert repeat_checks == [
        {"path": "project/AGENTS.md", "ok": False, "detail": "changed_after_repeat_install"},
        {"path": "project/notes.md", "ok": True, "detail": "unchanged_after_repeat_install"},
        {"path": "unexpected-graphify-files", "ok": True, "detail": "none_after_repeat_install"},
    ]

    first = scenario("first", ExpectedPath("project", "first.md"))
    second = scenario("second", ExpectedPath("home", ".second/graphify/SKILL.md"))
    (roots["project"] / "first.md").write_text("still installed\n", encoding="utf-8")
    expected_generated = roots["home"] / ".second/graphify/SKILL.md"
    expected_generated.parent.mkdir(parents=True)
    expected_generated.write_text("expected generated path may remain\n", encoding="utf-8")
    unexpected_generated = roots["project"] / "leftover/graphify.md"
    unexpected_generated.parent.mkdir(parents=True)
    unexpected_generated.write_text("generated by graphify\n", encoding="utf-8")
    install_checks = [{"path": "install", "ok": True, "detail": "installed"}]

    universal_checks = adapter.universal_uninstall_checks(repeat_scenario, (first, second), install_checks)

    assert universal_checks == [
        {"path": "install", "ok": True, "detail": "installed"},
        {
            "path": str(roots["project"] / "first.md"),
            "ok": False,
            "detail": "still_exists",
            "root": "project",
            "relative": "first.md",
        },
        {
            "path": str(roots["home"] / ".second/graphify/SKILL.md"),
            "ok": False,
            "detail": "still_exists",
            "root": "home",
            "relative": ".second/graphify/SKILL.md",
        },
        {
            "path": str(unexpected_generated),
            "ok": False,
            "detail": "unexpected_graphify_related_file_after_universal_uninstall",
            "root": "project",
            "relative": "leftover/graphify.md",
        },
    ]


def test_scenario_file_effects_adapter_orders_universal_uninstall_check_groups(oracle) -> None:
    calls: list[tuple[object, ...]] = []

    class RecordingOracle(file_effects.FileEffectOracle):
        def __init__(self, wrapped: file_effects.FileEffectOracle) -> None:
            super().__init__(
                roots=wrapped.roots,
                packaged_reference_resolution=wrapped.packaged_reference_resolution,
                expected_graphify_version=wrapped.expected_graphify_version,
                manifest_prune_dirs=wrapped.manifest_prune_dirs,
            )

        def expected_generated_relative_keys_for_scenarios(self, scenarios):
            items = list(scenarios)
            calls.append(("expected_generated_relative_keys_for_scenarios", tuple(item.platform for item in items)))
            return {("project", "first.md"), ("home", "second.md")}

        def assert_uninstalled(self, scenario_arg):
            calls.append(("assert_uninstalled", scenario_arg.platform))
            if scenario_arg.platform == "first":
                return [
                    {"path": "first.md", "ok": True, "detail": "removed"},
                    {"path": "first-sidecar", "ok": True, "detail": "removed"},
                ]
            return [{"path": "second.md", "ok": True, "detail": "removed"}]

        def assert_no_unexpected_graphify_files(self, scenario_arg, *, phase, expected_keys=None):
            calls.append(("assert_no_unexpected_graphify_files", scenario_arg.platform, phase, expected_keys))
            return [
                {"path": "leftover.md", "ok": False, "detail": "unexpected_graphify_related_file_after_universal_uninstall"},
                {"path": "unexpected-graphify-files", "ok": True, "detail": "none_after_universal_uninstall"},
            ]

    def write_manifest(*args, **kwargs) -> None:
        raise AssertionError("not used")

    def equivalence_check(scenario_arg, env, artifact_dir):
        raise AssertionError("not used")

    adapter = file_effects.ScenarioFileEffectsAdapter(RecordingOracle(oracle), write_manifest, equivalence_check)
    runner = scenario("runner", ExpectedPath("project", "runner.md"))
    first = scenario("first", ExpectedPath("project", "first.md"))
    second = scenario("second", ExpectedPath("home", "second.md"))
    install_checks = [
        {"path": "first-install", "ok": True, "detail": "installed"},
        {"path": "second-install", "ok": True, "detail": "installed"},
    ]

    assert adapter.universal_uninstall_checks(runner, (first, second), install_checks) == [
        {"path": "first-install", "ok": True, "detail": "installed"},
        {"path": "second-install", "ok": True, "detail": "installed"},
        {"path": "first.md", "ok": True, "detail": "removed"},
        {"path": "first-sidecar", "ok": True, "detail": "removed"},
        {"path": "second.md", "ok": True, "detail": "removed"},
        {"path": "leftover.md", "ok": False, "detail": "unexpected_graphify_related_file_after_universal_uninstall"},
        {"path": "unexpected-graphify-files", "ok": True, "detail": "none_after_universal_uninstall"},
    ]
    assert calls == [
        ("expected_generated_relative_keys_for_scenarios", ("first", "second")),
        ("assert_uninstalled", "first"),
        ("assert_uninstalled", "second"),
        (
            "assert_no_unexpected_graphify_files",
            "runner",
            "universal_uninstall",
            {("project", "first.md"), ("home", "second.md")},
        ),
    ]


def test_scenario_file_effects_adapter_pins_delegation_boundaries(oracle, roots, tmp_path) -> None:
    calls: list[tuple[object, ...]] = []

    class RecordingOracle(file_effects.FileEffectOracle):
        def __init__(self, wrapped: file_effects.FileEffectOracle) -> None:
            super().__init__(
                roots=wrapped.roots,
                packaged_reference_resolution=wrapped.packaged_reference_resolution,
                expected_graphify_version=wrapped.expected_graphify_version,
                manifest_prune_dirs=wrapped.manifest_prune_dirs,
            )

        def seed_user_owned_content(self, scenario_arg):
            calls.append(("seed_user_owned_content", scenario_arg.platform))

        def scenario_file_state(self, scenario_arg):
            calls.append(("scenario_file_state", scenario_arg.platform))
            return {"state": {"exists": True}}

        def assert_expected_files(self, scenario_arg):
            calls.append(("assert_expected_files", scenario_arg.platform))
            return [{"path": "expected", "ok": True, "detail": "expected"}]

        def assert_scope_boundaries(self, scenario_arg):
            calls.append(("assert_scope_boundaries", scenario_arg.platform))
            return [{"path": "scope", "ok": True, "detail": "scope"}]

        def assert_no_unexpected_graphify_files(self, scenario_arg, *, phase, expected_keys=None):
            calls.append(("assert_no_unexpected_graphify_files", scenario_arg.platform, phase, expected_keys))
            return [{"path": "unexpected", "ok": True, "detail": f"none_after_{phase}"}]

        def copy_generated_files(self, scenario_arg, artifact_dir):
            calls.append(("copy_generated_files", scenario_arg.platform, artifact_dir))

        def seed_stale_skill_sidecars(self, scenario_arg):
            calls.append(("seed_stale_skill_sidecars", scenario_arg.platform))
            return [{"path": "stale", "ok": True, "detail": "seeded_stale_reference_fragment"}]

        def assert_installed_skill_sidecars(self, scenario_arg):
            calls.append(("assert_installed_skill_sidecars", scenario_arg.platform))
            return [{"path": "sidecars", "ok": True, "detail": "sidecars"}]

        def assert_uninstalled(self, scenario_arg):
            calls.append(("assert_uninstalled", scenario_arg.platform))
            return [{"path": f"uninstalled-{scenario_arg.platform}", "ok": True, "detail": "removed"}]

        def expected_generated_relative_keys_for_scenarios(self, scenarios):
            items = list(scenarios)
            calls.append(("expected_generated_relative_keys_for_scenarios", tuple(item.platform for item in items)))
            return {("project", "expected-generated.md")}

    def write_manifest(path, roots_arg, **kwargs) -> None:
        calls.append(("write_manifest", path, roots_arg, kwargs))

    def equivalence_check(scenario_arg, env, artifact_dir):
        calls.append(("equivalence_check", scenario_arg.platform, env, artifact_dir))
        return [{"path": "equivalence", "ok": True, "detail": "equivalent"}]

    recording_oracle = RecordingOracle(oracle)
    adapter = file_effects.ScenarioFileEffectsAdapter(recording_oracle, write_manifest, equivalence_check)
    adapter_scenario = scenario("unit", ExpectedPath("project", "AGENTS.md"))
    artifact_dir = tmp_path / "artifact"
    manifest_path = tmp_path / "manifest.json"

    assert adapter.seed_scenario_inputs(adapter_scenario) is None
    adapter.write_manifest(manifest_path, roots, scenario=adapter_scenario)
    assert adapter.capture_state(adapter_scenario) == {"state": {"exists": True}}
    assert adapter.install_checks(adapter_scenario) == [
        {"path": "expected", "ok": True, "detail": "expected"},
        {"path": "scope", "ok": True, "detail": "scope"},
    ]
    assert adapter.unexpected_checks(adapter_scenario, phase="install") == [
        {"path": "unexpected", "ok": True, "detail": "none_after_install"}
    ]
    assert adapter.archive_generated_files(adapter_scenario, artifact_dir) is None
    assert adapter.repeat_install_checks(
        adapter_scenario,
        {"project/AGENTS.md": {"exists": True, "sha256": "a"}},
        {"project/AGENTS.md": {"exists": True, "sha256": "a"}},
        phase="repeat_install",
    ) == [
        {"path": "project/AGENTS.md", "ok": True, "detail": "unchanged_after_repeat_install"},
        {"path": "unexpected", "ok": True, "detail": "none_after_repeat_install"},
    ]
    assert adapter.seed_stale_sidecar_repair(adapter_scenario) == [
        {"path": "stale", "ok": True, "detail": "seeded_stale_reference_fragment"}
    ]
    assert adapter.stale_sidecar_repair_checks(adapter_scenario, phase="stale_sidecar_repair") == [
        {"path": "sidecars", "ok": True, "detail": "sidecars"},
        {"path": "unexpected", "ok": True, "detail": "none_after_stale_sidecar_repair"},
    ]
    assert adapter.uninstall_checks(adapter_scenario, phase="uninstall") == [
        {"path": "uninstalled-unit", "ok": True, "detail": "removed"},
        {"path": "unexpected", "ok": True, "detail": "none_after_uninstall"},
    ]
    assert adapter.equivalence_checks(adapter_scenario, {"HOME": str(roots["home"])}, artifact_dir) == [
        {"path": "equivalence", "ok": True, "detail": "equivalent"}
    ]
    assert adapter.universal_uninstall_checks(
        adapter_scenario,
        (scenario("first", ExpectedPath("project", "first.md")), scenario("second", ExpectedPath("home", "second.md"))),
        [{"path": "install", "ok": True, "detail": "installed"}],
    ) == [
        {"path": "install", "ok": True, "detail": "installed"},
        {"path": "uninstalled-first", "ok": True, "detail": "removed"},
        {"path": "uninstalled-second", "ok": True, "detail": "removed"},
        {"path": "unexpected", "ok": True, "detail": "none_after_universal_uninstall"},
    ]
    assert adapter.disposable_artifact_checks(roots["project"] / "graphify-out", removed=True) == [
        {"path": str(roots["project"] / "graphify-out"), "ok": True, "detail": "removed"}
    ]

    assert calls == [
        ("seed_user_owned_content", "unit"),
        ("write_manifest", manifest_path, roots, {"scenario": adapter_scenario}),
        ("scenario_file_state", "unit"),
        ("assert_expected_files", "unit"),
        ("assert_scope_boundaries", "unit"),
        ("assert_no_unexpected_graphify_files", "unit", "install", None),
        ("copy_generated_files", "unit", artifact_dir),
        ("assert_no_unexpected_graphify_files", "unit", "repeat_install", None),
        ("seed_stale_skill_sidecars", "unit"),
        ("assert_installed_skill_sidecars", "unit"),
        ("assert_no_unexpected_graphify_files", "unit", "stale_sidecar_repair", None),
        ("assert_uninstalled", "unit"),
        ("assert_no_unexpected_graphify_files", "unit", "uninstall", None),
        ("equivalence_check", "unit", {"HOME": str(roots["home"])}, artifact_dir),
        ("expected_generated_relative_keys_for_scenarios", ("first", "second")),
        ("assert_uninstalled", "first"),
        ("assert_uninstalled", "second"),
        (
            "assert_no_unexpected_graphify_files",
            "unit",
            "universal_uninstall",
            {("project", "expected-generated.md")},
        ),
    ]


def test_scenario_file_effects_adapter_preserves_setup_method_shapes(oracle) -> None:
    class RecordingOracle(file_effects.FileEffectOracle):
        def __init__(self, wrapped: file_effects.FileEffectOracle) -> None:
            super().__init__(
                roots=wrapped.roots,
                packaged_reference_resolution=wrapped.packaged_reference_resolution,
                expected_graphify_version=wrapped.expected_graphify_version,
                manifest_prune_dirs=wrapped.manifest_prune_dirs,
            )
            object.__setattr__(self, "calls", [])

        def seed_user_owned_content(self, scenario_arg):
            self.calls.append(("seed_user_owned_content", scenario_arg.platform))

        def seed_stale_skill_sidecars(self, scenario_arg):
            self.calls.append(("seed_stale_skill_sidecars", scenario_arg.platform))
            return [{"ok": True, "detail": "seeded_stale_reference_fragment"}]

    def write_manifest(*args, **kwargs) -> None:
        raise AssertionError("not used")

    def equivalence_check(scenario_arg, env, artifact_dir):
        raise AssertionError("not used")

    recording_oracle = RecordingOracle(oracle)
    adapter = file_effects.ScenarioFileEffectsAdapter(recording_oracle, write_manifest, equivalence_check)
    setup_scenario = scenario("unit", ExpectedPath("project", "AGENTS.md"))

    assert adapter.seed_scenario_inputs(setup_scenario) is None
    assert adapter.seed_stale_sidecar_repair(setup_scenario) == [
        {"ok": True, "detail": "seeded_stale_reference_fragment"}
    ]
    assert recording_oracle.calls == [
        ("seed_user_owned_content", "unit"),
        ("seed_stale_skill_sidecars", "unit"),
    ]


def test_universal_uninstall_aggregates_expected_keys_through_oracle(oracle, roots) -> None:
    def write_manifest(*args, **kwargs) -> None:
        raise AssertionError("not used")

    def equivalence_check(scenario_arg, env, artifact_dir):
        raise AssertionError("not used")

    class RecordingOracle(file_effects.FileEffectOracle):
        def __init__(self, wrapped: file_effects.FileEffectOracle) -> None:
            super().__init__(
                roots=wrapped.roots,
                packaged_reference_resolution=wrapped.packaged_reference_resolution,
                expected_graphify_version=wrapped.expected_graphify_version,
                manifest_prune_dirs=wrapped.manifest_prune_dirs,
            )
            object.__setattr__(self, "aggregate_calls", [])

        def expected_generated_relative_keys_for_scenarios(self, scenarios):
            items = list(scenarios)
            self.aggregate_calls.append([item.platform for item in items])
            return super().expected_generated_relative_keys_for_scenarios(items)

    recording_oracle = RecordingOracle(oracle)
    adapter = file_effects.ScenarioFileEffectsAdapter(recording_oracle, write_manifest, equivalence_check)
    runner = scenario("unit", ExpectedPath("project", "runner.md"))
    installed = (
        scenario("first", ExpectedPath("project", "first.md")),
        scenario("second", ExpectedPath("home", ".second/graphify/SKILL.md")),
    )
    (roots["project"] / "leftover/graphify.md").parent.mkdir(parents=True)
    (roots["project"] / "leftover/graphify.md").write_text("generated by graphify\n", encoding="utf-8")

    adapter.universal_uninstall_checks(runner, installed, [])

    assert recording_oracle.aggregate_calls == [["first", "second"]]
