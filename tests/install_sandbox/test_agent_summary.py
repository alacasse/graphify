from __future__ import annotations

import json
from pathlib import Path

from tools.install_sandbox import agent_summary


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def test_pass_manifest_reports_pass(tmp_path: Path) -> None:
    output = tmp_path / "out"
    write_json(
        output / "manifest.json",
        {
            "graphify_version": "9.9.9",
            "graphify_file_effect_pass_count": 2,
            "graphify_file_effect_fail_count": 0,
            "scenario_count": 2,
            "results": [{"id": "codex-project", "passed": True}, {"id": "cursor-project", "passed": True}],
        },
    )
    (output / "report.md").write_text("report\n", encoding="utf-8")

    summary = agent_summary.summarize_output(output)
    markdown = agent_summary.render_markdown(summary)

    assert summary["status"] == "PASS"
    assert summary["graphify"]["passed"] == 2
    assert summary["failures"] == []
    assert "first-read diagnostic" in summary["usage_guidance"]
    assert "For FAIL, fix the listed failed checks" in markdown
    assert "Target runtime verification: not performed" in markdown
    assert "Runtime:" not in markdown


def test_fail_manifest_includes_failed_assertions(tmp_path: Path) -> None:
    output = tmp_path / "out"
    write_json(
        output / "manifest.json",
        {
            "graphify_file_effect_pass_count": 0,
            "graphify_file_effect_fail_count": 1,
            "scenario_count": 1,
            "results": [
                {
                    "id": "codex-project",
                    "platform": "codex",
                    "scope": "project",
                    "passed": False,
                    "reproduction_command": "graphify install --project --platform codex",
                    "command_artifact": {
                        "exit_code": 0,
                        "transcript_path": "scenarios/codex-project/transcript.txt",
                    },
                }
            ],
        },
    )
    write_json(
        output / "scenarios" / "codex-project" / "assertions.json",
        {
            "checks": [
                {"ok": True, "relative": "AGENTS.md", "detail": "exists"},
                {"ok": False, "relative": "AGENTS.md", "root": "project", "detail": "missing Graphify block"},
            ]
        },
    )

    summary = agent_summary.summarize_output(output)
    markdown = agent_summary.render_markdown(summary)

    assert summary["status"] == "FAIL"
    assert summary["failure_count"] == 1
    assert summary["failures"][0]["failed_checks"] == [
        {"path": "AGENTS.md", "detail": "missing Graphify block", "root": "project"}
    ]
    assert "AGENTS.md: missing Graphify block" in markdown
    assert "scenarios/codex-project/assertions.json" in markdown


def test_fail_manifest_uses_command_snippets_when_assertions_have_no_failed_checks(tmp_path: Path) -> None:
    output = tmp_path / "out"
    write_json(
        output / "manifest.json",
        {
            "results": [
                {
                    "id": "cursor-project",
                    "platform": "cursor",
                    "scope": "project",
                    "passed": False,
                    "command_artifact": {
                        "command": "graphify install --platform cursor",
                        "exit_code": 1,
                        "transcript_path": "scenarios/cursor-project/transcript.txt",
                        "stdout_snippet": "starting install",
                        "stderr_snippet": "permission denied",
                    },
                }
            ],
        },
    )
    write_json(output / "scenarios" / "cursor-project" / "assertions.json", {"checks": []})

    summary = agent_summary.summarize_output(output)

    assert summary["status"] == "FAIL"
    assert summary["failures"][0]["failed_checks"] == []
    assert summary["failures"][0]["stderr"] == "permission denied"
    assert summary["failures"][0]["stdout"] == "starting install"


def test_incomplete_missing_manifest_reports_preflight_blocker(tmp_path: Path) -> None:
    output = tmp_path / "out"
    write_json(
        output / "preflight.json",
        {
            "repo_mount_exists": True,
            "repo_mount_read_only": False,
            "home_is_sandbox": True,
            "project_is_sandbox": True,
        },
    )

    summary = agent_summary.summarize_output(output)

    assert summary["status"] == "INCOMPLETE"
    assert summary["blocker"] == "Sandbox preflight failed: repo_mount_read_only"
    assert "For INCOMPLETE, treat the blocker" in summary["usage_guidance"]


def test_incomplete_package_install_failure_details(tmp_path: Path) -> None:
    output = tmp_path / "out"
    package = output / "package-install"
    package.mkdir(parents=True)
    (package / "exit-code.txt").write_text("1\n", encoding="utf-8")
    (package / "stderr.txt").write_text("ERROR: package build failed\nfull details\n", encoding="utf-8")

    summary = agent_summary.summarize_output(output)
    markdown = agent_summary.render_markdown(summary)

    assert summary["status"] == "INCOMPLETE"
    assert summary["blocker"] == "Graphify package install failed"
    assert summary["package_install_exit"] == "1"
    assert summary["package_install_stderr_tail"] == "ERROR: package build failed full details"
    assert "Package install stderr" in markdown


def test_write_summary_writes_markdown_and_json(tmp_path: Path) -> None:
    output = tmp_path / "out"
    summary = {"status": "PASS", "output": str(output), "failures": []}

    agent_summary.write_summary(output, summary)

    assert (output / "agent-summary.md").read_text(encoding="utf-8").startswith("# Install Sandbox Agent Summary")
    assert json.loads((output / "agent-summary.json").read_text(encoding="utf-8"))["status"] == "PASS"
