"""Strict retained verdicts preserve honest failures and reject contradictory transport."""

from dataclasses import asdict

import pytest

from tools.install_sandbox.contracts.results import VerificationResult


def test_incomplete_verdict_preserves_detached_obstacles_and_mismatches() -> None:
    mismatch = {
        "type": "content",
        "root": "project",
        "path": "GUIDE.md",
        "expected": "",
        "observed": "bad",
    }
    obstacle = {
        "operation": "read_file",
        "root": "home",
        "path": "personal.txt",
        "reason": "Unavailable",
    }
    raw = {"complete": False, "mismatches": [mismatch], "obstacles": [obstacle]}
    decoded = VerificationResult.from_data(raw)
    assert asdict(decoded) == raw
    obstacle["reason"] = "Changed outside the decoded result"
    mismatch["observed"] = "Changed outside the decoded result"
    assert decoded.obstacles[0]["reason"] == "Unavailable"
    assert decoded.mismatches[0].observed == "bad"


INVALID_VERDICTS: list[object] = [
    {"complete": 1, "mismatches": [], "obstacles": []},
    {"complete": True, "mismatches": {}, "obstacles": []},
    {"complete": True, "mismatches": [], "obstacles": None},
    {"complete": True, "mismatches": [], "obstacles": [], "extra": None},
    {"complete": False, "mismatches": [{}], "obstacles": []},
    {"complete": False, "mismatches": [], "obstacles": [{}]},
    {
        "complete": True,
        "mismatches": [],
        "obstacles": [{"operation": "read_file", "root": "home", "path": "x", "reason": "x"}],
    },
]


@pytest.mark.parametrize("raw", INVALID_VERDICTS)
def test_malformed_or_contradictory_verdict_is_rejected(raw: object) -> None:
    with pytest.raises(ValueError):
        VerificationResult.from_data(raw)
