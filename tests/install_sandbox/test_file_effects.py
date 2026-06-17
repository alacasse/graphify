from __future__ import annotations

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
    expectation = file_effects.ReferenceSidecarExpectation.from_resolution(resolution(status, names))

    assert expectation.expected_relatives(Path(".unit/graphify"), platform_specs.SkillSidecarExpectation()) == {Path(relative) for relative in expected_relatives}


def test_reference_sidecar_expectation_validates_installed_status_matrix(tmp_path: Path) -> None:
    def installed_reference_names(refs_dir: Path) -> list[str]:
        return sorted(path.name for path in refs_dir.glob("*.md") if path.is_file())

    refs_dir = tmp_path / "references"
    absent = file_effects.ReferenceSidecarExpectation.from_resolution(resolution("intentionally_absent", detail="absent refs"))
    ok, detail = absent.check_installed(refs_dir, installed_reference_names)
    assert ok is True
    assert detail == "intentionally_absent; references_absent; absent refs"

    refs_dir.mkdir()
    ok, detail = absent.check_installed(refs_dir, installed_reference_names)
    assert ok is False
    assert detail == "intentionally_absent; references_present; absent refs"

    source_error = file_effects.ReferenceSidecarExpectation.from_resolution(resolution("missing", detail="missing /package/refs"))
    ok, detail = source_error.check_installed(refs_dir, installed_reference_names)
    assert ok is False
    assert detail == "missing; missing /package/refs"

    expected = file_effects.ReferenceSidecarExpectation.from_resolution(resolution("available", ("query.md",), "available refs"))
    ok, detail = expected.check_installed(refs_dir, installed_reference_names)
    assert ok is False
    assert "missing=['query.md']" in detail

    (refs_dir / "query.md").write_text("query\n", encoding="utf-8")
    ok, detail = expected.check_installed(refs_dir, installed_reference_names)
    assert ok is True
    assert "status=available" in detail


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
    available = scenario("claude", skill_entry)
    empty = scenario("empty", expected_skill("project", ".empty/graphify/SKILL.md"))
    absent = scenario("aider", expected_skill("project", ".aider/graphify/SKILL.md"))

    available_manifest = oracle.expected_manifest_relatives(available, "project")
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
    before = {"project/AGENTS.md": {"exists": True, "sha256": "a"}}
    after = {"project/AGENTS.md": {"exists": True, "sha256": "b"}}

    checks = file_effects.assert_idempotent_state(before, after)
    assert checks[0]["ok"] is False
    assert file_effects.assert_idempotent_state(before, before)[0]["ok"] is True


def test_generated_files_filtering(oracle, roots, tmp_path) -> None:
    skill = roots["home"] / ".codex/skills/graphify/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# graphify skill\n", encoding="utf-8")
    (skill.parent / ".graphify_version").write_text("1.2.3", encoding="utf-8")
    dependency = roots["home"] / ".local/lib/python3.12/site-packages/example.py"
    dependency.parent.mkdir(parents=True)
    dependency.write_text("graphify dependency noise\n", encoding="utf-8")
    shared = roots["project"] / "AGENTS.md"
    shared.write_text("## graphify\n", encoding="utf-8")
    unrelated = roots["project"] / "notes.md"
    unrelated.write_text("user notes\n", encoding="utf-8")
    test_scenario = Scenario(
        platform="codex",
        scope="user",
        install_command=("true",),
        uninstall_command=None,
        cwd_root="user_cwd",
        expected=(expected_skill("home", ".codex/skills/graphify/SKILL.md"),),
    )

    artifact_dir = tmp_path / "artifact"
    oracle.copy_generated_files(test_scenario, artifact_dir)

    generated = artifact_dir / "generated-files"
    assert (generated / "home/.codex/skills/graphify/SKILL.md").exists()
    assert (generated / "home/.codex/skills/graphify/.graphify_version").exists()
    assert (generated / "project/AGENTS.md").exists()
    assert not (generated / "home/.local/lib/python3.12/site-packages/example.py").exists()
    assert not (generated / "project/notes.md").exists()
