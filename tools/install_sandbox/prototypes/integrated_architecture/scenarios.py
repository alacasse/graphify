"""Deterministic architecture demonstrations for issue #41."""

# pyright: strict

from __future__ import annotations

import ast
import hashlib
import json
import threading
from collections.abc import Callable
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from .bundle import (
    OWNER_MARKER,
    BundleCoherenceError,
    BundleFaults,
    RecoveryRejected,
    TerminalCommitPermit,
    TerminalCommitRejected,
    TerminalCommitted,
)
from .coordinator import (
    DurableNonterminal,
    DurableTerminal,
    PublicationAdapter,
    RecoveryCommitted,
    RecoveryRequest,
    RunController,
    RunRequest,
)
from .diagnostics import (
    CompletedAssessment,
    PublicationFact,
    PublicationFailed,
    Published,
    RecoveryReady,
    prepare_recovery,
)
from .documents import (
    DocumentError,
    PhaseStatus,
    RunningRunRecord,
    RunOutcome,
    ScenarioStatus,
    decode_manifest,
    decode_run_record,
    encode_document,
)
from .domain import (
    build_validation_plan,
    compile_catalog,
    independent_aggregate_cover_oracle,
    roll_up_phases,
    run_validation,
)
from .model import (
    AbsentRule,
    ActionId,
    ActionRequest,
    AggregateScenario,
    AggregateValidation,
    CapturedStream,
    CatalogDocumentsFact,
    CatalogReadRequest,
    CatalogReady,
    CommandFact,
    CommandRequest,
    CommandTermination,
    CompleteValidation,
    ContainsTextRule,
    ExactTextRule,
    Exited,
    FixturePreparationRequest,
    FixturePreparedFact,
    HarnessPolicy,
    ImageBuildRequest,
    ImmutableImageFact,
    LifecycleScenario,
    LifecycleValidation,
    ObservationFact,
    ObservationRequest,
    ObservationSpecification,
    ObservedAbsent,
    ObservedContent,
    PhaseFinding,
    PhaseKind,
    PhaseNotApplicable,
    PhasePassed,
    PhaseScenarioRecord,
    PlanReady,
    RawCatalogDocument,
    RawFact,
    RunId,
    ScenarioFinding,
    ScenarioIncomplete,
    Scope,
    StableInstallationEstablished,
    StreamCaptureFailure,
    SubjectPreparationRequest,
    SubjectPreparedFact,
    SubjectProbeFact,
    SubjectProbeRequest,
    TimedOut,
    ValidationIncomplete,
)
from .resources import (
    ContainerClaimed,
    ContainerClaimRejected,
    DockerDaemonAdapter,
    LeaseBackedFulfilment,
    RecoverySession,
    ResourceFaults,
    ResourceInputs,
    RetentionAdapter,
    nominate_recovery,
)


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class DemoFrame:
    number: int
    action: str
    sections: tuple[tuple[str, tuple[str, ...]], ...]


_INSTALL_SCRIPT = (
    "from pathlib import Path; import sys; target=sys.argv[1]; scope=sys.argv[3]; "
    "Path(f'{target}-{scope}.txt').write_text(f'{target}:{scope}', encoding='utf-8')"
)
_UNINSTALL_SCRIPT = (
    "from pathlib import Path; import sys; target=sys.argv[1]; scope=sys.argv[3]; "
    "Path(f'{target}-{scope}.txt').unlink(missing_ok=True)"
)
_AGGREGATE_SCRIPT = (
    "from pathlib import Path; import sys; scope=sys.argv[2]; "
    "[item.unlink(missing_ok=True) for item in Path('.').glob(f'*-{scope}.txt')]"
)
_PURGE_SCRIPT = (
    "from pathlib import Path; import shutil; "
    "[shutil.rmtree(Path(name), ignore_errors=True) "
    "for name in ('installations', 'graphify-out')]"
)
_EXITED_ZERO = Exited(0)
_RESOURCE_FAULTS = ResourceFaults()
_BUNDLE_FAULTS = BundleFaults()


def _policy(*, limitations: tuple[str, ...] = ()) -> HarnessPolicy:
    return HarnessPolicy(
        install_argv=("python3.12", "-c", _INSTALL_SCRIPT),
        uninstall_argv=("python3.12", "-c", _UNINSTALL_SCRIPT),
        aggregate_uninstall_argv=("python3.12", "-c", _AGGREGATE_SCRIPT),
        purge_argv=("python3.12", "-c", _PURGE_SCRIPT),
        runtime_limitations=limitations,
    )


def _scope(
    name: str,
    scope: str,
    *,
    supported: bool = True,
    target_uninstall: bool = True,
) -> dict[str, object]:
    if not supported:
        return {
            "supported": False,
            "reason": "fictional runtime does not expose this scope",
            "limitations": ["fictional unsupported scope"],
        }
    return {
        "supported": True,
        "target_uninstall": target_uninstall,
        "limitations": [f"prototype {name}:{scope}"],
        "effects": [
            {
                "kind": "owned_file",
                "location": f"{name}-{scope}.txt",
                "expected_text": f"{name}:{scope}",
            }
        ],
    }


