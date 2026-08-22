from __future__ import annotations

import hashlib
import itertools
import json
from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace
from typing import cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tools.install_sandbox.validation.catalog import (
    CatalogDocument,
    CatalogDocuments,
    OwnedFileSurface,
    RepairableBundleSurface,
    Scope,
    SupportedScopeFacts,
    SurfaceRoot,
    TextEntrySurface,
)
from tools.install_sandbox.validation.completion import ValidationCompleted, ValidationRejected
from tools.install_sandbox.validation.engine import validate
from tools.install_sandbox.validation.fact_validation import (
    validate_raw_fact,
    validate_session_chronology,
)
from tools.install_sandbox.validation.plan_types import (
    AggregatePlan,
    HarnessPolicy,
    LifecyclePlan,
    NotApplicablePhasePlan,
    PhasePlan,
    PurgePlan,
    ScopeIsolationPlan,
    UnsupportedPlan,
    ValidationRequest,
)
from tools.install_sandbox.validation.protocol import (
    ActionFailureFact,
    ActionId,
    ActionKind,
    ActionRequest,
    AggregateSubject,
    ByteCapture,
    CommandFact,
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
    TargetSubject,
)
from tools.install_sandbox.validation.results import (
    AggregateResult,
    LifecycleResult,
    PhaseResult,
    PhaseStatus,
    ProductFinding,
    PurgeResult,
    PurgeStatus,
    ScenarioStatus,
    ScopeIsolationResult,
    UnsupportedResult,
)


def _root_snapshot() -> FilesystemSnapshot:
    return FilesystemSnapshot(
        tuple(SnapshotEntry(root, ".", EntryKind.DIRECTORY) for root in SurfaceRoot)
    )


def _chronology(
    action_id: ActionId,
    started: OperationKind,
    finished: OperationKind,
) -> tuple[OperationEvent, ...]:
    first_sequence = action_id.ordinal * 2
    first_time = action_id.ordinal * 10 + 1
    return (
        OperationEvent(first_sequence, started, first_time),
        OperationEvent(first_sequence + 1, finished, first_time + 1),
    )


def _passing_observation(request: ObservationRequest) -> ObservationFact:
    surfaces: list[SurfaceFact] = []
    for surface, expectation in zip(
        request.surfaces,
        request.expectations,
        strict=True,
    ):
        if isinstance(surface, TextEntrySurface):
            payload = f"{surface.entry}\n{surface.required_text}\n".encode()
            source = None
        elif isinstance(surface, HarnessFileSurface):
            payload = surface.content
            source = None
        elif isinstance(surface, ManagedTreeSurface):
            payload = b""
            source = None
        else:
            payload = b"expected payload\n"
            source = EntryFact(
                PreparedSourcePath(surface.source),
                EntryKind.FILE,
                size=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                content=ByteCapture(payload, True),
            )
        installed = expectation is not SurfaceExpectation.ABSENT
        destination = EntryFact(
            SandboxPath(surface.root, surface.path),
            (
                EntryKind.DIRECTORY
                if installed and isinstance(surface, ManagedTreeSurface)
                else EntryKind.FILE
                if installed
                else EntryKind.MISSING
            ),
            size=(
                len(payload) if installed and not isinstance(surface, ManagedTreeSurface) else None
            ),
            sha256=(
                hashlib.sha256(payload).hexdigest()
                if installed and not isinstance(surface, ManagedTreeSurface)
                else None
            ),
            content=(
                ByteCapture(payload, True)
                if installed and not isinstance(surface, ManagedTreeSurface)
                else None
            ),
        )
        surfaces.append(SurfaceFact(surface, destination, source))
    chronology = _chronology(
        request.action_id,
        OperationKind.OBSERVATION_STARTED,
        OperationKind.OBSERVATION_FINISHED,
    )
    return ObservationFact(
        request.action_id,
        tuple(surfaces),
        chronology[0].occurred_ns,
        chronology[-1].occurred_ns,
        chronology,
    )


def _passing_command(request: CommandRequest) -> CommandFact:
    working_directory = SurfaceRoot.USER_CWD if request.scope is Scope.USER else SurfaceRoot.PROJECT
    chronology = _chronology(
        request.action_id,
        OperationKind.COMMAND_STARTED,
        OperationKind.COMMAND_FINISHED,
    )
    snapshot = _root_snapshot()
    return CommandFact(
        request.action_id,
        0,
        request.argv,
        working_directory,
        None,
        False,
        StreamCapture(b"", True),
        StreamCapture(b"", True),
        chronology[0].occurred_ns,
        chronology[-1].occurred_ns,
        chronology,
        snapshot,
        snapshot,
    )


def _timed_out_command(
    request: CommandRequest,
    *,
    stdout: StreamCapture,
    stderr: StreamCapture,
) -> CommandFact:
    first_sequence = request.action_id.ordinal * 4
    first_time = request.action_id.ordinal * 10 + 1
    chronology = tuple(
        OperationEvent(first_sequence + offset, kind, first_time + offset)
        for offset, kind in enumerate(
            (
                OperationKind.COMMAND_STARTED,
                OperationKind.COMMAND_TIMED_OUT,
                OperationKind.COMMAND_TERMINATED,
                OperationKind.COMMAND_FINISHED,
            )
        )
    )
    return replace(
        _passing_command(request),
        exit_code=-9,
        signal=9,
        timed_out=True,
        stdout=stdout,
        stderr=stderr,
        started_ns=chronology[0].occurred_ns,
        finished_ns=chronology[-1].occurred_ns,
        chronology=chronology,
    )


def _passing_preparation(request: PreparationRequest) -> PreparationFact:
    chronology = _chronology(
        request.action_id,
        OperationKind.PREPARATION_STARTED,
        OperationKind.PREPARATION_FINISHED,
    )
    entries = tuple(
        EntryFact(
            fixture.location,
            EntryKind.FILE,
            size=len(fixture.content),
            sha256=hashlib.sha256(fixture.content).hexdigest(),
            content=ByteCapture(fixture.content, True),
        )
        for fixture in request.files
    )
    return PreparationFact(
        request.action_id,
        entries,
        chronology[0].occurred_ns,
        chronology[-1].occurred_ns,
        chronology,
    )


def _passing_fulfil(
    request: CommandRequest | ObservationRequest | PreparationRequest,
) -> RawFact:
    if isinstance(request, CommandRequest):
        return _passing_command(request)
    if isinstance(request, PreparationRequest):
        return _passing_preparation(request)
    return _passing_observation(request)


class _SessionFacts:
    def __init__(self) -> None:
        self._next_sequence = 0
        self._next_time = 0

    def bind(self, fact: RawFact) -> RawFact:
        chronology = tuple(
            replace(
                event,
                sequence=self._next_sequence + offset,
                occurred_ns=self._next_time + offset,
            )
            for offset, event in enumerate(fact.chronology)
        )
        self._next_sequence += len(chronology)
        self._next_time += len(chronology)
        if isinstance(fact, CommandFact):
            return replace(
                fact,
                started_ns=chronology[0].occurred_ns,
                finished_ns=chronology[-1].occurred_ns,
                chronology=chronology,
            )
        if isinstance(fact, ObservationFact):
            return replace(
                fact,
                started_ns=chronology[0].occurred_ns,
                finished_ns=chronology[-1].occurred_ns,
                chronology=chronology,
            )
        if isinstance(fact, PreparationFact):
            return replace(
                fact,
                started_ns=chronology[0].occurred_ns,
                finished_ns=chronology[-1].occurred_ns,
                chronology=chronology,
            )
        return replace(fact, chronology=chronology)

    def passing(
        self,
        request: CommandRequest | ObservationRequest | PreparationRequest,
    ) -> RawFact:
        return self.bind(_passing_fulfil(request))


def _catalog_text(project: object, user: object | None = None) -> str:
    if user is None:
        user = {
            "supported": False,
            "reason": "User scope is unavailable.",
            "runtime_limitations": [],
        }
    return json.dumps({"scopes": {"user": user, "project": project}})


def _owned_file_surface(**changes: object) -> dict[str, object]:
    surface: dict[str, object] = {
        "kind": "owned_file",
        "root": "project",
        "path": ".fictional/config.txt",
        "source": "fixtures/config.txt",
    }
    surface.update(changes)
    return surface


