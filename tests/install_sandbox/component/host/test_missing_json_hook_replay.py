"""Exercise hook repair through the native host and replay its archived proof."""

import json
import shutil
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from tests.install_sandbox.component.host.native_support import ControlledTransport, arrange
from tools.install_sandbox.__main__ import main
from tools.install_sandbox.container.installer import InstallerCommandResult
from tools.install_sandbox.host import coordinator
from tools.install_sandbox.host.result_reader import read_evidence

SEARCH = {"type": "command", "command": "graphify hook-guard search", "timeout": 10}


def _fault(data: dict[str, Any], fault: str) -> None:
    groups = data["hooks"]["PreToolUse"]
    group = next(group for group in groups if SEARCH in group["hooks"])
    if fault == "duplicate":
        group["hooks"].append(dict(SEARCH))
    elif fault == "absent":
        group["hooks"].remove(SEARCH)
    elif fault == "matcher":
        group["matcher"] = "Write"
    elif fault == "event":
        group["hooks"].remove(SEARCH)
        data["hooks"].setdefault("PostToolUse", []).append(
            {"matcher": "Bash|Grep", "hooks": [SEARCH]}
        )
    elif fault == "content":
        group["hooks"][group["hooks"].index(SEARCH)] = {**SEARCH, "timeout": 99}
    elif fault == "moved":
        group["hooks"].remove(SEARCH)
        groups.append({"matcher": "Bash|Grep", "hooks": [SEARCH]})

    else:
        _personal_fault(data, fault)


def _personal_fault(data: dict[str, Any], fault: str) -> None:
    groups = data["hooks"]["PreToolUse"]
    if fault == "personal-group":
        groups[:] = [entry for entry in groups if entry.get("matcher") != "SandboxPersonalNeighbor"]
    elif fault == "personal-attribute":
        next(group for group in groups if "sandbox_personal" in group).pop("sandbox_personal")
    elif fault == "personal-order":
        groups.reverse()
    elif fault == "read":
        read = next(
            hook
            for g in groups
            for hook in g["hooks"]
            if hook.get("command") == "graphify hook-guard read"
        )
        read["timeout"] = 99


def conduct_hooks(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    separate: bool = False,
    fault: str | None = None,
    first: bool = False,
    case_name: str = "missing-json-hook",
    legacy_append: bool = False,
) -> tuple[dict[str, Any], Path, int]:
    subject, spec, context = arrange(root)
    transport = ControlledTransport(root)
    transport.installer.repair_hook_timeout = not legacy_append
    execute = transport.installer.execute
    calls: dict[Path, int] = {}

    def controlled(
        args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        result = execute(args, project, environment, timeout)
        if case_name not in project.parts:
            return result
        calls[project] = calls.get(project, 0) + 1
        path = project / ".synthetic/config.json"
        data = json.loads(path.read_text())
        if calls[project] == 2 and separate:
            _fault(data, "moved")
        if fault is not None and calls[project] == (1 if first else 2):
            _fault(data, fault)
            if fault == "backup":
                path.with_name("config.json.graphify-bak").write_text("Altered backup.\n")
            elif fault == "other-file":
                (project / "GUIDE.md").write_text("Altered unrelated document.\n")
        path.write_text(json.dumps(data) + "\n")
        return result

    transport.installer.execute = controlled

    monkeypatch.setattr(coordinator, "ContainerHarness", Mock(return_value=transport))
    output = root / "published"
    exit_code = main(
        [
            "--spec",
            str(spec),
            "--subject-context",
            str(context),
            "--repo",
            str(subject),
            "--output",
            str(output),
        ]
    )
    campaign = json.loads((output / "campaign.json").read_text())
    selected = next(case for case in campaign["cases"] if case["name"] == case_name)
    assert selected["construction"] == "constructed"
    result = selected["result"]["test"]
    assert exit_code == (0 if result["status"] == "passed" else 1)
    proof = _replay_after_cleanup(
        root, subject, spec, context, transport, output, result, case_name
    )
    return result, proof, sum(calls.values())


def _replay_after_cleanup(
    root: Path,
    subject: Path,
    spec: Path,
    context: Path,
    transport: ControlledTransport,
    output: Path,
    result: dict[str, Any],
    case_name: str,
) -> Path:
    shutil.rmtree(subject)
    spec.unlink()
    context.unlink()
    assert not transport.executable.exists()
    assert not (root / "environment").exists()
    proof = root / "restored"
    with zipfile.ZipFile(output / "evidence.zip") as archive:
        archive.extractall(proof)
    proof = proof / "evidence/cases" / case_name
    replayed = read_evidence(proof)
    decoded = asdict(replayed)
    decoded["preparation"] = replayed.preparation.to_data()
    decoded["steps"] = [step.to_data() for step in replayed.steps]
    assert decoded == result
    return proof


@pytest.mark.parametrize("case_name", ["missing-json-hook", "altered-json-hook"])
@pytest.mark.parametrize("separate", [False, True], ids=["mixed", "separate"])
def test_hook_repair_replays_exactly_after_host_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, separate: bool, case_name: str
) -> None:
    result, proof, calls = conduct_hooks(
        tmp_path, monkeypatch, separate=separate, case_name=case_name
    )
    assert result["status"] == "passed" and calls == 2
    if case_name == "altered-json-hook":
        prepared = json.loads(
            (proof / "intermediate/after/project/.synthetic/config.json").read_text()
        )
        targeted = [
            hook
            for group in prepared["hooks"]["PreToolUse"]
            for hook in group["hooks"]
            if hook.get("command") == SEARCH["command"]
        ]
        assert targeted == [{**SEARCH, "timeout": 11}]


