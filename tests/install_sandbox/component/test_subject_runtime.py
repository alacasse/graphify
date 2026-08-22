from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import pytest

from tools.install_sandbox.sandbox_runtime.process import (
    MINIMUM_TERMINATION_GRACE_SECONDS,
    LocalProcessRunner,
)
from tools.install_sandbox.sandbox_runtime.process_types import (
    IncompleteProcessExecution,
    ProcessExecution,
    ProcessFailure,
)
from tools.install_sandbox.sandbox_runtime.subject import SubjectRuntime
from tools.install_sandbox.sandbox_runtime.subject_types import SubjectRejected, SubjectVerified
from tools.install_sandbox.validation.protocol import OperationEvent, OperationKind, StreamCapture


def _subject_fixture(tmp_path: Path) -> Path:
    source = tmp_path / "subject"
    shutil.copytree(
        Path("tools/install_sandbox/container/fixtures/source"),
        source,
    )
    for excluded in (".git", ".venv", "__pycache__", "graphify-out", "my-docs"):
        sentinel = source / excluded
        sentinel.mkdir()
        (sentinel / "excluded.txt").write_text("excluded", encoding="utf-8")
    return source


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _seed_ambient_decoys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    decoy_python = tmp_path / "ambient-python/graphify"
    decoy_python.mkdir(parents=True)
    (decoy_python / "__init__.py").write_text("VERSION = 'ambient'\n", encoding="utf-8")
    decoy_bin = tmp_path / "ambient-bin"
    decoy_bin.mkdir()
    decoy_executable = decoy_bin / "graphify"
    decoy_executable.write_text("#!/bin/sh\necho ambient\n", encoding="utf-8")
    decoy_executable.chmod(0o755)
    monkeypatch.setenv("PYTHONPATH", str(decoy_python.parent))
    monkeypatch.setenv("PATH", f"{decoy_bin}{os.pathsep}{os.environ.get('PATH', '')}")


class _ControlledRunner:
    def __init__(
        self,
        failure_index: int,
        mode: Literal["custody", "malformed", "nonzero", "timeout"],
    ) -> None:
        self._delegate = LocalProcessRunner(
            60.0,
            MINIMUM_TERMINATION_GRACE_SECONDS,
            1_000_000,
        )
        self._failure_index = failure_index
        self._mode = mode
        self._index = 0

    def run(
        self,
        argv: tuple[str, ...],
        cwd: Path,
        environment: dict[str, str],
        event: Callable[[OperationKind], OperationEvent],
    ) -> ProcessExecution | IncompleteProcessExecution | ProcessFailure:
        index = self._index
        self._index += 1
        if index != self._failure_index:
            return self._delegate.run(argv, cwd, environment, event)
        started = event(OperationKind.COMMAND_STARTED)
        if self._mode == "custody":
            return ProcessFailure(
                "establish_process_custody",
                "forced custody failure",
                (started, event(OperationKind.COMMAND_FAILED)),
            )
        if self._mode == "timeout":
            chronology = (
                started,
                event(OperationKind.COMMAND_TIMED_OUT),
                event(OperationKind.COMMAND_TERMINATED),
                event(OperationKind.COMMAND_FINISHED),
            )
            return ProcessExecution(
                -9,
                9,
                True,
                StreamCapture(b"partial", True),
                StreamCapture(b"timed out", True),
                chronology[0].occurred_ns,
                chronology[-1].occurred_ns,
                chronology,
            )
        finished = event(OperationKind.COMMAND_FINISHED)
        return ProcessExecution(
            0 if self._mode == "malformed" else 17,
            None,
            False,
            StreamCapture(b"not-json\n" if self._mode == "malformed" else b"", True),
            StreamCapture(b"forced nonzero\n", True),
            started.occurred_ns,
            finished.occurred_ns,
            (started, finished),
        )


