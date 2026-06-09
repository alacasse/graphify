#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path


HARNESS_DIR = Path(__file__).resolve().parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = load_module("graphify_sandbox_runner", HARNESS_DIR / "sandbox_runner.py")
host = load_module("graphify_sandbox_host", HARNESS_DIR / "run.py")


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


@contextmanager
def patched_roots():
    old_roots = runner.ROOTS.copy()
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        roots = {"home": base / "home", "project": base / "project", "user_cwd": base / "user-cwd"}
        for root in roots.values():
            root.mkdir(parents=True)
        runner.ROOTS.clear()
        runner.ROOTS.update(roots)
        try:
            yield roots
        finally:
            runner.ROOTS.clear()
            runner.ROOTS.update(old_roots)


def test_scenario_id() -> None:
    assert_true(runner.scenario_id("trae-cn", "project") == "trae-cn-project", "scenario id should preserve safe hyphens")
    assert_true(runner.scenario_id("Bad Platform!", "User Scope") == "bad-platform-user-scope", "scenario id should sanitize unsafe chars")
    assert_true(runner.scenario_id("...", "___") == "scenario", "scenario id should fallback safely")


def test_expected_path_manifest_logic() -> None:
    user = runner.make_scenario("codex", "user")
    project = runner.make_scenario("codex", "project")
    assert_true(user is not None, "codex user scenario should exist")
    assert_true(project is not None, "codex project scenario should exist")
    assert_true(any(entry.root == "home" and entry.relative == ".codex/skills/graphify/SKILL.md" for entry in user.expected), "codex user skill path should be under home")
    assert_true(any(entry.root == "project" and entry.relative == ".codex/skills/graphify/SKILL.md" for entry in project.expected), "codex project skill path should be under project")
    assert_true(any(entry.root == "project" and entry.relative == ".codex/hooks.json" for entry in project.expected), "codex project hook should remain separate from skill path")
    codebuddy = runner.make_scenario("codebuddy", "project")
    assert_true(codebuddy is not None, "codebuddy project scenario should exist")
    assert_true(any(entry.relative == "CODEBUDDY.md" for entry in codebuddy.expected), "codebuddy project scenario should assert CODEBUDDY.md")
    assert_true(any(entry.relative == ".codebuddy/settings.json" for entry in codebuddy.expected), "codebuddy project scenario should assert settings hook")
    both = runner.platform_scenarios("cursor", "both")
    assert_true([scenario.scope for scenario in both] == ["project"], "cursor coverage should be project-only")


def test_registry_mirrors_install_surface() -> None:
    from graphify import __main__ as graphify_main

    cli_platforms = set(graphify_main._PLATFORM_CONFIG) | {"gemini", "cursor", "vscode"}
    assert_true(set(runner.ALL_PLATFORMS) == cli_platforms, "sandbox registry should mirror CLI install platforms")


def test_every_scope_is_runnable_or_explained() -> None:
    for platform_name in runner.ALL_PLATFORMS:
        for scope in ("user", "project"):
            scenario = runner.make_scenario(platform_name, scope)
            reason = runner.unsupported_scope_reason(platform_name, scope)
            assert_true((scenario is not None) != (reason is not None), f"{platform_name}/{scope} should have exactly one scenario or unsupported reason")
            if scenario is not None:
                assert_true(scenario.expected, f"{platform_name}/{scope} should assert at least one file effect")


def test_sandbox_registry_defines_all_platforms() -> None:
    specs = runner.sandbox_platform_specs()
    assert_true(list(specs) == runner.ALL_PLATFORMS, "ALL_PLATFORMS should be derived from the sandbox registry order")
    for platform_name, spec in specs.items():
        assert_true(spec.name == platform_name, f"{platform_name} registry key and spec name should match")
        assert_true(bool(spec.scopes or spec.unsupported_scopes), f"{platform_name} should define runnable or unsupported scopes")


def test_make_scenario_projects_registry_scope_specs() -> None:
    for platform_name in ("claude", "codex", "codebuddy", "kilo", "vscode", "antigravity", "windows"):
        spec = runner.platform_spec(platform_name)
        for scope, scope_spec in spec.scopes.items():
            scenario = runner.make_scenario(platform_name, scope)
            assert_true(scenario is not None, f"{platform_name}/{scope} should project to a scenario")
            assert_true(scenario.install_command == scope_spec.install_command, f"{platform_name}/{scope} install command should come from registry")
            assert_true(scenario.uninstall_command == scope_spec.uninstall_command, f"{platform_name}/{scope} uninstall command should come from registry")
            assert_true(scenario.cwd_root == scope_spec.cwd_root, f"{platform_name}/{scope} cwd root should come from registry")
            assert_true(scenario.expected == scope_spec.expected, f"{platform_name}/{scope} expected effects should come from registry")
            assert_true(scenario.risk_notes == scope_spec.risk_notes, f"{platform_name}/{scope} risk notes should come from registry")


def test_direct_equivalence_uses_registry_scope_specs() -> None:
    for platform_name in runner.ALL_PLATFORMS:
        spec = runner.platform_spec(platform_name)
        for scope, scope_spec in spec.scopes.items():
            scenario = runner.make_scenario(platform_name, scope)
            assert_true(scenario is not None, f"{platform_name}/{scope} should project to a scenario")
            assert_true(runner.equivalent_install_command(scenario) == scope_spec.equivalent_install_command, f"{platform_name}/{scope} equivalence should come from registry")


def test_platform_coverage_records_unsupported_scopes() -> None:
    records = runner.platform_coverage_records(["cursor"], "both")
    user = next(record for record in records if record["scope"] == "user")
    project = next(record for record in records if record["scope"] == "project")
    assert_true(user["status"] == "unsupported", "cursor user scope should be explicitly unsupported")
    assert_true("reason" in user, "unsupported scope should include a reason")
    assert_true(project["status"] == "runnable", "cursor project scope should remain runnable")