@pytest.mark.parametrize("case_name", ["missing-json-hook", "altered-json-hook"])
@pytest.mark.parametrize(
    "fault",
    [
        "duplicate",
        "absent",
        "matcher",
        "event",
        "content",
        "personal-group",
        "personal-attribute",
        "personal-order",
        "read",
        "backup",
        "other-file",
    ],
)
def test_zero_exit_faults_fail_hook_repair_and_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str, case_name: str
) -> None:
    result, _, calls = conduct_hooks(tmp_path, monkeypatch, fault=fault, case_name=case_name)
    assert result["status"] == "failed" and calls == 2
    second = result["steps"][1]["facts"]
    assert second["command"]["exit_code"] == 0
    assert second["verification"]["mismatches"]


@pytest.mark.parametrize("case_name", ["missing-json-hook", "altered-json-hook"])
@pytest.mark.parametrize("fault", ["absent", "moved"])
def test_invalid_first_install_blocks_hook_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str, case_name: str
) -> None:
    result, _, calls = conduct_hooks(
        tmp_path, monkeypatch, fault=fault, first=True, case_name=case_name
    )
    assert result["status"] == "failed" and calls == 1
    assert result["steps"][1]["phase"] == "idle"


@pytest.mark.parametrize(
    "relative",
    [
        "intermediate/operation.json",
        "intermediate/performed.json",
        "intermediate/verification.json",
        "expectations/reinstall.json",
        "intermediate/before.json",
        "intermediate/after.json",
    ],
)
def test_hook_replay_requires_retained_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    _, proof, _ = conduct_hooks(tmp_path, monkeypatch)
    (proof / relative).unlink()
    with pytest.raises((ValueError, OSError)):
        read_evidence(proof)


@pytest.mark.parametrize(
    "relative,field,value",
    [
        ("intermediate/operation.json", "case_sha256", "0" * 64),
        ("intermediate/operation.json", "observation_ref", "steps/1/after.json"),
        ("intermediate/verification.json", "complete", False),
        ("expectations/reinstall.json", "allowed_changes", []),
        ("result.json", "status", "failed"),
    ],
)
def test_hook_replay_rejects_forged_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str, field: str, value: object
) -> None:
    _, proof, _ = conduct_hooks(tmp_path, monkeypatch)
    path = proof / relative
    payload = json.loads(path.read_text())
    payload[field] = value
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        read_evidence(proof)


