"""Deterministic architecture demonstrations for issue #41."""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Callable
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from .bundle import (
    BundleCoherenceError,
    BundleFaults,
    BundleStore,
    IncompleteTerminalIntent,
    PersistenceRejected,
    RecoveryClaim,
    RecoveryRejected,
    TerminalCommitRejected,
    TerminalCommitted,
)
from .coordinator import (
    DurableNonterminal,
    DurableTerminal,
    RunController,
    RunRequest,
)
from .diagnostics import CompletedAssessment
from .documents import RunningRunRecord, RunOutcome, decode_run_record, encode_document
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
    CatalogReady,
    CommandFact,
    CommandRequest,
    CompleteValidation,
    ContainsTextRule,
    ExactTextRule,
    Exited,
    HarnessPolicy,
    LifecycleScenario,
    LifecycleValidation,
    ObservationFact,
    ObservationRequest,
    ObservedAbsent,
    ObservedContent,
    PhaseFinding,
    PhaseKind,
    PhasePassed,
    PhaseScenarioRecord,
    PlanReady,
    RawCatalogDocument,
    RawFact,
    RunId,
    ScenarioIncomplete,
    Scope,
    StableInstallationEstablished,
    StreamCaptureFailure,
)
from .resources import (
    ContainerClaimed,
    ContainerClaimRejected,
    DockerNamespaceRegistry,
    LeaseBackedFulfilment,
    ResourceFaults,
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
    "from pathlib import Path; import sys; "
    "target=sys.argv[1]; scope=sys.argv[3]; "
    "Path(f'{target}-{scope}.txt').write_text(f'{target}:{scope}', encoding='utf-8')"
)
_UNINSTALL_SCRIPT = (
    "from pathlib import Path; import sys; "
    "target=sys.argv[1]; scope=sys.argv[3]; "
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


def _policy() -> HarnessPolicy:
    return HarnessPolicy(
        install_argv=("python3.12", "-c", _INSTALL_SCRIPT),
        uninstall_argv=("python3.12", "-c", _UNINSTALL_SCRIPT),
        aggregate_uninstall_argv=("python3.12", "-c", _AGGREGATE_SCRIPT),
        purge_argv=("python3.12", "-c", _PURGE_SCRIPT),
    )


def _scope(name: str, scope: str, *, supported: bool = True) -> dict[str, object]:
    if not supported:
        return {
            "supported": False,
            "reason": "fictional runtime does not expose this scope",
            "limitations": ["fictional unsupported scope"],
        }
    return {
        "supported": True,
        "effects": [
            {
                "kind": "owned_file",
                "location": f"{name}-{scope}.txt",
                "expected_text": f"{name}:{scope}",
            }
        ],
    }


def _catalog_documents() -> tuple[RawCatalogDocument, ...]:
    return (
        {
            "source": "alpha.yaml",
            "name": "alpha",
            "scopes": {
                "user": _scope("alpha", "user"),
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


def _catalog() -> CatalogReady:
    compiled = compile_catalog(_catalog_documents())
    if not isinstance(compiled, CatalogReady):
        raise AssertionError(f"fixture catalog rejected: {compiled!r}")
    return compiled


def _lifecycle_plan() -> PlanReady:
    compiled = build_validation_plan(
        _catalog().catalog,
        LifecycleValidation("alpha", Scope.USER),
        _policy(),
    )
    if not isinstance(compiled, PlanReady):
        raise AssertionError(f"fixture plan rejected: {compiled!r}")
    return compiled


def _captured(content: bytes = b"") -> CapturedStream:
    return CapturedStream(content, hashlib.sha256(content).hexdigest(), len(content))


def _scripted_fulfil(
    request: ActionRequest,
    *,
    repair_finding: bool = False,
    invalid_exit: int | None = None,
) -> RawFact:
    if isinstance(request, CommandRequest):
        code = invalid_exit if invalid_exit is not None else 0
        return CommandFact(
            request.action_id,
            request.argv,
            request.cwd,
            request.action_id.ordinal,
            request.action_id.ordinal + 1,
            Exited(code),
            True,
            _captured(),
            _captured(),
            (f"command:{request.phase}",),
        )
    items = []
    for rule in request.specification.rules:
        if isinstance(rule, AbsentRule):
            items.append(ObservedAbsent(rule.key, rule.location))
            continue
        expected = rule.expected_text if isinstance(rule, ExactTextRule) else rule.required_text
        content = expected.encode()
        if repair_finding and request.phase == PhaseKind.REPAIR.value:
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
    return ObservationFact(request.action_id, tuple(items), (f"observe:{request.phase}",))


def _running_bytes(run_id: str) -> bytes:
    return encode_document(
        RunningRunRecord(run_id, "alpha:user", "sha256:fictional", "subject-1", "allocated")
    )


def _allocate_resources(
    base: Path,
    run_id: str,
    registry: DockerNamespaceRegistry,
    *,
    faults: ResourceFaults | None = None,
    bundle_faults: BundleFaults | None = None,
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
        registry,
        faults=ResourceFaults() if faults is None else faults,
        bundle_faults=BundleFaults() if bundle_faults is None else bundle_faults,
    )


def _request(run_id: str, *, raw_exit: int | None = None, signal: str | None = None) -> RunRequest:
    return RunRequest(
        RunId(run_id),
        "alpha:user",
        "sha256:fictional",
        "subject-1",
        _catalog_documents(),
        LifecycleValidation("alpha", Scope.USER),
        _policy(),
        raw_exit,
        signal,
    )


def _run_controller(
    base: Path,
    request: RunRequest,
    *,
    resource_faults: ResourceFaults | None = None,
    bundle_faults: BundleFaults | None = None,
) -> DurableTerminal | DurableNonterminal:
    sandbox = base / "sandbox"
    sandbox.mkdir()
    controller = RunController(base / "out", sandbox, DockerNamespaceRegistry("demo"))
    result = controller.run(
        request,
        resource_faults=ResourceFaults() if resource_faults is None else resource_faults,
        bundle_faults=BundleFaults() if bundle_faults is None else bundle_faults,
    )
    if not isinstance(result, (DurableTerminal, DurableNonterminal)):
        raise AssertionError(f"unexpected controller result: {result!r}")
    return result


def _catalog_case() -> str:
    compiled = _catalog()
    malformed = dict(_catalog_documents()[0])
    malformed["unknown"] = True
    rejected = compile_catalog((malformed,))
    assert not isinstance(rejected, CatalogReady)
    try:
        compiled.catalog.targets = ()  # type: ignore[misc]
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("frozen catalog accepted mutation")
    return "unknown keys and post-compilation mutation rejected"


def _summary_case() -> str:
    plan = _lifecycle_plan().plan
    scenario = plan.scenarios[0]
    assert isinstance(scenario, LifecycleScenario)
    summary = roll_up_phases(scenario, ())
    assert isinstance(summary, ScenarioIncomplete)
    return "empty/contradictory phase detail cannot summarize as passed"


def _witness_case() -> str:
    plan = _lifecycle_plan().plan
    outcome = run_validation(
        plan,
        RunId("witness"),
        lambda request: _scripted_fulfil(request, repair_finding=True),
    )
    record = outcome.scenario_records[0]
    assert isinstance(record, PhaseScenarioRecord)
    phases = record.phases
    repair = next(item for item in phases if item.phase is PhaseKind.REPAIR)
    assert isinstance(repair, PhaseFinding)
    assert isinstance(repair.finding.witness, StableInstallationEstablished)
    assert isinstance(phases[-1], PhasePassed)
    assert phases[-1].phase is PhaseKind.TARGET_UNINSTALL
    return "repair finding retained witness and safe uninstall continued"


def _aggregate_case() -> str:
    duplicate_surface = (
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
    expected = independent_aggregate_cover_oracle(compiled.catalog, Scope.USER)
    planned = build_validation_plan(compiled.catalog, AggregateValidation(Scope.USER), _policy())
    assert isinstance(planned, PlanReady)
    scenario = planned.plan.scenarios[0]
    assert isinstance(scenario, AggregateScenario)
    selected = tuple(item.target for item in scenario.preparations)
    assert selected == expected == ("x",)
    return "minimum cover matched independent oracle with lexical tie-break"


def _namespace_case() -> str:
    with TemporaryDirectory(prefix="issue41-namespace-") as temporary:
        base = Path(temporary)
        registry = DockerNamespaceRegistry("shared-daemon")
        first = _allocate_resources(base / "first", "owner-a", registry)
        second = _allocate_resources(base / "second", "owner-b", registry)
        try:
            assert isinstance(first.reserve_container("exact-name"), ContainerClaimed)
            assert isinstance(second.reserve_container("exact-name"), ContainerClaimRejected)
        finally:
            first.close()
            second.close()
    return "two adapters shared one daemon namespace and collision was mutation-free"


def _active_recovery_case() -> str:
    with TemporaryDirectory(prefix="issue41-active-") as temporary:
        resource = _allocate_resources(
            Path(temporary), "active-owner", DockerNamespaceRegistry("active")
        )
        try:
            assert isinstance(nominate_recovery(resource.snapshot().bundle_path), RecoveryRejected)
        finally:
            resource.close()
    return "active ownership and recovery ownership were mutually exclusive"


def _recovery_identity_case() -> str:
    with TemporaryDirectory(prefix="issue41-recovery-") as temporary:
        resource = _allocate_resources(
            Path(temporary), "abandoned", DockerNamespaceRegistry("recovery")
        )
        proof = resource.quiesce_and_seal()
        resource._invalidate_owner_for_recovery_demo(proof)
        bundle = resource.snapshot().bundle_path
        claim = nominate_recovery(bundle)
        assert isinstance(claim, RecoveryClaim)
        moved = bundle.with_name("moved")
        bundle.rename(moved)
        result = claim.commit_incomplete(IncompleteTerminalIntent(b"report", b"terminal"))
        assert isinstance(result, TerminalCommitRejected)
    return "rename after claim invalidated descriptor/path recovery authority"


def _capture_case() -> str:
    with TemporaryDirectory(prefix="issue41-capture-") as temporary:
        resource = _allocate_resources(
            Path(temporary),
            "capture",
            DockerNamespaceRegistry("capture"),
            faults=ResourceFaults(fail_stream="stdout", fail_after_bytes=2),
        )
        try:
            action = _lifecycle_plan().plan.plan_id
            request = CommandRequest(
                ActionId(RunId("capture"), action, 0),
                "capture",
                "command",
                ("python3.12", "-c", "print('captured')"),
                ".",
            )
            fact = resource.fulfil(request)
            assert isinstance(fact, CommandFact)
            assert isinstance(fact.termination, Exited) and fact.termination.code == 0
            assert fact.reaped and isinstance(fact.stdout, StreamCaptureFailure)
            assert fact.stdout.partial_content == b"ca"
        finally:
            resource.close()
    return "capture failure preserved raw exit, reap, and partial stream evidence"


def _lossless_case() -> str:
    plan = _lifecycle_plan().plan
    outcome = run_validation(plan, RunId("lossless"), _scripted_fulfil)
    commands = tuple(item for item in outcome.raw_facts if isinstance(item, CommandFact))
    assert commands
    for fact in commands:
        assert fact.argv and fact.cwd == "." and fact.finished_ns >= fact.started_ns
        assert fact.chronology and isinstance(fact.stdout, CapturedStream)
    return "every command fact retained invocation, timing, termination, reap, streams, chronology"


def _content_case() -> str:
    with TemporaryDirectory(prefix="issue41-content-") as temporary:
        base = Path(temporary)
        resource = _allocate_resources(base, "content", DockerNamespaceRegistry("content"))
        sandbox = base / "sandbox-content"
        (sandbox / "wanted.txt").write_text("wanted", encoding="utf-8")
        (sandbox / "secret.txt").write_text("secret", encoding="utf-8")
        plan_id = _lifecycle_plan().plan.plan_id
        from .model import ObservationSpecification

        request = ObservationRequest(
            ActionId(RunId("content"), plan_id, 0),
            "content",
            "observe",
            ObservationSpecification((ContainsTextRule("wanted", "wanted.txt", "want"),)),
        )
        try:
            fact = resource.fulfil(request)
            assert isinstance(fact, ObservationFact)
            assert len(fact.items) == 1
            assert isinstance(fact.items[0], ObservedContent)
            assert fact.items[0].content == b"wanted"
            assert b"secret" not in repr(fact).encode()
        finally:
            resource.close()
    return "only explicitly requested bounded semantic content crossed the seam"


def _mutation_case() -> str:
    with TemporaryDirectory(prefix="issue41-mutation-") as temporary:
        resource = _allocate_resources(
            Path(temporary),
            "mutation",
            DockerNamespaceRegistry("mutation"),
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
    return "whole-bundle mutation during enumeration failed closed"


def _invalid_exit_case() -> str:
    with TemporaryDirectory(prefix="issue41-exit-") as temporary:
        result = _run_controller(Path(temporary), _request("invalid-exit", raw_exit=999))
        assert isinstance(result, DurableTerminal)
        record = result.assessment.run_record
        assert record.outcome is RunOutcome.INCOMPLETE
        assert record.raw_exit == 2 and record.invalid_raw_exit == 999
    return "authoritative assessment rejected 999 while retaining it as invalid evidence"


def _terminal_store() -> tuple[TemporaryDirectory[str], BundleStore]:
    temporary = TemporaryDirectory(prefix="issue41-terminal-")
    base = Path(temporary.name)
    store = BundleStore.allocate(base, "bundle", "owner", _running_bytes("owner"))
    store.store_evidence_once("runner.log", b"host log")
    store.seal_evidence()
    return temporary, store


def _report_order_case() -> str:
    temporary, store = _terminal_store()
    try:
        before = store.read_coherent()
        assert isinstance(store.commit_terminal(before, b"terminal"), TerminalCommitRejected)
        assert not isinstance(store.persist_report(b"report"), PersistenceRejected)
        after = store.read_coherent()
        assert isinstance(store.commit_terminal(after, b"terminal"), TerminalCommitted)
    finally:
        store.close()
        temporary.cleanup()
    return "terminal publication was impossible until report persistence"


def _report_failure_case() -> str:
    with TemporaryDirectory(prefix="issue41-report-failure-") as temporary:
        result = _run_controller(
            Path(temporary),
            _request("report-failure"),
            bundle_faults=BundleFaults(fail_writes=frozenset({"report.md"})),
        )
        assert isinstance(result, DurableNonterminal)
        decoded = decode_run_record((result.bundle / "run.json").read_bytes())
        assert isinstance(decoded, RunningRunRecord)
    return "report failure left the durable Run Record running"


def _exclusive_terminal_case() -> str:
    temporary, store = _terminal_store()
    try:
        store.persist_report(b"report")
        view = store.read_coherent()
        first = store.commit_terminal(view, b"terminal")
        second = store.commit_terminal(view, b"other")
        assert isinstance(first, TerminalCommitted)
        assert isinstance(second, TerminalCommitRejected)
    finally:
        store.close()
        temporary.cleanup()
    return "concurrent-equivalent terminal attempts admitted exactly one winner"


def _reopen_case() -> str:
    with TemporaryDirectory(prefix="issue41-reopen-") as temporary:
        result = _run_controller(Path(temporary), _request("reopen"))
        assert isinstance(result, DurableTerminal)
        assert isinstance(result.assessment, CompletedAssessment)
        joined = " | ".join(result.trace)
        assert joined.index("terminal Run Record") < joined.index("fresh reopen")
        assert joined.index("fresh reopen") < joined.index("CI classification")
    return "fresh reopen/reassessment preceded publication-aware CI classification"


def _authority_case() -> str:
    root = Path(__file__).parent
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in root.glob("*.py")
        if path.name != "scenarios.py"
    )
    assert "retain" + "(event" not in source and "event_journal" not in source
    diagnostic_source = (root / "diagnostics.py").read_text(encoding="utf-8")
    assert "classify from this text" in diagnostic_source
    return "no retained callback, event journal, or report classification authority exists"


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
    return "static sibling imports matched the proposed acyclic dependency direction"


def _interrupt_case() -> str:
    with TemporaryDirectory(prefix="issue41-interrupt-") as temporary:
        result = _run_controller(
            Path(temporary),
            _request("interrupt", raw_exit=143, signal="SIGTERM"),
            resource_faults=ResourceFaults(fail_stream="stdout"),
        )
        assert isinstance(result, DurableTerminal)
        record = result.assessment.run_record
        assert record.outcome is RunOutcome.INCOMPLETE
        assert record.raw_exit == 143 and record.interrupt_signal == "SIGTERM"
    return "later incompleteness dominated while preserving SIGTERM and raw 143"


def _ordering_case() -> str:
    with TemporaryDirectory(prefix="issue41-ordering-") as temporary:
        result = _run_controller(Path(temporary), _request("ordering"))
        assert isinstance(result, DurableTerminal)
        manifest = result.assessment.manifest
        assert manifest is not None
        assert manifest.operational_chronology
        assert manifest.presentation_order
        assert manifest.operational_chronology != manifest.presentation_order
    return "operational chronology and canonical presentation order both survived"


def _complete_plan_case() -> str:
    planned = build_validation_plan(
        _catalog().catalog,
        CompleteValidation(("alpha", "beta"), (Scope.USER, Scope.PROJECT)),
        _policy(),
    )
    assert isinstance(planned, PlanReady)
    outcome = run_validation(planned.plan, RunId("complete"), _scripted_fulfil)
    assert len(outcome.scenario_records) == len(planned.plan.projection.scenarios)
    assert len(outcome.chronology) == len(set(outcome.chronology))
    return f"complete plan returned {len(outcome.scenario_records)} ordered records and one purge"


def _case(name: str, proof: Callable[[], str]) -> ScenarioResult:
    try:
        return ScenarioResult(name, True, proof())
    except Exception as error:  # outer demo boundary intentionally reports every case
        return ScenarioResult(name, False, f"{type(error).__name__}: {error}")


def run_all() -> tuple[ScenarioResult, ...]:
    """Run every independent architecture assertion without short-circuiting."""

    proofs = (
        ("strict-catalog", _catalog_case),
        ("phase-summary-coherence", _summary_case),
        ("finding-witness-uninstall", _witness_case),
        ("minimum-aggregate-cover", _aggregate_case),
        ("shared-docker-namespace", _namespace_case),
        ("active-recovery-exclusion", _active_recovery_case),
        ("recovery-path-identity", _recovery_identity_case),
        ("capture-failure-lossless", _capture_case),
        ("raw-command-round-trip", _lossless_case),
        ("bounded-semantic-content", _content_case),
        ("whole-bundle-mutation", _mutation_case),
        ("invalid-raw-exit", _invalid_exit_case),
        ("report-before-terminal", _report_order_case),
        ("report-failure-running", _report_failure_case),
        ("exclusive-terminal", _exclusive_terminal_case),
        ("fresh-reopen-before-ci", _reopen_case),
        ("no-third-authority", _authority_case),
        ("acyclic-imports", _dag_case),
        ("interrupt-facts-survive", _interrupt_case),
        ("chronology-vs-presentation", _ordering_case),
        ("complete-plan-cardinality", _complete_plan_case),
    )
    return tuple(_case(name, proof) for name, proof in proofs)


def interactive_frames() -> tuple[DemoFrame, ...]:
    """Return complete derived views after each action in one real run."""

    with TemporaryDirectory(prefix="issue41-interactive-") as temporary:
        result = _run_controller(Path(temporary), _request("interactive"))
    if not isinstance(result, DurableTerminal):
        return (
            DemoFrame(
                1,
                "run remained nonterminal",
                (("failure", tuple(result.failures)),),
            ),
        )
    record = result.assessment.run_record
    frames = []
    for number, action in enumerate(result.trace, 1):
        frames.append(
            DemoFrame(
                number,
                action,
                (
                    ("domain", (f"plan={result.outcome.plan.plan_id.value}",)),
                    ("resources", (f"bundle={result.bundle.name}", action)),
                    (
                        "diagnostics",
                        (
                            f"outcome={record.outcome.value}",
                            f"raw_exit={record.raw_exit}",
                            f"ci={result.ci_decision.annotation.value}",
                        ),
                    ),
                    (
                        "authorities",
                        (
                            "Validation Plan + detailed domain results",
                            "resource facts + coherent bundle revision",
                            "Run Record + Diagnostic Manifest; report is derived",
                        ),
                    ),
                    ("chronology", result.trace[:number]),
                ),
            )
        )
    return tuple(frames)
