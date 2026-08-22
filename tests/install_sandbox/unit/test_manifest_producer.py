from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from tools.install_sandbox.diagnostics.evidence import EvidenceWriter, write_raw_facts
from tools.install_sandbox.diagnostics.manifest import (
    DiagnosticInput,
    ManifestContext,
    ProducedManifest,
    produce_manifest,
    produce_preflight_manifest,
)
from tools.install_sandbox.sandbox_runtime.subject_types import (
    PreparedSubjectFact,
    SubjectCommandFact,
    SubjectRejected,
    SubjectVerified,
)
from tools.install_sandbox.validation.catalog import (
    CatalogDocument,
    CatalogDocuments,
    OwnedFileSurface,
    Scope,
    SurfaceRoot,
)
from tools.install_sandbox.validation.completion import ValidationCompleted
from tools.install_sandbox.validation.engine import validate
from tools.install_sandbox.validation.plan_types import HarnessPolicy, ValidationRequest
from tools.install_sandbox.validation.protocol import (
    ActionFailureFact,
    ActionId,
    ActionKind,
    ActionRequest,
    ByteCapture,
    CommandFact,
    CommandFailureFact,
    CommandRequest,
    EntryFact,
    EntryKind,
    FilesystemSnapshot,
    HarnessFileSurface,
    ManagedTreeSurface,
    ObservationFact,
    ObservationRequest,
    OperationEvent,
    OperationKind,
    PhaseKind,
    PreparationFact,
    PreparationRequest,
    PreparedSourcePath,
    RawFact,
    SandboxPath,
    SnapshotEntry,
    StreamCapture,
    SurfaceExpectation,
    SurfaceFact,
)


def _root_snapshot() -> FilesystemSnapshot:
    return FilesystemSnapshot(
        tuple(SnapshotEntry(root, ".", EntryKind.DIRECTORY) for root in SurfaceRoot)
    )


def _source_content(surface: OwnedFileSurface) -> bytes:
    return b"{}\n" if surface.source == "fixtures/graph.json" else b"fixture payload\n"


class _PassingFacts:
    def __init__(self) -> None:
        self._sequence = 0

    def _events(
        self,
        started: OperationKind,
        finished: OperationKind,
    ) -> tuple[OperationEvent, OperationEvent]:
        events = (
            OperationEvent(self._sequence, started, self._sequence),
            OperationEvent(self._sequence + 1, finished, self._sequence + 1),
        )
        self._sequence += 2
        return events

    def __call__(
        self,
        request: CommandRequest | ObservationRequest | PreparationRequest,
    ) -> RawFact:
        if isinstance(request, CommandRequest):
            chronology = self._events(
                OperationKind.COMMAND_STARTED,
                OperationKind.COMMAND_FINISHED,
            )
            return CommandFact(
                request.action_id,
                0,
                request.argv,
                SurfaceRoot.USER_CWD if request.scope is Scope.USER else SurfaceRoot.PROJECT,
                None,
                False,
                StreamCapture(b"", True),
                StreamCapture(b"", True),
                chronology[0].occurred_ns,
                chronology[-1].occurred_ns,
                chronology,
                _root_snapshot(),
                _root_snapshot(),
            )
        if isinstance(request, PreparationRequest):
            chronology = self._events(
                OperationKind.PREPARATION_STARTED,
                OperationKind.PREPARATION_FINISHED,
            )
            return PreparationFact(
                request.action_id,
                tuple(
                    EntryFact(
                        fixture.location,
                        EntryKind.FILE,
                        size=len(fixture.content),
                        sha256=hashlib.sha256(fixture.content).hexdigest(),
                        content=ByteCapture(fixture.content, True),
                    )
                    for fixture in request.files
                ),
                chronology[0].occurred_ns,
                chronology[-1].occurred_ns,
                chronology,
            )
        chronology = self._events(
            OperationKind.OBSERVATION_STARTED,
            OperationKind.OBSERVATION_FINISHED,
        )
        observed: list[SurfaceFact] = []
        for surface, expectation in zip(
            request.surfaces,
            request.expectations,
            strict=True,
        ):
            content = (
                surface.content
                if isinstance(surface, HarnessFileSurface)
                else _source_content(surface)
                if isinstance(surface, OwnedFileSurface)
                else b""
            )
            destination = EntryFact(
                SandboxPath(surface.root, surface.path),
                EntryKind.MISSING,
            )
            if expectation is SurfaceExpectation.INSTALLED:
                destination = EntryFact(
                    SandboxPath(surface.root, surface.path),
                    (
                        EntryKind.DIRECTORY
                        if isinstance(surface, ManagedTreeSurface)
                        else EntryKind.FILE
                    ),
                    size=None if isinstance(surface, ManagedTreeSurface) else len(content),
                    sha256=(
                        None
                        if isinstance(surface, ManagedTreeSurface)
                        else hashlib.sha256(content).hexdigest()
                    ),
                    content=(
                        None
                        if isinstance(surface, ManagedTreeSurface)
                        else ByteCapture(content, True)
                    ),
                )
            source = (
                EntryFact(
                    PreparedSourcePath(surface.source),
                    EntryKind.FILE,
                    size=len(content),
                    sha256=hashlib.sha256(content).hexdigest(),
                    content=ByteCapture(content, True),
                )
                if isinstance(surface, OwnedFileSurface)
                else None
            )
            observed.append(SurfaceFact(surface, destination, source))
        return ObservationFact(
            request.action_id,
            tuple(observed),
            chronology[0].occurred_ns,
            chronology[-1].occurred_ns,
            chronology,
        )