def _catalog_documents(*, alpha_uninstall: bool = True) -> tuple[RawCatalogDocument, ...]:
    return (
        {
            "source": "alpha.yaml",
            "name": "alpha",
            "scopes": {
                "user": _scope("alpha", "user", target_uninstall=alpha_uninstall),
                "project": _scope("alpha", "project"),
            },
        },
        {
            "source": "beta.yaml",
            "name": "beta",
            "scopes": {
                "user": _scope("beta", "user"),
                "project": _scope("beta", "project", supported=False),
            },
        },
    )


def _inputs(documents: tuple[RawCatalogDocument, ...] | None = None) -> ResourceInputs:
    return ResourceInputs(
        "prototype-source",
        _catalog_documents() if documents is None else documents,
    )


def _catalog() -> CatalogReady:
    compiled = compile_catalog(_catalog_documents())
    if not isinstance(compiled, CatalogReady):
        raise AssertionError(f"fixture catalog rejected: {compiled!r}")
    return compiled


def _lifecycle_plan(*, alpha_uninstall: bool = True) -> PlanReady:
    compiled_catalog = compile_catalog(_catalog_documents(alpha_uninstall=alpha_uninstall))
    if not isinstance(compiled_catalog, CatalogReady):
        raise AssertionError("fixture catalog rejected")
    compiled = build_validation_plan(
        compiled_catalog.catalog,
        LifecycleValidation("alpha", Scope.USER),
        _policy(),
    )
    if not isinstance(compiled, PlanReady):
        raise AssertionError(f"fixture plan rejected: {compiled!r}")
    return compiled


def _captured(content: bytes = b"") -> CapturedStream:
    return CapturedStream(content, hashlib.sha256(content).hexdigest(), len(content))


def _command_fact(
    request: CommandRequest,
    termination: CommandTermination = _EXITED_ZERO,
) -> CommandFact:
    return CommandFact(
        request.action_id,
        request.argv,
        request.cwd,
        request.action_id.ordinal,
        request.action_id.ordinal + 1,
        termination,
        True,
        _captured(),
        _captured(),
        (f"command:{request.phase}",),
        request.scenario,
        request.phase,
        request.purpose,
    )


def _scripted_fulfil(
    request: ActionRequest,
    *,
    repair_finding: bool = False,
) -> RawFact:
    control = _scripted_control(request)
    if control is not None:
        return control
    if isinstance(request, CommandRequest):
        return _command_fact(request)
    if not isinstance(request, ObservationRequest):
        raise TypeError("scripted fulfilment received an acquisition request")
    return _scripted_observation(request, repair_finding=repair_finding)


def _scripted_control(request: ActionRequest) -> RawFact | None:
    if isinstance(request, SubjectPreparationRequest):
        return SubjectPreparedFact(
            request.action_id,
            request.target,
            request.scope,
            f"prepared:{request.target}:{request.scope.value}",
        )
    if isinstance(request, SubjectProbeRequest):
        return SubjectProbeFact(
            request.action_id,
            request.target,
            request.scope,
            request.prepared_identity,
            "local-wheel",
            "prototype-1",
            True,
        )
    if isinstance(request, FixturePreparationRequest):
        return FixturePreparedFact(request.action_id, request.entries)
    return None


def _scripted_observation(
    request: ObservationRequest,
    *,
    repair_finding: bool,
) -> ObservationFact:
    items: list[ObservedAbsent | ObservedContent] = []
    for rule in request.specification.rules:
        if isinstance(rule, AbsentRule):
            items.append(ObservedAbsent(rule.key, rule.location))
            continue
        expected = rule.expected_text if isinstance(rule, ExactTextRule) else rule.required_text
        content = expected.encode()
        if repair_finding and request.phase.startswith(f"{PhaseKind.REPAIR.value}:"):
            content = b"deliberate semantic mismatch"
        items.append(
            ObservedContent(
                rule.key,
                rule.location,
                content,
                hashlib.sha256(content).hexdigest(),
                len(content),
            )
        )
    return ObservationFact(
        request.action_id,
        tuple(items),
        (f"observe:{request.phase}",),
        request.scenario,
        request.phase,
    )


def _running_bytes(run_id: str) -> bytes:
    return encode_document(
        RunningRunRecord(run_id, "alpha:user", "PENDING", "PENDING", "allocated")
    )


def _allocate_resources(
    base: Path,
    run_id: str,
    docker: DockerDaemonAdapter,
    *,
    faults: ResourceFaults = _RESOURCE_FAULTS,
    bundle_faults: BundleFaults = _BUNDLE_FAULTS,
    inputs: ResourceInputs | None = None,
) -> LeaseBackedFulfilment:
    output = base / "out"
    sandbox = base / f"sandbox-{run_id}"
    sandbox.mkdir(parents=True)
    return LeaseBackedFulfilment.allocate(
        output,
        run_id,
        RunId(run_id),
        _running_bytes(run_id),
        sandbox,
        docker,
        faults=faults,
        bundle_faults=bundle_faults,
        inputs=_inputs() if inputs is None else inputs,
    )


def _request(
    run_id: str,
    *,
    raw_exit: int | None = None,
    signal: str | None = None,
    validation: LifecycleValidation | CompleteValidation | AggregateValidation | None = None,
) -> RunRequest:
    return RunRequest(
        RunId(run_id),
        "alpha:user",
        "prototype-source",
        LifecycleValidation("alpha", Scope.USER) if validation is None else validation,
        _policy(limitations=("fake runtime is Component Evidence",)),
        raw_exit,
        signal,
    )


