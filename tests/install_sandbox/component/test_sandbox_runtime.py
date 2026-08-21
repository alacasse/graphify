from __future__ import annotations

import json
import sys
from pathlib import Path

from tools.install_sandbox.sandbox_runtime.session import SandboxRuntime
from tools.install_sandbox.sandbox_runtime.types import SandboxFinishReason
from tools.install_sandbox.validation.catalog import (
    CatalogDocument,
    CatalogDocuments,
    OwnedFileSurface,
    Scope,
    SurfaceRoot,
)
from tools.install_sandbox.validation.engine import ValidationCompleted, validate
from tools.install_sandbox.validation.plan_types import HarnessPolicy, ValidationRequest
from tools.install_sandbox.validation.protocol import (
    ActionFailureFact,
    ActionId,
    ActionKind,
    CommandFact,
    CommandRequest,
    EntryKind,
    ObservationFact,
    ObservationRequest,
    PhaseKind,
    PreparedSourcePath,
    SandboxPath,
    SurfaceExpectation,
    TargetSubject,
)
from tools.install_sandbox.validation.results import (
    LifecycleResult,
    PhaseStatus,
    ScenarioStatus,
)


def test_sandbox_runtime_preserves_raw_command_evidence_and_cleans_up(
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
            "import sys; print('captured-out'); print('captured-err', file=sys.stderr)",
        ),
    )

    fact = runtime.fulfil(request)

    assert isinstance(fact, CommandFact)
    assert fact.action_id == request.action_id
    assert fact.argv == request.argv
    assert fact.working_directory is SurfaceRoot.PROJECT
    assert fact.exit_code == 0
    assert fact.signal is None
    assert fact.timed_out is False
    assert fact.stdout.data == b"captured-out\n"
    assert fact.stdout.complete is True
    assert fact.stderr.data == b"captured-err\n"
    assert fact.stderr.complete is True
    assert fact.started_ns <= fact.finished_ns
    assert tuple(event.kind.value for event in fact.chronology) == (
        "command_started",
        "command_finished",
    )

    cleanup = runtime.finish(SandboxFinishReason.COMPLETED)

    assert cleanup.removed is True
    assert cleanup.failures == ()
    assert not session_root.exists()


def test_sandbox_runtime_preserves_partial_capture_when_a_command_times_out(
    tmp_path: Path,
) -> None:
    prepared_source = tmp_path / "prepared-source"
    prepared_source.mkdir()
    runtime = SandboxRuntime.open(
        tmp_path / "session",
        prepared_source,
        command_timeout_seconds=0.05,
        capture_limit_bytes=8,
    )
    request = CommandRequest(
        action_id=ActionId("plan-fixture", 0),
        subject=TargetSubject("fictional"),
        scope=Scope.USER,
        phase=PhaseKind.INSTALL,
        argv=(
            sys.executable,
            "-c",
            (
                "import sys, time; "
                "sys.stdout.write('before-timeout'); sys.stdout.flush(); time.sleep(10)"
            ),
        ),
    )

    fact = runtime.fulfil(request)

    assert isinstance(fact, CommandFact)
    assert fact.timed_out is True
    assert fact.exit_code < 0
    assert fact.signal == -fact.exit_code
    assert fact.stdout.data == b"before-t"
    assert fact.stdout.complete is False
    assert fact.stdout.omitted_bytes == len("before-timeout") - 8
    assert fact.stderr.data == b""
    assert fact.stderr.complete is False
    assert tuple(event.kind.value for event in fact.chronology) == (
        "command_started",
        "command_timed_out",
        "command_terminated",
        "command_finished",
    )

    runtime.finish(SandboxFinishReason.ABORTED)


def test_sandbox_runtime_preserves_non_utf8_stream_bytes(tmp_path: Path) -> None:
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
            "import sys; sys.stdout.buffer.write(bytes((255, 0, 254)))",
        ),
    )

    fact = runtime.fulfil(request)

    assert isinstance(fact, CommandFact)
    assert fact.stdout.data == bytes((255, 0, 254))
    assert fact.stdout.complete is True
    runtime.finish(SandboxFinishReason.COMPLETED)