def _supported_project(
    *surfaces: object,
    limitations: tuple[str, ...] | str = (),
) -> dict[str, object]:
    return {
        "supported": True,
        "runtime_limitations": list(limitations) if isinstance(limitations, tuple) else limitations,
        "surfaces": list(surfaces),
    }


def test_fictional_target_becomes_immutable_facts_and_a_complete_plan() -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                """
scopes:
  user:
    supported: false
    reason: Fictional user installs are unavailable.
    runtime_limitations: []
  project:
    supported: true
    runtime_limitations:
      - The fixture proves filesystem effects only.
    surfaces:
      - kind: owned_file
        root: project
        path: .fictional/config.txt
        source: fixtures/fictional.txt
""".lstrip(),
            ),
        )
    )
    requests: list[CommandRequest | ObservationRequest | PreparationRequest] = []

    def fulfil(
        request: CommandRequest | ObservationRequest | PreparationRequest,
    ) -> RawFact:
        requests.append(request)
        return _passing_fulfil(request)

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT, Scope.USER)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationCompleted)
    assert tuple(target.name for target in result.catalog.targets) == ("fictional",)
    project_facts = result.catalog.targets[0].facts_for(Scope.PROJECT)
    assert isinstance(project_facts, SupportedScopeFacts)
    assert project_facts.surfaces == (
        OwnedFileSurface(
            root=SurfaceRoot.PROJECT,
            path=".fictional/config.txt",
            source="fixtures/fictional.txt",
        ),
    )
    assert project_facts.runtime_limitations == ("The fixture proves filesystem effects only.",)
    with pytest.raises(FrozenInstanceError):
        result.catalog.targets[0].__setattr__("name", "mutated")

    lifecycle, unsupported, aggregate = result.plan.scenarios
    assert isinstance(lifecycle, LifecyclePlan)
    assert tuple(phase.kind for phase in lifecycle.phases) == (
        PhaseKind.INSTALL,
        PhaseKind.REINSTALL,
        PhaseKind.TARGET_UNINSTALL,
    )
    assert isinstance(unsupported, UnsupportedPlan)
    assert unsupported.reason == "Fictional user installs are unavailable."
    unsupported_result = result.scenario_results[1]
    assert unsupported_result == UnsupportedResult(
        "fictional",
        Scope.USER,
        ScenarioStatus.UNSUPPORTED,
        unsupported.reason,
        (),
    )
    assert isinstance(aggregate, AggregatePlan)
    assert aggregate.preparation_targets == ("fictional",)
    install_phase = lifecycle.phases[0]
    assert isinstance(install_phase, PhasePlan)
    assert install_phase.command.argv == (
        "graphify",
        "install",
        "--project",
        "--platform",
        "fictional",
    )
    assert (
        install_phase.observation.action_id,
        install_phase.observation.subject,
        install_phase.observation.scope,
        install_phase.observation.phase,
    ) == (
        ActionId(
            install_phase.command.action_id.plan_id,
            install_phase.command.action_id.ordinal + 1,
        ),
        install_phase.command.subject,
        install_phase.command.scope,
        install_phase.command.phase,
    )
    assert aggregate.uninstall.command.argv == ("graphify", "uninstall", "--project")
    assert len(requests) == len(result.raw_facts)
    assert result.raw_facts == tuple(_passing_fulfil(request) for request in requests)


def test_validation_engine_derives_semantic_lifecycle_results_from_raw_facts() -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                _catalog_text(_supported_project(_owned_file_surface())),
            ),
        )
    )

    def fulfil(
        request: CommandRequest | ObservationRequest | PreparationRequest,
    ) -> RawFact:
        return _passing_fulfil(request)

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationCompleted)
    lifecycle = result.scenario_results[0]
    assert isinstance(lifecycle, LifecycleResult)
    assert lifecycle.status is ScenarioStatus.PASS
    assert tuple(phase.status for phase in lifecycle.phases) == (
        PhaseStatus.PASS,
        PhaseStatus.PASS,
        PhaseStatus.PASS,
    )
    assert all(phase.findings == () for phase in lifecycle.phases)


def test_failed_setup_command_blocks_dependent_lifecycle_phases() -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                _catalog_text(_supported_project(_owned_file_surface())),
            ),
        )
    )
    requests: list[CommandRequest | ObservationRequest | PreparationRequest] = []
    session = _SessionFacts()

    def fulfil(
        request: CommandRequest | ObservationRequest | PreparationRequest,
    ) -> RawFact:
        requests.append(request)
        if isinstance(request, PreparationRequest):
            return session.passing(request)
        if isinstance(request, ObservationRequest):
            return session.bind(_passing_observation(request))
        return session.bind(
            replace(
                _passing_command(request),
                exit_code=17 if len(requests) == 1 else 0,
                stdout=StreamCapture(b"partial product output", True),
                stderr=StreamCapture(b"product error", True),
            )
        )

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationCompleted)
    lifecycle = result.scenario_results[0]
    assert isinstance(lifecycle, LifecycleResult)
    assert lifecycle.status is ScenarioStatus.FINDING
    install, reinstall, uninstall = lifecycle.phases
    assert install.status is PhaseStatus.FINDING
    assert install.command is not None
    assert install.command.exit_code == 17
    assert install.observation is not None
    assert reinstall.status is PhaseStatus.BLOCKED
    assert reinstall.blocked_by is PhaseKind.INSTALL
    assert reinstall.command is None
    assert uninstall.status is PhaseStatus.BLOCKED
    assert uninstall.blocked_by is PhaseKind.INSTALL
    assert uninstall.command is None
    assert isinstance(requests[0], CommandRequest)
    assert requests[0].phase is PhaseKind.INSTALL
    assert not any(
        request.phase in {PhaseKind.REINSTALL, PhaseKind.TARGET_UNINSTALL}
        for request in requests
        if isinstance(request, (CommandRequest, ObservationRequest))
    )


def test_validation_engine_rejects_changes_outside_planned_install_surfaces() -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                _catalog_text(_supported_project(_owned_file_surface())),
            ),
        )
    )

    def fulfil(
        request: CommandRequest | ObservationRequest | PreparationRequest,
    ) -> RawFact:
        if isinstance(request, PreparationRequest):
            return _passing_preparation(request)
        if isinstance(request, ObservationRequest):
            return _passing_observation(request)
        after_entries = _root_snapshot().entries
        if request.phase is PhaseKind.INSTALL:
            after_entries = (
                *_root_snapshot().entries,
                SnapshotEntry(SurfaceRoot.PROJECT, ".fictional", EntryKind.DIRECTORY),
                SnapshotEntry(
                    SurfaceRoot.PROJECT,
                    ".fictional/config.txt",
                    EntryKind.FILE,
                    size=8,
                    sha256="a" * 64,
                ),
                SnapshotEntry(
                    SurfaceRoot.PROJECT,
                    ".fictional/undeclared.txt",
                    EntryKind.FILE,
                    size=5,
                    sha256="b" * 64,
                ),
            )
        return replace(
            _passing_command(request),
            after_snapshot=FilesystemSnapshot(after_entries),
        )

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationCompleted)
    lifecycle = result.scenario_results[0]
    assert isinstance(lifecycle, LifecycleResult)
    install = lifecycle.phases[0]
    assert install.status is PhaseStatus.FINDING
    assert install.findings == (
        ProductFinding(
            "filesystem changes stay within declared surfaces",
            "undeclared changed paths: project:.fictional/undeclared.txt",
        ),
    )