@pytest.mark.parametrize(
    "reference",
    [
        "intermediate/operation.json",
        "intermediate/before.json",
        "intermediate/performed.json",
        "intermediate/after.json",
        "intermediate/verification.json",
    ],
)
def test_partial_hook_preparation_blocks_second_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reference: str
) -> None:
    from tools.install_sandbox.container.evidence_writer import TestResultWriter
    from tools.install_sandbox.contracts.results import ArtifactReceipt
    from tools.install_sandbox.rules.repair_actions import JsonArtifact, SnapshotArtifact

    original = TestResultWriter.retain

    def interrupted(
        writer: TestResultWriter, artifact: JsonArtifact | SnapshotArtifact
    ) -> ArtifactReceipt:
        if writer.output_directory.name == "missing-json-hook" and artifact.reference == reference:
            raise OSError("Controlled hook preparation publication failure")
        return original(writer, artifact)

    monkeypatch.setattr(TestResultWriter, "retain", interrupted)
    result, _, calls = conduct_hooks(tmp_path, monkeypatch)
    assert result["status"] == "incomplete" and calls == 1
    assert result["steps"][1]["phase"] == "idle"


@pytest.mark.parametrize("case_name", ["missing-json-hook", "altered-json-hook"])
def test_unobservable_hook_preparation_blocks_second_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case_name: str
) -> None:
    from tools.install_sandbox.container.effect_environment import EffectEnvironment
    from tools.install_sandbox.contracts.observation import FilesystemSnapshot

    original = EffectEnvironment.observe_intermediate

    def incomplete(environment: EffectEnvironment, phase: str) -> FilesystemSnapshot:
        snapshot = original(environment, phase)
        if case_name in environment.project.parts and phase == "after":
            snapshot.contents.pop(("project", ".synthetic/config.json"))
            snapshot.obstacles.append(
                {
                    "root": "project",
                    "path": ".synthetic/config.json",
                    "operation": "read_file",
                    "reason": "Controlled incomplete hook observation",
                }
            )
        return snapshot

    monkeypatch.setattr(EffectEnvironment, "observe_intermediate", incomplete)
    result, _, calls = conduct_hooks(tmp_path, monkeypatch, case_name=case_name)
    assert result["status"] == "incomplete" and calls == 1
    assert result["steps"][1]["phase"] == "idle"


@pytest.mark.parametrize("phase", ["before", "after"])
def test_hook_replay_rejects_changed_observed_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    _, proof, _ = conduct_hooks(tmp_path, monkeypatch)
    path = proof / "intermediate" / phase / "project/.synthetic/config.json"
    path.write_text('{"forged": true}\n')
    with pytest.raises(ValueError):
        read_evidence(proof)


@pytest.mark.parametrize("case_name", ["missing-json-hook", "altered-json-hook"])
@pytest.mark.parametrize("fault", ["no-removal", "extra-personal-removal"])
def test_observed_wrong_hook_mutation_blocks_second_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str, case_name: str
) -> None:
    from tools.install_sandbox.container import intermediate_execution
    from tools.install_sandbox.container.effect_environment import EffectEnvironment
    from tools.install_sandbox.contracts.bound_mutation import BoundMutation
    from tools.install_sandbox.contracts.observation import FilesystemSnapshot

    original = intermediate_execution.apply_mutation

    def mutate(
        operation: BoundMutation,
        environment: EffectEnvironment,
        case_bytes: bytes,
        first_after: FilesystemSnapshot,
        sources: FilesystemSnapshot,
    ) -> None:
        if environment.case.name != case_name:
            original(operation, environment, case_bytes, first_after, sources)
            return
        if fault == "no-removal":
            return
        original(operation, environment, case_bytes, first_after, sources)
        path = environment.project / ".synthetic/config.json"
        data = json.loads(path.read_text())
        mixed = next(group for group in data["hooks"]["PreToolUse"] if "sandbox_personal" in group)
        mixed["hooks"] = []
        path.write_text(json.dumps(data) + "\n")

    monkeypatch.setattr(intermediate_execution, "apply_mutation", mutate)
    result, proof, calls = conduct_hooks(tmp_path, monkeypatch, case_name=case_name)
    assert result["status"] == "failed" and calls == 1
    assert result["steps"][1]["phase"] == "idle"
    verification = json.loads((proof / "intermediate/verification.json").read_text())
    assert verification["complete"] is True
    assert verification["mismatches"]


