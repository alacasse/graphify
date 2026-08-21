from __future__ import annotations

import itertools
import json
from dataclasses import FrozenInstanceError
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
from tools.install_sandbox.validation.engine import (
    ValidationCompleted,
    ValidationRejected,
    validate,
)
from tools.install_sandbox.validation.plan_types import (
    AggregatePlan,
    HarnessPolicy,
    LifecyclePlan,
    NotApplicablePhasePlan,
    PhasePlan,
    UnsupportedPlan,
    ValidationRequest,
)
from tools.install_sandbox.validation.protocol import (
    ActionFailureFact,
    ActionId,
    ActionKind,
    AggregateSubject,
    ByteCapture,
    CommandFact,
    CommandRequest,
    EntryFact,
    EntryKind,
    FilesystemSnapshot,
    ObservationFact,
    ObservationRequest,
    PhaseKind,
    PreparedSourcePath,
    RawFact,
    SandboxPath,
    SnapshotEntry,
    StreamCapture,
    SurfaceExpectation,
    SurfaceFact,
)
from tools.install_sandbox.validation.results import (
    LifecycleResult,
    PhaseResult,
    PhaseStatus,
    ProductFinding,
    ScenarioStatus,
    UnsupportedResult,
)


def _passing_observation(request: ObservationRequest) -> ObservationFact:
    surfaces: list[SurfaceFact] = []
    for surface in request.surfaces:
        if isinstance(surface, TextEntrySurface):
            payload = f"{surface.entry}\n{surface.required_text}\n".encode()
            source = None
        else:
            payload = b"expected payload\n"
            source = EntryFact(
                PreparedSourcePath(surface.source),
                EntryKind.FILE,
                content=ByteCapture(payload, True),
            )
        destination = EntryFact(
            SandboxPath(surface.root, surface.path),
            (
                EntryKind.MISSING
                if request.expectation is SurfaceExpectation.ABSENT
                else EntryKind.FILE
            ),
            content=(
                None
                if request.expectation is SurfaceExpectation.ABSENT
                else ByteCapture(payload, True)
            ),
        )
        surfaces.append(SurfaceFact(surface, destination, source))
    return ObservationFact(request.action_id, tuple(surfaces))


