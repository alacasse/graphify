"""Read optional duration evidence without changing case or Docker verdicts."""

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from tools.install_sandbox.case import InstallTestCase
from tools.install_sandbox.result_reader import safe_evidence_path
from tools.install_sandbox.spec import fields
from tools.install_sandbox.timings import Timing, case_timings


@dataclass
class CaseTimingResult:
    phases: list[Timing] = field(default_factory=list[Timing])
    duration_seconds: float | None = None
    diagnostics: list[str] = field(default_factory=list[str])


def _duration(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Duration must be numeric or null")
    if not math.isfinite(value) or value < 0:
        raise ValueError("Duration must be finite and nonnegative")
    return float(value)


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate timing field: {key}")
        value[key] = item
    return value


def _record(value: object, expected: Timing) -> Timing:
    data = fields(value, "phase step state duration_seconds diagnostic")
    if (data["phase"], data["step"]) != (expected.phase, expected.step):
        raise ValueError("Timing phases do not match the requested case")
    if data["step"] is not None and type(data["step"]) is not int:
        raise ValueError("Timing step must be an integer or null")
    state = data["state"]
    if state not in ("pending", "running", "measured", "not_run", "unavailable"):
        raise ValueError("Invalid timing state")
    duration = _duration(data["duration_seconds"])
    if (state == "measured") != (duration is not None):
        raise ValueError("Only a measured phase has a duration")
    diagnostic = data["diagnostic"]
    if diagnostic is not None and not isinstance(diagnostic, str):
        raise ValueError("Invalid timing diagnostic")
    return Timing(expected.phase, expected.step, state, duration, diagnostic)


def _read(output: Path, case: InstallTestCase) -> CaseTimingResult:
    path = safe_evidence_path(output, "timings.json")
    data = fields(
        json.loads(path.read_text(), object_pairs_hook=_object), "version duration_seconds phases"
    )
    if type(data["version"]) is not int or data["version"] != 1:
        raise ValueError("Unsupported timing version")
    raw = data["phases"]
    expected = case_timings(case.name, len(case.operations))
    if not isinstance(raw, list):
        raise ValueError("Timing phases must be a list")
    raw = cast(list[object], raw)
    if len(raw) != len(expected):
        raise ValueError("Timing phases are missing or duplicated")
    phases = [_record(item, record) for item, record in zip(raw, expected, strict=True)]
    duration = _duration(data["duration_seconds"])
    measured = sum(record.duration_seconds or 0 for record in phases)
    if duration is not None and measured - duration > max(1e-9, math.ulp(duration) * len(phases)):
        raise ValueError("Phase durations exceed the measured container work")
    diagnostics = _diagnostics(phases, duration)
    return CaseTimingResult(phases, duration, diagnostics)


def _diagnostics(phases: list[Timing], duration: float | None) -> list[str]:
    diagnostics: list[str] = []
    if duration is None:
        diagnostics.append("Container timing finalization was not recorded")
    for record in phases:
        if record.state in {"pending", "running", "unavailable"}:
            diagnostics.append(f"{record.phase} step={record.step}: {record.state}")
    return diagnostics


def read_timings(output: Path, case: InstallTestCase) -> CaseTimingResult:
    try:
        return _read(output, case)
    except (OSError, ValueError, OverflowError, RecursionError) as error:
        return CaseTimingResult(diagnostics=[f"Timing evidence unavailable or invalid: {error}"])