def test_codebuddy_scopes_are_runnable() -> None:
    for scope in ("user", "project"):
        scenario = runner.make_scenario("codebuddy", scope)
        assert_true(scenario is not None, f"codebuddy {scope} scenario should be runnable")
        assert_true(any(entry.relative.endswith("SKILL.md") for entry in scenario.expected), f"codebuddy {scope} should assert skill")
        assert_true(any(entry.relative.endswith("CODEBUDDY.md") for entry in scenario.expected), f"codebuddy {scope} should assert CODEBUDDY.md")
        assert_true(any(entry.relative == ".codebuddy/settings.json" for entry in scenario.expected), f"codebuddy {scope} should assert settings hook")


def test_generic_direct_equivalence_applicability() -> None:
    gemini_user = runner.make_scenario("gemini", "user")
    codex_user = runner.make_scenario("codex", "user")
    codex_project = runner.make_scenario("codex", "project")
    codebuddy_user = runner.make_scenario("codebuddy", "user")
    codebuddy_project = runner.make_scenario("codebuddy", "project")
    cursor_project = runner.make_scenario("cursor", "project")
    assert_true(gemini_user is not None, "gemini user scenario should exist")
    assert_true(codex_user is not None, "codex user scenario should exist")
    assert_true(codex_project is not None, "codex project scenario should exist")
    assert_true(codebuddy_user is not None, "codebuddy user scenario should exist")
    assert_true(codebuddy_project is not None, "codebuddy project scenario should exist")
    assert_true(cursor_project is not None, "cursor project scenario should exist")
    assert_true(runner.equivalent_install_command(gemini_user) == ("graphify", "gemini", "install"), "gemini user generic install should compare with direct install")
    assert_true(runner.equivalent_install_command(codex_user) is None, "codex user direct install intentionally differs from generic user install")
    assert_true(runner.equivalent_install_command(codex_project) == ("graphify", "codex", "install", "--project"), "codex project generic install should compare with direct project install")
    assert_true(runner.equivalent_install_command(codebuddy_user) is None, "codebuddy user direct install intentionally differs from generic user install")
    assert_true(runner.equivalent_install_command(codebuddy_project) == ("graphify", "codebuddy", "install"), "codebuddy project generic install should compare with direct project install")
    assert_true(runner.equivalent_install_command(cursor_project) == ("graphify", "install", "--project", "--platform", "cursor"), "cursor project direct install should compare with generic project install")


def test_assertion_detects_missing_file() -> None:
    missing = runner.Scenario(
        platform="unit",
        scope="project",
        install_command=("true",),
        uninstall_command=None,
        cwd_root="project",
        expected=(runner.ExpectedPath("project", "missing.txt"),),
    )
    checks = runner.assert_expected_files(missing)
    assert_true(len(checks) == 1, "expected one assertion check")
    assert_true(checks[0]["ok"] is False, "missing expected file should fail assertion")
    assert_true(checks[0]["detail"] == "missing", "missing expected file should report missing")


def _write_skill(root: Path, relative: str, *, body: str = "# graphify skill\n", version: str | None = None) -> Path:
    skill = root / relative
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(body, encoding="utf-8")
    if version is not None:
        (skill.parent / ".graphify_version").write_text(version, encoding="utf-8")
    return skill


def _check_by_relative(checks: list[dict[str, object]], relative: str) -> dict[str, object]:
    return next(check for check in checks if check.get("relative") == relative)


def test_skill_assertion_detects_missing_version_stamp() -> None:
    with patched_roots() as roots:
        scenario = runner.Scenario(
            platform="aider",
            scope="project",
            install_command=("true",),
            uninstall_command=None,
            cwd_root="project",
            expected=(runner.ExpectedPath("project", ".aider/graphify/SKILL.md"),),
        )
        _write_skill(roots["project"], ".aider/graphify/SKILL.md")
        version = _check_by_relative(runner.assert_expected_files(scenario), ".aider/graphify/.graphify_version")
        assert_true(version["ok"] is False, "missing skill version stamp should fail")
        assert_true("missing" in str(version["detail"]), "missing version detail should be explicit")


def test_skill_assertion_detects_wrong_version_stamp() -> None:
    with patched_roots() as roots:
        scenario = runner.Scenario(
            platform="aider",
            scope="project",
            install_command=("true",),
            uninstall_command=None,
            cwd_root="project",
            expected=(runner.ExpectedPath("project", ".aider/graphify/SKILL.md"),),
        )
        _write_skill(roots["project"], ".aider/graphify/SKILL.md", version="0.0.0")
        version = _check_by_relative(runner.assert_expected_files(scenario), ".aider/graphify/.graphify_version")
        assert_true(version["ok"] is False, "wrong skill version stamp should fail")
        detail = str(version["detail"])
        assert_true("actual=0.0.0" in detail and "expected=" in detail, "wrong version detail should include actual and expected")


def test_skill_assertion_detects_missing_references_sidecar_from_body_pointer() -> None:
    with patched_roots() as roots:
        scenario = runner.Scenario(
            platform="aider",
            scope="project",
            install_command=("true",),
            uninstall_command=None,
            cwd_root="project",
            expected=(runner.ExpectedPath("project", ".aider/graphify/SKILL.md"),),
        )
        _write_skill(
            roots["project"],
            ".aider/graphify/SKILL.md",
            body="See references/query.md for details.\n",
            version=runner.expected_graphify_version(),
        )
        pointer_check = next(
            check
            for check in runner.assert_expected_files(scenario)
            if check.get("relative") == ".aider/graphify/SKILL.md" and "references_missing" in str(check.get("detail"))
        )
        assert_true(pointer_check["ok"] is False, "skill body references should fail when references/ is absent")
        assert_true("references_missing" in str(pointer_check["detail"]), "missing references detail should be explicit")


