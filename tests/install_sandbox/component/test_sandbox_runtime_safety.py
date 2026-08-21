from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tools.install_sandbox.sandbox_runtime.session import SandboxRuntime
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
    runtime.finish(SandboxFinishReason.COMPLETED)