def test_reinstall_state_must_equal_the_stable_installed_snapshot() -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                _catalog_text(_supported_project(_owned_file_surface())),
            ),
        )
    )

    def fulfil(
        request: CommandRequest | ObservationRequest | PreparationRequest,
    ) -> RawFact:
        if isinstance(request, PreparationRequest):
            return _passing_preparation(request)
        if isinstance(request, ObservationRequest):
            return _passing_observation(request)
        content_identity = "b" * 64 if request.phase is PhaseKind.REINSTALL else "a" * 64
        entries = (
            *_root_snapshot().entries,
            SnapshotEntry(SurfaceRoot.PROJECT, ".fictional", EntryKind.DIRECTORY),
            SnapshotEntry(
                SurfaceRoot.PROJECT,
                ".fictional/config.txt",
                EntryKind.FILE,
                size=8,
                sha256=content_identity,
            ),
        )
        return replace(
            _passing_command(request),
            before_snapshot=FilesystemSnapshot(entries),
            after_snapshot=FilesystemSnapshot(entries),
        )

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationCompleted)
    lifecycle = result.scenario_results[0]
    assert isinstance(lifecycle, LifecycleResult)
    install, reinstall, uninstall = lifecycle.phases
    assert install.status is PhaseStatus.PASS
    assert reinstall.status is PhaseStatus.FINDING
    assert reinstall.findings == (
        ProductFinding(
            "idempotent filesystem state",
            "reinstall post-state differs from the stable installed state",
        ),
    )
    assert uninstall.status is PhaseStatus.PASS


def test_runtime_failure_makes_the_scenario_and_dependents_incomplete() -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                _catalog_text(_supported_project(_owned_file_surface())),
            ),
        )
    )
    requests: list[CommandRequest | ObservationRequest | PreparationRequest] = []
    session = _SessionFacts()

    def fulfil(
        request: CommandRequest | ObservationRequest | PreparationRequest,
    ) -> RawFact:
        requests.append(request)
        if len(requests) == 1:
            chronology = _chronology(
                request.action_id,
                OperationKind.COMMAND_STARTED,
                OperationKind.COMMAND_FAILED,
            )
            return session.bind(
                ActionFailureFact(
                    request.action_id,
                    ActionKind.COMMAND,
                    "spawn_command",
                    "fixture executable is unavailable",
                    chronology,
                )
            )
        return session.passing(request)

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationCompleted)
    lifecycle = result.scenario_results[0]
    assert isinstance(lifecycle, LifecycleResult)
    assert lifecycle.status is ScenarioStatus.INCOMPLETE
    install, reinstall, uninstall = lifecycle.phases
    assert install.status is PhaseStatus.INCOMPLETE
    assert install.failure is not None
    assert install.failure.operation == "spawn_command"
    assert install.reason == "fixture executable is unavailable"
    assert reinstall.status is PhaseStatus.INCOMPLETE
    assert reinstall.blocked_by is PhaseKind.INSTALL
    assert reinstall.reason == "install diagnostic evidence is incomplete"
    assert uninstall.status is PhaseStatus.INCOMPLETE
    assert uninstall.blocked_by is PhaseKind.INSTALL
    assert uninstall.reason == "install diagnostic evidence is incomplete"
    assert not any(
        request.phase in {PhaseKind.REINSTALL, PhaseKind.TARGET_UNINSTALL}
        for request in requests
        if isinstance(request, (CommandRequest, ObservationRequest))
    )


@pytest.mark.parametrize("failure_kind", ("entry", "capture", "snapshot"))
def test_untrustworthy_filesystem_evidence_prevents_dependent_phases(
    failure_kind: str,
) -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                _catalog_text(_supported_project(_owned_file_surface())),
            ),
        )
    )
    requests: list[CommandRequest | ObservationRequest | PreparationRequest] = []
    session = _SessionFacts()

    def fulfil(
        request: CommandRequest | ObservationRequest | PreparationRequest,
    ) -> RawFact:
        requests.append(request)
        if request.action_id.ordinal not in {0, 1}:
            return session.passing(request)
        if isinstance(request, CommandRequest):
            command = _passing_command(request)
            if failure_kind != "snapshot":
                return session.bind(command)
            entries = tuple(
                replace(entry, error="root scan failed")
                if entry.root is SurfaceRoot.PROJECT
                else entry
                for entry in command.after_snapshot.entries
            )
            return session.bind(replace(command, after_snapshot=FilesystemSnapshot(entries)))
        assert isinstance(request, ObservationRequest)
        observation = _passing_observation(request)
        first = observation.surfaces[0]
        if failure_kind == "entry":
            destination = replace(
                first.destination,
                kind=EntryKind.OTHER,
                content=None,
                error="surface read failed",
            )
        else:
            destination = replace(
                first.destination,
                content=ByteCapture(b"partial", False, 10),
            )
        return session.bind(
            replace(
                observation,
                surfaces=(replace(first, destination=destination),),
            )
        )

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationCompleted)
    lifecycle = result.scenario_results[0]
    assert isinstance(lifecycle, LifecycleResult)
    assert lifecycle.status is ScenarioStatus.INCOMPLETE
    assert lifecycle.phases[0].status is PhaseStatus.INCOMPLETE
    assert tuple(phase.status for phase in lifecycle.phases[1:]) == (
        PhaseStatus.INCOMPLETE,
        PhaseStatus.INCOMPLETE,
    )
    assert not any(
        request.phase in {PhaseKind.REINSTALL, PhaseKind.TARGET_UNINSTALL}
        for request in requests
        if isinstance(request, (CommandRequest, ObservationRequest))
    )


def test_timeout_is_a_product_finding_with_partial_capture_preserved() -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                _catalog_text(_supported_project(_owned_file_surface())),
            ),
        )
    )

    session = _SessionFacts()

    def fulfil(request: ActionRequest) -> RawFact:
        if isinstance(request, CommandRequest) and request.phase is PhaseKind.INSTALL:
            return session.bind(
                _timed_out_command(
                    request,
                    stdout=StreamCapture(b"output before timeout", False, 7),
                    stderr=StreamCapture(b"error before timeout", False, 5),
                )
            )
        return session.passing(request)

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationCompleted)
    lifecycle = result.scenario_results[0]
    assert isinstance(lifecycle, LifecycleResult)
    install = lifecycle.phases[0]
    assert install.status is PhaseStatus.FINDING
    assert install.findings == (ProductFinding("product command", "command timed out"),)
    assert install.command is not None
    assert install.command.timed_out
    assert install.command.signal == 9
    assert install.command.stdout == StreamCapture(b"output before timeout", False, 7)
    assert install.command.stderr == StreamCapture(b"error before timeout", False, 5)


def test_phase_result_statuses_reject_incoherent_evidence() -> None:
    with pytest.raises(ValueError, match="PASS"):
        PhaseResult(PhaseKind.INSTALL, PhaseStatus.PASS, None, None)
    with pytest.raises(ValueError, match="FINDING"):
        PhaseResult(PhaseKind.INSTALL, PhaseStatus.FINDING, None, None)
    with pytest.raises(ValueError, match="BLOCKED"):
        PhaseResult(PhaseKind.INSTALL, PhaseStatus.BLOCKED, None, None)
    with pytest.raises(ValueError, match="NOT_APPLICABLE"):
        PhaseResult(PhaseKind.INSTALL, PhaseStatus.NOT_APPLICABLE, None, None)
    with pytest.raises(ValueError, match="INCOMPLETE"):
        PhaseResult(PhaseKind.INSTALL, PhaseStatus.INCOMPLETE, None, None)


def _wrong_working_directory(fact: CommandFact) -> CommandFact:
    return replace(fact, working_directory=SurfaceRoot.HOME)


def _missing_chronology(fact: CommandFact) -> CommandFact:
    return replace(fact, chronology=())


def _missing_snapshots(fact: CommandFact) -> CommandFact:
    return replace(
        fact,
        before_snapshot=FilesystemSnapshot(()),
        after_snapshot=FilesystemSnapshot(()),
    )


def _incoherent_signal(fact: CommandFact) -> CommandFact:
    return replace(fact, signal=9)


def _incoherent_timing(fact: CommandFact) -> CommandFact:
    return replace(fact, finished_ns=fact.finished_ns + 1)


def _incomplete_capture(fact: CommandFact) -> CommandFact:
    return replace(fact, stdout=StreamCapture(b"", False))


@pytest.mark.parametrize(
    "malform",
    (
        _wrong_working_directory,
        _missing_chronology,
        _missing_snapshots,
        _incoherent_signal,
        _incoherent_timing,
        _incomplete_capture,
    ),
)
def test_raw_fact_protocol_rejects_incoherent_command_evidence(
    malform: Callable[[CommandFact], CommandFact],
) -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                _catalog_text(_supported_project(_owned_file_surface())),
            ),
        )
    )

    def fulfil(request: ActionRequest) -> RawFact:
        assert isinstance(request, CommandRequest)
        return malform(_passing_command(request))

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationRejected)
    assert "Raw Fact" in result.reasons[0]