def test_skill_assertion_detects_references_tmp() -> None:
    with patched_roots() as roots:
        scenario = runner.Scenario(
            platform="aider",
            scope="project",
            install_command=("true",),
            uninstall_command=None,
            cwd_root="project",
            expected=(runner.ExpectedPath("project", ".aider/graphify/SKILL.md"),),
        )
        skill = _write_skill(roots["project"], ".aider/graphify/SKILL.md", version=runner.expected_graphify_version())
        (skill.parent / "references.tmp").mkdir()
        tmp_check = _check_by_relative(runner.assert_expected_files(scenario), ".aider/graphify/references.tmp")
        assert_true(tmp_check["ok"] is False, "leftover references.tmp should fail")
        assert_true(tmp_check["detail"] == "present", "references.tmp detail should report present")


def test_skill_assertion_detects_extra_packaged_reference_fragment() -> None:
    with patched_roots() as roots:
        scenario = runner.Scenario(
            platform="claude",
            scope="project",
            install_command=("true",),
            uninstall_command=None,
            cwd_root="project",
            expected=(runner.ExpectedPath("project", ".claude/skills/graphify/SKILL.md"),),
        )
        skill = _write_skill(roots["project"], ".claude/skills/graphify/SKILL.md", version=runner.expected_graphify_version())
        refs = skill.parent / "references"
        refs.mkdir()
        for name in runner.packaged_reference_names("claude") or []:
            (refs / name).write_text(f"# {name}\n", encoding="utf-8")
        (refs / "stale-sandbox-fragment.md").write_text("stale\n", encoding="utf-8")
        refs_check = _check_by_relative(runner.assert_expected_files(scenario), ".claude/skills/graphify/references")
        assert_true(refs_check["ok"] is False, "extra stale reference fragment should fail exact comparison")
        assert_true("stale-sandbox-fragment.md" in str(refs_check["detail"]), "extra fragment should appear in detail")


def test_skill_assertion_detects_missing_packaged_reference_fragment() -> None:
    with patched_roots() as roots:
        scenario = runner.Scenario(
            platform="claude",
            scope="project",
            install_command=("true",),
            uninstall_command=None,
            cwd_root="project",
            expected=(runner.ExpectedPath("project", ".claude/skills/graphify/SKILL.md"),),
        )
        skill = _write_skill(roots["project"], ".claude/skills/graphify/SKILL.md", version=runner.expected_graphify_version())
        refs = skill.parent / "references"
        refs.mkdir()
        names = runner.packaged_reference_names("claude") or []
        for name in names[1:]:
            (refs / name).write_text(f"# {name}\n", encoding="utf-8")
        refs_check = _check_by_relative(runner.assert_expected_files(scenario), ".claude/skills/graphify/references")
        assert_true(refs_check["ok"] is False, "missing packaged reference fragment should fail exact comparison")
        assert_true(names[0] in str(refs_check["detail"]), "missing fragment should appear in detail")


def test_skill_assertion_rejects_monolith_sidecar() -> None:
    with patched_roots() as roots:
        scenario = runner.Scenario(
            platform="aider",
            scope="project",
            install_command=("true",),
            uninstall_command=None,
            cwd_root="project",
            expected=(runner.ExpectedPath("project", ".aider/graphify/SKILL.md"),),
        )
        skill = _write_skill(roots["project"], ".aider/graphify/SKILL.md", version=runner.expected_graphify_version())
        refs = skill.parent / "references"
        refs.mkdir()
        (refs / "leftover.md").write_text("leftover\n", encoding="utf-8")
        refs_check = _check_by_relative(runner.assert_expected_files(scenario), ".aider/graphify/references")
        assert_true(refs_check["ok"] is False, "monolith platform should fail if references/ sidecar is installed")
        assert_true("no_packaged_references" in str(refs_check["detail"]), "monolith sidecar detail should explain no packaged references")


def test_stale_sidecar_seed_only_targets_progressive_skills() -> None:
    with patched_roots() as roots:
        progressive = runner.Scenario(
            platform="claude",
            scope="project",
            install_command=("true",),
            uninstall_command=None,
            cwd_root="project",
            expected=(runner.ExpectedPath("project", ".claude/skills/graphify/SKILL.md"),),
        )
        monolith = runner.Scenario(
            platform="aider",
            scope="project",
            install_command=("true",),
            uninstall_command=None,
            cwd_root="project",
            expected=(runner.ExpectedPath("project", ".aider/graphify/SKILL.md"),),
        )
        progressive_seeded = runner.seed_stale_skill_sidecars(progressive)
        monolith_seeded = runner.seed_stale_skill_sidecars(monolith)
        assert_true(progressive_seeded, "progressive skill should receive stale sidecar seed files")
        assert_true((roots["project"] / ".claude/skills/graphify/references/stale-sandbox-fragment.md").exists(), "stale reference fragment should be seeded")
        assert_true((roots["project"] / ".claude/skills/graphify/references.tmp/partial.md").exists(), "references.tmp partial should be seeded")
        assert_true(monolith_seeded == [], "monolith skill should not receive stale sidecar seed files")
        assert_true(not (roots["project"] / ".aider/graphify/references").exists(), "monolith references dir should not be created")


