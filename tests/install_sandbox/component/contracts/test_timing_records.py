"""Verify sandbox behavior at its owning boundary."""

import pytest

from tools.install_sandbox.contracts.timings import Timing, measure


def test_phase_exception_retains_duration_without_swallowing_error() -> None:
    record = Timing("command", 0)
    with pytest.raises(RuntimeError, match="Controlled failure"), measure(record):
        raise RuntimeError("Controlled failure")
    assert record.state == "measured" and record.duration_seconds is not None
    assert record.diagnostic == "Operation raised RuntimeError"