def _controller(
    base: Path,
    *,
    inputs: ResourceInputs | None = None,
    resource_faults: ResourceFaults = _RESOURCE_FAULTS,
    bundle_faults: BundleFaults = _BUNDLE_FAULTS,
    publication: PublicationAdapter | None = None,
    retention: RetentionAdapter | None = None,
    before_terminal_commit: (
        Callable[[LeaseBackedFulfilment, TerminalCommitPermit], None] | None
    ) = None,
) -> RunController:
    sandbox = base / "sandbox"
    sandbox.mkdir(parents=True)
    if before_terminal_commit is None:
        return RunController._for_harness(  # pyright: ignore[reportPrivateUsage]
            base / "out",
            sandbox,
            DockerDaemonAdapter(f"demo:{base}"),
            _inputs() if inputs is None else inputs,
            resource_faults=resource_faults,
            bundle_faults=bundle_faults,
            publication=publication,
            retention=retention,
        )

    return RunController._for_harness(  # pyright: ignore[reportPrivateUsage]
        base / "out",
        sandbox,
        DockerDaemonAdapter(f"demo:{base}"),
        _inputs() if inputs is None else inputs,
        resource_faults=resource_faults,
        bundle_faults=bundle_faults,
        publication=publication,
        retention=retention,
        before_terminal_commit=before_terminal_commit,
    )


def _strict_catalog_rejections() -> None:
    malformed = dict(_catalog_documents()[0])
    malformed["unknown"] = True
    assert not isinstance(compile_catalog((malformed,)), CatalogReady)
    unsafe = dict(_catalog_documents()[0])
    unsafe["source"] = "../alpha.yaml"
    assert not isinstance(compile_catalog((unsafe,)), CatalogReady)
    unknown_scope = cast(dict[str, object], json.loads(json.dumps(_catalog_documents()[0])))
    cast(dict[str, object], unknown_scope["scopes"])["machine"] = {}
    assert not isinstance(compile_catalog((unknown_scope,)), CatalogReady)
    unknown_effect = cast(dict[str, object], json.loads(json.dumps(_catalog_documents()[0])))
    scopes = cast(dict[str, object], unknown_effect["scopes"])
    user = cast(dict[str, object], scopes["user"])
    first_effect = cast(list[dict[str, object]], user["effects"])[0]
    first_effect["unknown"] = True
    assert not isinstance(compile_catalog((unknown_effect,)), CatalogReady)


def _catalog_immutability() -> None:
    compiled = _catalog()
    try:
        compiled.catalog.targets = ()  # type: ignore[misc]
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("frozen catalog accepted mutation")
    mutable = cast(dict[str, object], json.loads(json.dumps(_catalog_documents()[0])))
    resource_inputs = ResourceInputs("prototype-source", (mutable,))
    scopes = cast(dict[str, object], mutable["scopes"])
    user = cast(dict[str, object], scopes["user"])
    cast(list[dict[str, object]], user["effects"])[0]["expected_text"] = "mutated"
    with TemporaryDirectory(prefix="issue41-catalog-owned-") as temporary:
        resource = _allocate_resources(
            Path(temporary),
            "catalog-owned",
            DockerDaemonAdapter("catalog-owned"),
            inputs=resource_inputs,
        )
        plan_id = _lifecycle_plan().plan.plan_id
        try:
            built = resource.fulfil(
                ImageBuildRequest(
                    ActionId(RunId("catalog-owned"), plan_id, 0),
                    "prototype-source",
                )
            )
            assert isinstance(built, ImmutableImageFact)
            read = resource.fulfil(
                CatalogReadRequest(
                    ActionId(RunId("catalog-owned"), plan_id, 1),
                    built.immutable_image_identity,
                )
            )
            assert isinstance(read, CatalogDocumentsFact)
            frozen = cast(dict[str, object], read.documents[0])
            frozen_scopes = cast(dict[str, object], frozen["scopes"])
            frozen_user = cast(dict[str, object], frozen_scopes["user"])
            frozen_effect = cast(list[dict[str, object]], frozen_user["effects"])[0]
            assert frozen_effect["expected_text"] == "alpha:user"
        finally:
            resource.close()


def _catalog_case() -> str:
    _strict_catalog_rejections()
    _catalog_immutability()
    return "nested unknowns, unsafe sources, and source mutation fail closed"


def _summary_case() -> str:
    plan = _lifecycle_plan().plan
    scenario = plan.scenarios[0]
    assert isinstance(scenario, LifecycleScenario)
    assert isinstance(roll_up_phases(scenario, ()), ScenarioIncomplete)
    return "scenario summary cannot contradict phase cardinality"


def _witness_case() -> str:
    outcome = run_validation(
        _lifecycle_plan().plan,
        RunId("witness"),
        lambda request: _scripted_fulfil(request, repair_finding=True),
    )
    record = outcome.scenario_records[0]
    assert isinstance(record, PhaseScenarioRecord)
    repair = next(item for item in record.phases if item.phase is PhaseKind.REPAIR)
    assert isinstance(repair, PhaseFinding)
    assert isinstance(repair.finding.witness, StableInstallationEstablished)
    assert isinstance(record.phases[-1], PhasePassed)
    return "repair finding preserved the witness and safe uninstall continued"