@pytest.mark.parametrize(
    "operation",
    ("terminate_process_group", "complete_process_custody"),
)
def test_raw_fact_protocol_rejects_lossy_post_spawn_action_failure(operation: str) -> None:
    request = CommandRequest(
        action_id=ActionId("plan-fixture", 0),
        subject=TargetSubject("fictional"),
        scope=Scope.PROJECT,
        phase=PhaseKind.INSTALL,
        argv=("fictional", "install"),
    )
    chronology = tuple(
        OperationEvent(sequence, kind, sequence)
        for sequence, kind in enumerate(
            (
                OperationKind.COMMAND_STARTED,
                OperationKind.COMMAND_FAILED,
            )
        )
    )

    result = validate_raw_fact(
        request,
        ActionFailureFact(
            request.action_id,
            ActionKind.COMMAND,
            operation,
            "post-spawn evidence was discarded",
            chronology,
        ),
    )

    assert result == "Raw Fact failure evidence is invalid"


def test_raw_fact_protocol_rejects_an_unknown_surface_member() -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                _catalog_text(_supported_project(_owned_file_surface())),
            ),
        )
    )

    def fulfil(request: ActionRequest) -> RawFact:
        fact = _passing_fulfil(request)
        if isinstance(fact, ObservationFact):
            return replace(fact, surfaces=(cast(SurfaceFact, object()),))
        return fact

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationRejected)
    assert result.reasons == ("Raw Fact observation evidence is invalid",)


def test_raw_fact_protocol_rejects_a_restarted_session_chronology() -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                _catalog_text(_supported_project(_owned_file_surface())),
            ),
        )
    )

    def fulfil(request: ActionRequest) -> RawFact:
        fact = _passing_fulfil(request)
        chronology = tuple(
            replace(event, sequence=offset, occurred_ns=offset)
            for offset, event in enumerate(fact.chronology)
        )
        if isinstance(fact, CommandFact):
            return replace(
                fact,
                started_ns=chronology[0].occurred_ns,
                finished_ns=chronology[-1].occurred_ns,
                chronology=chronology,
            )
        assert isinstance(fact, ObservationFact)
        return replace(
            fact,
            started_ns=chronology[0].occurred_ns,
            finished_ns=chronology[-1].occurred_ns,
            chronology=chronology,
        )

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationRejected)
    assert result.reasons == ("Raw Facts do not form one total session chronology",)


def _wrong_file_size(entry: EntryFact) -> EntryFact:
    assert entry.size is not None
    return replace(entry, size=entry.size + 1)


def _non_hex_file_digest(entry: EntryFact) -> EntryFact:
    return replace(entry, sha256="z" * 64)


def _contradictory_file_digest(entry: EntryFact) -> EntryFact:
    return replace(entry, sha256="0" * 64)


def _wrong_omitted_byte_count(entry: EntryFact) -> EntryFact:
    return replace(entry, content=ByteCapture(b"expected", False, 2))


@pytest.mark.parametrize(
    "malform",
    (
        _wrong_file_size,
        _non_hex_file_digest,
        _contradictory_file_digest,
        _wrong_omitted_byte_count,
    ),
)
def test_raw_fact_protocol_rejects_incoherent_entry_file_evidence(
    malform: Callable[[EntryFact], EntryFact],
) -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                _catalog_text(_supported_project(_owned_file_surface())),
            ),
        )
    )

    def fulfil(request: ActionRequest) -> RawFact:
        fact = _passing_fulfil(request)
        if isinstance(fact, CommandFact) or request.action_id.ordinal != 1:
            return fact
        assert isinstance(fact, ObservationFact)
        surface = fact.surfaces[0]
        return replace(
            fact,
            surfaces=(replace(surface, destination=malform(surface.destination)),),
        )

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationRejected)
    assert result.reasons == ("Raw Fact observation evidence is invalid",)


def test_raw_fact_protocol_rejects_a_non_sha256_snapshot_digest() -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                _catalog_text(_supported_project(_owned_file_surface())),
            ),
        )
    )

    def fulfil(request: ActionRequest) -> RawFact:
        fact = _passing_fulfil(request)
        if isinstance(fact, ObservationFact):
            return fact
        assert isinstance(fact, CommandFact)
        invalid_entry = SnapshotEntry(
            SurfaceRoot.PROJECT,
            "invalid.txt",
            EntryKind.FILE,
            size=1,
            sha256="z" * 64,
        )
        return replace(
            fact,
            after_snapshot=FilesystemSnapshot((*fact.after_snapshot.entries, invalid_entry)),
        )

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationRejected)
    assert result.reasons == ("Raw Fact command evidence is invalid",)


def test_observation_failure_takes_precedence_over_a_product_timeout() -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                _catalog_text(_supported_project(_owned_file_surface())),
            ),
        )
    )
    requests: list[CommandRequest | ObservationRequest | PreparationRequest] = []
    session = _SessionFacts()

    def fulfil(
        request: CommandRequest | ObservationRequest | PreparationRequest,
    ) -> RawFact:
        requests.append(request)
        if isinstance(request, CommandRequest) and request.action_id.ordinal == 0:
            return session.bind(
                _timed_out_command(
                    request,
                    stdout=StreamCapture(b"partial", False),
                    stderr=StreamCapture(b"", False),
                )
            )
        if isinstance(request, ObservationRequest) and request.action_id.ordinal == 1:
            chronology = _chronology(
                request.action_id,
                OperationKind.OBSERVATION_STARTED,
                OperationKind.OBSERVATION_FAILED,
            )
            return session.bind(
                ActionFailureFact(
                    request.action_id,
                    ActionKind.OBSERVATION,
                    "observe_surface",
                    "filesystem became unreadable",
                    chronology,
                )
            )
        return session.passing(request)

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationCompleted)
    lifecycle = result.scenario_results[0]
    assert isinstance(lifecycle, LifecycleResult)
    assert lifecycle.status is ScenarioStatus.INCOMPLETE
    install = lifecycle.phases[0]
    assert install.status is PhaseStatus.INCOMPLETE
    assert install.reason == "filesystem became unreadable"
    assert install.failure is not None
    assert install.failure.operation == "observe_surface"
    assert tuple(type(request) for request in requests[:2]) == (
        CommandRequest,
        ObservationRequest,
    )
    assert not any(
        request.phase in {PhaseKind.REINSTALL, PhaseKind.TARGET_UNINSTALL}
        for request in requests
        if isinstance(request, (CommandRequest, ObservationRequest))
    )


def test_duplicate_yaml_classification_is_rejected_before_fulfilment() -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                """
scopes:
  user:
    supported: false
    reason: The first classification must not be overwritten.
    runtime_limitations: []
  user:
    supported: false
    reason: Duplicate classification.
    runtime_limitations: []
  project:
    supported: false
    reason: Project scope is unavailable.
    runtime_limitations: []
""".lstrip(),
            ),
        )
    )
    calls = 0

    def fulfil(request: ActionRequest) -> RawFact:
        nonlocal calls
        calls += 1
        raise AssertionError(f"unexpected request: {request!r}")

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.USER,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationRejected)
    assert result.reasons == ("fictional.yaml contains duplicate YAML key: 'user'",)
    assert calls == 0


def test_unknown_raw_fact_variant_fails_closed() -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                """
scopes:
  user:
    supported: false
    reason: User scope is unavailable.
    runtime_limitations: []
  project:
    supported: true
    runtime_limitations: []
    surfaces:
      - kind: owned_file
        root: project
        path: .fictional/config.txt
        source: fixtures/config.txt
""".lstrip(),
            ),
        )
    )

    def fulfil(request: ActionRequest) -> RawFact:
        del request
        return cast(RawFact, object())

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationRejected)
    assert result.reasons == ("Raw Fact has an unknown variant",)


def test_malformed_raw_fact_payload_fails_closed() -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                """
scopes:
  user:
    supported: false
    reason: User scope is unavailable.
    runtime_limitations: []
  project:
    supported: true
    runtime_limitations: []
    surfaces:
      - kind: owned_file
        root: project
        path: .fictional/config.txt
        source: fixtures/config.txt
""".lstrip(),
            ),
        )
    )

    def fulfil(request: ActionRequest) -> RawFact:
        assert isinstance(request, CommandRequest)
        return replace(_passing_command(request), exit_code=cast(int, object()))

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationRejected)
    assert result.reasons == ("Raw Fact command evidence is invalid",)