def test_seeded_stale_section_must_be_replaced() -> None:
    old_roots = runner.ROOTS.copy()
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        roots = {"home": base / "home", "project": base / "project", "user_cwd": base / "user-cwd"}
        for root in roots.values():
            root.mkdir(parents=True)
        runner.ROOTS.clear()
        runner.ROOTS.update(roots)
        try:
            scenario = runner.Scenario(
                platform="unit",
                scope="project",
                install_command=("true",),
                uninstall_command=None,
                cwd_root="project",
                expected=(runner.ExpectedPath("project", "AGENTS.md", marker=runner.GRAPHIFY_MARKER),),
            )
            runner.seed_user_owned_content(scenario)
            seeded = roots["project"] / "AGENTS.md"
            assert_true(runner.USER_SENTINEL in seeded.read_text(encoding="utf-8"), "seed should include user content")
            assert_true(runner.STALE_GRAPHIFY_SENTINEL in seeded.read_text(encoding="utf-8"), "seed should include stale graphify content")
            stale_checks = runner.assert_expected_files(scenario)
            assert_true(stale_checks[0]["ok"] is False, "stale graphify content should fail before install replaces it")
            seeded.write_text(f"# User Notes\n\n{runner.USER_SENTINEL}\n\n{runner.GRAPHIFY_MARKER}\nnew section\n", encoding="utf-8")
            fresh_checks = runner.assert_expected_files(scenario)
            assert_true(fresh_checks[0]["ok"] is True, "fresh graphify section with user content should pass")
        finally:
            runner.ROOTS.clear()
            runner.ROOTS.update(old_roots)


def test_idempotency_state_detects_content_change() -> None:
    before = {"project/AGENTS.md": {"exists": True, "sha256": "a"}}
    after = {"project/AGENTS.md": {"exists": True, "sha256": "b"}}
    checks = runner.assert_idempotent_state(before, after)
    assert_true(checks[0]["ok"] is False, "changed file fingerprint should fail idempotency")
    stable = runner.assert_idempotent_state(before, before)
    assert_true(stable[0]["ok"] is True, "unchanged file fingerprint should pass idempotency")


def test_universal_scenario_selection_requires_multiple_platforms() -> None:
    assert_true(runner.universal_uninstall_scenarios(["codex"], "project") == [], "single platform should not create universal scenario")
    groups = runner.universal_uninstall_scenarios(["codex", "claude", "gemini"], "project")
    assert_true(len(groups) == 1, "multiple project platforms should create a universal project scenario")
    assert_true(groups[0][0] == "project", "universal group should be project scoped")


def test_report_serialization_includes_risks() -> None:
    scenario = runner.make_scenario("codex", "project")
    assert_true(scenario is not None, "codex project scenario should exist")
    report = runner.risk_report(scenario, True)
    encoded = json.dumps(report)
    for status in (runner.RISK_GRAPHIFY_VERIFIED,):
        assert_true(status in encoded, f"risk status missing from serialized report: {status}")
    assert_true("target_tool_runtime" not in encoded, "risk report should not carry runtime probe fields")


def test_report_markdown_generation() -> None:
    manifest = {
        "graphify_file_effect_pass_count": 1,
        "graphify_file_effect_fail_count": 1,
        "scenario_count": 2,
        "architecture": "x86_64",
        "python_version": "3.12 synthetic",
        "graphify_version": "9.9.9",
        "os_release": {"PRETTY_NAME": "Synthetic Linux"},
        "package_install": {
            "install_mode": "normal",
            "package_name": "graphifyy",
            "location": "/tmp/site-packages",
            "installed_from_copied_source": True,
        },
        "source_snapshot": {"root": "/tmp/graphify-src"},
        "preflight": {"project": "/tmp/graphify-project"},
        "risk_status_values": runner.known_status_values(),
        "target_runtime_verification": {"performed": False},
        "platform_coverage": [
            {
                "platform": "codex",
                "scope": "project",
                "status": "runnable",
                "install_command": ["graphify", "install", "--project", "--platform", "codex"],
            }
        ],
        "windows_validation": {
            "status": "payload_consistency_only",
            "evidence_path": None,
            "strategy": "payload consistency only",
            "targets": ["windows", "antigravity mapping"],
            "notes": ["Linux sandbox does not prove Windows-specific behavior."],
        },
        "results": [
            {
                "id": "codex-project",
                "platform": "codex",
                "scope": "project",
                "passed": True,
                "graphify_file_effects_passed": True,
                "overall_status": runner.RISK_GRAPHIFY_VERIFIED,
                "duration_ms": 42,
                "command_artifact": {
                    "command": "graphify install --project --platform codex",
                    "started_at": "2026-06-02T00:00:00Z",
                    "duration_ms": 42,
                    "exit_code": 0,
                    "transcript_path": "scenarios/codex-project/transcript.txt",
                },
            },
            {
                "id": "cursor-project",
                "platform": "cursor",
                "scope": "project",
                "passed": False,
                "graphify_file_effects_passed": False,
                "overall_status": runner.RISK_GRAPHIFY_FAILED,
                "duration_ms": 7,
                "reproduction_command": "graphify cursor install",
                "command_artifact": {
                    "command": "graphify cursor install",
                    "started_at": "2026-06-02T00:00:01Z",
                    "duration_ms": 7,
                    "exit_code": 1,
                    "transcript_path": "scenarios/cursor-project/transcript.txt",
                    "stdout_snippet": "partial output",
                    "stderr_snippet": "boom",
                },
            },
        ],
    }

    markdown = runner.render_report_md(manifest)

    for expected in (
        "# Graphify Install Sandbox Report",
        "## Environment",
        "Synthetic Linux",
        "| Platform | Scope | Scenario | Graphify File Effects | Overall Status | Duration | Transcript |",
        "codex-project",
        "Target runtime verification: not performed by this Tier 1 file-effect sandbox.",
        "graphify cursor install",
        "boom",
        "scenarios/codex-project/transcript.txt",
        "2026-06-02T00:00:00Z",
        "## Windows Validation",
        "payload consistency only",
        "Linux sandbox does not prove Windows-specific behavior.",
    ):
        assert_true(expected in markdown, f"report markdown should include {expected}")