def _timeout_and_probe_case() -> str:
    def timed_out_product(request: ActionRequest) -> RawFact:
        if isinstance(request, CommandRequest) and request.phase.startswith("install:"):
            return _command_fact(request, TimedOut(5.0))
        return _scripted_fulfil(request)

    outcome = run_validation(
        _lifecycle_plan().plan,
        RunId("product-timeout"),
        timed_out_product,
    )
    assert not isinstance(outcome, ValidationIncomplete)
    first = outcome.scenario_records[0]
    assert isinstance(first, PhaseScenarioRecord)
    assert isinstance(first.result, ScenarioFinding)
    timed_out = next(item for item in first.phases if item.phase is PhaseKind.INSTALL)
    assert isinstance(timed_out, PhaseFinding)

    with TemporaryDirectory(prefix="issue41-probe-failure-") as temporary:
        result = _controller(
            Path(temporary),
            resource_faults=ResourceFaults(fail_probes=frozenset({"alpha:user"})),
        ).run(_request("probe-failure"))
        assert isinstance(result, DurableTerminal)
        assert result.assessment.run_record.outcome is RunOutcome.INCOMPLETE
        assert any(
            failure.stage == "application" for failure in result.assessment.run_record.failures
        )
    return "sound product timeout was a finding while failed package probe was incomplete"


def _not_applicable_case() -> str:
    plan = _lifecycle_plan(alpha_uninstall=False).plan
    outcome = run_validation(
        plan,
        RunId("not-applicable"),
        _scripted_fulfil,
    )
    record = outcome.scenario_records[0]
    assert isinstance(record, PhaseScenarioRecord)
    target = next(item for item in record.phases if item.phase is PhaseKind.TARGET_UNINSTALL)
    assert isinstance(target, PhaseNotApplicable)
    assert not any(
        isinstance(fact, CommandFact) and fact.phase.startswith("target-uninstall:")
        for fact in outcome.raw_facts
    )
    compiled = compile_catalog(_catalog_documents(alpha_uninstall=False))
    assert isinstance(compiled, CatalogReady)
    aggregate = build_validation_plan(
        compiled.catalog,
        AggregateValidation(Scope.USER),
        _policy(),
    )
    assert isinstance(aggregate, PlanReady)
    selected = independent_aggregate_cover_oracle(compiled.catalog, Scope.USER)
    assert "alpha" in selected
    aggregate_scenario = aggregate.plan.scenarios[0]
    assert isinstance(aggregate_scenario, AggregateScenario)
    assert "alpha" in tuple(item.target for item in aggregate_scenario.preparations)
    return "target uninstall N/A was command-free but independently joined to aggregate cleanup"


def _aggregate_case() -> str:
    duplicate_surface: tuple[RawCatalogDocument, ...] = (
        {
            "source": "x.yaml",
            "name": "x",
            "scopes": {"user": _scope("shared", "user"), "project": _scope("x", "project")},
        },
        {
            "source": "y.yaml",
            "name": "y",
            "scopes": {"user": _scope("shared", "user"), "project": _scope("y", "project")},
        },
    )
    compiled = compile_catalog(duplicate_surface)
    assert isinstance(compiled, CatalogReady)
    planned = build_validation_plan(compiled.catalog, AggregateValidation(Scope.USER), _policy())
    assert isinstance(planned, PlanReady)
    scenario = planned.plan.scenarios[0]
    assert isinstance(scenario, AggregateScenario)
    selected = tuple(item.target for item in scenario.preparations)
    assert selected == independent_aggregate_cover_oracle(compiled.catalog, Scope.USER) == ("x",)
    return "minimum aggregate cover matched the independent oracle"


def _namespace_case() -> str:
    with TemporaryDirectory(prefix="issue41-namespace-") as temporary:
        base = Path(temporary)
        first = _allocate_resources(base / "first", "owner-a", DockerDaemonAdapter("shared"))
        second = _allocate_resources(base / "second", "owner-b", DockerDaemonAdapter("shared"))
        try:
            assert isinstance(first.reserve_container("exact-name"), ContainerClaimed)
            assert isinstance(second.reserve_container("exact-name"), ContainerClaimRejected)
        finally:
            first.close()
            second.close()
    return "same-daemon adapters shared exact-name ownership"


def _active_recovery_case() -> str:
    with TemporaryDirectory(prefix="issue41-active-") as temporary:
        resource = _allocate_resources(
            Path(temporary), "active-owner", DockerDaemonAdapter("active")
        )
        try:
            assert isinstance(nominate_recovery(resource.snapshot().bundle_path), RecoveryRejected)
        finally:
            resource.close()
    return "active ownership and recovery ownership were mutually exclusive"


