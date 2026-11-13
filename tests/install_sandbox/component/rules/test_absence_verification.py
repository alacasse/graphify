"""Absence constraints distinguish a retained lock from an inaccessible path."""

import pytest

from tools.install_sandbox.contracts.expectations import Expectation, ExpectationSet
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import ObservationObstacle, SnapshotEntry
from tools.install_sandbox.rules.effect_verifier import EffectVerifier


@pytest.mark.parametrize("lock_kind", [None, "file", "unknown"])
def test_require_absent_distinguishes_absent_present_and_unreadable_lock(
    lock_kind: str | None,
) -> None:
    lock = "settings.json.graphify.lock"
    observed = FilesystemSnapshot(
        entries=[
            SnapshotEntry(root=root, path=".", kind="directory", listing_complete=True)
            for root in ("project", "home")
        ]
    )
    if lock_kind is not None:
        observed.entries.append(SnapshotEntry(root="project", path=lock, kind=lock_kind))
    if lock_kind == "file":
        observed.contents["project", lock] = b""
    diagnostic: ObservationObstacle = {
        "operation": "stat",
        "root": "project",
        "path": lock,
        "reason": "Permission denied",
    }
    if lock_kind == "unknown":
        observed.obstacles.append(diagnostic)
    expected = ExpectationSet(
        "install",
        (Expectation("absent", "project", lock, "install", "rule:json_lock"),),
        roots={"home": "/home/test", "project": "/project"},
    )
    verdict = EffectVerifier().verify(expected, observed)
    assert verdict.complete == (lock_kind != "unknown")
    if lock_kind == "file":
        assert [(m.type, m.path) for m in verdict.mismatches] == [("unexpected_entry", lock)]
    else:
        assert not verdict.mismatches
    if lock_kind == "unknown":
        assert diagnostic in verdict.obstacles
        assert any(
            o["operation"] == "verify_absence" and o["path"] == lock for o in verdict.obstacles
        )
    else:
        assert not verdict.obstacles