def test_physical_hook_guard_rejects_unauthorized_bytes_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from tools.install_sandbox.container import intermediate_execution
    from tools.install_sandbox.container.effect_environment import EffectEnvironment
    from tools.install_sandbox.contracts.bound_mutation import BoundFileReplacement, BoundMutation
    from tools.install_sandbox.contracts.observation import FilesystemSnapshot

    original = intermediate_execution.apply_mutation
    rejected: list[bool] = []

    def mutate(
        operation: BoundMutation,
        environment: EffectEnvironment,
        case_bytes: bytes,
        first_after: FilesystemSnapshot,
        sources: FilesystemSnapshot,
    ) -> None:
        if environment.case.name != "missing-json-hook":
            original(operation, environment, case_bytes, first_after, sources)
            return
        assert isinstance(operation, BoundFileReplacement)
        path = environment.project / ".synthetic/config.json"
        before = path.read_bytes()
        with pytest.raises(ValueError, match="Replacement differs"):
            original(
                replace(operation, content=operation.content + b" "),
                environment,
                case_bytes,
                first_after,
                sources,
            )
        assert path.read_bytes() == before
        rejected.append(True)
        raise ValueError("Unauthorized replacement rejected without modifying settings")

    monkeypatch.setattr(intermediate_execution, "apply_mutation", mutate)
    result, _, calls = conduct_hooks(tmp_path, monkeypatch)
    assert rejected == [True]
    assert result["status"] == "incomplete" and calls == 1
    assert result["steps"][1]["phase"] == "idle"


def test_hook_repair_preserves_an_alias_outside_the_observed_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.install_sandbox.container import intermediate_execution
    from tools.install_sandbox.container.effect_environment import EffectEnvironment
    from tools.install_sandbox.contracts.bound_mutation import BoundFileReplacement, BoundMutation
    from tools.install_sandbox.contracts.observation import FilesystemSnapshot

    apply = intermediate_execution.apply_mutation
    alias = tmp_path / "external-settings.json"

    def mutate(
        operation: BoundMutation,
        environment: EffectEnvironment,
        case_bytes: bytes,
        first_after: FilesystemSnapshot,
        sources: FilesystemSnapshot,
    ) -> None:
        if environment.case.name == "missing-json-hook" and isinstance(
            operation, BoundFileReplacement
        ):
            settings = environment.project / operation.destination.path
            alias.hardlink_to(settings)
            original = alias.read_bytes()
            apply(operation, environment, case_bytes, first_after, sources)
            assert alias.read_bytes() == original
            assert not alias.samefile(settings)
        else:
            apply(operation, environment, case_bytes, first_after, sources)

    monkeypatch.setattr(intermediate_execution, "apply_mutation", mutate)
    result, _, calls = conduct_hooks(tmp_path, monkeypatch)
    assert result["status"] == "passed" and calls == 2
    assert alias.is_file()


def test_legacy_append_keeps_both_timeouts_despite_zero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, proof, calls = conduct_hooks(
        tmp_path, monkeypatch, case_name="altered-json-hook", legacy_append=True
    )
    assert result["status"] == "failed" and calls == 2
    assert result["steps"][1]["facts"]["command"]["exit_code"] == 0
    settings = json.loads((proof / "steps/1/after/project/.synthetic/config.json").read_text())
    timeouts = [
        hook["timeout"]
        for group in settings["hooks"]["PreToolUse"]
        for hook in group["hooks"]
        if hook.get("command") == SEARCH["command"]
    ]
    assert timeouts == [11, 10]


def test_simulator_repairs_only_its_literal_timeout_variant(tmp_path: Path) -> None:
    from tests.install_sandbox.component.host.native_support import LiteralInstaller

    settings = tmp_path / ".synthetic/config.json"
    settings.parent.mkdir()
    personal = [
        {**SEARCH, "timeout": 11, "personal": True},
        {**SEARCH, "timeout": 12},
        {**SEARCH, "timeout": 11.0},
        {**SEARCH, "timeout": 10.0},
        {"type": "command", "command": "personal check", "timeout": 11},
    ]
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {"matcher": "Bash|Grep", "hooks": [{**SEARCH, "timeout": 11}, *personal]}
                    ]
                }
            }
        )
    )
    original = settings.read_bytes()
    installer = LiteralInstaller(skill=False, markdown=False)
    installer.execute(["install"], tmp_path, {"HOME": str(tmp_path)}, 60)
    data = json.loads(settings.read_text())
    assert data["hooks"]["PreToolUse"][0]["hooks"] == [*personal, SEARCH]
    assert settings.with_name("config.json.graphify-bak").read_bytes() == original