def test_default_windows_validation_status_marks_linux_as_risk() -> None:
    status = runner.default_windows_validation_status()
    assert_true(status["status"] == "payload_consistency_only", "Linux sandbox should not claim Windows validation passed")
    assert_true("payload" in " ".join(status["targets"]), "Windows validation targets should be explicit")
    assert_true("does not validate" in " ".join(status["notes"]), "notes should avoid implying local Windows validation exists")


def test_write_report_markdown() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "report.md"
        runner.write_report_md(path, {"results": [], "platform_coverage": []})
        content = path.read_text(encoding="utf-8")
    assert_true("Graphify Install Sandbox Report" in content, "write_report_md should write rendered markdown")


def test_run_capture_timeout_serialization() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        artifact = root / "artifact"
        result = runner.run_capture(
            (sys.executable, "-c", "import time; time.sleep(1)"),
            cwd=root,
            env=os.environ.copy(),
            artifact_dir=artifact,
            command_class="unit_timeout",
            timeout_seconds=0,
        )
        saved = json.loads((artifact / "command-result.json").read_text(encoding="utf-8"))
        assert_true(result.returncode == 124, "timed out command should use exit code 124")
        assert_true(saved["timed_out"] is True, "command-result should record timeout")
        assert_true(saved["timeout_seconds"] == 0, "command-result should record timeout seconds")
        assert_true(saved["command_class"] == "unit_timeout", "command-result should record command class")


def test_shell_safe_command_display() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        artifact = root / "artifact"
        runner.run_capture(
            (sys.executable, "-c", "print('hello world')"),
            cwd=root,
            env=os.environ.copy(),
            artifact_dir=artifact,
            command_class="unit",
        )
        saved = json.loads((artifact / "command-result.json").read_text(encoding="utf-8"))
        command_text = saved["command_display"]
        assert_true("'hello world'" in command_text or '"hello world"' in command_text, "command display should shell-quote arguments with spaces")
        assert_true((artifact / "command.txt").read_text(encoding="utf-8").strip() == command_text, "command.txt should use command display")


def test_install_graphify_version_probe_failure_is_precondition() -> None:
    old_output = runner.OUTPUT
    patched_names = ("run_capture", "read_installed_package_metadata")
    old_values = {name: getattr(runner, name) for name in patched_names}
    with tempfile.TemporaryDirectory() as tmp:
        runner.OUTPUT = Path(tmp)
        calls: list[str] = []

        def fake_run_capture(command, *, cwd, env, artifact_dir=None, command_class="installer", timeout_seconds=None):
            calls.append(command_class)
            if command_class == "package_install":
                return subprocess.CompletedProcess(list(command), 0, "installed", "")
            if command_class == "graphify_version":
                return subprocess.CompletedProcess(list(command), 124, "", "timed out after 60 seconds")
            raise AssertionError(f"unexpected command_class={command_class}")

        runner.run_capture = fake_run_capture
        runner.read_installed_package_metadata = lambda package_name, source: {"package_name": package_name, "version": None}
        try:
            try:
                runner.install_graphify({})
            except RuntimeError as exc:
                message = str(exc)
            else:
                raise AssertionError("install_graphify should fail when graphify --version fails")
        finally:
            runner.OUTPUT = old_output
            for name, value in old_values.items():
                setattr(runner, name, value)

    assert_true(calls == ["package_install", "graphify_version"], "package install and version probe should run before precondition failure")
    assert_true("version probe failed" in message, "version probe failure should have a clear precondition error")


def test_risk_report_is_file_effect_only() -> None:
    scenario = runner.make_scenario("codex", "project")
    assert_true(scenario is not None, "codex project scenario should exist")
    report = runner.risk_report(scenario, True)
    assert_true(report["statuses"] == [runner.RISK_GRAPHIFY_VERIFIED], "passing risk report should contain only Graphify file-effect status")
    assert_true("target_tool_runtime_verified" not in report, "risk report should not include runtime verification fields")


def test_combined_status_separates_graphify_and_runtime() -> None:
    assert_true(runner.combined_status(True) == runner.RISK_GRAPHIFY_VERIFIED, "passing file effects should produce verified status")
    assert_true(runner.combined_status(False) == runner.RISK_GRAPHIFY_FAILED, "failing file effects should produce failed status")


def test_docker_command_construction() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        out = Path(tmp) / "out"
        repo.mkdir()
        out.mkdir()
        command = host.build_container_command(
            runtime="docker",
            image="graphify-install-sandbox:local",
            repo=repo,
            output=out,
            platform="codex",
            all_platforms=False,
            scope="both",
            copy_source="always",
            keep_container=False,
        )
    joined = " ".join(command)
    assert_true("--rm" in command, "container should be removed by default")
    assert_true("--user" in command, "container should run as host uid/gid")
    assert_true("HOME=/tmp/graphify-home" in command, "HOME should be sandboxed")
    assert_true("XDG_CONFIG_HOME=/tmp/graphify-home/.config" in command, "XDG_CONFIG_HOME should be sandboxed")
    assert_true("GRAPHIFY_PROJECT=/tmp/graphify-project" in command, "project path should be sandboxed")
    assert_true(":/mnt/graphify-repo:ro" in joined, "repo mount should be read-only")
    assert_true(":/sandbox-out:rw" in joined, "output mount should be writable")
    assert_true("--platform codex" in joined, "platform should be passed through")


