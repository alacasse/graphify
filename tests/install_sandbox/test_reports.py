from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.install_sandbox.reporting import artifacts
from tools.install_sandbox.reporting import agent_summary
from tools.install_sandbox.reporting import harness_run
from tools.install_sandbox.reporting import manifest_projection
from tools.install_sandbox.reporting import reports
from tools.install_sandbox.reporting import status as reporting_status


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def test_known_status_values_are_serializable_file_effect_statuses() -> None:
    encoded = json.dumps({"risk_status_values": reports.known_status_values()})

    assert reports.RISK_GRAPHIFY_VERIFIED in encoded
    assert reports.RISK_GRAPHIFY_FAILED in encoded
    assert "target_tool_runtime" not in encoded


def test_status_values_are_owned_by_reporting() -> None:
    assert (
        reports.RISK_GRAPHIFY_VERIFIED
        == reporting_status.RISK_GRAPHIFY_VERIFIED
        == "graphify_install_verified"
    )
    assert (
        reports.RISK_GRAPHIFY_FAILED
        == reporting_status.RISK_GRAPHIFY_FAILED
        == "graphify_install_failed"
    )
    assert reports.known_status_values() == reporting_status.known_status_values()


def test_markdown_helpers_escape_table_and_code_cells() -> None:
    assert reports.md_cell("line 1\nline | 2") == "line 1 line \\| 2"
    assert reports.md_code("graphify `install`") == "`graphify 'install'`"

    table = reports.md_table(["A|B", "Count"], [["x\ny", 3]], right_align={1})

    assert table == [
        "| A\\|B | Count |",
        "|---|---:|",
        "| x y | 3 |",
    ]


def test_status_label_prefers_overall_status_then_passed_flag() -> None:
    assert reports.status_label({"overall_status": "custom_status", "passed": False}) == "custom_status"
    assert reports.status_label({"passed": True}) == reports.RISK_GRAPHIFY_VERIFIED
    assert reports.status_label({"passed": False}) == reports.RISK_GRAPHIFY_FAILED


