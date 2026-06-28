from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

try:
    from tools.install_sandbox.reporting.artifacts import (
        artifact_relpath,
        compact_path,
        load_json_object,
        normalized_text_snippet,
        tail_file,
    )
except ImportError:  # pragma: no cover - supports running this file directly.
    try:
        from reporting.artifacts import (  # type: ignore[no-redef]
            artifact_relpath,
            compact_path,
            load_json_object,
            normalized_text_snippet,
            tail_file,
        )
    except ImportError:
        from artifacts import (  # type: ignore[no-redef]
            artifact_relpath,
            compact_path,
            load_json_object,
            normalized_text_snippet,
            tail_file,
        )

USAGE_GUIDANCE = (
    "Use this as the first-read diagnostic. For FAIL, fix the listed failed checks "
    "using the reproduce command; inspect assertions/transcript only if the checks "
    "are insufficient. For INCOMPLETE, treat the blocker as preflight/package/container "
    "infrastructure unless artifacts show a code failure."
)


def load_json(path: Path) -> dict[str, Any]:
    return load_json_object(path)


def text_snippet(value: Any, *, limit: int = 240) -> str:
    return normalized_text_snippet(value, limit=limit)


def failed_checks(output_dir: Path, scenario_id: str, *, limit: int) -> list[dict[str, Any]]:
    assertions_path = output_dir / "scenarios" / scenario_id / "assertions.json"
    assertions = load_json(assertions_path)
    checks = assertions.get("checks") if isinstance(assertions.get("checks"), list) else []
    failed: list[dict[str, Any]] = []
    for check in checks:
        if not isinstance(check, dict) or check.get("ok") is True:
            continue
        detail = check.get("detail")
        if isinstance(detail, str) and detail.startswith("generic_direct_equivalent=True"):
            continue
        failed.append(
            {
                "path": check.get("relative") or compact_path(check.get("path")),
                "detail": detail,
                "root": check.get("root"),
            }
        )
        if len(failed) >= limit:
            break
    return failed


def summarize_incomplete(output_dir: Path, *, manifest_error: str | None = None) -> dict[str, Any]:
    preflight = load_json(output_dir / "preflight.json")
    package_dir = output_dir / "package-install"
    version_dir = package_dir / "graphify-version"

    package_exit = tail_file(package_dir / "exit-code.txt", limit=80)
    version_exit = tail_file(version_dir / "exit-code.txt", limit=80)
    package_stderr = text_snippet(tail_file(package_dir / "stderr.txt"), limit=360)
    version_stderr = text_snippet(tail_file(version_dir / "stderr.txt"), limit=360)

    reason = manifest_error or "manifest.json missing or unreadable"
    blocker = reason
    if package_exit and package_exit != "0":
        blocker = "Graphify package install failed"
    elif version_exit and version_exit != "0":
        blocker = "Graphify installer command probe failed"
    elif preflight:
        failed_preflight = [
            key
            for key, value in preflight.items()
            if key.endswith(("_exists", "_read_only", "_is_sandbox")) and value is False
        ]
        if failed_preflight:
            blocker = "Sandbox preflight failed: " + ", ".join(failed_preflight)

    summary: dict[str, Any] = {
        "status": "INCOMPLETE",
        "output": str(output_dir),
        "reason": reason,
        "blocker": blocker,
        "usage_guidance": USAGE_GUIDANCE,
        "target_runtime_verification_performed": False,
        "preflight": {
            "repo_mount_exists": preflight.get("repo_mount_exists"),
            "repo_mount_read_only": preflight.get("repo_mount_read_only"),
            "home_is_sandbox": preflight.get("home_is_sandbox"),
            "project_is_sandbox": preflight.get("project_is_sandbox"),
        },
        "next_read": "Read package-install or preflight artifacts if the blocker is insufficient.",
    }
    if package_exit:
        summary["package_install_exit"] = package_exit
    if package_stderr:
        summary["package_install_stderr_tail"] = package_stderr
    if version_exit:
        summary["graphify_version_exit"] = version_exit
    if version_stderr:
        summary["graphify_version_stderr_tail"] = version_stderr
    return summary


