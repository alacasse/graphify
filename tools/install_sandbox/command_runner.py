from __future__ import annotations

import json
import shlex
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


COMMAND_TIMEOUTS = {
    "package_install": 600,
    "graphify_version": 60,
    "installer": 120,
    "precondition": 60,
}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def timeout_for(command_class: str, timeout_seconds: int | None = None) -> int:
    return timeout_seconds if timeout_seconds is not None else COMMAND_TIMEOUTS.get(command_class, COMMAND_TIMEOUTS["installer"])


def timeout_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return "" if value is None else str(value)


def command_display(command: Iterable[str]) -> tuple[list[str], str]:
    command_list = list(command)
    return command_list, shlex.join(command_list)


def write_command_start_artifacts(artifact_dir: Path, command_text: str, env: dict[str, str]) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "command.txt").write_text(command_text + "\n", encoding="utf-8")
    (artifact_dir / "env.json").write_text(json.dumps({k: env.get(k, "") for k in sorted(("HOME", "XDG_CONFIG_HOME", "PATH", "GRAPHIFY_PROJECT"))}, indent=2) + "\n", encoding="utf-8")


def execute_command(command_list: list[str], *, cwd: Path, env: dict[str, str], timeout: int) -> tuple[subprocess.CompletedProcess[str], bool]:
    try:
        return subprocess.run(command_list, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout), False
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(command_list, 127, "", str(exc)), False
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(command_list, 124, timeout_text(exc.stdout), timeout_text(exc.stderr) or f"timed out after {timeout} seconds"), True


def command_result_metadata(
    *,
    command_list: list[str],
    command_text: str,
    command_class: str,
    cwd: Path,
    started_at: str,
    duration_ms: int,
    exit_code: int,
    timeout: int,
    timed_out: bool,
) -> dict[str, object]:
    return {
        "command": command_list,
        "command_display": command_text,
        "command_class": command_class,
        "cwd": str(cwd),
        "started_at": started_at,
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "timeout_seconds": timeout,
        "timed_out": timed_out,
    }


def write_command_result_artifacts(artifact_dir: Path, result: subprocess.CompletedProcess[str], metadata: dict[str, object]) -> None:
    (artifact_dir / "stdout.txt").write_text(result.stdout, encoding="utf-8")
    (artifact_dir / "stderr.txt").write_text(result.stderr, encoding="utf-8")
    (artifact_dir / "exit-code.txt").write_text(f"{result.returncode}\n", encoding="utf-8")
    (artifact_dir / "command-result.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (artifact_dir / "transcript.txt").write_text(
        f"$ {metadata['command_display']}\n[command-class]\n{metadata['command_class']}\n[timeout-seconds]\n{metadata['timeout_seconds']}\n[started-at]\n{metadata['started_at']}\n[duration-ms]\n{metadata['duration_ms']}\n[timed-out]\n{str(metadata['timed_out']).lower()}\n\n[stdout]\n{result.stdout}\n[stderr]\n{result.stderr}\n[exit-code]\n{result.returncode}\n",
        encoding="utf-8",
    )


def attach_command_metadata(result: subprocess.CompletedProcess[str], metadata: dict[str, object]) -> None:
    result.started_at = metadata["started_at"]  # type: ignore[attr-defined]
    result.duration_ms = metadata["duration_ms"]  # type: ignore[attr-defined]
    result.timed_out = metadata["timed_out"]  # type: ignore[attr-defined]
    result.timeout_seconds = metadata["timeout_seconds"]  # type: ignore[attr-defined]
    result.command_class = metadata["command_class"]  # type: ignore[attr-defined]


def run_capture(
    command: Iterable[str],
    *,
    cwd: Path,
    env: dict[str, str],
    artifact_dir: Path | None = None,
    command_class: str = "installer",
    timeout_seconds: int | None = None,
) -> subprocess.CompletedProcess[str]:
    command_list, command_text = command_display(command)
    timeout = timeout_for(command_class, timeout_seconds)
    started_at = utc_timestamp()
    start = time.monotonic()
    if artifact_dir is not None:
        write_command_start_artifacts(artifact_dir, command_text, env)
    result, timed_out = execute_command(command_list, cwd=cwd, env=env, timeout=timeout)
    duration_ms = int((time.monotonic() - start) * 1000)
    metadata = command_result_metadata(
        command_list=command_list,
        command_text=command_text,
        command_class=command_class,
        cwd=cwd,
        started_at=started_at,
        duration_ms=duration_ms,
        exit_code=result.returncode,
        timeout=timeout,
        timed_out=timed_out,
    )
    if artifact_dir is not None:
        write_command_result_artifacts(artifact_dir, result, metadata)
    attach_command_metadata(result, metadata)
    return result