@given(control=st.sampled_from(("\n", "\r", "\t", "\x00")))
def test_catalog_rejects_control_characters_in_surface_paths(control: str) -> None:
    body = json.dumps(
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
                            "path": f".fictional/{control}config.txt",
                            "source": "fixtures/config.txt",
                        }
                    ],
                },
            }
        }
    )

    def fulfil(request: ActionRequest) -> RawFact:
        raise AssertionError(f"unexpected request: {request!r}")

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        CatalogDocuments((CatalogDocument("fictional.yaml", body),)),
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationRejected)
    assert "canonical safe relative path" in result.reasons[0]


@pytest.mark.parametrize(
    "unsafe_path",
    (".", "./config.txt", "fictional/./config.txt", " config.txt", "config.txt "),
)
def test_catalog_rejects_noncanonical_surface_paths(unsafe_path: str) -> None:
    body = json.dumps(
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
                            "path": unsafe_path,
                            "source": "fixtures/config.txt",
                        }
                    ],
                },
            }
        }
    )

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        CatalogDocuments((CatalogDocument("fictional.yaml", body),)),
        HarnessPolicy(),
        lambda request: cast(RawFact, request),
    )

    assert isinstance(result, ValidationRejected)
    assert "canonical safe relative path" in result.reasons[0]


@given(owned_file_first=st.booleans())
def test_catalog_rejects_conflicting_surface_ownership(owned_file_first: bool) -> None:
    owned_file = {
        "kind": "owned_file",
        "root": "project",
        "path": ".fictional/config.txt",
        "source": "fixtures/config.txt",
    }
    text_entry = {
        "kind": "text_entry",
        "root": "project",
        "path": ".fictional/config.txt",
        "entry": "graphify",
        "required_text": "graphify query",
    }
    surfaces = [owned_file, text_entry]
    if not owned_file_first:
        surfaces.reverse()
    body = json.dumps(
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
                    "surfaces": surfaces,
                },
            }
        }
    )

    def fulfil(request: ActionRequest) -> RawFact:
        raise AssertionError(f"unexpected request: {request!r}")

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        CatalogDocuments((CatalogDocument("fictional.yaml", body),)),
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationRejected)
    assert "conflicting Install Surface ownership" in result.reasons[0]


def test_catalog_rejects_conflicting_cross_target_surface_facts() -> None:
    def target_document(name: str, source: str) -> CatalogDocument:
        return CatalogDocument(
            f"{name}.yaml",
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
                                    "source": source,
                                }
                            ],
                        },
                    }
                }
            ),
        )

    result = validate(
        ValidationRequest(targets=("alpha", "beta"), scopes=(Scope.PROJECT,)),
        CatalogDocuments(
            (
                target_document("alpha", "fixtures/alpha.txt"),
                target_document("beta", "fixtures/beta.txt"),
            )
        ),
        HarnessPolicy(),
        lambda request: cast(RawFact, request),
    )

    assert isinstance(result, ValidationRejected)
    assert "catalog targets disagree about Install Surface" in result.reasons[0]
    assert ".fictional/config.txt" in result.reasons[0]


def test_catalog_rejects_cross_target_ownership_conflicts() -> None:
    alpha = CatalogDocument(
        "alpha.yaml",
        _catalog_text(_supported_project(_owned_file_surface())),
    )
    beta = CatalogDocument(
        "beta.yaml",
        _catalog_text(
            _supported_project(
                {
                    "kind": "text_entry",
                    "root": "project",
                    "path": ".fictional/config.txt",
                    "entry": "graphify",
                    "required_text": "graphify query",
                }
            )
        ),
    )

    result = validate(
        ValidationRequest(targets=("alpha", "beta"), scopes=(Scope.PROJECT,)),
        CatalogDocuments((alpha, beta)),
        HarnessPolicy(),
        _passing_fulfil,
    )

    assert isinstance(result, ValidationRejected)
    assert result.reasons == (
        "catalog targets disagree about ownership at ('project', '.fictional/config.txt')",
    )


@pytest.mark.parametrize(
    ("location", "field", "value"),
    (
        ("top", "universal_uninstall_scopes", ["project"]),
        ("scope", "install_mode", "direct"),
        ("scope", "uninstall_mode", "direct"),
        ("scope", "execution_policy", "permissive"),
    ),
)
def test_catalog_rejects_unknown_and_obsolete_policy_fields(
    location: str,
    field: str,
    value: object,
) -> None:
    raw: dict[str, object] = {
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
    if location == "top":
        raw[field] = value
    else:
        scopes = cast(dict[str, dict[str, object]], raw["scopes"])
        scopes["project"][field] = value

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        CatalogDocuments((CatalogDocument("fictional.yaml", json.dumps(raw)),)),
        HarnessPolicy(),
        _passing_fulfil,
    )

    assert isinstance(result, ValidationRejected)
    assert f"unknown={field}" in result.reasons[0]


@pytest.mark.parametrize(
    ("project", "message"),
    (
        ([], "must be a mapping"),
        ({"supported": True, "runtime_limitations": [], "surfaces": []}, "non-empty list"),
        (
            _supported_project(_owned_file_surface(), limitations="not-a-list"),
            "list of non-empty strings",
        ),
        (
            _supported_project(_owned_file_surface(), limitations=("same", "same")),
            "must not contain duplicates",
        ),
        (
            {"supported": "yes", "runtime_limitations": [], "surfaces": []},
            "supported must be a boolean",
        ),
        (
            _supported_project(_owned_file_surface(root="outside")),
            "root is invalid",
        ),
        (
            _supported_project(_owned_file_surface(kind="directory")),
            "kind is unknown",
        ),
        (
            _supported_project(_owned_file_surface(), _owned_file_surface()),
            "duplicate classifications",
        ),
        (
            _supported_project(_owned_file_surface(path="../config.txt")),
            "canonical safe relative path",
        ),
        (
            {
                "supported": False,
                "reason": "Project scope is unavailable.",
                "runtime_limitations": [],
                "surfaces": [],
            },
            "unknown=surfaces",
        ),
    ),
)
def test_catalog_schema_rejection_matrix(project: object, message: str) -> None:
    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        CatalogDocuments((CatalogDocument("fictional.yaml", _catalog_text(project)),)),
        HarnessPolicy(),
        _passing_fulfil,
    )

    assert isinstance(result, ValidationRejected)
    assert message in result.reasons[0]


def test_catalog_preserves_an_explicitly_declared_cross_root_surface() -> None:
    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        CatalogDocuments(
            (
                CatalogDocument(
                    "fictional.yaml",
                    _catalog_text(_supported_project(_owned_file_surface(root="home"))),
                ),
            )
        ),
        HarnessPolicy(),
        _passing_fulfil,
    )

    assert isinstance(result, ValidationCompleted)
    facts = result.catalog.targets[0].facts_for(Scope.PROJECT)
    assert isinstance(facts, SupportedScopeFacts)
    assert facts.surfaces[0].root is SurfaceRoot.HOME


@pytest.mark.parametrize(
    ("documents", "message"),
    (
        (CatalogDocuments(()), "at least one target document"),
        (
            CatalogDocuments((CatalogDocument("../fictional.yaml", "scopes: {}\n"),)),
            "safe <target>.yaml leaf",
        ),
        (
            CatalogDocuments((CatalogDocument("fictional.yaml", "scopes: [\n"),)),
            "malformed YAML",
        ),
        (
            CatalogDocuments((CatalogDocument("fictional.yaml", "[]\n"),)),
            "must be a mapping",
        ),
        (
            CatalogDocuments((CatalogDocument("fictional.yaml", "scopes:\n  project: {}\n"),)),
            "missing=user",
        ),
        (
            CatalogDocuments(
                (
                    CatalogDocument(
                        "fictional.yaml",
                        _catalog_text(_supported_project(_owned_file_surface())),
                    ),
                    CatalogDocument(
                        "fictional.yaml",
                        _catalog_text(_supported_project(_owned_file_surface())),
                    ),
                )
            ),
            "duplicate target document",
        ),
    ),
)
def test_catalog_document_rejection_matrix(
    documents: CatalogDocuments,
    message: str,
) -> None:
    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        _passing_fulfil,
    )

    assert isinstance(result, ValidationRejected)
    assert message in result.reasons[0]