def test_source_excludes_nested_sandbox_out() -> None:
    assert_true(runner.should_exclude_source_path(".kilo/plans/private.md"), ".kilo personal planning files should be excluded")
    assert_true(runner.should_exclude_source_path("tools/install_sandbox/out"), "nested sandbox output root should be excluded")
    assert_true(runner.should_exclude_source_path("tools/install_sandbox/out/codex/manifest.json"), "nested sandbox output files should be excluded")
    assert_true(runner.should_exclude_source_path("graphifyy.egg-info/PKG-INFO"), "egg-info directories should be excluded")
    assert_true(not runner.should_exclude_source_path("tools/install_sandbox/sandbox_runner.py"), "sandbox source should remain copyable")


def test_package_provenance_parsing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "graphify-src"
        site = root / "site-packages"
        dist_info = site / "graphifyy-1.2.3.dist-info"
        source.mkdir()
        dist_info.mkdir(parents=True)
        (dist_info / "METADATA").write_text("Name: graphifyy\nVersion: 1.2.3\n", encoding="utf-8")
        (dist_info / "direct_url.json").write_text(json.dumps({"url": source.resolve().as_uri(), "dir_info": {}}), encoding="utf-8")

        metadata = runner.read_installed_package_metadata("graphifyy", source, [site])

    assert_true(metadata["package_name"] == "graphifyy", "package name should be parsed")
    assert_true(metadata["version"] == "1.2.3", "package version should be parsed")
    assert_true(metadata["location"].endswith("site-packages"), "install location should be dist-info parent")
    assert_true(metadata["installed_from_copied_source"] is True, "direct_url should identify copied source install")


def test_generated_files_filtering() -> None:
    old_roots = runner.ROOTS.copy()
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        roots = {
            "home": base / "home",
            "project": base / "project",
            "user_cwd": base / "user-cwd",
        }
        for root in roots.values():
            root.mkdir(parents=True)
        runner.ROOTS.clear()
        runner.ROOTS.update(roots)
        try:
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
            scenario = runner.Scenario(
                platform="codex",
                scope="user",
                install_command=("true",),
                uninstall_command=None,
                cwd_root="user_cwd",
                expected=(runner.ExpectedPath("home", ".codex/skills/graphify/SKILL.md"),),
            )
            artifact_dir = base / "artifact"
            runner.copy_generated_files(scenario, artifact_dir)
        finally:
            runner.ROOTS.clear()
            runner.ROOTS.update(old_roots)

        generated = artifact_dir / "generated-files"
        assert_true((generated / "home/.codex/skills/graphify/SKILL.md").exists(), "expected Graphify skill should be copied")
        assert_true((generated / "home/.codex/skills/graphify/.graphify_version").exists(), "version stamp should be copied")
        assert_true((generated / "project/AGENTS.md").exists(), "shared marker-bearing file should be copied")
        assert_true(not (generated / "home/.local/lib/python3.12/site-packages/example.py").exists(), "site-packages should not be copied")
        assert_true(not (generated / "project/notes.md").exists(), "unrelated files should not be copied")


def test_run_scenario_skips_followups_when_initial_install_fails() -> None:
    old_output = runner.OUTPUT
    patched_names = (
        "reset_sandbox_dirs",
        "seed_user_owned_content",
        "write_file_manifest",
        "run_capture",
        "scenario_file_state",
        "assert_expected_files",
        "assert_scope_boundaries",
        "assert_no_unexpected_graphify_files",
        "copy_generated_files",
    )
    old_values = {name: getattr(runner, name) for name in patched_names}
    with tempfile.TemporaryDirectory() as tmp:
        runner.OUTPUT = Path(tmp)
        calls: list[tuple[str, ...]] = []

        def fake_run_capture(command, *, cwd, env, artifact_dir=None, command_class="installer", timeout_seconds=None):
            command_tuple = tuple(command)
            calls.append(command_tuple)
            assert_true(len(calls) == 1, "repeat install, uninstall, and equivalence commands should be skipped after initial install failure")
            result = subprocess.CompletedProcess(list(command_tuple), 1, "", "install failed")
            result.started_at = "2026-06-02T00:00:00Z"
            result.duration_ms = 1
            if artifact_dir is not None:
                artifact_dir.mkdir(parents=True, exist_ok=True)
                (artifact_dir / "command-result.json").write_text(
                    json.dumps({"command": list(command_tuple), "exit_code": 1, "duration_ms": 1}) + "\n",
                    encoding="utf-8",
                )
            return result

        runner.reset_sandbox_dirs = lambda: None
        runner.seed_user_owned_content = lambda scenario: None
        runner.write_file_manifest = lambda path, roots, **kwargs: None
        runner.run_capture = fake_run_capture
        runner.scenario_file_state = lambda scenario: {}
        runner.assert_expected_files = lambda scenario: []
        runner.assert_scope_boundaries = lambda scenario: []
        runner.assert_no_unexpected_graphify_files = lambda scenario, *, phase: []
        runner.copy_generated_files = lambda scenario, artifact_dir: None
        scenario = runner.Scenario(
            platform="codex",
            scope="project",
            install_command=("graphify", "install", "--project", "--platform", "codex"),
            uninstall_command=("graphify", "uninstall", "--project", "--platform", "codex"),
            cwd_root="project",
            expected=(runner.ExpectedPath("project", "AGENTS.md"),),
        )
        try:
            result = runner.run_scenario(scenario, {})
            assertions = json.loads((runner.OUTPUT / "scenarios" / "codex-project" / "assertions.json").read_text(encoding="utf-8"))
        finally:
            runner.OUTPUT = old_output
            for name, value in old_values.items():
                setattr(runner, name, value)

    assert_true(calls == [scenario.install_command], "only the initial Graphify install command should run")
    assert_true(result["passed"] is False, "scenario should fail when initial Graphify install command fails")
    assert_true(assertions["repeat_install_exit_code"] is None, "repeat install should be recorded as skipped")
    assert_true(assertions["uninstall_exit_code"] is None, "uninstall should be recorded as skipped")


