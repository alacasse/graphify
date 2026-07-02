from __future__ import annotations

from tools.install_sandbox.reporting import reports


def current_generated_report_manifest() -> dict[str, object]:
    return {
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
        "target_coverage_summary": {
            "registered_target_count": 2,
            "requested_scope": "project",
            "runnable_scope_count": 1,
            "universal_scenario_count": 0,
            "unsupported_scope_count": 1,
        },
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


def legacy_platform_coverage_input_only_manifest() -> dict[str, object]:
    return {
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


def current_generated_failure_manifest() -> dict[str, object]:
    return {
        "graphify_file_effect_pass_count": 0,
        "graphify_file_effect_fail_count": 1,
        "scenario_count": 1,
        "results": [
            {
                "id": "codex-project",
                "target": "codex",
                "scope": "project",
                "passed": False,
                "reproduction_command": "graphify install --project --platform codex",
                "command_artifact": {
                    "exit_code": 0,
                    "transcript_path": "scenarios/codex-project/transcript.txt",
                },
            }
        ],
    }


def legacy_platform_failure_input_only_manifest() -> dict[str, object]:
    return {
        "results": [
            {
                "id": "legacy-project",
                "platform": "legacy",
                "scope": "project",
                "passed": False,
                "command_artifact": {
                    "command": "graphify install --platform legacy",
                    "exit_code": 1,
                    "transcript_path": "scenarios/legacy-project/transcript.txt",
                },
            }
        ],
    }
