"""Retained native evidence remains self-contained and rejects forged verdicts."""

import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import cast

import pytest

from tests.install_sandbox.component.container.effect_case_support import EffectsRun
from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.container.effect_verifier import EffectVerifier
from tools.install_sandbox.container.installer import InstallerCommandResult, InstallerDriver
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.effect_case import (
    EffectInstallCase,
    EffectRules,
    SubjectContext,
    build_reinstall_case,
)
from tools.install_sandbox.contracts.effects import (
    Destination,
    EffectSpec,
    JsonHooksEffect,
    MarkdownSectionEffect,
)
from tools.install_sandbox.contracts.spec import HookExpectation
from tools.install_sandbox.host.evidence_reader import retained_snapshot
from tools.install_sandbox.host.result_reader import read_result


def _run(tmp_path: Path) -> tuple[Path, Path]:
    subject = tmp_path / "subject"
    subject.mkdir()
    (subject / "section.md").write_text("## graphify\n\nControlled guidance.\n")
    case = build_reinstall_case(
        EffectSpec((MarkdownSectionEffect("section.md", Destination("project", "AGENTS.md")),)),
        SubjectContext(
            "controlled-only",
            ("install", "--project"),
            "METADATA",
            EffectRules(10, "persistent", ".graphify-bak", ".bak", False),
        ),
    )
    case_file = tmp_path / "case.json"
    case.write(case_file)

    def execute(
        args: list[str], cwd: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        _ = environment, timeout
        (cwd / "AGENTS.md").write_text(
            "# My project\n\n## Language\nRespond in English.\n\n"
            "## graphify\n\nControlled guidance.\n"
        )
        return InstallerCommandResult(args, str(cwd), "completed", 0, None)

    output = tmp_path / "output"
    result = InstallTestRunner(InstallerDriver(execute)).run_case(
        reference_sources=subject,
        prepared_executable=tmp_path / "prepared",
        case_file=case_file,
        work_directory=tmp_path / "work",
        output_directory=output,
    )
    assert result.status == "passed"
    shutil.rmtree(subject)
    shutil.rmtree(tmp_path / "work")
    return output, case_file


def test_markdown_only_reads_after_subject_and_work_cleanup(tmp_path: Path) -> None:
    output, case_file = _run(tmp_path)
    case = EffectInstallCase.from_json(case_file.read_text())
    assert read_result(output, case).status == "passed"


@pytest.mark.parametrize("artifact", ["case.json", "expected/section.md", "steps/1/after.json"])
def test_missing_native_evidence_is_rejected(tmp_path: Path, artifact: str) -> None:
    output, case_file = _run(tmp_path)
    case = EffectInstallCase.from_json(case_file.read_text())
    (output / artifact).unlink()
    with pytest.raises((OSError, ValueError)):
        read_result(output, case)


def test_forged_success_recomputed_from_after_bytes(tmp_path: Path) -> None:
    output, case_file = _run(tmp_path)
    case = EffectInstallCase.from_json(case_file.read_text())
    (output / "steps/1/after/project/AGENTS.md").write_text("## graphify\nWrong contents.\n")
    with pytest.raises(ValueError, match="verification contradicts"):
        read_result(output, case)


def test_tampered_subject_context_is_rejected(tmp_path: Path) -> None:
    output, case_file = _run(tmp_path)
    case = EffectInstallCase.from_json(case_file.read_text())
    document = cast(dict[str, object], json.loads((output / "case.json").read_text()))
    subject = cast(dict[str, object], document["subject"])
    subject["identity"] = "different-subject"
    (output / "case.json").write_text(json.dumps(document))
    with pytest.raises(ValueError, match="Retained effects case"):
        read_result(output, case)


def test_json_hooks_only_runs_and_replays_empty_source_inventory(tmp_path: Path) -> None:
    subject = tmp_path / "subject"
    subject.mkdir()
    case = build_reinstall_case(
        EffectSpec(
            (
                JsonHooksEffect(
                    Destination("project", "settings.json"),
                    (
                        HookExpectation(
                            "controlled",
                            "SessionStart",
                            "startup",
                            {
                                "type": "command",
                                "command": "echo controlled",
                                "timeout": 10,
                            },
                        ),
                    ),
                ),
            )
        ),
        SubjectContext(
            "json-only",
            ("install",),
            "METADATA",
            EffectRules(10, "persistent", ".graphify-bak", ".bak", False),
        ),
    )
    case_file = tmp_path / "case.json"
    case.write(case_file)

    def execute(
        args: list[str], cwd: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        _ = environment, timeout
        settings = cwd / "settings.json"
        backup = cwd / "settings.json.graphify-bak"
        if not backup.exists():
            backup.write_bytes(settings.read_bytes())
        document = cast(dict[str, object], json.loads(backup.read_text()))
        hooks = cast(dict[str, object], document["hooks"])
        hooks["SessionStart"] = [
            {
                "matcher": "startup",
                "hooks": [
                    {
                        "type": "command",
                        "command": "echo controlled",
                        "timeout": 10,
                    }
                ],
            }
        ]
        settings.write_text(json.dumps(document))
        return InstallerCommandResult(args, str(cwd), "completed", 0, None)

    output = tmp_path / "output"
    result = InstallTestRunner(InstallerDriver(execute)).run_case(
        reference_sources=subject,
        prepared_executable=tmp_path / "controlled",
        case_file=case_file,
        work_directory=tmp_path / "work",
        output_directory=output,
    )
    assert result.status == "passed", result
    assert json.loads((output / "expected.json").read_text()) == {"entries": [], "obstacles": []}
    shutil.rmtree(subject)
    shutil.rmtree(tmp_path / "work")
    assert read_result(output, case) == result


def test_failed_initial_verification_requires_retained_observations(tmp_path: Path) -> None:
    output, case_file = _run(tmp_path)
    case = EffectInstallCase.from_json(case_file.read_text())
    # Simulate a retained failed initial verdict by changing the expected source kind.
    expected = cast(dict[str, object], json.loads((output / "expected.json").read_text()))
    expected["entries"] = []
    (output / "expected.json").write_text(json.dumps(expected))
    sources = retained_snapshot(output, "expected.json")
    before = retained_snapshot(output, "steps/0/before.json")
    verdict = EffectVerifier().verify_initial(case, sources, before)
    (output / "initial-verification.json").write_text(json.dumps(asdict(verdict)))
    document = cast(dict[str, object], json.loads((output / "result.json").read_text()))
    preparation = cast(dict[str, object], document["preparation"])
    preparation["ready"] = False
    preparation["reason"] = "Initial verification failed: " + json.dumps(asdict(verdict))
    document["status"] = "not_run"
    document["steps"] = [
        {
            "operation": "install",
            "skip_reason": "Initial verification failed",
            "command": None,
            "verification": None,
            "observations": None,
        }
    ] * 2
    (output / "result.json").write_text(json.dumps(document))
    assert read_result(output, case).status == "not_run"
    (output / "steps/0/before.json").unlink()
    with pytest.raises(OSError):
        read_result(output, case)


def _observation_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> EffectsRun:
    local = EffectsRun(tmp_path)

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("Controlled observation failure")

    monkeypatch.setattr(EffectEnvironment, "observe", fail)
    assert local.run().status == "not_run"
    assert local.calls == []
    return local


@pytest.mark.parametrize("artifact", ["expected.json", "expected/skill.md", "journal.log"])
def test_observation_failure_requires_retained_sources_and_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifact: str
) -> None:
    local = _observation_failure(tmp_path, monkeypatch)
    (local.output / artifact).unlink()
    with pytest.raises(OSError):
        local.reread_after_cleanup()


def test_observation_failure_rejects_altered_retained_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = _observation_failure(tmp_path, monkeypatch)
    (local.output / "expected/skill.md").write_text("Altered skill\n")
    with pytest.raises(ValueError, match="snapshot digest"):
        local.reread_after_cleanup()


def test_observation_failure_rejects_missing_source_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = _observation_failure(tmp_path, monkeypatch)
    (local.output / "expected.json").write_text('{"entries": [], "obstacles": []}')
    with pytest.raises(ValueError, match="Missing retained effects source"):
        local.reread_after_cleanup()


def test_observation_failure_preserves_source_obstacles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = EffectsRun(tmp_path)
    (tmp_path / "subject/skill.md").unlink()

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("Controlled observation failure")

    monkeypatch.setattr(EffectEnvironment, "observe", fail)
    result = local.run()
    assert result.status == "not_run" and local.calls == []
    expected = retained_snapshot(local.output, "expected.json")
    assert any(obstacle["path"] == "skill.md" for obstacle in expected.obstacles)
    assert local.reread_after_cleanup() == result


@pytest.mark.parametrize("source", ["skill.md", "skills/claude/references"])
def test_observation_failure_preserves_wrong_source_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    local = EffectsRun(tmp_path)
    path = tmp_path / "subject" / source
    if path.is_dir():
        shutil.rmtree(path)
        path.write_text("Expected directory is a file\n")
    else:
        path.unlink()
        path.mkdir()

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("Controlled observation failure")

    monkeypatch.setattr(EffectEnvironment, "observe", fail)
    result = local.run()
    assert result.status == "not_run" and local.calls == []
    assert local.reread_after_cleanup() == result


@pytest.mark.parametrize("stage", ["started", "sources_retained"])
def test_completed_initial_verification_cannot_be_downgraded(tmp_path: Path, stage: str) -> None:
    local = EffectsRun(tmp_path)
    (tmp_path / "subject/skill.md").unlink()
    assert local.run().status == "not_run"
    document = json.loads((local.output / "result.json").read_text())
    document["preparation"]["stage"] = stage
    if stage == "started":
        document["evidence"]["expected_contents"] = None
    (local.output / "result.json").write_text(json.dumps(document))
    with pytest.raises(ValueError, match="stage contradicts retained initial verification"):
        local.reread_after_cleanup()


@pytest.mark.parametrize("historical", [False, True])
@pytest.mark.parametrize(
    "artifact", ["expected.json", "steps/0/before.json", "initial-verification.json"]
)
def test_failed_initial_verification_still_requires_all_proofs(
    tmp_path: Path, historical: bool, artifact: str
) -> None:
    local = EffectsRun(tmp_path)
    (tmp_path / "subject/skill.md").unlink()
    result = local.run()
    assert result.status == "not_run" and local.calls == []
    if historical:
        document = json.loads((local.output / "result.json").read_text())
        del document["preparation"]["stage"]
        (local.output / "result.json").write_text(json.dumps(document))
        del result.preparation["stage"]
    assert local.reread_after_cleanup() == result
    (local.output / artifact).unlink()
    with pytest.raises(OSError):
        read_result(local.output, local.case)


@pytest.mark.parametrize(
    "artifact", ["initial-verification.json", "steps/0/before/project/CODEBUDDY.md"]
)
def test_failed_initial_verification_is_recomputed(tmp_path: Path, artifact: str) -> None:
    local = EffectsRun(tmp_path)
    (tmp_path / "subject/skill.md").unlink()
    assert local.run().status == "not_run"
    path = local.output / artifact
    if artifact == "initial-verification.json":
        path.write_text(json.dumps({"complete": True, "mismatches": [], "obstacles": []}))
    else:
        path.write_text("Altered initial witness\n")
    with pytest.raises(ValueError):
        local.reread_after_cleanup()


def test_missing_stage_cannot_excuse_missing_initial_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = _observation_failure(tmp_path, monkeypatch)
    document = json.loads((local.output / "result.json").read_text())
    del document["preparation"]["stage"]
    (local.output / "result.json").write_text(json.dumps(document))
    with pytest.raises(OSError):
        local.reread_after_cleanup()


def test_historical_success_retains_strict_evidence_checks(tmp_path: Path) -> None:
    local = EffectsRun(tmp_path)
    result = local.run()
    document = json.loads((local.output / "result.json").read_text())
    del document["preparation"]["stage"]
    (local.output / "result.json").write_text(json.dumps(document))
    del result.preparation["stage"]
    assert local.reread_after_cleanup() == result
    (local.output / "initial-verification.json").unlink()
    with pytest.raises(OSError):
        read_result(local.output, local.case)
