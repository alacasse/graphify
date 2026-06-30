from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any


def artifact_relpath(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def compact_path(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    replacements = {
        "/tmp/graphify-project/": "project/",
        "/tmp/graphify-home/": "home/",
        "/tmp/graphify-user-cwd/": "user_cwd/",
    }
    for prefix, replacement in replacements.items():
        if value.startswith(prefix):
            return replacement + value[len(prefix) :]
    return value


def read_json_object(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        return {"_error": f"invalid json: {exc}"}
    return data if isinstance(data, dict) else {"_error": "json root is not an object"}


def file_text_snippet(path: Path, limit: int = 500) -> str:
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def normalized_text_snippet(value: Any, *, limit: int = 240) -> str:
    if not isinstance(value, str):
        return ""
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def tail_file(path: Path, *, limit: int = 600) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[-limit:]


def command_artifact_summary(artifact_dir: Path, *, output_root: Path) -> dict[str, object]:
    result = read_json_object(artifact_dir / "command-result.json")
    command = result.get("command")
    command_text = str(
        result.get("command_display")
        or (shlex.join([str(part) for part in command]) if isinstance(command, list) else file_text_snippet(artifact_dir / "command.txt", 1000))
    )
    return {
        "command": command_text,
        "command_class": result.get("command_class"),
        "started_at": result.get("started_at"),
        "duration_ms": result.get("duration_ms"),
        "exit_code": result.get("exit_code"),
        "timeout_seconds": result.get("timeout_seconds"),
        "timed_out": result.get("timed_out"),
        "transcript_path": artifact_relpath(artifact_dir / "transcript.txt", output_root),
        "stdout_snippet": file_text_snippet(artifact_dir / "stdout.txt"),
        "stderr_snippet": file_text_snippet(artifact_dir / "stderr.txt"),
    }


def failed_checks(output_dir: Path, scenario_id: str, *, limit: int) -> list[dict[str, Any]]:
    assertions_path = output_dir / "scenarios" / scenario_id / "assertions.json"
    assertions = load_json_object(assertions_path)
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


def failure_summary(item: dict[str, Any], *, output_dir: Path, max_checks: int) -> dict[str, Any]:
    scenario_id = str(item.get("id") or "")
    artifact = item.get("command_artifact") if isinstance(item.get("command_artifact"), dict) else {}
    checks = failed_checks(output_dir, scenario_id, limit=max_checks) if scenario_id else []
    failure: dict[str, Any] = {
        "scenario": scenario_id,
        "target": item.get("target") or item.get("platform"),
        "scope": item.get("scope"),
        "reproduce": item.get("reproduction_command") or artifact.get("command"),
        "exit": artifact.get("exit_code"),
        "transcript": artifact.get("transcript_path"),
        "assertions": artifact_relpath(output_dir / "scenarios" / scenario_id / "assertions.json", output_dir) if scenario_id else None,
        "failed_checks": checks,
    }
    if not checks:
        stderr = normalized_text_snippet(artifact.get("stderr_snippet"), limit=240)
        stdout = normalized_text_snippet(artifact.get("stdout_snippet"), limit=240)
        if stderr:
            failure["stderr"] = stderr
        if stdout:
            failure["stdout"] = stdout
    return failure