def _completed_validation(
    scopes: tuple[Scope, ...] = (Scope.PROJECT,),
    *,
    user_supported: bool = False,
    transform: Callable[[ActionRequest, RawFact], RawFact] | None = None,
) -> ValidationCompleted:
    user: dict[str, object] = {
        "supported": False,
        "reason": "User scope is unavailable in this fixture.",
        "runtime_limitations": [],
    }
    if user_supported:
        user = {
            "supported": True,
            "runtime_limitations": ["The user fixture proves filesystem effects only."],
            "surfaces": [
                {
                    "kind": "owned_file",
                    "root": "home",
                    "path": ".fictional/user.txt",
                    "source": "fixtures/user.txt",
                }
            ],
        }
    passing = _PassingFacts()

    def fulfil(request: ActionRequest) -> RawFact:
        fact = passing(request)
        return fact if transform is None else transform(request, fact)

    result = validate(
        ValidationRequest(("fictional",), scopes),
        CatalogDocuments(
            (
                CatalogDocument(
                    "fictional.yaml",
                    json.dumps(
                        {
                            "scopes": {
                                "user": user,
                                "project": {
                                    "supported": True,
                                    "runtime_limitations": [
                                        "The fixture proves filesystem effects only."
                                    ],
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
        ),
        HarnessPolicy(),
        fulfil,
    )
    assert isinstance(result, ValidationCompleted)
    return result


def _subject(targets: tuple[str, ...]) -> SubjectVerified:
    preparation = PreparedSubjectFact(
        "/subject",
        "/work/subject/prepared",
        ("graphify/__init__.py",),
        (".git", ".venv", "__pycache__", "graphify-out", "my-docs"),
    )
    return SubjectVerified(
        "graphify-fixture@1.0",
        "1.0",
        Path("/work/subject/environment/bin/graphify"),
        Path(preparation.prepared_root),
        Path("/work/subject/artifacts/graphify_fixture-1.0.whl"),
        targets,
        preparation,
        (),
    )


def _produce(
    output: Path,
    context: ManifestContext,
    validation: ValidationCompleted,
) -> ProducedManifest:
    return produce_manifest(
        output, context, DiagnosticInput(validation, _subject(validation.request.targets))
    )


def test_manifest_producer_content_binds_every_subordinate_document(tmp_path: Path) -> None:
    output = tmp_path / "diagnostic"
    validation = _completed_validation()
    context = ManifestContext(
        run_id="run-fixture",
        image_identity="sha256:image-fixture",
        harness_runtime_limitations=(
            "Tier 1 validates installer filesystem effects, not target application behavior.",
        ),
    )

    produced = _produce(output, context, validation)

    manifest_path = output / "manifest.json"
    assert produced.path == manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == {
        "kind": "graphify.install-sandbox.diagnostic-manifest",
        "version": 1,
    }
    assert manifest["validation_plan"]["id"] == validation.plan.plan_id
    assert manifest["run"]["subject_identity"] == "graphify-fixture@1.0"
    assert manifest["subject"]["published_targets"] == ["fictional"]
    assert manifest["subject"]["preparation"] == "subject/preparation.json"
    assert manifest["purge"]["status"] == "PASS"
    assert manifest["runtime_limitations"] == [
        "Tier 1 validates installer filesystem effects, not target application behavior.",
        "The fixture proves filesystem effects only.",
    ]

    references = manifest["evidence"]
    paths = [reference["path"] for reference in references]
    assert len(paths) == len(set(paths))
    assert any(path.endswith(".stdout.log") for path in paths)
    assert any(path.endswith(".stderr.log") for path in paths)
    assert set(paths) == {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file() and path != manifest_path
    }
    for reference in references:
        payload = (output / reference["path"]).read_bytes()
        assert reference["size"] == len(payload)
        assert reference["sha256"] == hashlib.sha256(payload).hexdigest()
        if reference["path"].endswith(".json"):
            document = json.loads(payload)
            assert document["schema"]["version"] == 1
            if any(
                reference["path"].endswith(suffix)
                for suffix in (
                    ".command.json",
                    ".observation.json",
                    ".preparation.json",
                    ".failure.json",
                )
            ):
                assert all(
                    set(event) == {"sequence", "kind", "occurred_ns"}
                    for event in document["chronology"]
                )


def _context() -> ManifestContext:
    return ManifestContext(
        "run-fixture",
        "sha256:image-fixture",
        (),
    )


def test_manifest_projects_isolation_and_unsupported_scenarios(tmp_path: Path) -> None:
    isolation = _completed_validation(
        (Scope.USER, Scope.PROJECT),
        user_supported=True,
    )
    unsupported = _completed_validation((Scope.USER, Scope.PROJECT))

    _produce(tmp_path / "isolation", _context(), isolation)
    _produce(tmp_path / "unsupported", _context(), unsupported)

    isolation_manifest = json.loads(
        (tmp_path / "isolation/manifest.json").read_text(encoding="utf-8")
    )
    unsupported_manifest = json.loads(
        (tmp_path / "unsupported/manifest.json").read_text(encoding="utf-8")
    )
    assert "scope-isolation" in {
        scenario["kind"] for scenario in isolation_manifest["validation_plan"]["scenarios"]
    }
    assert "unsupported-target" in {
        scenario["kind"] for scenario in unsupported_manifest["validation_plan"]["scenarios"]
    }
    assert any(
        scenario["id"].endswith("unsupported-fictional-user")
        for scenario in unsupported_manifest["scenarios"]
    )


def test_manifest_reports_finding_and_incomplete_outcomes(tmp_path: Path) -> None:
    def product_finding(request: ActionRequest, fact: RawFact) -> RawFact:
        if (
            isinstance(request, CommandRequest)
            and request.phase is PhaseKind.INSTALL
            and isinstance(fact, CommandFact)
        ):
            return replace(fact, exit_code=17)
        return fact

    finding_validation = _completed_validation(transform=product_finding)
    finding = _produce(tmp_path / "finding", _context(), finding_validation)

    def diagnostic_failure(request: ActionRequest, fact: RawFact) -> RawFact:
        if (
            isinstance(request, CommandRequest)
            and request.phase is PhaseKind.INSTALL
            and isinstance(fact, CommandFact)
        ):
            chronology = (
                fact.chronology[0],
                replace(fact.chronology[-1], kind=OperationKind.COMMAND_FAILED),
            )
            return ActionFailureFact(
                request.action_id,
                ActionKind.COMMAND,
                "spawn_command",
                "fictional diagnostic failure",
                chronology,
            )
        return fact

    incomplete_validation = _completed_validation(transform=diagnostic_failure)
    incomplete = _produce(tmp_path / "incomplete", _context(), incomplete_validation)

    def purge_tree_remains(request: ActionRequest, fact: RawFact) -> RawFact:
        if not (
            isinstance(request, ObservationRequest)
            and request.phase is PhaseKind.PURGE
            and isinstance(fact, ObservationFact)
        ):
            return fact
        surfaces = tuple(
            replace(
                surface,
                destination=EntryFact(
                    surface.destination.location,
                    EntryKind.DIRECTORY,
                ),
            )
            if isinstance(surface.surface, ManagedTreeSurface)
            else surface
            for surface in fact.surfaces
        )
        return replace(fact, surfaces=surfaces)

    purge_finding = _completed_validation(transform=purge_tree_remains)
    purge = _produce(tmp_path / "purge-finding", _context(), purge_finding)

    assert finding.has_findings is True
    assert incomplete.complete is False
    assert purge.has_findings is True


def test_preflight_manifest_retains_failed_probe_evidence_without_scenarios(
    tmp_path: Path,
) -> None:
    preparation = _subject(("fictional",)).preparation
    command = SubjectCommandFact(
        "probe-version",
        ("/isolated/graphify", "--version"),
        "/neutral",
        0,
        False,
        StreamCapture(b"not-a-version\n", True),
        StreamCapture(b"", True),
        1,
        2,
    )
    rejection = SubjectRejected(
        "probe-version",
        "public version disagrees with distribution",
        preparation,
        (command,),
    )

    produced = produce_preflight_manifest(
        tmp_path / "preflight",
        _context(),
        ValidationRequest(("fictional",), (Scope.USER, Scope.PROJECT)),
        rejection,
    )

    manifest = json.loads(produced.path.read_text(encoding="utf-8"))
    assert produced.complete is False
    assert produced.has_findings is False
    assert manifest["summary"] == {"INCOMPLETE": 1}
    assert manifest["subject"]["failed_stage"] == "probe-version"
    assert manifest["scenarios"] == []
    assert manifest["purge"] == {"result": None, "status": "INCOMPLETE"}
    assert manifest["subject"]["commands"] == ["subject/commands/00-probe-version.json"]


def test_evidence_writer_serializes_failure_variants_and_rejects_unsafe_paths(
    tmp_path: Path,
) -> None:
    validation = _completed_validation()
    command = next(fact for fact in validation.raw_facts if isinstance(fact, CommandFact))
    command_failure = CommandFailureFact(
        ActionId(command.action_id.plan_id, 900),
        command.exit_code,
        command.argv,
        command.working_directory,
        command.signal,
        command.timed_out,
        command.stdout,
        command.stderr,
        command.started_ns,
        command.finished_ns,
        command.chronology,
        command.before_snapshot,
        command.after_snapshot,
        "complete_process_custody",
        "fictional custody failure",
    )
    action_failure = ActionFailureFact(
        ActionId(command.action_id.plan_id, 901),
        ActionKind.COMMAND,
        "spawn_command",
        "fictional spawn failure",
        (),
    )
    writer = EvidenceWriter(tmp_path / "evidence")

    paths = write_raw_facts(writer, (command_failure, action_failure))

    assert paths[command_failure.action_id].endswith(".command.json")
    assert paths[action_failure.action_id].endswith(".failure.json")
    failure_document = json.loads(
        (tmp_path / "evidence" / paths[action_failure.action_id]).read_text(encoding="utf-8")
    )
    command_document = json.loads(
        (tmp_path / "evidence" / paths[command_failure.action_id]).read_text(encoding="utf-8")
    )
    assert failure_document["diagnostic_failure"] == "fictional spawn failure"
    assert command_document["chronology"] == [
        {
            "sequence": event.sequence,
            "kind": event.kind.value,
            "occurred_ns": event.occurred_ns,
        }
        for event in command_failure.chronology
    ]
    assert failure_document["chronology"] == [
        {
            "sequence": event.sequence,
            "kind": event.kind.value,
            "occurred_ns": event.occurred_ns,
        }
        for event in action_failure.chronology
    ]
    with pytest.raises(ValueError, match="unsafe evidence path"):
        writer.write_bytes("../outside", "fixture", b"unsafe")
    writer.write_bytes("fresh.txt", "fixture", b"fresh")
    with pytest.raises(ValueError, match="not fresh"):
        writer.write_bytes("fresh.txt", "fixture", b"duplicate")


def test_manifest_rejects_invalid_context_and_output_roots(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="identities"):
        ManifestContext("", "image", ())

    validation = _completed_validation()
    with pytest.raises(ValueError, match="evidence disagrees"):
        replace(
            validation,
            request=ValidationRequest(("different",), (Scope.PROJECT,)),
        )
    with pytest.raises(ValueError, match="evidence disagrees"):
        replace(
            validation,
            scenario_results=tuple(reversed(validation.scenario_results)),
        )
    with pytest.raises(ValueError, match="evidence disagrees"):
        replace(
            validation,
            scenario_results=(
                validation.scenario_results[0],
                validation.scenario_results[0],
            ),
        )
    with pytest.raises(ValueError, match="evidence disagrees"):
        replace(validation, raw_facts=validation.raw_facts[:-1])
    with pytest.raises(ValueError, match="evidence disagrees"):
        replace(
            validation,
            purge_result=replace(
                validation.purge_result,
                runtime_limitations=("incorrect limitation",),
            ),
        )
    with pytest.raises(ValueError, match="target selection disagrees"):
        DiagnosticInput(validation, _subject(("different",)))
    real_directory = tmp_path / "real"
    real_directory.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real_directory, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        _produce(linked, _context(), validation)

    nonempty = tmp_path / "nonempty"
    nonempty.mkdir()
    (nonempty / "existing.txt").write_text("existing", encoding="utf-8")
    with pytest.raises(ValueError, match="absent or empty"):
        _produce(nonempty, _context(), validation)

    regular_file = tmp_path / "regular-file"
    regular_file.write_text("existing", encoding="utf-8")
    with pytest.raises(ValueError, match="absent or empty"):
        _produce(regular_file, _context(), validation)
