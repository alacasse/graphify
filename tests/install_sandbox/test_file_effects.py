from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.install_sandbox import file_effects
from tools.install_sandbox.platform_specs import ExpectedPath, Scenario
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


def scenario(platform: str, *expected: ExpectedPath, scope: str = "project") -> Scenario:
    return Scenario(
        platform=platform,
        scope=scope,
        install_command=("true",),
        uninstall_command=None,
        cwd_root="project" if scope == "project" else "user_cwd",
        expected=expected,
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
    test_scenario = scenario("unit", ExpectedPath("project", relative, marker="graphify"))
    path = roots["project"] / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return oracle.assert_expected_files(test_scenario)[0]


def test_assertion_detects_missing_file(oracle) -> None:
    checks = oracle.assert_expected_files(scenario("unit", ExpectedPath("project", "missing.txt")))

    assert len(checks) == 1
    assert checks[0]["ok"] is False
    assert checks[0]["detail"] == "missing"


def test_skill_assertion_detects_missing_and_wrong_version_stamp(oracle, roots) -> None:
    missing_version = scenario("aider", ExpectedPath("project", ".aider/graphify/SKILL.md"))
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
    test_scenario = scenario("aider", ExpectedPath("project", ".aider/graphify/SKILL.md"))
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


def test_skill_assertion_detects_references_tmp(oracle, roots) -> None:
    test_scenario = scenario("aider", ExpectedPath("project", ".aider/graphify/SKILL.md"))
    skill = write_skill(roots["project"], ".aider/graphify/SKILL.md", version="9.9.9")
    (skill.parent / "references.tmp").mkdir()

    tmp_check = check_by_relative(oracle.assert_expected_files(test_scenario), ".aider/graphify/references.tmp")
    assert tmp_check["ok"] is False
    assert tmp_check["detail"] == "present"


def test_skill_assertion_detects_extra_and_missing_packaged_reference_fragments(oracle, roots) -> None:
    test_scenario = scenario("claude", ExpectedPath("project", ".claude/skills/graphify/SKILL.md"))
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
    test_scenario = scenario("aider", ExpectedPath("project", ".aider/graphify/SKILL.md"))
    skill = write_skill(roots["project"], ".aider/graphify/SKILL.md", version="9.9.9")
    refs = skill.parent / "references"
    refs.mkdir()
    (refs / "leftover.md").write_text("leftover\n", encoding="utf-8")

    refs_check = check_by_relative(oracle.assert_expected_files(test_scenario), ".aider/graphify/references")
    assert refs_check["ok"] is False
    assert "intentionally_absent" in str(refs_check["detail"])


def test_absent_packaged_reference_statuses_pass_when_references_absent(oracle, roots) -> None:
    for platform in ("aider", "no_eligible"):
        test_scenario = scenario(platform, ExpectedPath("project", f".{platform}/graphify/SKILL.md"))
        write_skill(roots["project"], f".{platform}/graphify/SKILL.md", version="9.9.9")

        refs_check = check_by_relative(oracle.assert_expected_files(test_scenario), f".{platform}/graphify/references")

        expected_status = "intentionally_absent" if platform == "aider" else "no_eligible_bundle"
        assert refs_check["ok"] is True
        assert expected_status in str(refs_check["detail"])


def test_no_eligible_bundle_fails_when_references_present(oracle, roots) -> None:
    test_scenario = scenario("no_eligible", ExpectedPath("project", ".no_eligible/graphify/SKILL.md"))
    skill = write_skill(roots["project"], ".no_eligible/graphify/SKILL.md", version="9.9.9")
    refs = skill.parent / "references"
    refs.mkdir()
    (refs / "leftover.md").write_text("leftover\n", encoding="utf-8")

    refs_check = check_by_relative(oracle.assert_expected_files(test_scenario), ".no_eligible/graphify/references")

    assert refs_check["ok"] is False
    assert "no_eligible_bundle" in str(refs_check["detail"])


def test_empty_packaged_references_requires_empty_installed_directory(oracle, roots) -> None:
    test_scenario = scenario("empty", ExpectedPath("project", ".empty/graphify/SKILL.md"))
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
        test_scenario = scenario(platform, ExpectedPath("project", f".{platform}/graphify/SKILL.md"))
        write_skill(roots["project"], f".{platform}/graphify/SKILL.md", version="9.9.9")

        refs_check = check_by_relative(oracle.assert_expected_files(test_scenario), f".{platform}/graphify/references")

        assert refs_check["ok"] is False
        assert platform in str(refs_check["detail"])
        assert "/package/refs" in str(refs_check["detail"])


def test_reference_resolution_status_controls_manifest_generated_keys_and_state(oracle, roots) -> None:
    skill_entry = ExpectedPath("project", ".claude/skills/graphify/SKILL.md")
    available = scenario("claude", skill_entry)
    empty = scenario("empty", ExpectedPath("project", ".empty/graphify/SKILL.md"))
    absent = scenario("aider", ExpectedPath("project", ".aider/graphify/SKILL.md"))

    available_manifest = oracle.expected_manifest_relatives(available, "project")
    assert Path(".claude/skills/graphify/references") in available_manifest
    assert Path(".claude/skills/graphify/references/query.md") in available_manifest
    assert ("project", ".claude/skills/graphify/references/update.md") in oracle.expected_generated_relative_keys(available)
    assert "project/.claude/skills/graphify/references/query.md" in oracle.scenario_file_state(available)

    empty_manifest = oracle.expected_manifest_relatives(empty, "project")
    assert Path(".empty/graphify/references") in empty_manifest
    assert not any(path.name.endswith(".md") and "references" in path.parts for path in empty_manifest)
    assert ("project", ".empty/graphify/references") in oracle.expected_generated_relative_keys(empty)
    assert "project/.empty/graphify/references" in oracle.scenario_file_state(empty)

    absent_manifest = oracle.expected_manifest_relatives(absent, "project")
    absent_generated_keys = oracle.expected_generated_relative_keys(absent)
    assert Path(".aider/graphify/references") not in absent_manifest
    assert ("project", ".aider/graphify/references") not in absent_generated_keys
    assert not any(key[1].startswith(".aider/graphify/references/") for key in absent_generated_keys)
    assert "project/.aider/graphify/references" not in oracle.scenario_file_state(absent)


def test_stale_sidecar_seed_only_targets_progressive_skills(oracle, roots) -> None:
    progressive = scenario("claude", ExpectedPath("project", ".claude/skills/graphify/SKILL.md"))
    monolith = scenario("aider", ExpectedPath("project", ".aider/graphify/SKILL.md"))

    progressive_seeded = oracle.seed_stale_skill_sidecars(progressive)
    monolith_seeded = oracle.seed_stale_skill_sidecars(monolith)

    assert progressive_seeded
    assert (roots["project"] / ".claude/skills/graphify/references/stale-sandbox-fragment.md").exists()
    assert (roots["project"] / ".claude/skills/graphify/references.tmp/partial.md").exists()
    assert monolith_seeded == []
    assert not (roots["project"] / ".aider/graphify/references").exists()


def test_seeded_stale_section_must_be_replaced(oracle, roots) -> None:
    test_scenario = scenario("unit", ExpectedPath("project", "AGENTS.md", marker=file_effects.GRAPHIFY_MARKER))

    oracle.seed_user_owned_content(test_scenario)
    seeded = roots["project"] / "AGENTS.md"
    assert file_effects.USER_SENTINEL in seeded.read_text(encoding="utf-8")
    assert file_effects.STALE_GRAPHIFY_SENTINEL in seeded.read_text(encoding="utf-8")
    assert oracle.assert_expected_files(test_scenario)[0]["ok"] is False

    seeded.write_text(f"# User Notes\n\n{file_effects.USER_SENTINEL}\n\n{file_effects.GRAPHIFY_MARKER}\nnew section\n", encoding="utf-8")
    assert oracle.assert_expected_files(test_scenario)[0]["ok"] is True


def test_uninstall_requires_seeded_user_content_to_survive(oracle, roots) -> None:
    test_scenario = scenario("unit", ExpectedPath("project", "AGENTS.md", marker=file_effects.GRAPHIFY_MARKER))
    oracle.seed_user_owned_content(test_scenario)
    (roots["project"] / "AGENTS.md").unlink()

    check = oracle.assert_uninstalled(test_scenario)[0]
    assert check["ok"] is False
    assert check["detail"] == "user_content_file_missing"

    (roots["project"] / "AGENTS.md").write_text("# User Notes\n", encoding="utf-8")
    check = oracle.assert_uninstalled(test_scenario)[0]
    assert check["ok"] is False
    assert "user_content_preserved=False" in str(check["detail"])


def test_json_marker_assertion_rejects_invalid_json(oracle, roots) -> None:
    test_scenario = scenario("unit", ExpectedPath("project", ".codebuddy/settings.json", marker="graphify"))
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
    assert json_shape_check(oracle, roots, ".claude/settings.json", claude_valid)["ok"] is True
    assert json_shape_check(oracle, roots, ".codebuddy/settings.json", {"note": "graphify in wrong location"})["ok"] is False

    codex_valid = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "/tmp/bin/graphify hook-check"}]}]}}
    assert json_shape_check(oracle, roots, ".codex/hooks.json", codex_valid)["ok"] is True
    assert json_shape_check(oracle, roots, ".codex/hooks.json", {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "graphify query"}]}]}})["ok"] is False

    gemini_valid = {"hooks": {"BeforeTool": [{"matcher": "read_file|list_directory", "hooks": [{"type": "command", "command": "python -c 'print(\"graphify\")'"}]}]}}
    assert json_shape_check(oracle, roots, ".gemini/settings.json", gemini_valid)["ok"] is True
    assert json_shape_check(oracle, roots, ".gemini/settings.json", {"hooks": {"PreToolUse": [{"matcher": "read_file|list_directory", "hooks": [{"type": "command", "command": "graphify"}]}]}})["ok"] is False

    assert json_shape_check(oracle, roots, ".kilo/kilo.json", {"plugin": ["file:///tmp/project/.kilo/plugins/graphify.js"]})["ok"] is True
    assert json_shape_check(oracle, roots, ".kilo/kilo.json", {"plugin": ["graphify"]})["ok"] is False
    assert json_shape_check(oracle, roots, ".opencode/opencode.json", {"plugin": [".opencode/plugins/graphify.js"]})["ok"] is True
    assert json_shape_check(oracle, roots, ".opencode/opencode.json", {"plugin": ["file:///tmp/project/.opencode/plugins/graphify.js"]})["ok"] is False


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
        expected=(ExpectedPath("home", ".codex/skills/graphify/SKILL.md"),),
    )

    artifact_dir = tmp_path / "artifact"
    oracle.copy_generated_files(test_scenario, artifact_dir)

    generated = artifact_dir / "generated-files"
    assert (generated / "home/.codex/skills/graphify/SKILL.md").exists()
    assert (generated / "home/.codex/skills/graphify/.graphify_version").exists()
    assert (generated / "project/AGENTS.md").exists()
    assert not (generated / "home/.local/lib/python3.12/site-packages/example.py").exists()
    assert not (generated / "project/notes.md").exists()
