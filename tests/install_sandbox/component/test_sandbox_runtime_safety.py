from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from tools.install_sandbox.sandbox_runtime.session import (
    SandboxConfigurationError,
    SandboxRuntime,
)
from tools.install_sandbox.sandbox_runtime.types import SandboxFinishReason
from tools.install_sandbox.validation.catalog import Scope, SurfaceRoot
from tools.install_sandbox.validation.protocol import (
    ActionId,
    CommandFact,
    CommandRequest,
    EntryKind,
    PhaseKind,
    TargetSubject,
)


def test_sandbox_runtime_rejects_a_session_nested_in_prepared_source(tmp_path: Path) -> None:
    prepared_source = tmp_path / "prepared-source"
    prepared_source.mkdir()

    with pytest.raises(ValueError, match="must not alias"):
        SandboxRuntime.open(prepared_source / "session", prepared_source)


def test_sandbox_runtime_rejects_a_grace_shorter_than_the_supervisor_budget(
    tmp_path: Path,
) -> None:
    prepared_source = tmp_path / "prepared-source"
    prepared_source.mkdir()

    with pytest.raises(SandboxConfigurationError, match=r"at least 0\.25 seconds"):
        SandboxRuntime.open(
            tmp_path / "session",
            prepared_source,
            termination_grace_seconds=0.01,
        )


def test_snapshot_records_root_replacement_without_following_it(tmp_path: Path) -> None:
    prepared_source = tmp_path / "prepared-source"
    prepared_source.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "must-not-be-read.txt").write_text("outside", encoding="utf-8")
    runtime = SandboxRuntime.open(tmp_path / "session", prepared_source)
    request = CommandRequest(
        action_id=ActionId("plan-fixture", 0),
        subject=TargetSubject("fictional"),
        scope=Scope.PROJECT,
        phase=PhaseKind.INSTALL,
        argv=(
            sys.executable,
            "-c",
            (
                "import os, shutil, sys; from pathlib import Path; os.chdir('..'); "
                "shutil.rmtree('project'); "
                "Path('project').symlink_to(sys.argv[1], target_is_directory=True)"
            ),
            str(outside),
        ),
    )

    fact = runtime.fulfil(request)

    assert isinstance(fact, CommandFact)
    project_root = next(
        entry
        for entry in fact.after_snapshot.entries
        if entry.root is SurfaceRoot.PROJECT and entry.path == "."
    )
    assert project_root.kind is EntryKind.SYMLINK
    assert project_root.symlink_target == str(outside)
    assert not any(entry.path == "must-not-be-read.txt" for entry in fact.after_snapshot.entries)
    cleanup = runtime.finish(SandboxFinishReason.COMPLETED)
    assert cleanup.removed
    assert cleanup.failures == ()
    assert outside.joinpath("must-not-be-read.txt").read_text(encoding="utf-8") == "outside"


def test_cleanup_unlinks_a_dangling_session_root_symlink(tmp_path: Path) -> None:
    prepared_source = tmp_path / "prepared-source"
    prepared_source.mkdir()
    session_root = tmp_path / "session"
    dangling_target = tmp_path / "missing-outside"
    runtime = SandboxRuntime.open(session_root, prepared_source)
    request = CommandRequest(
        action_id=ActionId("plan-fixture", 0),
        subject=TargetSubject("fictional"),
        scope=Scope.PROJECT,
        phase=PhaseKind.INSTALL,
        argv=(
            sys.executable,
            "-c",
            (
                "import os, shutil, sys; from pathlib import Path; "
                "os.chdir(sys.argv[1]); shutil.rmtree(sys.argv[2]); "
                "Path(sys.argv[2]).symlink_to(sys.argv[3], target_is_directory=True)"
            ),
            str(prepared_source),
            str(session_root),
            str(dangling_target),
        ),
    )

    fact = runtime.fulfil(request)
    assert isinstance(fact, CommandFact)
    assert session_root.is_symlink()
    assert not session_root.exists()

    cleanup = runtime.finish(SandboxFinishReason.COMPLETED)

    assert cleanup.removed
    assert cleanup.failures == ()
    assert not os.path.lexists(session_root)


