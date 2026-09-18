"""End-of-campaign retention with conservative writer and ownership checks."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

from tools.install_sandbox.contracts.results import EvidenceWriteError
from tools.install_sandbox.host.docker_runtime import runtime_identity
from tools.install_sandbox.host.output_report import OutputReport, Writer, read_report
from tools.install_sandbox.host.output_storage import (
    FileLock,
    campaign_directories,
    coordination,
    identity_matches,
    safe_path,
)

_RETENTION = timedelta(days=14)


def _runtime_query(runtime: str, arguments: list[str]) -> str:
    result = subprocess.run(
        [runtime, *arguments], capture_output=True, text=True, timeout=10, check=False
    )
    if result.returncode != 0:
        raise ValueError("Docker activity inspection unavailable")
    return result.stdout.strip()


def writer_stopped(writer: Writer, runtime: str) -> bool:
    if writer.state == "stopped":
        return True
    if runtime_identity(runtime) != writer.runtime:
        return False
    daemon = _runtime_query(runtime, ["info", "--format", "{{.ID}}"])
    if daemon != writer.daemon_id:
        return False
    found = _runtime_query(
        runtime, ["container", "ls", "--all", "--quiet", "--filter", f"name=^/{writer.name}$"]
    )
    if not found:
        # An intent may still have a surviving client with a delayed launch request.
        return writer.state == "returned"
    value = cast(
        list[dict[str, object]], json.loads(_runtime_query(runtime, ["inspect", writer.name]))
    )
    return len(value) == 1 and _terminal_container(value[0], writer.name)


def _terminal_container(data: dict[str, object], name: str) -> bool:
    state = cast(dict[str, object], data["State"])
    host = cast(dict[str, object], data["HostConfig"])
    restart = cast(dict[str, object], host["RestartPolicy"])
    return (
        data["Name"] == "/" + name
        and state["Status"] in {"exited", "dead"}
        and state["Running"] is False
        and state["Restarting"] is False
        and state["Paused"] is False
        and restart["Name"] in {"", "no"}
    )


def retain_finished(
    root: Path, current: Path, runtime: str, now: Callable[[], datetime]
) -> list[str]:
    diagnostics: list[str] = []
    try:
        with coordination(root):
            candidates = list(campaign_directories(root))
    except OSError as error:
        return [f"Retention scan unavailable at {root}: {error}; retry at next campaign end"]
    for directory in candidates:
        if directory == current:
            continue
        try:
            _consider(directory, root, runtime, now, diagnostics)
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            EvidenceWriteError,
            subprocess.SubprocessError,
        ) as error:
            diagnostics.append(f"Retained {directory}: {error}; retry at the next campaign end")
    return diagnostics


def _consider(
    directory: Path,
    root: Path,
    runtime: str,
    now: Callable[[], datetime],
    diagnostics: list[str],
) -> None:
    with coordination(root):
        safe_path(directory)
        report = read_report(directory, root)
        identity = directory.stat()
        lock = FileLock(directory / ".active.lock")
        if not lock.acquire(wait=False):
            lock.close()
            return
    try:
        # Docker may block; no global lock is held here.
        if not all(writer_stopped(writer, runtime) for writer in report.writers):
            diagnostics.append(f"Retained {directory}: writer activity uncertain; inspect manually")
            return
        current = directory.stat()
        if (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
            diagnostics.append(f"Retained {directory}: directory changed during inspection")
            return
        _expire(directory, root, report, now(), diagnostics)
    finally:
        try:
            with coordination(root):
                lock.remove_file(directory / ".active.lock")
        finally:
            lock.close()


def _expire(
    directory: Path, root: Path, report: OutputReport, now: datetime, diagnostics: list[str]
) -> None:
    with coordination(root):
        if not identity_matches(directory, report, root):
            diagnostics.append(
                f"Retained {directory}: identity or report changed during inspection"
            )
            return
        if report.finished_at is None and report.stopped_observed_at is None:
            report.stopped_observed_at = now.isoformat()
            report.save(directory)
        end = datetime.fromisoformat(report.finished_at or report.stopped_observed_at or "")
        if end.tzinfo is None or now - end < _RETENTION:
            return
    # Keep the report/reservation and activity lock until every other entry is gone.
    for path in directory.iterdir():
        if path.name not in {"campaign.json", "campaign.txt", ".active.lock"}:
            _remove(path)
    with coordination(root):
        if identity_matches(directory, report, root):
            _remove_last(directory, report)


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _remove_last(directory: Path, report: OutputReport) -> None:
    try:
        (directory / "campaign.txt").unlink(missing_ok=True)
        (directory / ".active.lock").unlink()
        (directory / "campaign.json").unlink()
        directory.rmdir()
    except OSError:
        # A failed final directory removal must not orphan remaining owned evidence.
        if directory.is_dir():
            report.save(directory)
        raise