def _capture_case() -> str:
    with TemporaryDirectory(prefix="issue41-capture-") as temporary:
        resource = _allocate_resources(
            Path(temporary),
            "capture",
            DockerDaemonAdapter("capture"),
            faults=ResourceFaults(fail_stream="stdout", fail_after_bytes=2),
        )
        try:
            request = CommandRequest(
                ActionId(RunId("capture"), _lifecycle_plan().plan.plan_id, 0),
                "capture",
                "command",
                ("python3.12", "-c", "print('captured')"),
                ".",
            )
            fact = resource.fulfil(request)
            assert isinstance(fact, CommandFact)
            assert isinstance(fact.stdout, StreamCaptureFailure)
            assert fact.stdout.partial_content == b"ca" and fact.reaped
        finally:
            resource.close()
    return "capture failure retained raw termination, reap, and partial bytes"


def _content_case() -> str:
    with TemporaryDirectory(prefix="issue41-content-") as temporary:
        base = Path(temporary)
        resource = _allocate_resources(base, "content", DockerDaemonAdapter("content"))
        sandbox = base / "sandbox-content"
        (sandbox / "wanted.txt").write_text("wanted", encoding="utf-8")
        (sandbox / "secret.txt").write_text("TOP-SECRET", encoding="utf-8")
        request = ObservationRequest(
            ActionId(RunId("content"), _lifecycle_plan().plan.plan_id, 0),
            "content",
            "observe",
            ObservationSpecification((ContainsTextRule("wanted", "wanted.txt", "want"),)),
        )
        try:
            fact = resource.fulfil(request)
            assert isinstance(fact, ObservationFact)
            assert isinstance(fact.items[0], ObservedContent)
            assert fact.items[0].content == b"wanted"
            assert b"TOP-SECRET" not in repr(fact).encode()
        finally:
            resource.close()
    secret_documents: tuple[RawCatalogDocument, ...] = (
        {
            "source": "secret.yaml",
            "name": "secret",
            "scopes": {
                "user": {
                    "supported": True,
                    "target_uninstall": True,
                    "limitations": [],
                    "effects": [
                        {
                            "kind": "text_entry",
                            "location": "secret-user.txt",
                            "entry": "wanted",
                            "required_text": "wanted",
                        }
                    ],
                },
                "project": _scope("secret", "project", supported=False),
            },
        },
    )
    secret_install = (
        "from pathlib import Path; import sys; target=sys.argv[1]; scope=sys.argv[3]; "
        "Path(f'{target}-{scope}.txt').write_text("
        "Path('source-secret.txt').read_text(encoding='utf-8'), encoding='utf-8')"
    )
    policy = HarnessPolicy(
        install_argv=("python3.12", "-c", secret_install),
        uninstall_argv=("python3.12", "-c", _UNINSTALL_SCRIPT),
        aggregate_uninstall_argv=("python3.12", "-c", _AGGREGATE_SCRIPT),
        purge_argv=("python3.12", "-c", _PURGE_SCRIPT),
    )
    with TemporaryDirectory(prefix="issue41-content-projection-") as temporary:
        base = Path(temporary)
        controller = _controller(base, inputs=_inputs(secret_documents))
        (base / "sandbox" / "source-secret.txt").write_text(
            "wanted TOP-SECRET",
            encoding="utf-8",
        )
        request = RunRequest(
            RunId("content-projection"),
            "secret:user",
            "prototype-source",
            LifecycleValidation("secret", Scope.USER),
            policy,
        )
        result = controller.run(request)
        assert isinstance(result, DurableTerminal)
        manifest_bytes = (result.bundle / "manifest.json").read_bytes()
        assert b"TOP-SECRET" not in manifest_bytes
        assert b"wanted TOP-SECRET" not in manifest_bytes
    return "bounded content informed semantics but unrelated secret text was not persisted"


def _coherent_mutation_case() -> str:
    with TemporaryDirectory(prefix="issue41-mutation-") as temporary:
        resource = _allocate_resources(
            Path(temporary),
            "mutation",
            DockerDaemonAdapter("mutation"),
            bundle_faults=BundleFaults(mutate_during_next_read=True),
        )
        try:
            try:
                resource.read_bundle()
            except BundleCoherenceError:
                pass
            else:
                raise AssertionError("concurrent bundle mutation was accepted")
        finally:
            resource.close()
    return "whole-bundle enumeration mutation failed closed"


def _basic_run_case() -> str:
    with TemporaryDirectory(prefix="issue41-run-") as temporary:
        result = _controller(Path(temporary)).run(_request("basic"))
        assert isinstance(result, DurableTerminal)
        assert result.assessment.run_record.outcome is RunOutcome.PASSED
        manifest = result.assessment.manifest
        assert manifest is not None
        assert manifest.runtime_limitations
        assert all(item.status in ScenarioStatus for item in manifest.scenarios)
        assert all(
            phase.status in PhaseStatus
            for scenario in manifest.scenarios
            for phase in scenario.phases
        )
    return "full controller run produced uppercase closed status tokens"


def _invalid_exit_case() -> str:
    with TemporaryDirectory(prefix="issue41-exit-") as temporary:
        result = _controller(Path(temporary)).run(_request("invalid-exit", raw_exit=999))
        assert isinstance(result, DurableTerminal)
        record = result.assessment.run_record
        assert record.outcome is RunOutcome.INCOMPLETE
        assert record.raw_exit == 2 and record.invalid_raw_exit == 999
    return "impossible raw exit forced incomplete while retaining 999"