def test_sandbox_runtime_bounds_large_streams_during_capture(tmp_path: Path) -> None:
    prepared_source = tmp_path / "prepared-source"
    prepared_source.mkdir()
    runtime = SandboxRuntime.open(
        tmp_path / "session",
        prepared_source,
        capture_limit_bytes=32,
    )
    request = CommandRequest(
        action_id=ActionId("plan-fixture", 0),
        subject=TargetSubject("fictional"),
        scope=Scope.PROJECT,
        phase=PhaseKind.INSTALL,
        argv=(
            sys.executable,
            "-c",
            "import os; os.write(1, b'o' * 1048576); os.write(2, b'e' * 1048576)",
        ),
    )

    fact = runtime.fulfil(request)

    assert isinstance(fact, CommandFact)
    assert fact.stdout.data == b"o" * 32
    assert fact.stdout.omitted_bytes == 1_048_576 - 32
    assert fact.stdout.complete is False
    assert fact.stdout.error is None
    assert fact.stderr.data == b"e" * 32
    assert fact.stderr.omitted_bytes == 1_048_576 - 32
    assert fact.stderr.complete is False
    assert fact.stderr.error is None
    runtime.finish(SandboxFinishReason.COMPLETED)


def test_sandbox_runtime_observes_files_without_classifying_them(tmp_path: Path) -> None:
    prepared_source = tmp_path / "prepared-source"
    source = prepared_source / "fixtures" / "config.txt"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"expected payload\n")
    runtime = SandboxRuntime.open(tmp_path / "session", prepared_source)
    subject = TargetSubject("fictional")
    command = CommandRequest(
        action_id=ActionId("plan-fixture", 0),
        subject=subject,
        scope=Scope.PROJECT,
        phase=PhaseKind.INSTALL,
        argv=(
            sys.executable,
            "-c",
            "from pathlib import Path; Path('.fictional').mkdir(); "
            "Path('.fictional/config.txt').write_bytes(b'expected payload\\n')",
        ),
    )
    surface = OwnedFileSurface(
        root=SurfaceRoot.PROJECT,
        path=".fictional/config.txt",
        source="fixtures/config.txt",
    )
    observation = ObservationRequest(
        action_id=ActionId("plan-fixture", 1),
        subject=subject,
        scope=Scope.PROJECT,
        phase=PhaseKind.INSTALL,
        surfaces=(surface,),
        expectation=SurfaceExpectation.INSTALLED,
    )

    runtime.fulfil(command)
    fact = runtime.fulfil(observation)

    assert isinstance(fact, ObservationFact)
    assert fact.action_id == observation.action_id
    assert len(fact.surfaces) == 1
    observed = fact.surfaces[0]
    assert observed.surface == surface
    assert observed.destination.location == SandboxPath(
        SurfaceRoot.PROJECT,
        ".fictional/config.txt",
    )
    assert observed.destination.kind is EntryKind.FILE
    assert observed.destination.content is not None
    assert observed.destination.content.data == b"expected payload\n"
    assert observed.destination.content.complete is True
    assert observed.source is not None
    assert observed.source.location == PreparedSourcePath("fixtures/config.txt")
    assert observed.source.kind is EntryKind.FILE
    assert observed.source.content is not None
    assert observed.source.content.data == b"expected payload\n"
    assert not hasattr(fact, "matched")
    assert tuple(event.kind.value for event in fact.chronology) == (
        "observation_started",
        "observation_finished",
    )

    runtime.finish(SandboxFinishReason.COMPLETED)


