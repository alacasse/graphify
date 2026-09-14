"""Controlled arrangements shared by sandbox behavior tests."""

from pathlib import Path

import pytest

from tests.install_sandbox.component.container import reinstall_support as reinstall
from tools.install_sandbox.contracts.timings import Timing


def arrange_reinstall(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reinstall.arrange_reinstall(path, monkeypatch, "passed", 1)


def assert_total(total: float | None, records: list[Timing]) -> None:
    assert total is not None and total > 0
    assert all(r.state == "measured" and r.duration_seconds is not None for r in records)
    assert sum(r.duration_seconds or 0 for r in records) <= total
