"""Durable user reports, separate from the coordinator's raw evidence."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import cast

from tools.install_sandbox.contracts.results import EvidenceWriteError
from tools.install_sandbox.host.coordinator import CampaignResult
from tools.install_sandbox.host.timing_report import render_campaign


@dataclass
class Writer:
    name: str
    role: str
    runtime: str
    daemon_id: str
    state: str = "intent"


@dataclass
class OutputReport:
    started_at: str
    destination: str
    managed_root: str | None
    subject: str
    specs: str
    target: str
    requested_cases: list[str] | None
    identity: str = field(default_factory=lambda: uuid.uuid4().hex)
    available_directory: str | None = None
    finished_at: str | None = None
    stopped_observed_at: str | None = None
    phase: str = "allocated"
    archive: str = "absent"
    raw_evidence: bool = False
    exit_code: int = 2
    writers: list[Writer] = field(default_factory=list[Writer])
    diagnostics: list[str] = field(default_factory=list[str])
    execution: dict[str, object] = field(default_factory=dict[str, object])
    execution_text: str = "Execution has not started.\n"

    def observe(self, result: CampaignResult) -> None:
        # Export references, never mutate the raw coordinator result or its readers.
        raw = json.dumps(result.payload(), default=str)
        self.execution = cast(dict[str, object], json.loads(raw))
        self.execution = cast(
            dict[str, object], relative_values(self.execution, result.output_directory, "evidence")
        )
        self.execution_text = render_campaign(result).replace(
            str(result.output_directory), "evidence"
        )

    def payload(self) -> dict[str, object]:
        lifecycle = asdict(self)
        lifecycle.pop("execution")
        lifecycle.pop("execution_text")
        return {**self.execution, "output_lifecycle": {"version": 1, **lifecycle}}

    def render(self) -> str:
        return (
            self.execution_text
            + "\n"
            + "\n".join(
                [
                    f"Product: {self.subject}",
                    f"Target: {self.target}; specs: {self.specs}",
                    f"Command exit code: {self.exit_code}",
                    f"Result available at: {self.available_directory or 'not allocated'}",
                    f"Output phase: {self.phase}; archive: {self.archive}",
                    "Evidence references are relative ZIP entries (or files while unarchived).",
                    *[f"Output diagnostic: {message}" for message in self.diagnostics],
                ]
            )
            + "\n"
        )

    def save(self, directory: Path) -> None:
        try:
            atomic_text(directory / "campaign.txt", self.render())
            atomic_text(directory / "campaign.json", json.dumps(self.payload(), indent=2) + "\n")
        except OSError as error:
            raise EvidenceWriteError(
                f"Cannot save output report at {directory}: {error}"
            ) from error


def atomic_text(path: Path, content: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    with os.fdopen(os.open(temporary, flags, 0o600), "w", encoding="utf-8") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def relative_values(value: object, root: Path, prefix: str) -> object:
    if isinstance(value, dict):
        return {
            k: relative_values(v, root, prefix) for k, v in cast(dict[str, object], value).items()
        }
    if isinstance(value, list):
        return [relative_values(v, root, prefix) for v in cast(list[object], value)]
    if isinstance(value, str) and (value == str(root) or value.startswith(str(root) + "/")):
        return prefix + value[len(str(root)) :]
    return value


def read_report(directory: Path, root: Path) -> OutputReport:
    path = directory / "campaign.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing regular campaign report")
    decoded: object = json.loads(path.read_text())
    if not isinstance(decoded, dict):
        raise ValueError("Invalid campaign report")
    data = cast(dict[str, object], decoded)
    state = _validate_state(data["output_lifecycle"])
    if state["version"] != 1 or state["managed_root"] != str(root):
        raise ValueError("Unrecognized campaign ownership")
    identity = str(state["identity"])
    if uuid.UUID(hex=identity).hex != identity:
        raise ValueError("Invalid campaign identity")
    # Only recognized complete lifecycle reports may establish ownership.
    values = dict(state)
    values.pop("version")
    writers = cast(list[dict[str, str]], values.pop("writers"))
    report = OutputReport(**values)  # type: ignore[arg-type]
    report.writers = [Writer(**writer) for writer in writers]
    if not all(w.state in {"intent", "returned", "stopped"} for w in report.writers):
        raise ValueError("Unknown writer state")
    report.execution = {key: value for key, value in data.items() if key != "output_lifecycle"}
    # Keep the original human execution report when adding an observed stop timestamp.
    human = directory / "campaign.txt"
    if human.is_symlink():
        raise ValueError("Campaign text must not be a symlink")
    report.execution_text = human.read_text().split("\nProduct:", 1)[0]
    return report


def _validate_state(value: object) -> dict[str, object]:
    expected = {f.name for f in fields(OutputReport)} - {"execution", "execution_text"}
    if not isinstance(value, dict) or set(cast(dict[str, object], value)) != expected | {"version"}:
        raise ValueError("Incomplete lifecycle report")
    state = cast(dict[str, object], value)
    for key in ("started_at", "finished_at", "stopped_observed_at"):
        value = state[key]
        if value is None and key != "started_at":
            continue
        if not isinstance(value, str) or datetime.fromisoformat(value).tzinfo is None:
            raise ValueError(f"Invalid lifecycle timestamp: {key}")
    _validate_writers(state["writers"])
    return state


def _validate_writers(value: object) -> None:
    if not isinstance(value, list):
        raise ValueError("Invalid writer inventory")
    for writer in cast(list[object], value):
        if not isinstance(writer, dict) or set(cast(dict[str, object], writer)) != {
            "name",
            "role",
            "runtime",
            "daemon_id",
            "state",
        }:
            raise ValueError("Incomplete writer identity")
        data = cast(dict[str, object], writer)
        if not all(isinstance(v, str) and v for v in data.values()):
            raise ValueError("Invalid writer identity")
