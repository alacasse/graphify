"""Thin composition root for the unreachable replacement diagnostic image."""

from __future__ import annotations

import os
import sys
from pathlib import Path, PurePosixPath

from tools.install_sandbox.diagnostics.manifest import (
    DiagnosticInput,
    ManifestContext,
    produce_manifest,
    produce_preflight_manifest,
)
from tools.install_sandbox.sandbox_runtime.session import SandboxRuntime
from tools.install_sandbox.sandbox_runtime.subject import SubjectRuntime
from tools.install_sandbox.sandbox_runtime.subject_types import SubjectRejected
from tools.install_sandbox.sandbox_runtime.types import SandboxFinishReason
from tools.install_sandbox.validation.catalog import CatalogDocuments, Scope
from tools.install_sandbox.validation.completion import ValidationCompleted
from tools.install_sandbox.validation.engine import validate
from tools.install_sandbox.validation.plan_types import HarnessPolicy, ValidationRequest

_CATALOG = Path("/opt/graphify-fixture/catalog")
_SUBJECT_SOURCE = Path("/opt/graphify-fixture/source")
_SUBJECT_WORK = Path("/work/subject")
_SESSION_ROOT = Path("/work/session")
_TIER_ONE_LIMITATION = (
    "Tier 1 validates installer filesystem effects, not target application behavior."
)


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise ValueError(f"missing required container identity: {name}")
    return value


def _selected_targets(documents: CatalogDocuments) -> tuple[str, ...]:
    return tuple(PurePosixPath(document.filename).stem for document in documents.documents)


def _cleanup(runtime: SandboxRuntime, reason: SandboxFinishReason) -> bool:
    cleanup = runtime.finish(reason)
    if cleanup.removed and not cleanup.failures:
        return True
    details = (
        "; ".join(f"{failure.operation}: {failure.detail}" for failure in cleanup.failures)
        or "session root remains without a reported runtime failure"
    )
    print(
        f"replacement sandbox cleanup did not reach quiescence: removed={cleanup.removed}; "
        f"{details}",
        file=sys.stderr,
    )
    return False


def main() -> int:
    """Compose final owners once; keep lifecycle and evidence policy behind them."""

    runtime: SandboxRuntime | None = None
    try:
        documents = CatalogDocuments.from_directory(_CATALOG)
        targets = _selected_targets(documents)
        request = ValidationRequest(targets, (Scope.USER, Scope.PROJECT))
        context = ManifestContext(
            _required_environment("GRAPHIFY_RUN_ID"),
            _required_environment("GRAPHIFY_IMAGE_ID"),
            (_TIER_ONE_LIMITATION,),
        )
        subject = SubjectRuntime().assess(_SUBJECT_SOURCE, _SUBJECT_WORK, targets)
        if isinstance(subject, SubjectRejected):
            produce_preflight_manifest(Path("/diagnostic"), context, request, subject)
            print(f"subject {subject.stage} failed: {subject.detail}", file=sys.stderr)
            return 2
        runtime = SandboxRuntime.open(_SESSION_ROOT, subject.prepared_source)
        executable = str(subject.executable)
        result = validate(
            request,
            documents,
            HarnessPolicy(
                install_argv=(executable, "install"),
                uninstall_argv=(executable, "uninstall"),
                purge_argv=(executable, "uninstall", "--purge"),
            ),
            runtime.fulfil,
            runtime.begin_scenario,
        )
        if not isinstance(result, ValidationCompleted):
            _cleanup(runtime, SandboxFinishReason.REJECTED)
            print("; ".join(result.reasons), file=sys.stderr)
            return 2
        if not _cleanup(runtime, SandboxFinishReason.COMPLETED):
            return 2
        runtime = None
        produced = produce_manifest(Path("/diagnostic"), context, DiagnosticInput(result, subject))
        if not produced.complete:
            return 2
        return 1 if produced.has_findings else 0
    except Exception as error:
        if runtime is not None:
            try:
                _cleanup(runtime, SandboxFinishReason.ABORTED)
            except Exception as cleanup_error:
                print(f"replacement cleanup failed: {cleanup_error}", file=sys.stderr)
        print(f"replacement diagnostic failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