def test_subject_runtime_installs_and_origin_binds_the_prepared_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _subject_fixture(tmp_path)
    distinctive = source / "graphify/working_tree_input.py"
    distinctive.write_text("SOURCE = 'working tree'\n", encoding="utf-8")
    before = _files(source)
    _seed_ambient_decoys(tmp_path, monkeypatch)

    result = SubjectRuntime().assess(source, tmp_path / "work", ("fictional",))

    assert isinstance(result, SubjectVerified)
    assert result.identity == "graphify-fictional@1.0.0"
    assert result.target_names == ("fictional",)
    assert result.executable.is_file()
    assert result.built_artifact.suffix == ".whl"
    assert result.built_artifact.is_file()
    assert (result.prepared_source / distinctive.relative_to(source)).read_text(
        encoding="utf-8"
    ) == "SOURCE = 'working tree'\n"
    assert before == _files(source)
    assert result.executable.is_relative_to(tmp_path / "work/environment")
    assert all(
        not (result.prepared_source / excluded).exists()
        for excluded in result.preparation.excluded_names
    )
    assert tuple(command.stage for command in result.commands) == (
        "build-subject",
        "create-environment",
        "install-subject",
        "probe-origins",
        "probe-version",
        "probe-targets",
    )
    assert all(command.exit_code == 0 and command.failure is None for command in result.commands)
    assert all(command.working_directory.endswith("/neutral") for command in result.commands)
    origins = json.loads(result.commands[3].stdout.data)
    assert Path(origins["distribution_root"]).is_relative_to(tmp_path / "work/environment")
    assert Path(origins["import_path"]).is_relative_to(tmp_path / "work/environment")
    assert Path(origins["executable_path"]).is_relative_to(tmp_path / "work/environment")


def test_subject_runtime_rejects_catalog_probe_mismatch_with_command_evidence(
    tmp_path: Path,
) -> None:
    source = _subject_fixture(tmp_path)

    result = SubjectRuntime().assess(source, tmp_path / "work", ("different",))

    assert isinstance(result, SubjectRejected)
    assert result.stage == "probe-targets"
    assert result.commands[-1].stage == "probe-targets"
    assert result.commands[-1].stdout.data == b"fictional\n"


def test_subject_runtime_rejects_malformed_public_version_before_target_probe(
    tmp_path: Path,
) -> None:
    source = _subject_fixture(tmp_path)
    cli = source / "graphify/cli.py"
    cli.write_text(
        cli.read_text(encoding="utf-8").replace(
            'print("graphify-fictional 1.0.0")',
            'print("graphify-fictional malformed")',
        ),
        encoding="utf-8",
    )

    result = SubjectRuntime().assess(source, tmp_path / "work", ("fictional",))

    assert isinstance(result, SubjectRejected)
    assert result.stage == "probe-version"
    assert result.detail == "public version disagrees with distribution"
    assert result.commands[-1].stage == "probe-version"


@pytest.mark.parametrize(
    ("stage", "failure_index", "mode"),
    (
        ("build-subject", 0, "custody"),
        ("build-subject", 0, "timeout"),
        ("create-environment", 1, "nonzero"),
        ("install-subject", 2, "nonzero"),
        ("probe-origins", 3, "nonzero"),
        ("probe-origins", 3, "malformed"),
    ),
)
def test_subject_runtime_retains_fail_closed_evidence_at_each_command_boundary(
    tmp_path: Path,
    stage: str,
    failure_index: int,
    mode: Literal["custody", "malformed", "nonzero", "timeout"],
) -> None:
    source = _subject_fixture(tmp_path)
    runtime = SubjectRuntime(process_runner=_ControlledRunner(failure_index, mode))

    result = runtime.assess(source, tmp_path / "work", ("fictional",))

    assert isinstance(result, SubjectRejected)
    assert result.stage == stage
    evidence = result.commands[-1]
    assert evidence.stage == stage
    assert evidence.working_directory.endswith("/neutral")
    if mode == "custody":
        assert evidence.failure == "establish_process_custody: forced custody failure"
    elif mode == "timeout":
        assert evidence.timed_out is True
        assert evidence.stdout.data == b"partial"
    elif mode == "malformed":
        assert evidence.exit_code == 0
        assert result.detail.startswith("malformed origin probe")
    else:
        assert evidence.exit_code == 17
        assert evidence.stderr.data == b"forced nonzero\n"


@pytest.mark.parametrize("through_symlink", (False, True))
def test_subject_runtime_rejects_work_roots_aliased_to_the_source_before_mutation(
    tmp_path: Path,
    through_symlink: bool,
) -> None:
    source = _subject_fixture(tmp_path)
    before = _files(source)
    parent = source
    if through_symlink:
        parent = tmp_path / "source-alias"
        parent.symlink_to(source, target_is_directory=True)
    work = parent / "work"

    result = SubjectRuntime().assess(source, work, ("fictional",))

    assert isinstance(result, SubjectRejected)
    assert result.stage == "prepare-source"
    assert not work.exists()
    assert _files(source) == before
