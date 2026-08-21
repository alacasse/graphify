"""Parse the private mechanical status stream from the command supervisor."""

from __future__ import annotations

from dataclasses import dataclass


def _detail(frames: tuple[str, ...], prefix: str) -> str | None:
    return next(
        (frame.removeprefix(prefix) for frame in frames if frame.startswith(prefix)),
        None,
    )


def _target_exit(frame: str | None) -> int | None:
    value = frame.removeprefix("TARGET_EXIT:") if frame is not None else None
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
    transcript_valid: bool

    @classmethod
    def parse(cls, frames: tuple[str, ...]) -> SupervisorStatus:
        spawned = bool(frames) and frames[0] == "SPAWNED"
        cursor = 1 if spawned else 0
        terminated = cursor < len(frames) and frames[cursor] == "DESCENDANTS_TERMINATED"
        cursor += int(terminated)
        escalated = cursor < len(frames) and frames[cursor] == "KILL_ESCALATED"
        cursor += int(escalated)
        custody_frame = (
            frames[cursor]
            if cursor < len(frames) and frames[cursor].startswith("CUSTODY_ERROR:")
            else None
        )
        cursor += int(custody_frame is not None)
        target_frame = (
            frames[cursor]
            if cursor < len(frames) and frames[cursor].startswith("TARGET_EXIT:")
            else None
        )
        cursor += int(target_frame is not None)
        quiescent = cursor < len(frames) and frames[cursor] == "QUIESCENT"
        cursor += int(quiescent)
        target_exit = _target_exit(target_frame)
        terminal = (
            target_exit is not None
            and (not escalated or terminated)
            and (
                (quiescent and custody_frame is None)
                or (not quiescent and custody_frame is not None)
            )
        )
        pre_spawn = len(frames) == 1 and (
            frames[0].startswith("SPAWN_ERROR:") or frames[0].startswith("CUSTODY_ERROR:")
        )
        return cls(
            spawned=spawned,
            descendants_terminated=terminated,
            kill_escalated=escalated,
            quiescent=quiescent,
            target_exit=target_exit,
            spawn_error=_detail(frames, "SPAWN_ERROR:"),
            custody_error=(
                custody_frame.removeprefix("CUSTODY_ERROR:")
                if custody_frame is not None
                else _detail(frames, "CUSTODY_ERROR:")
            ),
            status_error=_detail(frames, "STATUS_ERROR:"),
            transcript_valid=pre_spawn or (spawned and terminal and cursor == len(frames)),
        )