def _report_failure_case() -> str:
    with TemporaryDirectory(prefix="issue41-report-failure-") as temporary:
        result = _controller(
            Path(temporary),
            bundle_faults=BundleFaults(fail_writes=frozenset({"report.md"})),
        ).run(_request("report-failure"))
        assert isinstance(result, DurableNonterminal)
        assert isinstance(
            decode_run_record((result.bundle / "run.json").read_bytes()), RunningRunRecord
        )
    return "report persistence failure preserved Running authority"


def _initial_running_failure_case() -> str:
    with TemporaryDirectory(prefix="issue41-running-failure-") as temporary:
        result = _controller(
            Path(temporary),
            bundle_faults=BundleFaults(fail_writes=frozenset({"run.json"})),
        ).run(_request("running-failure"))
        assert isinstance(result, DurableNonterminal)
        assert result.bundle.name == "running-failure" and result.failures
    return "post-allocation initial Running failure returned the exact orphan path"


def _commit_mutation_case() -> str:
    def mutate(resources: LeaseBackedFulfilment, permit: TerminalCommitPermit) -> None:
        del permit
        (resources.snapshot().bundle_path / "late-evidence.txt").write_text(
            "changed", encoding="utf-8"
        )

    with TemporaryDirectory(prefix="issue41-commit-mutation-") as temporary:
        result = _controller(
            Path(temporary),
            before_terminal_commit=mutate,
        ).run(_request("commit-mutation"))
        assert isinstance(result, DurableNonterminal)
        assert isinstance(
            decode_run_record((result.bundle / "run.json").read_bytes()), RunningRunRecord
        )
    return "mutation after assessment invalidated the opaque terminal permit"


def _recovery_case() -> str:
    with TemporaryDirectory(prefix="issue41-recovery-") as temporary:
        controller = _controller(Path(temporary))
        bundle, expected = controller._abandon_for_harness(  # pyright: ignore[reportPrivateUsage]
            _request("recoverable")
        )
        result = controller.recover(RecoveryRequest(bundle, expected, "owner process disappeared"))
        assert isinstance(result, RecoveryCommitted)
        assert result.assessment.run_record.outcome is RunOutcome.INCOMPLETE
        assert result.assessment.run_record.failures
    return "typed recovery derived report/run bytes then freshly reassessed incomplete"


def _recovery_identity_case() -> str:
    with TemporaryDirectory(prefix="issue41-recovery-identity-") as temporary:
        controller = _controller(Path(temporary))
        bundle, expected = controller._abandon_for_harness(  # pyright: ignore[reportPrivateUsage]
            _request("recover-rename")
        )
        session = nominate_recovery(bundle)
        assert not isinstance(session, RecoveryRejected)
        prepared = prepare_recovery(session.read_bundle(), expected, "owner lost")
        assert isinstance(prepared, RecoveryReady)
        moved = bundle.with_name("moved")
        bundle.rename(moved)
        committed = session.commit_incomplete(prepared.permit)
        assert committed.__class__.__name__ == "TerminalCommitRejected"
        session.close()
    return "rename after recovery assessment invalidated commit authority"


def _reject_recovery_variant(variant: str) -> None:
    with TemporaryDirectory(prefix=f"issue41-recovery-{variant}-") as temporary:
        controller = _controller(Path(temporary))
        bundle, expected = controller._abandon_for_harness(  # pyright: ignore[reportPrivateUsage]
            _request(f"recover-{variant}")
        )
        session = nominate_recovery(bundle)
        assert not isinstance(session, RecoveryRejected)
        prepared = prepare_recovery(session.read_bundle(), expected, "owner lost")
        assert isinstance(prepared, RecoveryReady)
        if variant in {"replacement", "symlink"}:
            moved = bundle.with_name(f"{bundle.name}-moved")
            bundle.rename(moved)
            if variant == "replacement":
                bundle.mkdir()
            else:
                bundle.symlink_to(moved, target_is_directory=True)
        elif variant == "owner-marker":
            (bundle / OWNER_MARKER).write_text("changed\n", encoding="utf-8")
        else:
            (bundle / "late-public.txt").write_text("changed\n", encoding="utf-8")
        assert isinstance(session.commit_incomplete(prepared.permit), TerminalCommitRejected)
        session.close()


def _claim_recovery(
    barrier: threading.Barrier,
    bundle: Path,
    claims_lock: threading.Lock,
    claims: list[RecoverySession | RecoveryRejected],
) -> None:
    barrier.wait()
    result = nominate_recovery(bundle)
    with claims_lock:
        claims.append(result)


def _race_recovery_once(index: int) -> None:
    with TemporaryDirectory(prefix="issue41-recovery-race-") as temporary:
        resource = _allocate_resources(
            Path(temporary),
            f"race-{index}",
            DockerDaemonAdapter(f"race-{index}"),
        )
        proof = resource.quiesce_and_seal()
        resource.abandon_after_failure(proof)
        bundle = resource.snapshot().bundle_path
        resource.close()
        barrier = threading.Barrier(2)
        claims: list[RecoverySession | RecoveryRejected] = []
        claims_lock = threading.Lock()
        workers = tuple(
            threading.Thread(
                target=_claim_recovery,
                args=(barrier, bundle, claims_lock, claims),
            )
            for _ in range(2)
        )
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        winners = tuple(item for item in claims if not isinstance(item, RecoveryRejected))
        assert len(winners) == 1 and len(claims) == 2
        winners[0].close()