@given(
    removed=st.frozensets(
        st.sampled_from(("kind", "root", "path", "source")),
    ),
    add_unknown=st.booleans(),
)
def test_owned_file_surface_accepts_only_its_exact_field_combination(
    removed: frozenset[str],
    add_unknown: bool,
) -> None:
    surface: dict[str, object] = {
        "kind": "owned_file",
        "root": "project",
        "path": ".fictional/config.txt",
        "source": "fixtures/config.txt",
    }
    for field in removed:
        del surface[field]
    if add_unknown:
        surface["backup"] = True
    body = json.dumps(
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
                    "surfaces": [surface],
                },
            }
        }
    )

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        CatalogDocuments((CatalogDocument("fictional.yaml", body),)),
        HarnessPolicy(),
        _passing_fulfil,
    )

    if removed or add_unknown:
        assert isinstance(result, ValidationRejected)
    else:
        assert isinstance(result, ValidationCompleted)


def test_non_exhaustive_requested_scope_fails_closed() -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                """
scopes:
  user:
    supported: false
    reason: User scope is unavailable.
    runtime_limitations: []
  project:
    supported: true
    runtime_limitations: []
    surfaces:
      - kind: owned_file
        root: project
        path: .fictional/config.txt
        source: fixtures/config.txt
""".lstrip(),
            ),
        )
    )

    result = validate(
        ValidationRequest(
            targets=("fictional",),
            scopes=(cast(Scope, "workspace"),),
        ),
        documents,
        HarnessPolicy(),
        _passing_fulfil,
    )

    assert isinstance(result, ValidationRejected)
    assert result.reasons == ("validation request contains an unknown scope variant",)


@pytest.mark.parametrize(
    ("validation_request", "policy", "message"),
    (
        (
            ValidationRequest(targets=(), scopes=(Scope.PROJECT,)),
            HarnessPolicy(),
            "unique selected targets",
        ),
        (
            ValidationRequest(targets=("fictional", "fictional"), scopes=(Scope.PROJECT,)),
            HarnessPolicy(),
            "unique selected targets",
        ),
        (
            ValidationRequest(targets=("fictional",), scopes=()),
            HarnessPolicy(),
            "unique selected scopes",
        ),
        (
            ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT, Scope.PROJECT)),
            HarnessPolicy(),
            "unique selected scopes",
        ),
        (
            ValidationRequest(targets=("missing",), scopes=(Scope.PROJECT,)),
            HarnessPolicy(),
            "unknown Install Target",
        ),
        (
            ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
            HarnessPolicy(install_argv=()),
            "install command policy is invalid",
        ),
        (
            ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
            HarnessPolicy(uninstall_argv=("graphify", "")),
            "uninstall command policy is invalid",
        ),
    ),
)
def test_validation_request_and_policy_rejection_matrix(
    validation_request: ValidationRequest,
    policy: HarnessPolicy,
    message: str,
) -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                _catalog_text(_supported_project(_owned_file_surface())),
            ),
        )
    )

    result = validate(validation_request, documents, policy, _passing_fulfil)

    assert isinstance(result, ValidationRejected)
    assert message in result.reasons[0]


@pytest.mark.parametrize("mismatch", ("action-id", "variant"))
def test_raw_facts_must_match_the_planned_action(mismatch: str) -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                _catalog_text(_supported_project(_owned_file_surface())),
            ),
        )
    )

    def fulfil(request: ActionRequest) -> RawFact:
        if mismatch == "action-id":
            assert isinstance(request, CommandRequest)
            return replace(
                _passing_command(request),
                action_id=ActionId("different-plan", 0),
            )
        chronology = _chronology(
            request.action_id,
            OperationKind.OBSERVATION_STARTED,
            OperationKind.OBSERVATION_FINISHED,
        )
        return ObservationFact(
            request.action_id,
            (),
            chronology[0].occurred_ns,
            chronology[-1].occurred_ns,
            chronology,
        )

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationRejected)
    assert "Raw Fact" in result.reasons[0]


def test_malformed_observation_fact_fails_closed() -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                _catalog_text(_supported_project(_owned_file_surface())),
            ),
        )
    )

    def fulfil(request: ActionRequest) -> RawFact:
        if isinstance(request, CommandRequest):
            return _passing_command(request)
        assert isinstance(request, ObservationRequest)
        observation = _passing_observation(request)
        return replace(observation, surfaces=cast(tuple[SurfaceFact, ...], object()))

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationRejected)
    assert result.reasons == ("Raw Fact observation evidence is invalid",)


def test_aggregate_plan_derives_a_minimal_surface_cover_with_bound_action_ids() -> None:
    target_surfaces = {
        "alpha": ("first.txt", "second.txt"),
        "beta": ("first.txt",),
        "gamma": ("second.txt",),
    }
    documents = CatalogDocuments(
        tuple(
            CatalogDocument(
                f"{target}.yaml",
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
                                        "path": f".fictional/{path}",
                                        "source": f"fixtures/{path}",
                                    }
                                    for path in paths
                                ],
                            },
                        }
                    }
                ),
            )
            for target, paths in target_surfaces.items()
        )
    )
    requests: list[CommandRequest | ObservationRequest | PreparationRequest] = []

    def fulfil(
        request: CommandRequest | ObservationRequest | PreparationRequest,
    ) -> RawFact:
        requests.append(request)
        return _passing_fulfil(request)

    result = validate(
        ValidationRequest(targets=("alpha", "beta", "gamma"), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationCompleted)
    aggregate = result.plan.scenarios[-1]
    assert isinstance(aggregate, AggregatePlan)
    assert aggregate.preparation_targets == ("alpha",)
    assert aggregate.uninstall.command.subject == AggregateSubject(("alpha",))
    action_ids = tuple(request.action_id for request in requests)
    assert len(action_ids) == len(set(action_ids))
    assert {action_id.plan_id for action_id in action_ids} == {result.plan.plan_id}
    assert tuple(action_id.ordinal for action_id in action_ids) == tuple(range(len(action_ids)))


def test_aggregate_cover_avoids_duplicate_surface_preparation() -> None:
    target_surfaces = {
        "alpha": ("a.txt", "b.txt"),
        "beta": ("b.txt", "c.txt"),
        "gamma": ("c.txt",),
    }
    documents = CatalogDocuments(
        tuple(
            CatalogDocument(
                f"{target}.yaml",
                _catalog_text(
                    _supported_project(
                        *(
                            _owned_file_surface(
                                path=f".fictional/{path}",
                                source=f"fixtures/{path}",
                            )
                            for path in paths
                        )
                    )
                ),
            )
            for target, paths in target_surfaces.items()
        )
    )

    result = validate(
        ValidationRequest(targets=tuple(target_surfaces), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        _passing_fulfil,
    )

    assert isinstance(result, ValidationCompleted)
    aggregate = result.plan.scenarios[-1]
    assert isinstance(aggregate, AggregatePlan)
    assert aggregate.preparation_targets == ("alpha", "gamma")


@given(
    surface_families=st.lists(
        st.frozensets(st.integers(min_value=0, max_value=5), min_size=1, max_size=4),
        min_size=1,
        max_size=5,
    )
)
def test_generated_aggregate_plans_are_complete_and_minimal(
    surface_families: list[frozenset[int]],
) -> None:
    names = tuple(f"target-{index}" for index in range(len(surface_families)))
    documents = CatalogDocuments(
        tuple(
            CatalogDocument(
                f"{name}.yaml",
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
                                        "path": f".fictional/surface-{surface}.txt",
                                        "source": f"fixtures/surface-{surface}.txt",
                                    }
                                    for surface in sorted(family)
                                ],
                            },
                        }
                    }
                ),
            )
            for name, family in zip(names, surface_families, strict=True)
        )
    )

    result = validate(
        ValidationRequest(targets=names, scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        _passing_fulfil,
    )

    assert isinstance(result, ValidationCompleted)
    aggregate = result.plan.scenarios[-1]
    assert isinstance(aggregate, AggregatePlan)
    family_by_name = dict(zip(names, surface_families, strict=True))
    universe = frozenset(itertools.chain.from_iterable(surface_families))
    prepared = tuple(family_by_name[name] for name in aggregate.preparation_targets)
    assert frozenset(itertools.chain.from_iterable(prepared)) == universe
    assert all(
        frozenset(itertools.chain.from_iterable(selection)) != universe
        for size in range(1, len(prepared))
        for selection in itertools.combinations(surface_families, size)
    )
    complete_at_selected_size = tuple(
        selection
        for selection in itertools.combinations(surface_families, len(prepared))
        if frozenset(itertools.chain.from_iterable(selection)) == universe
    )
    prepared_overlap = sum(map(len, prepared)) - len(universe)
    assert prepared_overlap == min(
        sum(map(len, selection)) - len(universe) for selection in complete_at_selected_size
    )
    observed_paths = tuple(surface.path for surface in aggregate.uninstall.surfaces)
    assert len(observed_paths) == len(set(observed_paths)) == len(universe)


def test_repairable_bundle_derives_an_applicable_repair_phase() -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                """
scopes:
  user:
    supported: true
    runtime_limitations: []
    surfaces:
      - kind: repairable_bundle
        root: home
        path: .fictional/skills/graphify/SKILL.md
        source: fixtures/SKILL.md
        reference_bundle: fictional
  project:
    supported: false
    reason: Project scope is unavailable.
    runtime_limitations: []
""".lstrip(),
            ),
        )
    )

    session = _SessionFacts()
    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.USER,)),
        documents,
        HarnessPolicy(),
        session.passing,
    )

    assert isinstance(result, ValidationCompleted)
    lifecycle = result.plan.scenarios[0]
    assert isinstance(lifecycle, LifecyclePlan)
    assert tuple(phase.kind for phase in lifecycle.phases) == (
        PhaseKind.INSTALL,
        PhaseKind.REINSTALL,
        PhaseKind.REPAIR,
        PhaseKind.TARGET_UNINSTALL,
    )
    facts = result.catalog.targets[0].facts_for(Scope.USER)
    assert isinstance(facts, SupportedScopeFacts)
    assert isinstance(facts.surfaces[0], RepairableBundleSurface)
    lifecycle_result = result.scenario_results[0]
    assert isinstance(lifecycle_result, LifecycleResult)
    assert lifecycle_result.status is ScenarioStatus.INCOMPLETE
    assert lifecycle_result.phases[0].status is PhaseStatus.INCOMPLETE
    assert "repairable bundle" in (lifecycle_result.phases[0].reason or "")


