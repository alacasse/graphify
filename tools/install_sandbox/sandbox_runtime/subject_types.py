"""Immutable package-preparation and origin-probe evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tools.install_sandbox.validation.protocol import StreamCapture


@dataclass(frozen=True, slots=True)
class PreparedSubjectFact:
    source_root: str
    prepared_root: str
    copied_files: tuple[str, ...]
    excluded_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SubjectCommandFact:
    stage: str
    argv: tuple[str, ...]
    working_directory: str
    exit_code: int | None
    timed_out: bool
    stdout: StreamCapture
    stderr: StreamCapture
    started_ns: int
    finished_ns: int
    failure: str | None = None


@dataclass(frozen=True, slots=True)
class SubjectVerified:
    identity: str
    version: str
    executable: Path
    prepared_source: Path
    built_artifact: Path
    target_names: tuple[str, ...]
    preparation: PreparedSubjectFact
    commands: tuple[SubjectCommandFact, ...]


@dataclass(frozen=True, slots=True)
class SubjectRejected:
    stage: str
    detail: str
    preparation: PreparedSubjectFact | None
    commands: tuple[SubjectCommandFact, ...]


type SubjectAssessment = SubjectVerified | SubjectRejected
