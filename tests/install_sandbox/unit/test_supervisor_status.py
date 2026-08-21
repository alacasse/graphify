from __future__ import annotations

import pytest

from tools.install_sandbox.sandbox_runtime.supervisor_status import SupervisorStatus


@pytest.mark.parametrize(
    "frames",
    (
        ("SPAWNED", "TARGET_EXIT:17", "QUIESCENT"),
        (
            "SPAWNED",
            "DESCENDANTS_TERMINATED",
            "KILL_ESCALATED",
            "TARGET_EXIT:-9",
            "QUIESCENT",
        ),
        ("SPAWN_ERROR:missing executable",),
        ("CUSTODY_ERROR:subreaper unavailable",),
    ),
)
def test_supervisor_status_accepts_only_complete_ordered_transcripts(
    frames: tuple[str, ...],
) -> None:
    assert SupervisorStatus.parse(frames).transcript_valid


@pytest.mark.parametrize(
    "frames",
    (
        (),
        ("STATUS_ERROR:connection reset",),
        ("SPAWNED",),
        ("SPAWNED", "QUIESCENT"),
        ("SPAWNED", "TARGET_EXIT:invalid", "QUIESCENT"),
        ("SPAWNED", "QUIESCENT", "TARGET_EXIT:0"),
        ("SPAWNED", "TARGET_EXIT:0", "QUIESCENT", "QUIESCENT"),
        ("SPAWNED", "KILL_ESCALATED", "TARGET_EXIT:0", "QUIESCENT"),
        ("TARGET_EXIT:0", "QUIESCENT"),
    ),
)
def test_supervisor_status_rejects_partial_reordered_or_duplicate_transcripts(
    frames: tuple[str, ...],
) -> None:
    assert not SupervisorStatus.parse(frames).transcript_valid