def test_matrix_collects_graphify_failures() -> None:
    old_platform_scenarios = runner.platform_scenarios
    old_run_scenario = runner.run_scenario
    old_universal_uninstall_scenarios = runner.universal_uninstall_scenarios
    old_run_purge_scenario = runner.run_purge_scenario
    calls: list[str] = []

    def fake_platform_scenarios(platform_name: str, scope: str):
        return [
            runner.Scenario(
                platform=platform_name,
                scope="project",
                install_command=("graphify", "install", "--platform", platform_name),
                uninstall_command=None,
                cwd_root="project",
                expected=(runner.ExpectedPath("project", f"{platform_name}.md"),),
            )
        ]

    def fake_run_scenario(scenario, env):
        calls.append(scenario.platform)
        return {
            "id": runner.scenario_id(scenario.platform, scenario.scope),
            "platform": scenario.platform,
            "scope": scenario.scope,
            "passed": False,
            "graphify_file_effects_passed": False,
        }

    def unexpected_universal(*args, **kwargs):
        raise AssertionError("universal uninstall should not run after a Graphify install failure")

    def unexpected_purge(*args, **kwargs):
        raise AssertionError("purge scenario should not run after a Graphify install failure")

    runner.platform_scenarios = fake_platform_scenarios
    runner.run_scenario = fake_run_scenario
    runner.universal_uninstall_scenarios = unexpected_universal
    runner.run_purge_scenario = unexpected_purge
    try:
        results = runner.run_matrix_scenarios(["first", "second"], "project", {})
    finally:
        runner.platform_scenarios = old_platform_scenarios
        runner.run_scenario = old_run_scenario
        runner.universal_uninstall_scenarios = old_universal_uninstall_scenarios
        runner.run_purge_scenario = old_run_purge_scenario

    assert_true(calls == ["first", "second"], "matrix should collect scenario failures across selected platforms")
    assert_true(len(results) == 2 and all(result["passed"] is False for result in results), "matrix should return every failing scenario result")


def test_matrix_fail_fast_stops_first_graphify_failure() -> None:
    old_platform_scenarios = runner.platform_scenarios
    old_run_scenario = runner.run_scenario
    calls: list[str] = []

    def fake_platform_scenarios(platform_name: str, scope: str):
        return [
            runner.Scenario(
                platform=platform_name,
                scope="project",
                install_command=("graphify", "install", "--platform", platform_name),
                uninstall_command=None,
                cwd_root="project",
                expected=(runner.ExpectedPath("project", f"{platform_name}.md"),),
            )
        ]

    def fake_run_scenario(scenario, env):
        calls.append(scenario.platform)
        return {"id": runner.scenario_id(scenario.platform, scenario.scope), "platform": scenario.platform, "scope": scenario.scope, "passed": False}

    runner.platform_scenarios = fake_platform_scenarios
    runner.run_scenario = fake_run_scenario
    try:
        results = runner.run_matrix_scenarios(["first", "second"], "project", {}, fail_fast_scenarios=True)
    finally:
        runner.platform_scenarios = old_platform_scenarios
        runner.run_scenario = old_run_scenario

    assert_true(calls == ["first"], "fail-fast should stop at the first platform scenario failure")
    assert_true(len(results) == 1 and results[0]["passed"] is False, "fail-fast should return only the first failing result")


def test_matrix_collects_universal_failures_and_runs_purge() -> None:
    old_platform_scenarios = runner.platform_scenarios
    old_run_scenario = runner.run_scenario
    old_universal_uninstall_scenarios = runner.universal_uninstall_scenarios
    old_run_universal_uninstall_scenario = runner.run_universal_uninstall_scenario
    old_run_purge_scenario = runner.run_purge_scenario
    calls: list[str] = []

    def scenario(platform_name: str, scope: str) -> runner.Scenario:
        return runner.Scenario(
            platform=platform_name,
            scope=scope,
            install_command=("graphify", "install", "--platform", platform_name),
            uninstall_command=None,
            cwd_root="project",
            expected=(runner.ExpectedPath("project", f"{platform_name}-{scope}.md"),),
        )

    def fake_platform_scenarios(platform_name: str, scope: str):
        return [scenario(platform_name, "project")]

    def fake_run_scenario(item, env):
        calls.append(f"scenario:{item.platform}")
        return {"id": runner.scenario_id(item.platform, item.scope), "platform": item.platform, "scope": item.scope, "passed": True}

    def fake_universal_uninstall_scenarios(platforms, scope):
        return [("user", [scenario("first", "user"), scenario("second", "user")]), ("project", [scenario("first", "project"), scenario("second", "project")])]

    def fake_run_universal_uninstall_scenario(universal_scope, scenarios, env):
        calls.append(f"universal:{universal_scope}")
        return {"id": f"universal-uninstall-{universal_scope}", "platform": "multiple", "scope": universal_scope, "passed": False}

    def fake_run_purge_scenario(env):
        calls.append("purge")
        return {"id": "purge-disposable-graphify-out", "platform": "purge", "scope": "project", "passed": False}

    runner.platform_scenarios = fake_platform_scenarios
    runner.run_scenario = fake_run_scenario
    runner.universal_uninstall_scenarios = fake_universal_uninstall_scenarios
    runner.run_universal_uninstall_scenario = fake_run_universal_uninstall_scenario
    runner.run_purge_scenario = fake_run_purge_scenario
    try:
        results = runner.run_matrix_scenarios(["first", "second"], "both", {})
    finally:
        runner.platform_scenarios = old_platform_scenarios
        runner.run_scenario = old_run_scenario
        runner.universal_uninstall_scenarios = old_universal_uninstall_scenarios
        runner.run_universal_uninstall_scenario = old_run_universal_uninstall_scenario
        runner.run_purge_scenario = old_run_purge_scenario

    assert_true(calls == ["scenario:first", "scenario:second", "universal:user", "universal:project", "purge"], "matrix should keep collecting meaningful universal and purge failures")
    assert_true([result["id"] for result in results][-3:] == ["universal-uninstall-user", "universal-uninstall-project", "purge-disposable-graphify-out"], "universal failures and purge should all be returned")