@pytest.mark.parametrize("unsafe_bundle", (".", "../../outside", "nested/name"))
def test_repairable_bundle_rejects_unsafe_reference_leaves(unsafe_bundle: str) -> None:
    body = _catalog_text(
        _supported_project(
            {
                "kind": "repairable_bundle",
                "root": "project",
                "path": ".fictional/skills/graphify/SKILL.md",
                "source": "fixtures/SKILL.md",
                "reference_bundle": unsafe_bundle,
            }
        )
    )

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        CatalogDocuments((CatalogDocument("fictional.yaml", body),)),
        HarnessPolicy(),
        _passing_fulfil,
    )

    assert isinstance(result, ValidationRejected)
    assert "canonical safe" in result.reasons[0]


def test_user_lifecycle_does_not_add_ceremonial_repair_for_shared_text() -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                """
scopes:
  user:
    supported: true
    runtime_limitations: []
    surfaces:
      - kind: text_entry
        root: xdg
        path: fictional/config.md
        entry: graphify-section
        required_text: graphify query
  project:
    supported: false
    reason: Project scope is unavailable.
    runtime_limitations: []
""".lstrip(),
            ),
        )
    )

    def fulfil(request: ActionRequest) -> RawFact:
        return _passing_fulfil(request)

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.USER,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationCompleted)
    lifecycle, aggregate = result.plan.scenarios
    assert isinstance(lifecycle, LifecyclePlan)
    install, reinstall, uninstall = lifecycle.phases
    assert isinstance(install, PhasePlan)
    assert isinstance(reinstall, PhasePlan)
    assert tuple(phase.kind for phase in (install, reinstall)) == (
        PhaseKind.INSTALL,
        PhaseKind.REINSTALL,
    )
    assert isinstance(uninstall, NotApplicablePhasePlan)
    assert uninstall.kind is PhaseKind.TARGET_UNINSTALL
    assert uninstall.cleanup_scope is Scope.USER
    lifecycle_result = result.scenario_results[0]
    assert isinstance(lifecycle_result, LifecycleResult)
    assert lifecycle_result.status is ScenarioStatus.PASS
    target_uninstall = lifecycle_result.phases[2]
    assert target_uninstall.status is PhaseStatus.NOT_APPLICABLE
    assert target_uninstall.reason == "the public user-scope uninstall is aggregate-only"
    assert target_uninstall.command is None
    assert target_uninstall.observation is None
    assert isinstance(aggregate, AggregatePlan)
    assert aggregate.scope is uninstall.cleanup_scope
    assert aggregate.uninstall.surfaces == install.surfaces


def _both_scope_documents() -> CatalogDocuments:
    return CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                _catalog_text(
                    _supported_project(
                        _owned_file_surface(
                            path=".fictional/project.txt",
                            source="fixtures/project.txt",
                        )
                    ),
                    {
                        "supported": True,
                        "runtime_limitations": ["User behavior is fixture-bounded."],
                        "surfaces": [
                            _owned_file_surface(
                                root="home",
                                path=".fictional/user.txt",
                                source="fixtures/user.txt",
                            )
                        ],
                    },
                ),
            ),
        )
    )


def test_validation_executes_isolation_and_purge_as_closed_results() -> None:
    documents = _both_scope_documents()
    session = _SessionFacts()
    begun: list[str] = []

    result = validate(
        ValidationRequest(("fictional",), (Scope.USER, Scope.PROJECT)),
        documents,
        HarnessPolicy(),
        session.passing,
        begun.append,
    )

    assert isinstance(result, ValidationCompleted)
    assert sum(isinstance(plan, ScopeIsolationPlan) for plan in result.plan.scenarios) == 2
    isolation = tuple(
        scenario
        for scenario in result.scenario_results
        if isinstance(scenario, ScopeIsolationResult)
    )
    assert len(isolation) == 2
    assert all(scenario.status is ScenarioStatus.PASS for scenario in isolation)
    assert isinstance(result.plan.purge, PurgePlan)
    assert isinstance(result.purge_result, PurgeResult)
    assert result.purge_result.status is PurgeStatus.PASS
    assert isinstance(result.purge_result.preparation, PreparationFact)
    assert begun[-1] == "purge"
    assert len(begun) == len(set(begun)) == 7
    assert tuple(fact.action_id.ordinal for fact in result.raw_facts) == tuple(
        range(len(result.raw_facts))
    )


@pytest.mark.parametrize(
    ("selected_scope", "preserved_root"),
    ((Scope.USER, SurfaceRoot.PROJECT), (Scope.PROJECT, SurfaceRoot.HOME)),
)
def test_scope_isolation_detects_opposite_scope_removal_in_both_directions(
    selected_scope: Scope,
    preserved_root: SurfaceRoot,
) -> None:
    session = _SessionFacts()

    def fulfil(request: ActionRequest) -> RawFact:
        fact = session.passing(request)
        if not (
            isinstance(request, ObservationRequest)
            and request.scope is selected_scope
            and request.phase is PhaseKind.INSTALL
            and isinstance(fact, ObservationFact)
        ):
            return fact
        damaged = tuple(
            replace(
                surface,
                destination=EntryFact(
                    SandboxPath(surface.surface.root, surface.surface.path),
                    EntryKind.MISSING,
                ),
            )
            if surface.surface.root is preserved_root
            else surface
            for surface in fact.surfaces
        )
        return replace(fact, surfaces=damaged)

    result = validate(
        ValidationRequest(("fictional",), (Scope.USER, Scope.PROJECT)),
        _both_scope_documents(),
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationCompleted)
    isolation = next(
        scenario
        for scenario in result.scenario_results
        if isinstance(scenario, ScopeIsolationResult) and scenario.selected_scope is selected_scope
    )
    assert isolation.status is ScenarioStatus.FINDING
    assert any(phase.status is PhaseStatus.FINDING for phase in isolation.phases)


