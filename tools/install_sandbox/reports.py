from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Iterable

try:
    from .json_helpers import object_dict, object_dicts, object_list
    from .status import RISK_GRAPHIFY_FAILED, RISK_GRAPHIFY_VERIFIED, known_status_values
except ImportError:
    from json_helpers import object_dict, object_dicts, object_list
    from status import RISK_GRAPHIFY_FAILED, RISK_GRAPHIFY_VERIFIED, known_status_values


def artifact_relpath(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def read_json_object(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def text_snippet(path: Path, limit: int = 500) -> str:
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def command_artifact_summary(artifact_dir: Path, *, output_root: Path) -> dict[str, object]:
    result = read_json_object(artifact_dir / "command-result.json")
    command = result.get("command")
    command_text = str(result.get("command_display") or (shlex.join([str(part) for part in command]) if isinstance(command, list) else text_snippet(artifact_dir / "command.txt", 1000)))
    return {
        "command": command_text,
        "command_class": result.get("command_class"),
        "started_at": result.get("started_at"),
        "duration_ms": result.get("duration_ms"),
        "exit_code": result.get("exit_code"),
        "timeout_seconds": result.get("timeout_seconds"),
        "timed_out": result.get("timed_out"),
        "transcript_path": artifact_relpath(artifact_dir / "transcript.txt", output_root),
        "stdout_snippet": text_snippet(artifact_dir / "stdout.txt"),
        "stderr_snippet": text_snippet(artifact_dir / "stderr.txt"),
    }


def status_label(result: dict[str, object]) -> str:
    if "overall_status" in result:
        return str(result["overall_status"])
    if result.get("passed") is True:
        return RISK_GRAPHIFY_VERIFIED
    return RISK_GRAPHIFY_FAILED


def md_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("\n", " ").replace("|", "\\|")


def md_code(value: object) -> str:
    text = "" if value is None else str(value)
    return "`" + text.replace("`", "'") + "`"


def md_row(cells: Iterable[object]) -> str:
    return "| " + " | ".join(md_cell(cell) for cell in cells) + " |"


def md_separator(column_count: int, *, right_align: Iterable[int] = ()) -> str:
    aligned = set(right_align)
    return "|" + "|".join("---:" if index in aligned else "---" for index in range(column_count)) + "|"


def md_table(headers: Iterable[str], rows: Iterable[Iterable[object]], *, right_align: Iterable[int] = ()) -> list[str]:
    header_list = list(headers)
    lines = [md_row(header_list), md_separator(len(header_list), right_align=right_align)]
    lines.extend(md_row(row) for row in rows)
    return lines


def render_report_md(manifest: dict[str, object]) -> str:
    package = object_dict(manifest.get("package_install"))
    preflight_data = object_dict(manifest.get("preflight"))
    os_release = object_dict(manifest.get("os_release"))
    source_snapshot = object_dict(manifest.get("source_snapshot"))
    results = object_dicts(manifest.get("results"))
    coverage = object_dicts(manifest.get("platform_coverage"))
    validation_sections = object_dicts(manifest.get("target_runtime_validation_sections"))
    risk_status_values = object_list(manifest.get("risk_status_values")) or list(known_status_values())

    lines: list[str] = ["# Graphify Install Sandbox Report", ""]
    lines.extend(
        [
            "## Summary",
            "",
            f"- Graphify file effects: {manifest.get('graphify_file_effect_pass_count', manifest.get('pass_count', 0))} passed, {manifest.get('graphify_file_effect_fail_count', manifest.get('fail_count', 0))} failed.",
            "- Target runtime verification: not performed by this Tier 1 file-effect sandbox.",
            f"- Scenario count: {manifest.get('scenario_count', len(results))}.",
            f"- Artifacts: {md_code('manifest.json')}, {md_code('preflight.json')}, {md_code('package-install/')}, {md_code('scenarios/')}.",
            "",
            "## Environment",
            "",
            *md_table(
                ["Field", "Value"],
                [
                    ("OS", os_release.get("PRETTY_NAME") or os_release.get("NAME")),
                    ("Architecture", manifest.get("architecture")),
                    ("Python", manifest.get("python_version")),
                    ("Graphify version", manifest.get("graphify_version")),
                    ("Install mode", package.get("install_mode")),
                    ("Package name", package.get("package_name")),
                    ("Install location", package.get("location")),
                    ("Installed from copied source", package.get("installed_from_copied_source")),
                    ("Source root", source_snapshot.get("root")),
                    ("Sandbox project", preflight_data.get("project")),
                ],
            ),
            "",
            "## Status Vocabulary",
            "",
        ]
    )
    for status in risk_status_values:
        lines.append(f"- {md_code(status)}")
    lines.extend(["", "## Scenario Status", ""])
    scenario_rows = []
    for item in results:
        graphify_status = RISK_GRAPHIFY_VERIFIED if item.get("graphify_file_effects_passed", item.get("passed")) else RISK_GRAPHIFY_FAILED
        command_artifact = object_dict(item.get("command_artifact"))
        duration = item.get("duration_ms") or command_artifact.get("duration_ms")
        transcript = command_artifact.get("transcript_path") or item.get("transcript_path") or ""
        scenario_rows.append(
            (
                item.get("platform"),
                item.get("scope"),
                item.get("id"),
                graphify_status,
                status_label(item),
                f"{duration} ms" if duration is not None else "",
                transcript,
            )
        )
    lines.extend(md_table(["Platform", "Scope", "Scenario", "Graphify File Effects", "Overall Status", "Duration", "Transcript"], scenario_rows, right_align={5}))

    lines.extend(["", "## Platform Coverage", ""])
    coverage_rows = []
    for record in coverage:
        command = record.get("install_command")
        command_text = shlex.join([str(part) for part in command]) if isinstance(command, list) else record.get("reason", "")
        coverage_rows.append((record.get("platform"), record.get("scope"), record.get("status"), command_text))
    lines.extend(md_table(["Platform", "Scope", "Coverage", "Graphify Installer Command"], coverage_rows))

    lines.extend(["", "## Target Runtime Verification", "", "- Not performed by this sandbox. The report validates Graphify-owned installer file effects only."])

    for validation in validation_sections:
        section_title = str(validation.get("section_title") or "Target Runtime Validation")
        lines.extend(
            [
                "",
                f"## {md_cell(section_title)}",
                "",
                f"- Status: {md_code(validation.get('status'))}",
                f"- Evidence: {md_code(validation.get('evidence_path'))}",
                f"- Strategy: {md_cell(validation.get('strategy'))}",
            ]
        )
        notes = object_list(validation.get("notes"))
        targets = object_list(validation.get("targets"))
        for note in notes:
            lines.append(f"- {md_cell(note)}")
        if targets:
            lines.append(f"- Targets: {md_cell(', '.join(str(target) for target in targets))}")

    failures = [item for item in results if item.get("passed") is not True]
    lines.extend(["", "## Failures", ""])
    if failures:
        for item in failures:
            command_artifact = object_dict(item.get("command_artifact"))
            lines.append(f"### {item.get('id')}")
            lines.append("")
            lines.append(f"- Reproduce: {md_code(item.get('reproduction_command') or command_artifact.get('command'))}")
            lines.append(f"- Transcript: {md_code(command_artifact.get('transcript_path') or item.get('transcript_path'))}")
            if command_artifact.get("stdout_snippet"):
                lines.append(f"- stdout: {md_code(command_artifact.get('stdout_snippet'))}")
            if command_artifact.get("stderr_snippet"):
                lines.append(f"- stderr: {md_code(command_artifact.get('stderr_snippet'))}")
            lines.append("")
    else:
        lines.append("- None.")

    lines.extend(["", "## Command Transcripts", ""])
    transcript_rows = []
    for item in results:
        command_artifact = object_dict(item.get("command_artifact"))
        if not command_artifact:
            continue
        transcript_rows.append(
            (
                item.get("id"),
                command_artifact.get("command"),
                command_artifact.get("started_at"),
                command_artifact.get("duration_ms"),
                command_artifact.get("exit_code"),
                command_artifact.get("transcript_path"),
            )
        )
    lines.extend(md_table(["Scenario", "Command", "Started", "Duration", "Exit", "Transcript"], transcript_rows, right_align={3, 4}))

    return "\n".join(lines).rstrip() + "\n"


def write_report_md(path: Path, manifest: dict[str, object]) -> None:
    path.write_text(render_report_md(manifest), encoding="utf-8")


def write_manifest_json(path: Path, manifest: dict[str, object]) -> None:
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def print_summary(output: Path, *, passed: int, failed: int) -> None:
    print(
        json.dumps(
            {
                "passed": passed,
                "failed": failed,
                "output": str(output),
                "report": str(output / "report.md"),
                "target_runtime_verification_performed": False,
            },
            indent=2,
        ),
        flush=True,
    )
