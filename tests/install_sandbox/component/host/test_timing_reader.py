"""Timing transport is optional and validates its own explicit records."""

import json
from pathlib import Path

import pytest

from tools.install_sandbox.contracts.effect_case import (
    EffectInstallCase,
    EffectRules,
    SubjectContext,
)
from tools.install_sandbox.contracts.effects import Destination, EffectSpec, MarkdownSectionEffect
from tools.install_sandbox.host.timing_reader import read_timings
from tools.install_sandbox.host.timing_report import format_duration


def case() -> EffectInstallCase:
    return EffectInstallCase(
        "reinstall",
        "synthetic",
        "project",
        EffectSpec((MarkdownSectionEffect("instructions.md", Destination("project", "GUIDE.md")),)),
        SubjectContext(
            "synthetic",
            ("install",),
            "METADATA",
            EffectRules(10, "persistent", ".graphify-bak", ".bak", False),
        ),
        [],
        ["install", "install"],
    )


def payload() -> dict[str, object]:
    phases = [
        ("initial", None),
        ("command", 0),
        ("checks", 0),
        ("step_preparation", 1),
        ("command", 1),
        ("checks", 1),
        ("finalize", None),
    ]
    return {
        "version": 2,
        "duration_seconds": 7.0,
        "phases": [
            {
                "phase": phase,
                "step": step,
                "state": "measured",
                "duration_seconds": 1.0,
                "diagnostic": None,
            }
            for phase, step in phases
        ],
    }


def test_exact_timing_records(tmp_path: Path) -> None:
    (tmp_path / "timings.json").write_text(json.dumps(payload()))
    result = read_timings(tmp_path, case())
    assert not result.diagnostics
    assert result.duration_seconds == 7.0
    assert [(p.phase, p.step, p.duration_seconds) for p in result.phases] == [
        ("initial", None, 1.0),
        ("command", 0, 1.0),
        ("checks", 0, 1.0),
        ("step_preparation", 1, 1.0),
        ("command", 1, 1.0),
        ("checks", 1, 1.0),
        ("finalize", None, 1.0),
    ]


@pytest.mark.parametrize("bad", [None, True, -1, float("nan"), float("inf"), "1.0"])
def test_invalid_measured_duration_is_optional_diagnostic(tmp_path: Path, bad: object) -> None:
    data = payload()
    data["duration_seconds"] = bad
    # Null total is allowed, but a measured phase always requires a finite duration.
    encoded = json.dumps(data).replace(
        '"duration_seconds": 1.0', '"duration_seconds": ' + json.dumps(bad), 1
    )
    (tmp_path / "timings.json").write_text(encoded)
    result = read_timings(tmp_path, case())
    assert result.diagnostics and not result.phases


@pytest.mark.parametrize(
    "payload",
    [
        '{"version":2,"version":2,"duration_seconds":null,"phases":[]}',
        '{"version":1,"duration_seconds":null,"phases":[]}',
        '{"version":2,"duration_seconds":null,"phases":[{}]}',
        '{"version":2,"duration_seconds":null,"phases":null}',
        '{"version":2',
    ],
)
def test_malformed_timing_file_does_not_escape_reader(tmp_path: Path, payload: str) -> None:
    (tmp_path / "timings.json").write_text(payload)
    assert read_timings(tmp_path, case()).diagnostics


def test_missing_timing_evidence_is_optional(tmp_path: Path) -> None:
    assert read_timings(tmp_path, case()).diagnostics


def test_phase_total_cannot_exceed_measured_work(tmp_path: Path) -> None:
    data = payload()
    data["duration_seconds"] = 6.0
    (tmp_path / "timings.json").write_text(json.dumps(data))
    assert read_timings(tmp_path, case()).diagnostics


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (None, "unavailable"),
        (0, "0.000 s"),
        (0.0001, "< 0.001 s"),
        (1.2345, "1.234 s"),
    ],
)
def test_duration_presentation(seconds: float | None, expected: str) -> None:
    assert format_duration(seconds) == expected