def _passing_fulfil(request: CommandRequest | ObservationRequest) -> RawFact:
    if isinstance(request, CommandRequest):
        working_directory = (
            SurfaceRoot.USER_CWD if request.scope is Scope.USER else SurfaceRoot.PROJECT
        )
        return CommandFact(
            request.action_id,
            0,
            argv=request.argv,
            working_directory=working_directory,
            stdout=StreamCapture(b"", True),
            stderr=StreamCapture(b"", True),
            started_ns=request.action_id.ordinal * 10 + 1,
            finished_ns=request.action_id.ordinal * 10 + 2,
        )
    return _passing_observation(request)


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
    requests: list[CommandRequest | ObservationRequest] = []

    def fulfil(request: CommandRequest | ObservationRequest) -> RawFact:
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
    assert len(requests) == 10
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

    def fulfil(request: CommandRequest | ObservationRequest) -> RawFact:
        if isinstance(request, CommandRequest):
            working_directory = (
                SurfaceRoot.USER_CWD if request.scope is Scope.USER else SurfaceRoot.PROJECT
            )
            return CommandFact(
                request.action_id,
                0,
                argv=request.argv,
                working_directory=working_directory,
                stdout=StreamCapture(b"", True),
                stderr=StreamCapture(b"", True),
                started_ns=request.action_id.ordinal * 10 + 1,
                finished_ns=request.action_id.ordinal * 10 + 2,
            )
        surfaces: list[SurfaceFact] = []
        for surface in request.surfaces:
            content = ByteCapture(b"expected payload\n", True)
            destination = EntryFact(
                SandboxPath(surface.root, surface.path),
                (
                    EntryKind.MISSING
                    if request.expectation is SurfaceExpectation.ABSENT
                    else EntryKind.FILE
                ),
                content=None if request.expectation is SurfaceExpectation.ABSENT else content,
            )
            source = EntryFact(
                PreparedSourcePath(cast(OwnedFileSurface, surface).source),
                EntryKind.FILE,
                content=content,
            )
            surfaces.append(SurfaceFact(surface, destination, source))
        return ObservationFact(
            request.action_id,
            tuple(surfaces),
            started_ns=request.action_id.ordinal * 10 + 1,
            finished_ns=request.action_id.ordinal * 10 + 2,
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
    requests: list[CommandRequest | ObservationRequest] = []

    def fulfil(request: CommandRequest | ObservationRequest) -> RawFact:
        requests.append(request)
        if isinstance(request, ObservationRequest):
            return _passing_observation(request)
        return CommandFact(
            request.action_id,
            17 if len(requests) == 1 else 0,
            argv=request.argv,
            working_directory=SurfaceRoot.PROJECT,
            stdout=StreamCapture(b"partial product output", True),
            stderr=StreamCapture(b"product error", True),
            started_ns=request.action_id.ordinal * 10 + 1,
            finished_ns=request.action_id.ordinal * 10 + 2,
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
    assert requests[0].phase is PhaseKind.INSTALL
    assert not any(
        request.phase in {PhaseKind.REINSTALL, PhaseKind.TARGET_UNINSTALL} for request in requests
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

    def fulfil(request: CommandRequest | ObservationRequest) -> RawFact:
        if isinstance(request, ObservationRequest):
            return _passing_observation(request)
        after_entries = ()
        if request.phase is PhaseKind.INSTALL:
            after_entries = (
                SnapshotEntry(SurfaceRoot.PROJECT, ".fictional", EntryKind.DIRECTORY),
                SnapshotEntry(
                    SurfaceRoot.PROJECT,
                    ".fictional/config.txt",
                    EntryKind.FILE,
                    size=8,
                    sha256="declared",
                ),
                SnapshotEntry(
                    SurfaceRoot.PROJECT,
                    ".fictional/undeclared.txt",
                    EntryKind.FILE,
                    size=5,
                    sha256="extra",
                ),
            )
        return CommandFact(
            request.action_id,
            0,
            argv=request.argv,
            working_directory=SurfaceRoot.PROJECT,
            stdout=StreamCapture(b"", True),
            stderr=StreamCapture(b"", True),
            started_ns=request.action_id.ordinal * 10 + 1,
            finished_ns=request.action_id.ordinal * 10 + 2,
            before_snapshot=FilesystemSnapshot(()),
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

    def fulfil(request: CommandRequest | ObservationRequest) -> RawFact:
        if isinstance(request, ObservationRequest):
            return _passing_observation(request)
        content_identity = "changed" if request.phase is PhaseKind.REINSTALL else "stable"
        entries = (
            SnapshotEntry(SurfaceRoot.PROJECT, ".fictional", EntryKind.DIRECTORY),
            SnapshotEntry(
                SurfaceRoot.PROJECT,
                ".fictional/config.txt",
                EntryKind.FILE,
                size=8,
                sha256=content_identity,
            ),
        )
        return CommandFact(
            request.action_id,
            0,
            argv=request.argv,
            working_directory=SurfaceRoot.PROJECT,
            stdout=StreamCapture(b"", True),
            stderr=StreamCapture(b"", True),
            started_ns=request.action_id.ordinal * 10 + 1,
            finished_ns=request.action_id.ordinal * 10 + 2,
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
    requests: list[CommandRequest | ObservationRequest] = []

    def fulfil(request: CommandRequest | ObservationRequest) -> RawFact:
        requests.append(request)
        if len(requests) == 1:
            return ActionFailureFact(
                request.action_id,
                ActionKind.COMMAND,
                "spawn_command",
                "fixture executable is unavailable",
                (),
            )
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
        request.phase in {PhaseKind.REINSTALL, PhaseKind.TARGET_UNINSTALL} for request in requests
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

    def fulfil(request: CommandRequest | ObservationRequest) -> RawFact:
        if isinstance(request, CommandRequest) and request.phase is PhaseKind.INSTALL:
            return CommandFact(
                request.action_id,
                -9,
                argv=request.argv,
                working_directory=SurfaceRoot.PROJECT,
                signal=9,
                timed_out=True,
                stdout=StreamCapture(b"output before timeout", False, 7),
                stderr=StreamCapture(b"error before timeout", False, 5),
                started_ns=1,
                finished_ns=2,
            )
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


def test_observation_failure_takes_precedence_over_a_product_timeout() -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                _catalog_text(_supported_project(_owned_file_surface())),
            ),
        )
    )
    requests: list[CommandRequest | ObservationRequest] = []

    def fulfil(request: CommandRequest | ObservationRequest) -> RawFact:
        requests.append(request)
        if isinstance(request, CommandRequest) and request.action_id.ordinal == 0:
            return CommandFact(
                request.action_id,
                -9,
                argv=request.argv,
                working_directory=SurfaceRoot.PROJECT,
                signal=9,
                timed_out=True,
                stdout=StreamCapture(b"partial", False),
                stderr=StreamCapture(b"", False),
                started_ns=1,
                finished_ns=2,
            )
        if isinstance(request, ObservationRequest) and request.action_id.ordinal == 1:
            return ActionFailureFact(
                request.action_id,
                ActionKind.OBSERVATION,
                "observe_surface",
                "filesystem became unreadable",
                (),
            )
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
        request.phase in {PhaseKind.REINSTALL, PhaseKind.TARGET_UNINSTALL} for request in requests
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

    def fulfil(request: CommandRequest | ObservationRequest) -> RawFact:
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

    def fulfil(request: CommandRequest | ObservationRequest) -> RawFact:
        del request
        return cast(RawFact, object())

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationRejected)
    assert result.reasons == ("fulfil returned an unknown Raw Fact variant",)


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

    def fulfil(request: CommandRequest | ObservationRequest) -> RawFact:
        return CommandFact(request.action_id, cast(int, object()))

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationRejected)
    assert result.reasons == ("Command Fact exit_code must be an integer",)


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

    def fulfil(request: CommandRequest | ObservationRequest) -> RawFact:
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

    def fulfil(request: CommandRequest | ObservationRequest) -> RawFact:
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

    def fulfil(request: CommandRequest | ObservationRequest) -> RawFact:
        if mismatch == "action-id":
            return CommandFact(ActionId("different-plan", 0), 0)
        return ObservationFact(request.action_id, ())

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationRejected)
    assert "Raw Fact does not match planned action" in result.reasons[0]


