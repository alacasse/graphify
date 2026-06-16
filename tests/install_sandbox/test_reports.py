from __future__ import annotations

import json

import pytest

from tools.install_sandbox import platform_specs, reports, status


def test_known_status_values_are_serializable_file_effect_statuses() -> None:
    encoded = json.dumps({"risk_status_values": reports.known_status_values()})

    assert reports.RISK_GRAPHIFY_VERIFIED in encoded
    assert reports.RISK_GRAPHIFY_FAILED in encoded
    assert "target_tool_runtime" not in encoded


def test_reports_reexport_shared_status_values() -> None:
    assert reports.RISK_GRAPHIFY_VERIFIED == status.RISK_GRAPHIFY_VERIFIED == "graphify_install_verified"
    assert reports.RISK_GRAPHIFY_FAILED == status.RISK_GRAPHIFY_FAILED == "graphify_install_failed"
    assert reports.known_status_values() == status.known_status_values()


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
        "platform_coverage": [
            {
                "platform": "codex",
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
                "platform": "codex",
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
                "platform": "cursor",
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
        "| Platform | Scope | Scenario | Graphify File Effects | Overall Status | Duration | Transcript |",
        "codex-project",
        "- Scenario count: 2.",
        "Target runtime verification: not performed by this Tier 1 file-effect sandbox.",
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
            "platform_coverage": [],
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
    registry = platform_specs.ScenarioRegistry(
        {
            "arbitrary-target": platform_specs.PlatformSpec(
                name="arbitrary-target",
                target_runtime_validation=(
                    platform_specs.TargetRuntimeValidationSpec(
                        section_title="Arbitrary Target Runtime",
                        status="payload_only",
                        evidence_path="runtime/evidence.json",
                        strategy="declared synthetic strategy",
                        targets=("non-windows target",),
                        notes=("declared note",),
                    ),
                ),
            )
        }
    )
    sections = registry.target_runtime_validation_sections()

    markdown = reports.render_report_md({"results": [], "platform_coverage": [], "target_runtime_validation_sections": sections})

    assert "## Arbitrary Target Runtime" in markdown
    assert "declared synthetic strategy" in markdown
    assert "non-windows target" in markdown
    assert "runtime/evidence.json" in markdown


def test_write_report_markdown(tmp_path) -> None:
    path = tmp_path / "report.md"

    reports.write_report_md(path, {"results": [], "platform_coverage": []})

    assert "Graphify Install Sandbox Report" in path.read_text(encoding="utf-8")


def test_print_summary_includes_agent_summary_path(tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    reports.print_summary(tmp_path, passed=1, failed=0)

    data = json.loads(capsys.readouterr().out)
    assert data["agent_summary"] == str(tmp_path / "agent-summary.md")
    assert data["target_runtime_verification_performed"] is False
