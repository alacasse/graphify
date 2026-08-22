from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tools.install_sandbox.container import entrypoint
from tools.install_sandbox.diagnostics.manifest import (
    DiagnosticInput,
    ManifestContext,
    ProducedManifest,
)
from tools.install_sandbox.sandbox_runtime.subject_types import (
    PreparedSubjectFact,
    SubjectRejected,
    SubjectVerified,
)
from tools.install_sandbox.sandbox_runtime.types import (
    SandboxCleanupFact,
    SandboxFinishReason,
    SandboxRuntimeFailure,
)
from tools.install_sandbox.validation.catalog import Scope
from tools.install_sandbox.validation.completion import ValidationCompleted, ValidationRejected
from tools.install_sandbox.validation.plan_types import ValidationRequest
from tools.install_sandbox.validation.protocol import ActionRequest, RawFact


@dataclass
class _Runtime:
    cleanup: SandboxCleanupFact
    reasons: list[SandboxFinishReason] = field(default_factory=lambda: list[SandboxFinishReason]())
    fail_cleanup: bool = False

    def fulfil(self, _request: ActionRequest) -> RawFact:
        raise AssertionError("validation is replaced at this composition-root seam")

    def begin_scenario(self, _identity: str) -> None:
        return None

    def finish(self, reason: SandboxFinishReason) -> SandboxCleanupFact:
        self.reasons.append(reason)
        if self.fail_cleanup:
            raise OSError("forced cleanup failure")
        return self.cleanup


def _cleanup(
    *,
    removed: bool = True,
    failures: tuple[SandboxRuntimeFailure, ...] = (),
) -> SandboxCleanupFact:
    return SandboxCleanupFact(
        SandboxFinishReason.COMPLETED,
        removed,
        failures,
        (),
    )


def _completed() -> ValidationCompleted:
    result = object.__new__(ValidationCompleted)
    object.__setattr__(
        result,
        "request",
        ValidationRequest(("first", "second"), (Scope.USER, Scope.PROJECT)),
    )
    return result


def _subject(source: Path, work: Path, targets: tuple[str, ...]) -> SubjectVerified:
    preparation = PreparedSubjectFact(str(source), str(work / "prepared"), ("pyproject.toml",), ())
    return SubjectVerified(
        "graphify-fixture@1.0",
        "1.0",
        work / "environment/bin/graphify",
        work / "prepared",
        work / "artifacts/graphify_fixture-1.0.whl",
        targets,
        preparation,
        (),
    )


def _arrange(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runtime: _Runtime,
    result: ValidationCompleted | ValidationRejected,
) -> list[ManifestContext]:
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    (catalog / "second.yaml").write_text("fixture", encoding="utf-8")
    (catalog / "first.yaml").write_text("fixture", encoding="utf-8")
    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setattr(entrypoint, "_CATALOG", catalog)
    subject_work = tmp_path / "subject-work"
    monkeypatch.setattr(entrypoint, "_SUBJECT_SOURCE", source)
    monkeypatch.setattr(entrypoint, "_SUBJECT_WORK", subject_work)
    monkeypatch.setattr(entrypoint, "_SESSION_ROOT", tmp_path / "session")

    def open_runtime(*_args: object, **_kwargs: object) -> _Runtime:
        return runtime

    def run_validation(
        *_args: object, **_kwargs: object
    ) -> ValidationCompleted | ValidationRejected:
        return result

    monkeypatch.setattr(entrypoint.SandboxRuntime, "open", open_runtime)
    monkeypatch.setattr(entrypoint, "validate", run_validation)

    def assess_subject(
        _runtime: entrypoint.SubjectRuntime,
        given_source: Path,
        given_work: Path,
        targets: tuple[str, ...],
    ) -> SubjectVerified:
        return _subject(given_source, given_work, targets)

    monkeypatch.setattr(entrypoint.SubjectRuntime, "assess", assess_subject)
    for name, value in (
        ("GRAPHIFY_RUN_ID", "run-fixture"),
        ("GRAPHIFY_IMAGE_ID", "sha256:image-fixture"),
    ):
        monkeypatch.setenv(name, value)
    observed: list[ManifestContext] = []

    def produce(
        _output: Path,
        context: ManifestContext,
        _diagnostic: DiagnosticInput,
    ) -> ProducedManifest:
        observed.append(context)
        return ProducedManifest(tmp_path / "manifest.json", "digest", True, False)

    monkeypatch.setattr(entrypoint, "produce_manifest", produce)
    return observed