def test_main_records_tier1_runtime_boundary() -> None:
    old_output = runner.OUTPUT
    patched_names = (
        "sandbox_env",
        "preflight",
        "copy_source_tree",
        "install_graphify",
        "selected_platforms",
        "selected_scenarios",
        "run_matrix_scenarios",
        "platform_coverage_records",
        "read_os_release",
        "write_report_md",
    )
    old_values = {name: getattr(runner, name) for name in patched_names}
    with tempfile.TemporaryDirectory() as tmp:
        runner.OUTPUT = Path(tmp)

        runner.sandbox_env = lambda: {}
        runner.preflight = lambda: {"project": "/tmp/graphify-project"}
        runner.copy_source_tree = lambda copy_source="always": {"root": "/tmp/graphify-src", "copy_source_mode": copy_source}
        runner.install_graphify = lambda env: {"version": "test", "install_mode": "normal"}
        runner.selected_platforms = lambda args: ["codex"]
        runner.selected_scenarios = lambda args: [runner.make_scenario("codex", "project")]
        runner.run_matrix_scenarios = lambda platforms, scope, env, fail_fast_scenarios=False: [
            {
                "id": "codex-project",
                "platform": "codex",
                "scope": "project",
                "passed": False,
                "graphify_file_effects_passed": False,
            }
        ]
        runner.platform_coverage_records = lambda platforms, scope: []
        runner.read_os_release = lambda: {"PRETTY_NAME": "Synthetic Linux"}
        runner.write_report_md = lambda path, manifest: path.write_text("report\n", encoding="utf-8")
        try:
            exit_code = runner.main(["--platform", "codex", "--scope", "project"])
            manifest = json.loads((runner.OUTPUT / "manifest.json").read_text(encoding="utf-8"))
        finally:
            runner.OUTPUT = old_output
            for name, value in old_values.items():
                setattr(runner, name, value)

    assert_true(exit_code == 1, "main should fail when Graphify install scenarios fail")
    assert_true(manifest["target_runtime_verification"]["performed"] is False, "manifest should record runtime verification as out of scope")
    assert_true("target_tool_runtime" not in manifest, "manifest should not include legacy target runtime probe schema")


def run_python_compile() -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "py_compile",
            str(HARNESS_DIR / "run.py"),
            str(HARNESS_DIR / "sandbox_runner.py"),
        ],
        check=True,
    )


def run_docker_smoke() -> None:
    if os.environ.get("GRAPHIFY_RUN_DOCKER_TESTS") != "1":
        raise RuntimeError("Docker smoke is gated; set GRAPHIFY_RUN_DOCKER_TESTS=1")
    repo = Path("/home/alacasse/projects/graphify")
    output = HARNESS_DIR / "out" / "selftest-codex"
    command = [
        sys.executable,
        str(HARNESS_DIR / "run.py"),
        "--repo",
        str(repo),
        "--platform",
        "codex",
        "--scope",
        "both",
        "--output",
        str(output),
    ]
    subprocess.run(command, check=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Self-test the private Graphify install sandbox harness.")
    parser.add_argument("--docker", action="store_true", help="Run the gated Docker smoke test.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    tests = [
        run_python_compile,
        test_scenario_id,
        test_expected_path_manifest_logic,
        test_registry_mirrors_install_surface,
        test_every_scope_is_runnable_or_explained,
        test_sandbox_registry_defines_all_platforms,
        test_make_scenario_projects_registry_scope_specs,
        test_direct_equivalence_uses_registry_scope_specs,
        test_platform_coverage_records_unsupported_scopes,
        test_codebuddy_scopes_are_runnable,
        test_generic_direct_equivalence_applicability,
        test_assertion_detects_missing_file,
        test_skill_assertion_detects_missing_version_stamp,
        test_skill_assertion_detects_wrong_version_stamp,
        test_skill_assertion_detects_missing_references_sidecar_from_body_pointer,
        test_skill_assertion_detects_references_tmp,
        test_skill_assertion_detects_extra_packaged_reference_fragment,
        test_skill_assertion_detects_missing_packaged_reference_fragment,
        test_skill_assertion_rejects_monolith_sidecar,
        test_stale_sidecar_seed_only_targets_progressive_skills,
        test_seeded_stale_section_must_be_replaced,
        test_idempotency_state_detects_content_change,
        test_universal_scenario_selection_requires_multiple_platforms,
        test_report_serialization_includes_risks,
        test_report_markdown_generation,
        test_default_windows_validation_status_marks_linux_as_risk,
        test_write_report_markdown,
        test_run_capture_timeout_serialization,
        test_shell_safe_command_display,
        test_install_graphify_version_probe_failure_is_precondition,
        test_risk_report_is_file_effect_only,
        test_combined_status_separates_graphify_and_runtime,
        test_docker_command_construction,
        test_source_excludes_nested_sandbox_out,
        test_package_provenance_parsing,
        test_generated_files_filtering,
        test_run_scenario_skips_followups_when_initial_install_fails,
        test_matrix_collects_graphify_failures,
        test_matrix_fail_fast_stops_first_graphify_failure,
        test_matrix_collects_universal_failures_and_runs_purge,
        test_main_records_tier1_runtime_boundary,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    if args.docker:
        run_docker_smoke()
        print("PASS run_docker_smoke")
    print("selftest passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
