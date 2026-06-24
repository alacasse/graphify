from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tools.install_sandbox.effects import file_effect_generated_artifacts
from tools.install_sandbox.effects import file_effect_oracle
from tools.install_sandbox.effects import file_effect_sidecars
from tools.install_sandbox.effects import file_effect_state
from tools.install_sandbox import platform_specs
from tools.install_sandbox.platform_specs import InstallSurface, Scenario
from tools.install_sandbox.reference_resolution import PackagedReferenceResolution

from install_target_test_support import expected_entry, scenario_for

# Sandbox sidecar records live here. Direct sidecar status and path-planning
# decisions remain in test_install_surface_core_sidecars.py.


@pytest.fixture
def roots(tmp_path) -> dict[str, Path]:
    paths = {"home": tmp_path / "home", "project": tmp_path / "project", "user_cwd": tmp_path / "user-cwd"}
    for path in paths.values():
        path.mkdir(parents=True)
    return paths


def resolution(status: str, names: tuple[str, ...] = (), detail: str = "test detail") -> PackagedReferenceResolution:
    return PackagedReferenceResolution(status, expected_names=names, detail=detail)


@pytest.fixture
def oracle(roots) -> file_effect_oracle.FileEffectOracle:
    def packaged_reference_resolution(platform: str) -> PackagedReferenceResolution:
        if platform == "agents":
            return resolution("available", ("query.md", "update.md"), "agents refs")
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

    return file_effect_oracle.FileEffectOracle(
        roots=roots,
        packaged_reference_resolution=packaged_reference_resolution,
        expected_graphify_version=lambda: "9.9.9",
        manifest_prune_dirs=set(file_effect_generated_artifacts.GENERATED_COPY_EXCLUDES),
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


def test_agents_skill_surface_uses_standard_progressive_sidecar_records(oracle, roots) -> None:
    test_scenario = scenario_for("agents", "project")
    skill = write_skill(
        roots["project"],
        ".agents/skills/graphify/SKILL.md",
        body="See references/query.md and references/update.md for details.\n",
        version="9.9.9",
    )
    refs = skill.parent / "references"
    refs.mkdir()
    (refs / "query.md").write_text("# query\n", encoding="utf-8")
    (refs / "update.md").write_text("# update\n", encoding="utf-8")

    checks = oracle.assert_expected_files(test_scenario)

    assert check_by_relative(checks, ".agents/skills/graphify/.graphify_version")["detail"] == "actual=9.9.9; expected=9.9.9"
    assert check_by_relative(checks, ".agents/skills/graphify/references.tmp")["detail"] == "absent"
    assert "actual_names=['query.md', 'update.md']" in str(check_by_relative(checks, ".agents/skills/graphify/references")["detail"])


def test_agents_amp_and_antigravity_keep_distinct_agents_surface_facts() -> None:
    agents_user = expected_entry("agents", "user", "home", ".agents/skills/graphify/SKILL.md")
    amp_user = expected_entry("amp", "user", "home", ".config/agents/skills/graphify/SKILL.md")
    amp_project = expected_entry("amp", "project", "project", ".agents/skills/graphify/SKILL.md")
    antigravity_project_skill = expected_entry("antigravity", "project", "project", ".agents/skills/graphify/SKILL.md")
    antigravity_rules = expected_entry("antigravity", "project", "project", ".agents/rules/graphify.md")
    antigravity_workflow = expected_entry("antigravity", "project", "project", ".agents/workflows/graphify.md")

    assert agents_user.skill_sidecar_expectation == platform_specs.SkillSidecarExpectation()
    assert amp_user.skill_sidecar_expectation == platform_specs.SkillSidecarExpectation()
    assert amp_project.skill_sidecar_expectation == platform_specs.SkillSidecarExpectation()
    assert antigravity_project_skill.skill_sidecar_expectation == platform_specs.SkillSidecarExpectation()
    assert amp_user.relative != agents_user.relative
    assert antigravity_rules.skill_sidecar_expectation is None
    assert antigravity_workflow.skill_sidecar_expectation is None


def test_sidecar_topic_module_renders_installed_skill_records(oracle, roots) -> None:
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

    assert file_effect_sidecars.assert_installed_skill_sidecars(
        test_scenario,
        roots,
        oracle.packaged_reference_resolution,
        oracle.expected_graphify_version,
    ) == oracle.assert_installed_skill_sidecars(test_scenario)


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


@pytest.mark.parametrize(
    ("platform", "skill_relative", "state_relatives"),
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
        ),
        (
            "aider",
            ".aider/graphify/SKILL.md",
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
        ),
    ],
)
def test_sidecar_idempotency_state_tracks_packaged_reference_status(
    oracle: file_effect_oracle.FileEffectOracle,
    roots: dict[str, Path],
    platform: str,
    skill_relative: str,
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
    notes_text = f"# Notes\n\n{file_effect_state.USER_SENTINEL}\n\n{platform_specs.GRAPHIFY_MARKER}\ninstalled\n"
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
    oracle: file_effect_oracle.FileEffectOracle,
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
    oracle: file_effect_oracle.FileEffectOracle,
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
