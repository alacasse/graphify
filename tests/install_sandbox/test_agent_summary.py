from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.install_sandbox import agent_summary as root_agent_summary
from tools.install_sandbox.reporting import agent_summary


def test_root_agent_summary_wrapper_preserves_module_entrypoint_compatibility() -> None:
    assert root_agent_summary.main is agent_summary.main
    assert root_agent_summary.summarize_output is agent_summary.summarize_output
    # Root __all__ is the compatibility surface. Helper behavior below is
    # migration characterization, not new public API.
    assert root_agent_summary.__all__ == [
        "USAGE_GUIDANCE",
        "artifact_relpath",
        "compact_path",
        "failed_checks",
        "load_json",
        "main",
        "parse_args",
        "render_json",
        "render_markdown",
        "summarize_incomplete",
        "summarize_output",
        "tail_file",
        "text_snippet",
        "write_summary",
    ]


def test_reporting_agent_summary_direct_script_help() -> None:
    repo_root = Path(__file__).parents[2]
    result = subprocess.run(
        [sys.executable, "tools/install_sandbox/reporting/agent_summary.py", "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Summarize Graphify install sandbox artifacts" in result.stdout


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def test_agent_summary_artifact_helpers_characterize_current_contract(tmp_path: Path) -> None:
    output = tmp_path / "out"
    scenario_dir = output / "scenarios" / "codex-project"
    scenario_dir.mkdir(parents=True)
    write_json(output / "object.json", {"ok": True})
    write_json(output / "array.json", [])
    (output / "invalid.json").write_text("{", encoding="utf-8")
    (output / "tail.txt").write_text("0123456789", encoding="utf-8")
    write_json(
        scenario_dir / "assertions.json",
        {
            "checks": [
                {"ok": False, "relative": "AGENTS.md", "root": "project", "detail": "missing Graphify block"},
                {"ok": False, "path": "/tmp/graphify-home/.codex/AGENTS.md", "root": "home", "detail": "missing local block"},
                {"ok": False, "relative": "skip.md", "detail": "generic_direct_equivalent=True"},
                {"ok": True, "relative": "ok.md", "detail": "exists"},
            ]
        },
    )

    assert agent_summary.load_json(output / "object.json") == {"ok": True}
    assert agent_summary.load_json(output / "missing.json") == {}
    assert agent_summary.load_json(output / "array.json") == {"_error": "json root is not an object"}
    assert agent_summary.load_json(output / "invalid.json")["_error"].startswith("invalid json:")
    assert agent_summary.artifact_relpath(scenario_dir / "assertions.json", output) == "scenarios/codex-project/assertions.json"
    assert agent_summary.artifact_relpath(tmp_path / "elsewhere.txt", output) == str(tmp_path / "elsewhere.txt")
    assert agent_summary.compact_path("/tmp/graphify-project/AGENTS.md") == "project/AGENTS.md"
    assert agent_summary.compact_path("/tmp/graphify-home/.codex/AGENTS.md") == "home/.codex/AGENTS.md"
    assert agent_summary.compact_path("/tmp/graphify-user-cwd/file.txt") == "user_cwd/file.txt"
    assert agent_summary.compact_path(123) == ""
    assert agent_summary.text_snippet(" alpha\n\n beta\tgamma ", limit=20) == "alpha beta gamma"
    assert agent_summary.text_snippet("abcdefghij", limit=8) == "abcde..."
    assert agent_summary.tail_file(output / "tail.txt", limit=4) == "6789"
    assert agent_summary.tail_file(output / "missing-tail.txt") == ""
    assert agent_summary.failed_checks(output, "codex-project", limit=2) == [
        {"path": "AGENTS.md", "detail": "missing Graphify block", "root": "project"},
        {"path": "home/.codex/AGENTS.md", "detail": "missing local block", "root": "home"},
    ]


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
    assert summary["graphify"]["scenarios"] == 2
    assert summary["target_runtime_verification_performed"] is False
    assert summary["failures"] == []
    assert "first-read diagnostic" in summary["usage_guidance"]
    assert "For FAIL, fix the listed failed checks" in markdown
    assert "Target runtime verification: not performed" in markdown
    assert "Runtime:" not in markdown
    assert "target_tool_runtime" not in json.dumps(summary)


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
