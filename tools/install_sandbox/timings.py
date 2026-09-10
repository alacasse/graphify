"""Bounded duration records for one sandbox case, independent of its verdict."""

import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal

TimingState = Literal["pending", "running", "measured", "not_run", "unavailable"]


@dataclass
class Timing:
    phase: str
    step: int | None = None
    state: TimingState = "pending"
    duration_seconds: float | None = None
    diagnostic: str | None = None


def elapsed(started_ns: int) -> float:
    return (time.monotonic_ns() - started_ns) / 1_000_000_000


@contextmanager
def measure(record: Timing) -> Generator[Timing]:
    """Measure locally; a command may supply its narrower execution duration."""
    record.state = "running"
    started = time.monotonic_ns()
    try:
        yield record
    except BaseException as error:
        record.diagnostic = f"Operation raised {type(error).__name__}"
        raise
    finally:
        if record.state == "running":
            if record.duration_seconds is None:
                record.duration_seconds = elapsed(started)
            record.state = "measured"


def case_timings(case_name: str, step_count: int) -> list[Timing]:
    records = [Timing(phase) for phase in ("copy_sources", "venv", "pip", "initial")]
    for index in range(step_count):
        if index:
            record = Timing("step_preparation", index)
            if case_name == "reinstall":
                record.diagnostic = "Retain the previous state for reinstallation"
            records.append(record)
        records.extend([Timing("command", index), Timing("checks", index)])
    records.append(Timing("finalize"))
    return records


def skip_pending(records: list[Timing]) -> None:
    for record in records:
        if record.state == "pending":
            record.state = "not_run"
            record.diagnostic = "Case stopped before this operation"
