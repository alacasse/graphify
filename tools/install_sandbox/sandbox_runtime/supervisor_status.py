"""Parse the private mechanical status stream from the command supervisor."""

from __future__ import annotations

from dataclasses import dataclass


def _detail(frames: tuple[str, ...], prefix: str) -> str | None:
    return next(
        (frame.removeprefix(prefix) for frame in frames if frame.startswith(prefix)),
        None,
    )


def _target_exit(frames: tuple[str, ...]) -> int | None:
    value = _detail(frames, "TARGET_EXIT:")
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class SupervisorStatus:
    spawned: bool
    descendants_terminated: bool
    kill_escalated: bool
    quiescent: bool
    target_exit: int | None
    spawn_error: str | None
    custody_error: str | None
    status_error: str | None

    @classmethod
    def parse(cls, frames: tuple[str, ...]) -> SupervisorStatus:
        return cls(
            spawned="SPAWNED" in frames,
            descendants_terminated="DESCENDANTS_TERMINATED" in frames,
            kill_escalated="KILL_ESCALATED" in frames,
            quiescent="QUIESCENT" in frames,
            target_exit=_target_exit(frames),
            spawn_error=_detail(frames, "SPAWN_ERROR:"),
            custody_error=_detail(frames, "CUSTODY_ERROR:"),
            status_error=_detail(frames, "STATUS_ERROR:"),
        )