def test_malformed_observation_fact_fails_closed() -> None:
    documents = CatalogDocuments(
        (
            CatalogDocument(
                "fictional.yaml",
                _catalog_text(_supported_project(_owned_file_surface())),
            ),
        )
    )

    def fulfil(request: CommandRequest | ObservationRequest) -> RawFact:
        if isinstance(request, CommandRequest):
            return CommandFact(request.action_id, 0)
        return ObservationFact(request.action_id, cast(tuple[SurfaceFact, ...], object()))

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationRejected)
    assert result.reasons == ("Observation Fact surfaces must be a tuple",)


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
    requests: list[CommandRequest | ObservationRequest] = []

    def fulfil(request: CommandRequest | ObservationRequest) -> RawFact:
        requests.append(request)
        if isinstance(request, CommandRequest):
            return CommandFact(request.action_id, 0)
        return _passing_observation(request)

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
    observed_paths = tuple(surface.path for surface in aggregate.uninstall.observation.surfaces)
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

    result = validate(
        ValidationRequest(targets=("fictional",), scopes=(Scope.USER,)),
        documents,
        HarnessPolicy(),
        _passing_fulfil,
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

    def fulfil(request: CommandRequest | ObservationRequest) -> RawFact:
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
    assert aggregate.uninstall.observation.surfaces == install.observation.surfaces
