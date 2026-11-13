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
from tools.install_sandbox.contracts.effect_case import CaseKey
from tools.install_sandbox.host import coordinator
from tools.install_sandbox.host.result_reader import read_evidence

SEARCH = {"type": "command", "command": "graphify hook-guard search", "timeout": 10}


def _key(operation: str) -> CaseKey:
    if operation == "reinstall":
        return CaseKey("synthetic", "project", operation)
    return CaseKey("synthetic", "project", operation, "json-hooks", "PreToolUse-search")


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
    elif fault in {"personal-command-order", "merge-groups"}:
        ordered = next(entry for entry in groups if entry.get("sandbox_personal") == "ordered")
        if fault == "personal-command-order":
            ordered["hooks"].reverse()
        else:
            seeded = next(entry for entry in groups if entry.get("sandbox_personal") == "preserve")
            seeded["hooks"].extend(ordered["hooks"])
            groups.remove(ordered)
    elif fault == "read":
        read = next(
            hook
            for g in groups
            for hook in g["hooks"]
            if hook.get("command") == "graphify hook-guard read"
        )
        read["timeout"] = 99


def _seed_personal_backup(monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.install_sandbox.container.effect_environment import EffectEnvironment

    prepare = EffectEnvironment.prepare

    def prepare_with_personal_backup(environment: EffectEnvironment) -> None:
        prepare(environment)
        (environment.project / "personal.json.graphify-bak").write_bytes(
            b"Personal backup retained before installation\n"
        )

    monkeypatch.setattr(EffectEnvironment, "prepare", prepare_with_personal_backup)


def _deny_backup_read(backup: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    read_bytes = Path.read_bytes

    def read_observed_file(observed: Path) -> bytes:
        if observed == backup:
            raise PermissionError("Controlled unreadable backup")
        return read_bytes(observed)

    monkeypatch.setattr(Path, "read_bytes", read_observed_file)


def _file_fault(
    fault: str, path: Path, project: Path, backup_content: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    backup = path.with_name("config.json.graphify-bak")
    if fault == "backup":
        backup.write_bytes(backup_content)
    elif fault == "unreadable-backup":
        _deny_backup_read(backup, monkeypatch)
    elif fault == "backup-absent":
        backup.unlink()
    elif fault == "backup-directory":
        backup.unlink()
        backup.mkdir()
    elif fault == "other-backup":
        (project / "personal.json.graphify-bak").write_text("Changed personal backup")
    elif fault == "other-file":
        (project / "GUIDE.md").write_text("Altered unrelated document.\n")


def _selection(root: Path, case_name: str) -> list[str]:
    if case_name == "reinstall":
        return ["--case", case_name]
    request = root / "request.json"
    request.write_text(
        json.dumps(
            {
                "operation": case_name,
                "target": {
                    "participant": "synthetic:project",
                    "effect_id": "json-hooks",
                    "member": "PreToolUse-search",
                },
            }
        )
    )
    return ["--request", str(request)]


def conduct_hooks(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    separate: bool = False,
    fault: str | None = None,
    first: bool = False,
    case_name: str = "missing-json-hook",
) -> tuple[dict[str, Any], Path, int]:
    subject, spec, context = arrange(root)
    transport = ControlledTransport(root)
    execute = transport.installer.execute
    calls: dict[Path, int] = {}
    if fault == "other-backup":
        _seed_personal_backup(monkeypatch)

    def controlled(
        args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        path = project / ".synthetic/config.json"
        settings_before_install = path.read_bytes()
        result = execute(args, project, environment, timeout)
        calls[project] = calls.get(project, 0) + 1
        data = json.loads(path.read_text())
        if calls[project] == 2 and separate:
            _fault(data, "moved")
        if fault is not None and calls[project] == (1 if first else 2):
            _fault(data, fault)
            _file_fault(
                fault,
                path,
                project,
                path.read_bytes() if first else settings_before_install,
                monkeypatch,
            )
        path.write_text(json.dumps(data) + "\n")
        return result

    transport.installer.execute = controlled

    monkeypatch.setattr(coordinator, "ContainerHarness", Mock(return_value=transport))
    output = root / "published"
    exit_code = main(
        [
            *_selection(root, case_name),
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
    result = _selected_result(output, case_name)
    assert exit_code == (0 if result["status"] == "passed" else 1)
    proof = _replay_after_cleanup(
        root, subject, spec, context, transport, output, result, case_name
    )
    return result, proof, sum(calls.values())


def _selected_result(output: Path, case_name: str) -> dict[str, Any]:
    campaign = json.loads((output / "campaign.json").read_text())
    selected = next(case for case in campaign["cases"] if case["key"] == _key(case_name).to_data())
    assert selected["construction"] == "constructed"
    return selected["result"]["test"]


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
    proof = proof / "evidence/cases" / _key(case_name).storage_id
    replayed = read_evidence(proof)
    assert json.loads(json.dumps(asdict(replayed))) == result
    return proof


@pytest.mark.parametrize("separate", [False, True], ids=["mixed", "separate"])
def test_hook_repair_replays_exactly_after_host_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, separate: bool
) -> None:
    result, _, calls = conduct_hooks(
        tmp_path, monkeypatch, separate=separate, case_name="missing-json-hook"
    )
    assert result["status"] == "passed" and calls == 2


@pytest.mark.parametrize(
    "fault",
    [
        "absent",
        "matcher",
        "event",
        "content",
        "personal-group",
        "personal-attribute",
        "personal-order",
        "personal-command-order",
        "merge-groups",
        "read",
        "other-file",
    ],
)
def test_zero_exit_faults_fail_hook_repair_and_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    result, _, calls = conduct_hooks(
        tmp_path, monkeypatch, fault=fault, case_name="missing-json-hook"
    )
    assert result["status"] == "failed" and calls == 2
    second = result["steps"][1]["facts"]
    assert second["command"]["exit_code"] == 0
    assert second["verification"]["mismatches"]


def test_invalid_first_install_blocks_hook_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _, calls = conduct_hooks(
        tmp_path, monkeypatch, fault="absent", first=True, case_name="missing-json-hook"
    )
    assert result["status"] == "failed" and calls == 1
    assert result["steps"][1]["phase"] == "idle"
    assert result["steps"][1]["facts"]["command"] is None


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
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative: str,
    field: str,
    value: object,
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
        if (
            writer.output_directory.name == _key("missing-json-hook").storage_id
            and artifact.reference == reference
        ):
            raise OSError("Controlled hook preparation publication failure")
        return original(writer, artifact)

    monkeypatch.setattr(TestResultWriter, "retain", interrupted)
    result, _, calls = conduct_hooks(tmp_path, monkeypatch)
    assert result["status"] == "incomplete" and calls == 1
    assert result["steps"][1]["phase"] == "idle"
    assert result["steps"][1]["facts"]["command"] is None


def test_unobservable_hook_preparation_blocks_second_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.install_sandbox.container.effect_environment import EffectEnvironment
    from tools.install_sandbox.contracts.observation import FilesystemSnapshot

    original = EffectEnvironment.observe_intermediate

    def incomplete(environment: EffectEnvironment, phase: str) -> FilesystemSnapshot:
        snapshot = original(environment, phase)
        if _key("missing-json-hook").storage_id in environment.project.parts and phase == "after":
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
    result, _, calls = conduct_hooks(tmp_path, monkeypatch, case_name="missing-json-hook")
    assert result["status"] == "incomplete" and calls == 1
    assert result["steps"][1]["phase"] == "idle"
    assert result["steps"][1]["facts"]["command"] is None


@pytest.mark.parametrize("phase", ["before", "after"])
def test_hook_replay_rejects_changed_observed_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    _, proof, _ = conduct_hooks(tmp_path, monkeypatch)
    path = proof / "intermediate" / phase / "project/.synthetic/config.json"
    path.write_text('{"forged": true}\n')
    with pytest.raises(ValueError):
        read_evidence(proof)


@pytest.mark.parametrize("fault", ["no-removal", "extra-personal-removal"])
def test_observed_wrong_hook_mutation_blocks_second_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
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
        if environment.case.name != "missing-json-hook":
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
    result, proof, calls = conduct_hooks(tmp_path, monkeypatch, case_name="missing-json-hook")
    assert result["status"] == "failed" and calls == 1
    assert result["steps"][1]["phase"] == "idle"
    assert result["steps"][1]["facts"]["command"] is None
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
    assert result["steps"][1]["facts"]["command"] is None


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


@pytest.mark.parametrize(
    "case_name,first,status,calls",
    [
        ("missing-json-hook", False, "passed", 2),
        ("missing-json-hook", True, "failed", 1),
        ("reinstall", False, "failed", 2),
        ("reinstall", True, "failed", 1),
    ],
)
def test_only_repaired_missing_hook_allows_new_target_backup_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case_name: str,
    first: bool,
    status: str,
    calls: int,
) -> None:
    result, proof, observed_calls = conduct_hooks(
        tmp_path, monkeypatch, case_name=case_name, first=first, fault="backup"
    )
    assert result["status"] == status and observed_calls == calls
    if status == "passed":
        backup = proof / "steps/1/after/project/.synthetic/config.json.graphify-bak"
        prepared = proof / "intermediate/after/project/.synthetic/config.json"
        original_backup = proof / "steps/0/after/project/.synthetic/config.json.graphify-bak"
        assert backup.read_bytes() == prepared.read_bytes()
        assert backup.read_bytes() != original_backup.read_bytes()


@pytest.mark.parametrize("fault", ["backup-absent", "backup-directory", "other-backup"])
@pytest.mark.parametrize("first", [False, True])
def test_backup_shape_and_unrelated_backup_are_never_relaxed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    first: bool,
) -> None:
    result, _, calls = conduct_hooks(tmp_path, monkeypatch, fault=fault, first=first)
    assert result["status"] == "failed" and calls == (1 if first else 2)


@pytest.mark.parametrize("step_index", [0, 1])
def test_unreadable_target_backup_cannot_pass_or_replay_as_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    step_index: int,
) -> None:
    result, _, calls = conduct_hooks(
        tmp_path, monkeypatch, fault="unreadable-backup", first=step_index == 0
    )
    assert result["status"] == "incomplete" and calls == step_index + 1
    obstacles = result["steps"][step_index]["facts"]["verification"]["obstacles"]
    assert any(
        operation == "read_file" and path == ".synthetic/config.json.graphify-bak"
        for operation, _root, path, _reason in obstacles
    )


def test_hook_preparation_cannot_change_target_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.install_sandbox.container import intermediate_execution
    from tools.install_sandbox.container.effect_environment import EffectEnvironment
    from tools.install_sandbox.contracts.bound_mutation import BoundMutation
    from tools.install_sandbox.contracts.observation import FilesystemSnapshot

    apply = intermediate_execution.apply_mutation

    def mutate(
        operation: BoundMutation,
        environment: EffectEnvironment,
        case_bytes: bytes,
        first_after: FilesystemSnapshot,
        sources: FilesystemSnapshot,
    ) -> None:
        apply(operation, environment, case_bytes, first_after, sources)
        if environment.case.name == "missing-json-hook":
            (environment.project / ".synthetic/config.json.graphify-bak").write_text(
                "Unauthorized preparation backup generation\n"
            )

    monkeypatch.setattr(intermediate_execution, "apply_mutation", mutate)
    result, _, calls = conduct_hooks(tmp_path, monkeypatch)
    assert result["status"] == "failed" and calls == 1
    assert result["steps"][1]["phase"] == "idle"


@pytest.mark.parametrize("case_name", ["reinstall", "missing-json-hook"])
def test_installer_created_duplicate_is_a_failure_even_on_conformant_reinstall(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case_name: str,
) -> None:
    result, _, calls = conduct_hooks(tmp_path, monkeypatch, case_name=case_name, fault="duplicate")
    assert result["status"] == "failed" and calls == 2
    facts = result["steps"][1]["facts"]
    assert facts["command"]["exit_code"] == 0
    assert "hook_count" in {item["type"] for item in facts["verification"]["mismatches"]}


def test_first_install_can_move_target_without_losing_personal_group_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _, calls = conduct_hooks(tmp_path, monkeypatch, fault="moved", first=True)
    assert result["status"] == "passed" and calls == 2