@pytest.mark.parametrize("stdio", ("inherit", "closed"))
@pytest.mark.parametrize("detached", (False, True), ids=("same-session", "detached-session"))
def test_timeout_terminates_descendants_and_reaches_quiescence(
    tmp_path: Path,
    stdio: str,
    detached: bool,
) -> None:
    prepared_source = tmp_path / "prepared-source"
    prepared_source.mkdir()
    session_root = tmp_path / "session"
    runtime = SandboxRuntime.open(
        session_root,
        prepared_source,
        command_timeout_seconds=0.2,
    )
    late_path = session_root / "project" / "late.txt"
    child = (
        "import signal, sys, time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(1); "
        "path = Path(sys.argv[1]); path.parent.mkdir(parents=True, exist_ok=True); "
        "path.write_text('late')"
    )
    child_stdio = (
        "" if stdio == "inherit" else ", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL"
    )
    request = CommandRequest(
        action_id=ActionId("plan-fixture", 0),
        subject=TargetSubject("fictional"),
        scope=Scope.PROJECT,
        phase=PhaseKind.INSTALL,
        argv=(
            sys.executable,
            "-c",
            (
                "import subprocess, sys, time; "
                f"subprocess.Popen([sys.executable, '-c', {child!r}, {str(late_path)!r}], "
                f"start_new_session={detached!r}{child_stdio}); "
                "time.sleep(5)"
            ),
        ),
    )

    started = time.monotonic()
    fact = runtime.fulfil(request)
    elapsed = time.monotonic() - started

    assert isinstance(fact, CommandFact)
    assert fact.timed_out
    assert elapsed < 0.8
    assert any(event.kind.value == "command_terminated" for event in fact.chronology)
    if not detached:
        assert any(event.kind.value == "command_kill_escalated" for event in fact.chronology)
    cleanup = runtime.finish(SandboxFinishReason.ABORTED)
    assert cleanup.removed
    time.sleep(1.1)
    assert not session_root.exists()


def test_subprocess_pwd_matches_its_isolated_logical_working_directory(
    tmp_path: Path,
) -> None:
    prepared_source = tmp_path / "prepared-source"
    prepared_source.mkdir()
    session_root = tmp_path / "session"
    runtime = SandboxRuntime.open(session_root, prepared_source)
    request = CommandRequest(
        action_id=ActionId("plan-fixture", 0),
        subject=TargetSubject("fictional"),
        scope=Scope.PROJECT,
        phase=PhaseKind.INSTALL,
        argv=(
            sys.executable,
            "-c",
            "import os; print(os.getcwd()); print(os.environ['PWD'])",
        ),
    )

    fact = runtime.fulfil(request)

    assert isinstance(fact, CommandFact)
    expected = str((session_root / "project").resolve())
    assert fact.stdout.data.decode().splitlines() == [expected, expected]
    runtime.finish(SandboxFinishReason.COMPLETED)


def test_product_sigkill_is_preserved_without_a_supervisor_traceback(tmp_path: Path) -> None:
    prepared_source = tmp_path / "prepared-source"
    prepared_source.mkdir()
    runtime = SandboxRuntime.open(tmp_path / "session", prepared_source)
    request = CommandRequest(
        action_id=ActionId("plan-fixture", 0),
        subject=TargetSubject("fictional"),
        scope=Scope.PROJECT,
        phase=PhaseKind.INSTALL,
        argv=(
            sys.executable,
            "-c",
            "import os, signal; os.kill(os.getpid(), signal.SIGKILL)",
        ),
    )

    fact = runtime.fulfil(request)

    assert isinstance(fact, CommandFact)
    assert fact.exit_code == -9
    assert fact.signal == 9
    assert fact.stderr.data == b""
    assert fact.stderr.error is None
    runtime.finish(SandboxFinishReason.COMPLETED)