def _recovery_adversarial_case() -> str:
    for variant in ("replacement", "symlink", "owner-marker", "public-evidence"):
        _reject_recovery_variant(variant)
    for index in range(25):
        _race_recovery_once(index)
    return "replacement, symlink, marker, evidence mutation, and 25 recovery races failed closed"


def _codec_case() -> str:
    with TemporaryDirectory(prefix="issue41-codec-") as temporary:
        result = _controller(Path(temporary)).run(_request("codec"))
        assert isinstance(result, DurableTerminal)
        payload = cast(
            dict[str, object],
            json.loads((result.bundle / "manifest.json").read_bytes()),
        )
        scenarios = cast(list[dict[str, object]], payload["scenarios"])
        scenarios[0]["status"] = "BANANA"
        malformed = (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode()
        try:
            decode_manifest(malformed)
        except DocumentError:
            pass
        else:
            raise AssertionError("unknown status variant decoded")
        payload = cast(
            dict[str, object],
            json.loads((result.bundle / "manifest.json").read_bytes()),
        )
        facts = cast(list[dict[str, object]], payload["raw_facts"])
        command = next(item for item in facts if item.get("fact") == "command")
        command["termination"] = {
            "kind": "SIGNALLED",
            "raw_exit": 0,
            "signal": "9",
            "detail": None,
        }
        contradictory = (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode()
        try:
            decode_manifest(contradictory)
        except DocumentError:
            pass
        else:
            raise AssertionError("contradictory termination decoded")
    return "unknown and contradictory machine-document variants failed closed"


class _OrderedPublication:
    def __init__(self, retention: RetentionAdapter) -> None:
        self.retention = retention
        self.calls: list[str] = []

    def publish(self, bundle: Path, assessment: CompletedAssessment) -> PublicationFact:
        assert self.retention.applied()
        assert assessment.revision
        self.calls.append(bundle.name)
        return Published("ordered-artifact")


def _retention_publication_case() -> str:
    with TemporaryDirectory(prefix="issue41-retention-") as temporary:
        retention = RetentionAdapter()
        publication = _OrderedPublication(retention)
        result = _controller(
            Path(temporary),
            retention=retention,
            publication=publication,
        ).run(_request("retention"))
        assert isinstance(result, DurableTerminal)
        assert publication.calls == ["retention"]
        joined = " | ".join(result.trace)
        assert (
            joined.index("fresh reopen")
            < joined.index("keep-five")
            < joined.index("publication fact")
        )
    return "fresh trust authorized keep-five retention before publication and CI"


class _FailedPublication:
    def publish(self, bundle: Path, assessment: CompletedAssessment) -> PublicationFact:
        del bundle, assessment
        return PublicationFailed("injected publication failure")


def _exclusive_and_publication_case() -> str:
    commits: list[TerminalCommitted | TerminalCommitRejected] = []
    commit_lock = threading.Lock()

    def race(resources: LeaseBackedFulfilment, permit: TerminalCommitPermit) -> None:
        def commit() -> None:
            result = resources.commit_terminal(permit)
            with commit_lock:
                commits.append(result)

        workers = (threading.Thread(target=commit), threading.Thread(target=commit))
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()

    with TemporaryDirectory(prefix="issue41-exclusive-") as temporary:
        _controller(Path(temporary), before_terminal_commit=race).run(_request("exclusive"))
    assert sum(isinstance(item, TerminalCommitted) for item in commits) == 1
    assert sum(isinstance(item, TerminalCommitRejected) for item in commits) == 1

    with TemporaryDirectory(prefix="issue41-publication-failure-") as temporary:
        result = _controller(
            Path(temporary),
            publication=_FailedPublication(),
        ).run(_request("publication-failure"))
        assert isinstance(result, DurableTerminal)
        assert result.ci_decision.exit_code != 0
    return "concurrent terminal publication was exclusive and publication failure stayed red"


def _interrupt_and_ordering_case() -> str:
    with TemporaryDirectory(prefix="issue41-interrupt-") as temporary:
        result = _controller(
            Path(temporary),
            resource_faults=ResourceFaults(fail_observations=frozenset({"alpha-user.txt"})),
        ).run(_request("interrupt", raw_exit=143, signal="SIGTERM"))
        assert isinstance(result, DurableTerminal)
        record = result.assessment.run_record
        assert record.outcome is RunOutcome.INCOMPLETE
        assert record.raw_exit == 143 and record.interrupt_signal == "SIGTERM"

    with TemporaryDirectory(prefix="issue41-ordering-") as temporary:
        result = _controller(Path(temporary)).run(_request("ordering"))
        assert isinstance(result, DurableTerminal)
        manifest = result.assessment.manifest
        assert manifest is not None
        assert manifest.operational_chronology
        assert manifest.presentation_order
        assert manifest.operational_chronology != manifest.presentation_order
    return (
        "interrupt/raw exit survived incompleteness and chronology stayed separate "
        "from presentation"
    )


def _complete_plan_case() -> str:
    compiled = build_validation_plan(
        _catalog().catalog,
        CompleteValidation(("alpha", "beta"), (Scope.USER, Scope.PROJECT)),
        _policy(),
    )
    assert isinstance(compiled, PlanReady)
    outcome = run_validation(compiled.plan, RunId("complete"), _scripted_fulfil)
    assert not isinstance(outcome, ValidationIncomplete)
    assert len(outcome.scenario_records) == len(compiled.plan.projection.scenarios)
    assert outcome.purge_result.evidence
    planned = {
        action.ordinal
        for scenario in compiled.plan.projection.scenarios
        for action in scenario.expected_actions
    }
    planned.update(action.ordinal for action in compiled.plan.projection.subject_actions)
    planned.update(action.ordinal for action in compiled.plan.projection.purge_actions)
    assert {fact.action_id.ordinal for fact in outcome.raw_facts}.issubset(planned)
    return "complete plan preserved exact scenario cardinality, action bindings, and one purge"


def _dag_case() -> str:
    root = Path(__file__).parent
    forbidden = {
        "domain.py": {"resources", "diagnostics", "coordinator"},
        "resources.py": {"diagnostics", "coordinator"},
        "diagnostics.py": {"coordinator"},
    }
    for filename, denied in forbidden.items():
        tree = ast.parse((root / filename).read_text(encoding="utf-8"))
        imported = {
            node.module.rsplit(".", 1)[-1]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert not imported.intersection(denied)
    return "sibling imports preserve the acyclic ownership direction"


def _case(name: str, proof: Callable[[], str]) -> ScenarioResult:
    try:
        return ScenarioResult(name, True, proof())
    except Exception as error:
        return ScenarioResult(name, False, f"{type(error).__name__}: {error}")


def run_all() -> tuple[ScenarioResult, ...]:
    """Run each independent architecture assertion without short-circuiting."""

    proofs: tuple[tuple[str, Callable[[], str]], ...] = (
        ("strict-catalog", _catalog_case),
        ("phase-summary-coherence", _summary_case),
        ("finding-witness-uninstall", _witness_case),
        ("timeout-and-probe-boundaries", _timeout_and_probe_case),
        ("command-free-not-applicable", _not_applicable_case),
        ("minimum-aggregate-cover", _aggregate_case),
        ("shared-docker-namespace", _namespace_case),
        ("active-recovery-exclusion", _active_recovery_case),
        ("capture-failure-lossless", _capture_case),
        ("bounded-semantic-content", _content_case),
        ("whole-bundle-mutation", _coherent_mutation_case),
        ("full-integrated-run", _basic_run_case),
        ("invalid-raw-exit", _invalid_exit_case),
        ("report-failure-running", _report_failure_case),
        ("initial-running-failure", _initial_running_failure_case),
        ("assessment-to-commit-mutation", _commit_mutation_case),
        ("typed-recovery", _recovery_case),
        ("recovery-path-identity", _recovery_identity_case),
        ("recovery-adversarial", _recovery_adversarial_case),
        ("strict-document-codecs", _codec_case),
        ("retention-publication-order", _retention_publication_case),
        ("exclusive-terminal-and-publication", _exclusive_and_publication_case),
        ("interrupt-and-ordering", _interrupt_and_ordering_case),
        ("complete-plan-cardinality", _complete_plan_case),
        ("acyclic-imports", _dag_case),
    )
    return tuple(_case(name, proof) for name, proof in proofs)


def interactive_frames() -> tuple[DemoFrame, ...]:
    """Render complete state known at each actual controller transition."""

    with TemporaryDirectory(prefix="issue41-interactive-") as temporary:
        result = _controller(Path(temporary)).run(_request("interactive"))
    if not isinstance(result, DurableTerminal):
        failures = tuple(f"{item.stage}:{item.path}:{item.message}" for item in result.failures)
        return (DemoFrame(1, "run remained nonterminal", (("failures", failures),)),)
    record = result.assessment.run_record
    frames: list[DemoFrame] = []
    actions = (*result.trace, "CI classified from fresh assessment and publication fact")
    plan_number = next(
        index for index, item in enumerate(actions, 1) if "Validation Plan compiled" in item
    )
    commit_number = next(index for index, item in enumerate(actions, 1) if "committed last" in item)
    ci_number = len(actions)
    for number, action in enumerate(actions, 1):
        domain_lines = (
            (f"plan={result.outcome.plan.plan_id.value}",)
            if number >= plan_number
            else ("plan=not-yet-compiled",)
        )
        diagnostic_lines = (
            (f"outcome={record.outcome.value}", f"raw_exit={record.raw_exit}")
            if number >= commit_number
            else ("authority=RUNNING", "outcome=not-yet-published")
        )
        if number >= ci_number:
            diagnostic_lines = (
                *diagnostic_lines,
                f"ci={result.ci_decision.annotation.value}",
            )
        else:
            diagnostic_lines = (*diagnostic_lines, "ci=not-yet-classified")
        frames.append(
            DemoFrame(
                number,
                action,
                (
                    ("domain", domain_lines),
                    ("resources", (f"bundle={result.bundle.name}", action)),
                    ("diagnostics", diagnostic_lines),
                    ("chronology", actions[:number]),
                ),
            )
        )
    return tuple(frames)