def summarize_output(output_dir: Path, *, max_failures: int = 5, max_checks: int = 6) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve()
    manifest_path = output_dir / "manifest.json"
    manifest = load_json(manifest_path)
    if not manifest or manifest.get("_error"):
        error = str(manifest.get("_error")) if manifest.get("_error") else None
        return summarize_incomplete(output_dir, manifest_error=error)

    results = manifest.get("results") if isinstance(manifest.get("results"), list) else []
    failures = [item for item in results if isinstance(item, dict) and item.get("passed") is not True]
    failure_summaries: list[dict[str, Any]] = []
    for item in failures[:max_failures]:
        scenario_id = str(item.get("id") or "")
        artifact = item.get("command_artifact") if isinstance(item.get("command_artifact"), dict) else {}
        checks = failed_checks(output_dir, scenario_id, limit=max_checks) if scenario_id else []
        failure: dict[str, Any] = {
            "scenario": scenario_id,
            "platform": item.get("platform"),
            "scope": item.get("scope"),
            "reproduce": item.get("reproduction_command") or artifact.get("command"),
            "exit": artifact.get("exit_code"),
            "transcript": artifact.get("transcript_path"),
            "assertions": artifact_relpath(output_dir / "scenarios" / scenario_id / "assertions.json", output_dir) if scenario_id else None,
            "failed_checks": checks,
        }
        if not checks:
            stderr = text_snippet(artifact.get("stderr_snippet"), limit=240)
            stdout = text_snippet(artifact.get("stdout_snippet"), limit=240)
            if stderr:
                failure["stderr"] = stderr
            if stdout:
                failure["stdout"] = stdout
        failure_summaries.append(failure)

    report_path = output_dir / "report.md"
    return {
        "status": "FAIL" if failures else "PASS",
        "output": str(output_dir),
        "report": str(report_path) if report_path.exists() else None,
        "graphify": {
            "version": manifest.get("graphify_version"),
            "passed": manifest.get("graphify_file_effect_pass_count", manifest.get("pass_count", 0)),
            "failed": manifest.get("graphify_file_effect_fail_count", manifest.get("fail_count", 0)),
            "scenarios": manifest.get("scenario_count", len(results)),
        },
        "target_runtime_verification_performed": False,
        "target_runtime_note": "Target runtime verification not performed by this Tier 1 file-effect sandbox.",
        "usage_guidance": USAGE_GUIDANCE,
        "failures": failure_summaries,
        "failure_count": len(failures),
        "next_read": "Read listed assertions/transcript files only if the failed checks are insufficient.",
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = ["# Install Sandbox Agent Summary", ""]
    lines.append(f"Status: **{summary.get('status')}**")
    lines.append(f"Output: `{summary.get('output')}`")
    if summary.get("report"):
        lines.append(f"Report: `{summary.get('report')}`")
    if summary.get("reason"):
        lines.append(f"Reason: {summary.get('reason')}")
    if summary.get("blocker"):
        lines.append(f"Blocker: {summary.get('blocker')}")
    if summary.get("usage_guidance"):
        lines.extend(["", str(summary.get("usage_guidance"))])

    graphify = summary.get("graphify") if isinstance(summary.get("graphify"), dict) else {}
    if graphify:
        lines.extend(
            [
                "",
                f"Graphify file effects: {graphify.get('passed')} passed, {graphify.get('failed')} failed, {graphify.get('scenarios')} scenarios, version {graphify.get('version')}.",
            ]
        )

    lines.extend(["", "Target runtime verification: not performed by this Tier 1 file-effect sandbox."])

    failures = summary.get("failures") if isinstance(summary.get("failures"), list) else []
    lines.extend(["", "Failures:"])
    if failures:
        for failure in failures:
            if not isinstance(failure, dict):
                continue
            lines.append(
                f"- `{failure.get('scenario')}` ({failure.get('platform')}/{failure.get('scope')}): reproduce `{failure.get('reproduce')}`; exit {failure.get('exit')}; transcript `{failure.get('transcript')}`"
            )
            checks = failure.get("failed_checks") if isinstance(failure.get("failed_checks"), list) else []
            for check in checks:
                if isinstance(check, dict):
                    path = check.get("path") or "<unknown>"
                    detail = check.get("detail") or "failed"
                    lines.append(f"  - {path}: {detail}")
            if not checks:
                if failure.get("stderr"):
                    lines.append(f"  - stderr: {failure.get('stderr')}")
                if failure.get("stdout"):
                    lines.append(f"  - stdout: {failure.get('stdout')}")
            if failure.get("assertions"):
                lines.append(f"  - assertions: `{failure.get('assertions')}`")
        if summary.get("failure_count", 0) > len(failures):
            lines.append(f"- {summary.get('failure_count') - len(failures)} additional failures omitted; inspect manifest/report.")
    else:
        lines.append("- None.")

    package_stderr = summary.get("package_install_stderr_tail")
    version_stderr = summary.get("graphify_version_stderr_tail")
    if package_stderr:
        lines.extend(["", f"Package install stderr: `{package_stderr}`"])
    if version_stderr:
        lines.extend(["", f"Graphify version stderr: `{version_stderr}`"])

    if summary.get("next_read"):
        lines.extend(["", str(summary.get("next_read"))])
    return "\n".join(lines).rstrip() + "\n"


def render_json(summary: dict[str, Any]) -> str:
    import json

    return json.dumps(summary, separators=(",", ":"), sort_keys=True) + "\n"


def write_summary(output_dir: Path, summary: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "agent-summary.md").write_text(render_markdown(summary), encoding="utf-8")
    (output_dir / "agent-summary.json").write_text(render_json(summary), encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize Graphify install sandbox artifacts for low-token agent consumption.")
    parser.add_argument("output", type=Path, help="Sandbox output directory containing manifest.json.")
    parser.add_argument("--json", action="store_true", help="Print compact JSON instead of Markdown.")
    parser.add_argument("--write", action="store_true", help="Write agent-summary.md and agent-summary.json into the output directory.")
    parser.add_argument("--max-failures", type=int, default=5)
    parser.add_argument("--max-checks", type=int, default=6)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    summary = summarize_output(args.output, max_failures=args.max_failures, max_checks=args.max_checks)
    if args.write:
        write_summary(args.output.expanduser().resolve(), summary)
    sys.stdout.write(render_json(summary) if args.json else render_markdown(summary))
    return 0 if summary.get("status") in {"PASS", "FAIL", "INCOMPLETE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