def test_sandbox_runtime_snapshots_every_filesystem_mutation_around_a_command(
    tmp_path: Path,
) -> None:
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
            (
                "from pathlib import Path; root=Path('.fictional'); root.mkdir(); "
                "(root/'config.txt').write_text('payload'); "
                "(root/'link').symlink_to('config.txt')"
            ),
        ),
    )

    fact = runtime.fulfil(request)

    assert isinstance(fact, CommandFact)
    assert tuple(
        (entry.root, entry.path, entry.kind) for entry in fact.before_snapshot.entries
    ) == tuple((root, ".", EntryKind.DIRECTORY) for root in SurfaceRoot)
    changed_entries = tuple(entry for entry in fact.after_snapshot.entries if entry.path != ".")
    assert tuple((entry.root, entry.path, entry.kind) for entry in changed_entries) == (
        (SurfaceRoot.PROJECT, ".fictional", EntryKind.DIRECTORY),
        (SurfaceRoot.PROJECT, ".fictional/config.txt", EntryKind.FILE),
        (SurfaceRoot.PROJECT, ".fictional/link", EntryKind.SYMLINK),
    )
    file_entry = changed_entries[1]
    assert file_entry.size == len("payload")
    assert file_entry.sha256 is not None
    assert not hasattr(file_entry, "content")
    assert changed_entries[2].symlink_target == "config.txt"

    runtime.finish(SandboxFinishReason.COMPLETED)


def test_fictional_lifecycle_crosses_validation_and_real_runtime_owners(
    tmp_path: Path,
) -> None:
    prepared_source = tmp_path / "prepared-source"
    source = prepared_source / "fixtures" / "config.txt"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"expected payload\n")
    product = tmp_path / "fictional_product.py"
    product.write_text(
        """
from pathlib import Path
import sys

destination = Path(".fictional/config.txt")
if sys.argv[1] == "install":
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"expected payload\\n")
else:
    destination.unlink(missing_ok=True)
""".lstrip(),
        encoding="utf-8",
    )
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                json.dumps(
                    {
                        "scopes": {
                            "user": {
                                "supported": False,
                                "reason": "User scope is unavailable.",
                                "runtime_limitations": [],
                            },
                            "project": {
                                "supported": True,
                                "runtime_limitations": [],
                                "surfaces": [
                                    {
                                        "kind": "owned_file",
                                        "root": "project",
                                        "path": ".fictional/config.txt",
                                        "source": "fixtures/config.txt",
                                    }
                                ],
                            },
                        }
                    }
                ),
            ),
        )
    )
    runtime = SandboxRuntime.open(tmp_path / "session", prepared_source)

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(
            install_argv=(sys.executable, str(product), "install"),
            uninstall_argv=(sys.executable, str(product), "uninstall"),
        ),
        runtime.fulfil,
    )
    cleanup = runtime.finish(SandboxFinishReason.COMPLETED)

    assert isinstance(result, ValidationCompleted)
    lifecycle = result.scenario_results[0]
    assert isinstance(lifecycle, LifecycleResult)
    assert lifecycle.status is ScenarioStatus.PASS
    assert tuple(phase.status for phase in lifecycle.phases) == (
        PhaseStatus.PASS,
        PhaseStatus.PASS,
        PhaseStatus.PASS,
    )
    events = tuple(event for fact in result.raw_facts for event in fact.chronology)
    assert tuple(event.sequence for event in events) == tuple(range(len(events)))
    assert cleanup.removed is True
    assert cleanup.failures == ()


def test_sandbox_runtime_returns_a_typed_raw_spawn_failure(tmp_path: Path) -> None:
    prepared_source = tmp_path / "prepared-source"
    prepared_source.mkdir()
    runtime = SandboxRuntime.open(tmp_path / "session", prepared_source)
    request = CommandRequest(
        action_id=ActionId("plan-fixture", 0),
        subject=TargetSubject("fictional"),
        scope=Scope.PROJECT,
        phase=PhaseKind.INSTALL,
        argv=(str(tmp_path / "does-not-exist"),),
    )

    fact = runtime.fulfil(request)

    assert isinstance(fact, ActionFailureFact)
    assert fact.action_id == request.action_id
    assert fact.action_kind is ActionKind.COMMAND
    assert fact.operation == "spawn_command"
    assert "No such file or directory" in fact.detail
    assert tuple(event.kind.value for event in fact.chronology) == (
        "command_started",
        "command_failed",
    )

    runtime.finish(SandboxFinishReason.REJECTED)