@pytest.mark.parametrize(
    ("complete", "findings", "expected"),
    ((True, False, 0), (True, True, 1), (False, False, 2)),
)
def test_entrypoint_returns_closed_manifest_outcomes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    complete: bool,
    findings: bool,
    expected: int,
) -> None:
    runtime = _Runtime(_cleanup())
    observed = _arrange(tmp_path, monkeypatch, runtime, _completed())

    def produce(
        _output: Path,
        context: ManifestContext,
        _diagnostic: DiagnosticInput,
    ) -> ProducedManifest:
        observed.append(context)
        return ProducedManifest(tmp_path / "manifest.json", "digest", complete, findings)

    monkeypatch.setattr(entrypoint, "produce_manifest", produce)

    assert entrypoint.main() == expected
    assert runtime.reasons == [SandboxFinishReason.COMPLETED]
    assert observed[0].run_id == "run-fixture"


def test_entrypoint_rejects_validation_and_cleans_the_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = _Runtime(_cleanup())
    observed = _arrange(
        tmp_path,
        monkeypatch,
        runtime,
        ValidationRejected(("fictional plan rejected",)),
    )

    assert entrypoint.main() == 2
    assert runtime.reasons == [SandboxFinishReason.REJECTED]
    assert observed == []
    assert "fictional plan rejected" in capsys.readouterr().err


@pytest.mark.parametrize(
    "stage",
    (
        "prepare-source",
        "build-subject",
        "create-environment",
        "install-subject",
        "probe-origins",
        "probe-version",
        "probe-targets",
    ),
)
def test_entrypoint_publishes_incomplete_probe_evidence_before_any_scenario(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stage: str,
) -> None:
    runtime = _Runtime(_cleanup())
    observed = _arrange(tmp_path, monkeypatch, runtime, _completed())
    rejection = SubjectRejected(stage, "forced subject diagnostic failure", None, ())

    def reject_subject(
        _runtime: entrypoint.SubjectRuntime,
        _source: Path,
        _work: Path,
        _targets: tuple[str, ...],
    ) -> SubjectRejected:
        return rejection

    monkeypatch.setattr(entrypoint.SubjectRuntime, "assess", reject_subject)
    preflights: list[SubjectRejected] = []

    def produce_preflight(
        _output: Path,
        _context: ManifestContext,
        _request: object,
        failure: SubjectRejected,
    ) -> ProducedManifest:
        preflights.append(failure)
        return ProducedManifest(tmp_path / "manifest.json", "digest", False, False)

    monkeypatch.setattr(entrypoint, "produce_preflight_manifest", produce_preflight)

    assert entrypoint.main() == 2
    assert runtime.reasons == []
    assert observed == []
    assert preflights == [rejection]
    assert f"subject {stage} failed" in capsys.readouterr().err


@pytest.mark.parametrize(
    "cleanup",
    (
        _cleanup(removed=False),
        _cleanup(
            removed=False,
            failures=(SandboxRuntimeFailure("remove_session_root", "permission denied"),),
        ),
    ),
)
def test_entrypoint_refuses_to_publish_after_incomplete_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    cleanup: SandboxCleanupFact,
) -> None:
    runtime = _Runtime(cleanup)
    observed = _arrange(tmp_path, monkeypatch, runtime, _completed())

    assert entrypoint.main() == 2
    assert observed == []
    assert "cleanup did not reach quiescence" in capsys.readouterr().err


@pytest.mark.parametrize("fail_cleanup", (False, True))
def test_entrypoint_aborts_and_reports_unexpected_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fail_cleanup: bool,
) -> None:
    runtime = _Runtime(_cleanup(), fail_cleanup=fail_cleanup)
    _arrange(tmp_path, monkeypatch, runtime, _completed())

    def fail_validation(*_args: object) -> ValidationCompleted:
        raise ValueError("fictional validation failure")

    monkeypatch.setattr(entrypoint, "validate", fail_validation)

    assert entrypoint.main() == 2
    assert runtime.reasons == [SandboxFinishReason.ABORTED]
    error = capsys.readouterr().err
    assert "fictional validation failure" in error
    if fail_cleanup:
        assert "replacement cleanup failed: forced cleanup failure" in error


@pytest.mark.parametrize("blank", (False, True))
def test_entrypoint_rejects_missing_or_blank_identity_before_preparation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    blank: bool,
) -> None:
    runtime = _Runtime(_cleanup())
    _arrange(tmp_path, monkeypatch, runtime, _completed())
    if blank:
        monkeypatch.setenv("GRAPHIFY_RUN_ID", "  ")
    else:
        monkeypatch.delenv("GRAPHIFY_RUN_ID")

    assert entrypoint.main() == 2
    assert runtime.reasons == []
    assert "missing required container identity: GRAPHIFY_RUN_ID" in capsys.readouterr().err