def test_reporting_artifacts_characterize_primitive_artifact_contract(tmp_path: Path) -> None:
    output = tmp_path / "out"
    artifact_dir = output / "scenarios" / "codex-project"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "command-result.json").write_text(
        json.dumps(
            {
                "command": ["graphify", "install", "--project", "--platform", "codex"],
                "command_class": "installer",
                "started_at": "2026-06-02T00:00:00Z",
                "duration_ms": 123,
                "exit_code": 0,
                "timeout_seconds": 30,
                "timed_out": False,
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "stdout.txt").write_text(" line 1\n\n line\t2 \n", encoding="utf-8")
    (artifact_dir / "stderr.txt").write_text(("x" * 502) + "\nsecond line", encoding="utf-8")
    (artifact_dir / "tail.txt").write_text("0123456789", encoding="utf-8")
    write_json(
        artifact_dir / "assertions.json",
        {
            "checks": [
                {"ok": False, "relative": "AGENTS.md", "root": "project", "detail": "missing Graphify block"},
                {"ok": False, "path": "/tmp/graphify-home/.codex/AGENTS.md", "root": "home", "detail": "missing local block"},
                {"ok": False, "relative": "skip.md", "detail": "generic_direct_equivalent=True"},
                {"ok": True, "relative": "ok.md", "detail": "exists"},
            ]
        },
    )

    assert artifacts.artifact_relpath(artifact_dir / "transcript.txt", output) == "scenarios/codex-project/transcript.txt"
    assert artifacts.artifact_relpath(tmp_path / "elsewhere.txt", output) == str(tmp_path / "elsewhere.txt")
    assert artifacts.read_json_object(artifact_dir / "command-result.json")["command_class"] == "installer"
    assert artifacts.read_json_object(artifact_dir / "missing.json") == {}
    (artifact_dir / "invalid.json").write_text("{", encoding="utf-8")
    (artifact_dir / "array.json").write_text("[]", encoding="utf-8")
    assert artifacts.read_json_object(artifact_dir / "invalid.json") == {}
    assert artifacts.read_json_object(artifact_dir / "array.json") == {}
    assert artifacts.load_json_object(artifact_dir / "missing.json") == {}
    assert artifacts.load_json_object(artifact_dir / "invalid.json")["_error"].startswith("invalid json:")
    assert artifacts.load_json_object(artifact_dir / "array.json") == {"_error": "json root is not an object"}
    assert artifacts.file_text_snippet(artifact_dir / "stdout.txt") == "line 1\n\n line\t2"
    assert artifacts.normalized_text_snippet(" alpha\n\n beta\tgamma ", limit=20) == "alpha beta gamma"
    assert artifacts.normalized_text_snippet("abcdefghij", limit=8) == "abcde..."
    assert artifacts.tail_file(artifact_dir / "tail.txt", limit=4) == "6789"
    assert artifacts.tail_file(artifact_dir / "missing-tail.txt") == ""
    assert artifacts.failed_checks(output, "codex-project", limit=2) == [
        {"path": "AGENTS.md", "detail": "missing Graphify block", "root": "project"},
        {"path": "home/.codex/AGENTS.md", "detail": "missing local block", "root": "home"},
    ]

    summary = artifacts.command_artifact_summary(artifact_dir, output_root=output)

    assert summary == {
        "command": "graphify install --project --platform codex",
        "command_class": "installer",
        "started_at": "2026-06-02T00:00:00Z",
        "duration_ms": 123,
        "exit_code": 0,
        "timeout_seconds": 30,
        "timed_out": False,
        "transcript_path": "scenarios/codex-project/transcript.txt",
        "stdout_snippet": "line 1\n\n line\t2",
        "stderr_snippet": ("x" * 500) + "...",
    }


def test_reporting_artifacts_characterize_command_text_precedence(tmp_path: Path) -> None:
    output = tmp_path / "out"
    display_dir = output / "scenarios" / "display"
    fallback_dir = output / "scenarios" / "fallback"
    display_dir.mkdir(parents=True)
    fallback_dir.mkdir(parents=True)
    (display_dir / "command-result.json").write_text(
        json.dumps(
            {
                "command": ["ignored", "list"],
                "command_display": "display wins",
            }
        ),
        encoding="utf-8",
    )
    (fallback_dir / "command-result.json").write_text(
        json.dumps(
            {
                "command": "not-a-list",
                "command_display": "",
            }
        ),
        encoding="utf-8",
    )
    (fallback_dir / "command.txt").write_text(" fallback command\nwith preserved newline ", encoding="utf-8")

    assert artifacts.command_artifact_summary(display_dir, output_root=output)["command"] == "display wins"
    assert artifacts.command_artifact_summary(fallback_dir, output_root=output)["command"] == (
        "fallback command\nwith preserved newline"
    )


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
        "risk_status_values": reports.known_status_values(),
        "target_runtime_verification": {"performed": False},
        "target_coverage": [
            {
                "target": "codex",
                "scope": "project",
                "status": "runnable",
                "install_command": ["graphify", "install", "--project", "--platform", "codex"],
            }
        ],
        "target_runtime_validation_sections": [
            {
                "section_title": "Synthetic Runtime Validation",
                "status": "payload_consistency_only",
                "evidence_path": None,
                "strategy": "payload consistency only",
                "targets": ["synthetic runtime", "synthetic mapping"],
                "notes": ["Linux sandbox does not prove synthetic target runtime behavior."],
            }
        ],
        "results": [
            {
                "id": "codex-project",
                "target": "codex",
                "scope": "project",
                "passed": True,
                "graphify_file_effects_passed": True,
                "overall_status": reports.RISK_GRAPHIFY_VERIFIED,
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
                "target": "cursor",
                "scope": "project",
                "passed": False,
                "graphify_file_effects_passed": False,
                "overall_status": reports.RISK_GRAPHIFY_FAILED,
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

    markdown = reports.render_report_md(manifest)

    for expected in (
        "# Graphify Install Sandbox Report",
        "## Environment",
        "Synthetic Linux",
        "| Target | Scope | Scenario | Graphify File Effects | Overall Status | Duration | Transcript |",
        "codex-project",
        "- Scenario count: 2.",
        "Target runtime verification: not performed by this Tier 1 file-effect sandbox.",
        "## Target Coverage",
        "| Target | Scope | Coverage | Graphify Installer Command |",
        "| codex | project | runnable | graphify install --project --platform codex |",
        "graphify cursor install",
        "boom",
        "scenarios/codex-project/transcript.txt",
        "2026-06-02T00:00:00Z",
        "## Synthetic Runtime Validation",
        "payload consistency only",
        "Linux sandbox does not prove synthetic target runtime behavior.",
    ):
        assert expected in markdown
    assert "target_runtime_verification" not in markdown
    assert "target_tool_runtime" not in markdown


def test_report_markdown_omits_target_runtime_validation_sections_when_metadata_absent() -> None:
    markdown = reports.render_report_md(
        {
            "results": [],
            "target_coverage": [],
            "windows_validation": {
                "status": "legacy_payload_consistency_only",
                "strategy": "legacy field must not render",
                "notes": ["legacy Windows metadata"],
            },
        }
    )

    assert "## Target Runtime Verification" in markdown
    assert "## Windows Validation" not in markdown
    assert "legacy field must not render" not in markdown
    assert "legacy Windows metadata" not in markdown


def test_target_runtime_validation_sections_are_registry_declared_manifest_data() -> None:
    sections = [
        {
            "section_title": "Arbitrary Target Runtime",
            "status": "payload_only",
            "evidence_path": "runtime/evidence.json",
            "strategy": "declared synthetic strategy",
            "targets": ["non-windows target"],
            "notes": ["declared note"],
        }
    ]

    markdown = reports.render_report_md({"results": [], "target_coverage": [], "target_runtime_validation_sections": sections})

    assert "## Arbitrary Target Runtime" in markdown
    assert "declared synthetic strategy" in markdown
    assert "non-windows target" in markdown
    assert "runtime/evidence.json" in markdown
    assert "declared note" in markdown


def test_report_renders_manifest_projection_fields_not_planner_alias_names() -> None:
    manifest = {
        "results": [],
        "target_coverage": [
            {
                "target": "codex",
                "scope": "project",
                "status": "runnable",
                "install_command": ["graphify", "install", "--platform", "codex"],
            }
        ],
        "target_runtime_validation_sections": [
            {
                "section_title": "Projected Runtime Boundary",
                "status": "payload_consistency_only",
                "evidence_path": None,
                "strategy": "render manifest projection only",
                "targets": ["codex"],
                "notes": ["planner alias names are compatibility paths, not report inputs"],
            }
        ],
        "selected_targets": ["must-not-render"],
        "platforms": ["must-not-render"],
        "coverage_records": [{"platform": "must-not-render"}],
        "runtime_limitation_sections": [
            {
                "section_title": "Must Not Render",
                "status": "legacy",
                "strategy": "legacy alias",
            }
        ],
    }

    markdown = reports.render_report_md(manifest)

    assert "## Target Coverage" in markdown
    assert "| codex | project | runnable | graphify install --platform codex |" in markdown
    assert "## Projected Runtime Boundary" in markdown
    assert "render manifest projection only" in markdown
    assert "must-not-render" not in markdown
    assert "Must Not Render" not in markdown
    assert "legacy alias" not in markdown


def test_report_reads_legacy_platform_coverage_as_transitional_input_only() -> None:
    markdown = reports.render_report_md(
        {
            "results": [{"id": "legacy-project", "platform": "legacy", "scope": "project", "passed": True}],
            "platform_coverage": [
                {
                    "platform": "legacy",
                    "scope": "project",
                    "status": "runnable",
                    "install_command": ["graphify", "install", "--platform", "legacy"],
                }
            ],
        }
    )

    assert "## Target Coverage" in markdown
    assert "| Target | Scope | Coverage | Graphify Installer Command |" in markdown
    assert "| legacy | project | runnable | graphify install --platform legacy |" in markdown
    assert "## Platform Coverage" not in markdown


def test_report_target_coverage_prefers_target_identity_over_stale_platform_alias() -> None:
    markdown = reports.render_report_md(
        {
            "results": [],
            "target_coverage": [
                {
                    "target": "codex",
                    "platform": "stale-platform-alias",
                    "scope": "project",
                    "status": "runnable",
                    "install_command": ["graphify", "install", "--platform", "codex"],
                }
            ],
            "platform_coverage": [
                {
                    "platform": "must-not-render",
                    "scope": "project",
                    "status": "stale-legacy-input",
                    "install_command": ["graphify", "install", "--platform", "must-not-render"],
                }
            ],
        }
    )

    assert "| codex | project | runnable | graphify install --platform codex |" in markdown
    assert "stale-platform-alias" not in markdown
    assert "must-not-render" not in markdown
    assert "stale-legacy-input" not in markdown


def test_report_prefers_explicit_empty_target_coverage_over_stale_legacy_rows() -> None:
    markdown = reports.render_report_md(
        {
            "results": [],
            "target_coverage": [],
            "platform_coverage": [
                {
                    "platform": "stale",
                    "scope": "project",
                    "status": "must-not-render",
                    "install_command": ["graphify", "install", "--platform", "stale"],
                }
            ],
        }
    )

    assert "## Target Coverage" in markdown
    assert "stale" not in markdown
    assert "must-not-render" not in markdown
    assert "graphify install --platform stale" not in markdown


def test_manifest_projection_plan_interface_names_reporting_inputs() -> None:
    assert set(manifest_projection.ManifestProjectionPlan.__annotations__) == {
        "standard_validation_count",
        "coverage_records",
        "target_runtime_validation_sections",
        "target_coverage_summary",
        "target_runtime_verification",
    }


def test_validation_plan_manifest_projection_returns_manifest_primitives() -> None:
    class Plan:
        standard_validation_count = 1
        coverage_records = (
            {
                "target": "codex",
                "platform": "stale-record-alias",
                "scope": "project",
                "status": "runnable",
                "install_command": ["graphify", "install", "--platform", "codex"],
            },
        )
        target_runtime_validation_sections = ({"section_title": "Projected Runtime", "status": "declared"},)
        target_coverage_summary = {
            "registered_target_count": 1,
            "requested_scope": "project",
            "runnable_scope_count": 1,
            "universal_scenario_count": 0,
            "unsupported_scope_count": 0,
        }
        target_runtime_verification = {"performed": False, "reason": "file effects only"}

        platform_coverage = ({"platform": "legacy-alias", "status": "must-not-project"},)
        runtime_limitation_sections = ({"section_title": "Legacy Alias", "status": "must-not-project"},)

    projected = manifest_projection.validation_plan_manifest_projection(
        Plan(),
        [
            {"id": "codex-project", "passed": True},
            {"id": "universal-cleanup", "passed": True},
        ],
    )

    assert projected == {
        "target_runtime_verification": {"performed": False, "reason": "file effects only"},
        "target_runtime_validation_sections": [{"section_title": "Projected Runtime", "status": "declared"}],
        "target_coverage": [
            {
                "target": "codex",
                "scope": "project",
                "status": "runnable",
                "install_command": ["graphify", "install", "--platform", "codex"],
            }
        ],
        "target_coverage_summary": {
            "registered_target_count": 1,
            "requested_scope": "project",
            "runnable_scope_count": 1,
            "universal_scenario_count": 1,
            "unsupported_scope_count": 0,
        },
        "scenario_count": 2,
    }
    assert "stale-record-alias" not in json.dumps(projected)
    assert "platform_coverage" not in projected


def test_harness_run_result_uses_reporting_manifest_projection(monkeypatch) -> None:
    class Plan:
        standard_validation_count = 1

    projection_calls: list[tuple[object, int]] = []

    def project_plan(plan_arg, results_arg):
        results_list = list(results_arg)
        projection_calls.append((plan_arg, len(results_list)))
        return {
            "target_runtime_verification": {"performed": False},
            "target_runtime_validation_sections": [],
            "target_coverage": [],
            "target_coverage_summary": {"universal_scenario_count": 1},
            "scenario_count": len(results_list),
        }

    monkeypatch.setattr(harness_run.manifest_projection, "validation_plan_manifest_projection", project_plan)
    plan = Plan()
    run_result = harness_run.harness_run_result(
        harness_version="test-harness",
        python_version="3.12 synthetic",
        os_release={"PRETTY_NAME": "Synthetic Linux"},
        architecture="x86_64",
        package_install={"version": "9.9.9"},
        source_snapshot={"root": "/tmp/src"},
        preflight={"project": "/tmp/project"},
        plan=plan,
        results=[{"id": "codex-project", "passed": True}, {"id": "cleanup", "passed": False}],
    )

    manifest = run_result.manifest()

    assert projection_calls == [(plan, 2)]
    assert run_result.passed == 1
    assert run_result.failed == 1
    assert manifest["graphify_version"] == "9.9.9"
    assert manifest["scenario_count"] == 2
    assert manifest["target_coverage_summary"] == {"universal_scenario_count": 1}
    assert manifest["graphify_file_effect_pass_count"] == 1
    assert manifest["graphify_file_effect_fail_count"] == 1
    assert manifest["risk_status_values"] == reporting_status.known_status_values()


def test_harness_run_output_writer_creates_coherent_artifact_bundle(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "out"
    output.mkdir()

    class Plan:
        standard_validation_count = 2
        coverage_records = (
            {
                "target": "codex",
                "platform": "stale-record-alias",
                "scope": "project",
                "status": "runnable",
                "install_command": ["graphify", "install", "--project", "--platform", "codex"],
            },
            {
                "target": "cursor",
                "platform": "stale-cursor-alias",
                "scope": "project",
                "status": "runnable",
                "install_command": ["graphify", "install", "--project", "--platform", "cursor"],
            },
        )
        target_runtime_validation_sections = ()
        target_coverage_summary = {
            "registered_target_count": 2,
            "requested_scope": "project",
            "runnable_scope_count": 2,
            "universal_scenario_count": 0,
            "unsupported_scope_count": 0,
        }
        target_runtime_verification = {"performed": False, "reason": "file effects only"}

    write_json(
        output / "scenarios" / "cursor-project" / "assertions.json",
        {
            "checks": [
                {"ok": True, "relative": "ok.md", "detail": "exists"},
                {"ok": False, "relative": "AGENTS.md", "root": "project", "detail": "missing Graphify block"},
            ]
        },
    )
    run_result = harness_run.harness_run_result(
        harness_version="test-harness",
        python_version="3.12 synthetic",
        os_release={"PRETTY_NAME": "Synthetic Linux"},
        architecture="x86_64",
        package_install={"version": "9.9.9", "package_name": "graphifyy"},
        source_snapshot={"root": "/tmp/src"},
        preflight={"project": "/tmp/project"},
        plan=Plan(),
        results=[
            {
                "id": "codex-project",
                "target": "codex",
                "scope": "project",
                "passed": True,
                "graphify_file_effects_passed": True,
                "overall_status": reports.RISK_GRAPHIFY_VERIFIED,
                "duration_ms": 42,
                "command_artifact": {
                    "command": "graphify install --project --platform codex",
                    "exit_code": 0,
                    "transcript_path": "scenarios/codex-project/transcript.txt",
                },
            },
            {
                "id": "cursor-project",
                "target": "cursor",
                "scope": "project",
                "passed": False,
                "graphify_file_effects_passed": False,
                "overall_status": reports.RISK_GRAPHIFY_FAILED,
                "duration_ms": 7,
                "reproduction_command": "graphify install --project --platform cursor",
                "command_artifact": {
                    "command": "graphify install --project --platform cursor",
                    "exit_code": 1,
                    "transcript_path": "scenarios/cursor-project/transcript.txt",
                    "stderr_snippet": "boom",
                },
            },
        ],
    )

    harness_run.write_harness_run_outputs(output, run_result)

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    report_markdown = (output / "report.md").read_text(encoding="utf-8")
    summary_json = json.loads((output / "agent-summary.json").read_text(encoding="utf-8"))
    summary_markdown = (output / "agent-summary.md").read_text(encoding="utf-8")
    stdout_summary = json.loads(capsys.readouterr().out)

    assert manifest["target_coverage"] == [
        {
            "target": "codex",
            "scope": "project",
            "status": "runnable",
            "install_command": ["graphify", "install", "--project", "--platform", "codex"],
        },
        {
            "target": "cursor",
            "scope": "project",
            "status": "runnable",
            "install_command": ["graphify", "install", "--project", "--platform", "cursor"],
        },
    ]
    assert "platform_coverage" not in manifest
    assert "stale-record-alias" not in json.dumps(manifest)
    assert "| codex | project | runnable | graphify install --project --platform codex |" in report_markdown
    assert "### cursor-project" in report_markdown
    assert "graphify install --project --platform cursor" in report_markdown
    assert "boom" in report_markdown
    assert "First read: `agent-summary.md`" in report_markdown
    assert summary_json["status"] == "FAIL"
    assert summary_json["failure_count"] == 1
    assert summary_json["failures"][0]["scenario"] == "cursor-project"
    assert summary_json["failures"][0]["failed_checks"] == [
        {"path": "AGENTS.md", "detail": "missing Graphify block", "root": "project"}
    ]
    assert "Status: **FAIL**" in summary_markdown
    assert "cursor-project" in summary_markdown
    assert "AGENTS.md: missing Graphify block" in summary_markdown
    assert stdout_summary["passed"] == 1
    assert stdout_summary["failed"] == 1
    assert stdout_summary["agent_summary"] == str(output / "agent-summary.md")


def test_harness_run_output_writer_preserves_summary_order(monkeypatch, tmp_path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    calls: list[str] = []

    class RunResult:
        passed = 1
        failed = 0

        def manifest(self) -> dict[str, object]:
            calls.append("manifest")
            return {"results": [], "target_coverage": [], "pass_count": 1, "fail_count": 0}

    def write_manifest(path, manifest):
        calls.append("write-manifest")
        path.write_text(json.dumps(manifest), encoding="utf-8")

    def write_report(path, manifest):
        calls.append("write-report")
        path.write_text("report\n", encoding="utf-8")

    def summarize_output(path):
        calls.append("summarize-output")
        assert (path / "manifest.json").exists()
        assert (path / "report.md").exists()
        return {"status": "PASS", "output": str(path), "failures": []}

    def write_summary(path, summary):
        calls.append("write-agent-summary")
        (path / "agent-summary.md").write_text("summary\n", encoding="utf-8")
        (path / "agent-summary.json").write_text(json.dumps(summary), encoding="utf-8")

    def print_summary(path, *, passed, failed):
        calls.append(f"stdout-summary:{passed}:{failed}")
        assert (path / "agent-summary.md").exists()
        assert (path / "agent-summary.json").exists()

    monkeypatch.setattr(harness_run.reports, "write_manifest_json", write_manifest)
    monkeypatch.setattr(harness_run.reports, "write_report_md", write_report)
    monkeypatch.setattr(harness_run.agent_summary, "summarize_output", summarize_output)
    monkeypatch.setattr(harness_run.agent_summary, "write_summary", write_summary)
    monkeypatch.setattr(harness_run.reports, "print_summary", print_summary)

    harness_run.write_harness_run_outputs(output, RunResult())

    assert calls == [
        "manifest",
        "write-manifest",
        "write-report",
        "summarize-output",
        "write-agent-summary",
        "stdout-summary:1:0",
    ]


def test_write_report_markdown(tmp_path) -> None:
    path = tmp_path / "report.md"

    reports.write_report_md(path, {"results": [], "target_coverage": []})

    assert "Graphify Install Sandbox Report" in path.read_text(encoding="utf-8")


def test_print_summary_includes_agent_summary_path(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    reports.print_summary(tmp_path, passed=1, failed=0)

    data = json.loads(capsys.readouterr().out)
    assert data["agent_summary"] == str(tmp_path / "agent-summary.md")
    assert data["target_runtime_verification_performed"] is False