def test_aggregate_continues_independent_preparations_after_one_product_failure() -> None:
    documents = CatalogDocuments(
        tuple(
            CatalogDocument(
                f"target-{index}.yaml",
                _catalog_text(
                    _supported_project(
                        _owned_file_surface(
                            path=f".fictional/{index}.txt",
                            source=f"fixtures/{index}.txt",
                        )
                    )
                ),
            )
            for index in range(3)
        )
    )
    session = _SessionFacts()
    requests: list[ActionRequest] = []

    def fulfil(request: ActionRequest) -> RawFact:
        requests.append(request)
        fact = session.passing(request)
        if (
            isinstance(request, CommandRequest)
            and request.phase is PhaseKind.AGGREGATE_PREPARE
            and isinstance(request.subject, TargetSubject)
            and request.subject.name == "target-0"
        ):
            assert isinstance(fact, CommandFact)
            return replace(fact, exit_code=17)
        return fact

    result = validate(
        ValidationRequest(
            ("target-0", "target-1", "target-2"),
            (Scope.PROJECT,),
        ),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationCompleted)
    aggregate = next(
        scenario for scenario in result.scenario_results if isinstance(scenario, AggregateResult)
    )
    assert aggregate.status is ScenarioStatus.FINDING
    assert tuple(phase.status for phase in aggregate.phases) == (
        PhaseStatus.FINDING,
        PhaseStatus.PASS,
        PhaseStatus.PASS,
        PhaseStatus.PASS,
    )
    aggregate_commands = tuple(
        request.phase
        for request in requests
        if isinstance(request, CommandRequest)
        and request.phase in {PhaseKind.AGGREGATE_PREPARE, PhaseKind.AGGREGATE_UNINSTALL}
    )
    assert aggregate_commands == (
        PhaseKind.AGGREGATE_PREPARE,
        PhaseKind.AGGREGATE_PREPARE,
        PhaseKind.AGGREGATE_PREPARE,
        PhaseKind.AGGREGATE_UNINSTALL,
    )


@pytest.mark.parametrize("damaged", ("tree", "sentinel"))
def test_purge_requires_whole_tree_removal_and_unrelated_content_preservation(
    damaged: str,
) -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                _catalog_text(_supported_project(_owned_file_surface())),
            ),
        )
    )
    session = _SessionFacts()

    def fulfil(request: ActionRequest) -> RawFact:
        fact = session.passing(request)
        if not isinstance(request, ObservationRequest) or request.phase is not PhaseKind.PURGE:
            return fact
        assert isinstance(fact, ObservationFact)
        surfaces = list(fact.surfaces)
        for index, observed in enumerate(surfaces):
            if damaged == "tree" and isinstance(observed.surface, ManagedTreeSurface):
                surfaces[index] = replace(
                    observed,
                    destination=EntryFact(
                        observed.destination.location,
                        EntryKind.DIRECTORY,
                    ),
                )
            if damaged == "sentinel" and isinstance(observed.surface, HarnessFileSurface):
                surfaces[index] = replace(
                    observed,
                    destination=EntryFact(
                        observed.destination.location,
                        EntryKind.MISSING,
                    ),
                )
        return replace(fact, surfaces=tuple(surfaces))

    result = validate(
        ValidationRequest(("fictional",), (Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationCompleted)
    assert result.purge_result.status is PurgeStatus.FINDING
    assert result.purge_result.phases[-1].status is PhaseStatus.FINDING


def test_raw_fact_boundary_rejects_new_malformed_preparation_and_entry_shapes() -> None:
    surface = OwnedFileSurface(
        SurfaceRoot.PROJECT,
        ".fictional/config.txt",
        "fixtures/config.txt",
    )
    observation_request = ObservationRequest(
        ActionId("plan-fixture", 0),
        TargetSubject("fictional"),
        Scope.PROJECT,
        PhaseKind.INSTALL,
        (surface,),
        (SurfaceExpectation.INSTALLED,),
    )
    observation = _passing_observation(observation_request)
    observed = observation.surfaces[0]
    malformed_observations = (
        replace(observation, surfaces=cast(tuple[SurfaceFact, ...], object())),
        replace(observation, surfaces=()),
        replace(
            observation,
            surfaces=(
                replace(
                    observed,
                    destination=replace(
                        observed.destination,
                        location=SandboxPath(SurfaceRoot.PROJECT, "different.txt"),
                    ),
                ),
            ),
        ),
        replace(
            observation,
            surfaces=(
                replace(
                    observed,
                    destination=replace(
                        observed.destination,
                        content=cast(ByteCapture, object()),
                    ),
                ),
            ),
        ),
    )
    for malformed in malformed_observations:
        assert validate_raw_fact(observation_request, malformed) == (
            "Raw Fact observation evidence is invalid"
        )

    preparation_request = PreparationRequest(
        ActionId("plan-fixture", 0),
        HarnessPolicy().purge_fixtures,
    )
    preparation = _passing_preparation(preparation_request)
    malformed_preparations = (
        replace(preparation, files=cast(tuple[EntryFact, ...], object())),
        replace(preparation, files=()),
        replace(
            preparation,
            files=(
                replace(
                    preparation.files[0],
                    location=SandboxPath(SurfaceRoot.PROJECT, "different.txt"),
                ),
                *preparation.files[1:],
            ),
        ),
        replace(
            preparation,
            files=(
                replace(preparation.files[0], content=ByteCapture(b"wrong", True)),
                *preparation.files[1:],
            ),
        ),
    )
    for malformed in malformed_preparations:
        assert validate_raw_fact(preparation_request, malformed) == (
            "Raw Fact preparation evidence is invalid"
        )

    failure_chronology = _chronology(
        preparation_request.action_id,
        OperationKind.PREPARATION_STARTED,
        OperationKind.PREPARATION_FAILED,
    )
    preparation_failure = ActionFailureFact(
        preparation_request.action_id,
        ActionKind.PREPARATION,
        "prepare_fixture",
        "fictional preparation failure",
        failure_chronology,
    )
    assert validate_raw_fact(preparation_request, preparation_failure) is preparation_failure


def test_raw_fact_boundary_rejects_invalid_identity_location_and_time_order() -> None:
    request = CommandRequest(
        ActionId("plan-fixture", 0),
        TargetSubject("fictional"),
        Scope.PROJECT,
        PhaseKind.INSTALL,
        ("fictional",),
    )
    command = _passing_command(request)
    invalid_identity = replace(command, action_id=cast(ActionId, object()))

    assert validate_raw_fact(request, invalid_identity) == "Raw Fact action identity is invalid"
    reversed_time = replace(
        command,
        chronology=(
            replace(command.chronology[0], occurred_ns=2),
            replace(command.chronology[1], occurred_ns=1),
        ),
    )
    assert validate_session_chronology((reversed_time,)) == (
        "Raw Facts do not form one total session chronology"
    )


@pytest.mark.parametrize("failure", ("raised", "chronology", "typed"))
def test_purge_preparation_failures_remain_closed_diagnostic_results(failure: str) -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                _catalog_text(_supported_project(_owned_file_surface())),
            ),
        )
    )
    session = _SessionFacts()

    def fulfil(request: ActionRequest) -> RawFact:
        if not isinstance(request, PreparationRequest):
            return session.passing(request)
        if failure == "raised":
            raise RuntimeError("fictional preparation exception")
        if failure == "chronology":
            return _passing_preparation(request)
        chronology = _chronology(
            request.action_id,
            OperationKind.PREPARATION_STARTED,
            OperationKind.PREPARATION_FAILED,
        )
        return session.bind(
            ActionFailureFact(
                request.action_id,
                ActionKind.PREPARATION,
                "prepare_fixture",
                "fictional preparation failure",
                chronology,
            )
        )

    result = validate(
        ValidationRequest(("fictional",), (Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    if failure == "typed":
        assert isinstance(result, ValidationCompleted)
        assert result.purge_result.status is PurgeStatus.INCOMPLETE
        assert isinstance(result.purge_result.preparation, ActionFailureFact)
    else:
        assert isinstance(result, ValidationRejected)
