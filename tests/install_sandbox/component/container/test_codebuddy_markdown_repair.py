"""CodeBuddy Markdown repair retains independent preparation and installation proof."""

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.codebuddy_support import (
    CodeBuddyMarkdownRepairCase as MarkdownCase,
)
from tools.install_sandbox.container.environment import FilesystemSnapshot
from tools.install_sandbox.container.environment import TestEnvironment as Environment
from tools.install_sandbox.container.verifier import InstallVerifier
from tools.install_sandbox.contracts.case import first_install_files, markdown_repair_plan
from tools.install_sandbox.contracts.results import FileAlterationPlan, SnapshotEntry
from tools.install_sandbox.host.result_reader import read_result

_MARKDOWN = "CODEBUDDY.md"
_CONFORMING = (
    b"# My project\n\n## Language\nRespond in English.\n\n"
    b"## graphify\nUse the synthetic graph.\n\n## Changes\nExplain proposed changes.\n"
)
_ALTERED = _CONFORMING.replace(b"Use the synthetic graph.", b"Sandbox altered Markdown section.")


def test_markdown_restored_and_independently_read_after_cleanup(tmp_path: Path) -> None:
    local = MarkdownCase(tmp_path)
    result = local.run()
    assert result.status == "passed", result
    assert len(local.calls) == 2
    assert local.calls[0] == local.calls[1]
    for phase, content in [
        ("steps/0/after", _CONFORMING),
        ("steps/1/before", _ALTERED),
        ("steps/1/after", _CONFORMING),
    ]:
        assert (local.output / phase / "project" / _MARKDOWN).read_bytes() == content
    assert (local.output / "steps/1/preparation/altered-content.bin").read_bytes() == _ALTERED
    assert (
        local.output / "steps/1/after/project/.codebuddy/settings.json.graphify-bak"
    ).read_bytes() == (
        local.output / "steps/0/before/project/.codebuddy/settings.json"
    ).read_bytes()
    shutil.rmtree(tmp_path / "work")
    shutil.rmtree(tmp_path / "subject")
    assert read_result(local.output, local.retained_case()) == result


@pytest.mark.parametrize(
    "mode,mismatch",
    [
        ("no-op", "content_mismatch"),
        ("lost-prefix", "user_content_lost"),
        ("lost-suffix", "user_content_lost"),
        ("foreign", "unexpected_change"),
        ("registry", "unexpected_change"),
        ("wrong-skill", "content_mismatch"),
        ("wrong-reference", "content_mismatch"),
        ("wrong-version", "version_changed"),
        ("rolling-backup", "content_mismatch"),
        ("duplicate-hook", "hook_count"),
        ("json-format", "content_mismatch"),
    ],
)
def test_markdown_repair_rejects_bad_effects(tmp_path: Path, mode: str, mismatch: str) -> None:
    local = MarkdownCase(tmp_path, mode)
    result = local.run()
    assert result.status == "failed", result
    assert len(local.calls) == 2
    verification = result.steps[1]["verification"]
    assert verification is not None
    assert mismatch in {m.type for m in verification.mismatches}
    assert read_result(local.output, local.retained_case()) == result


@pytest.mark.parametrize("mode", ["no-change", "wrong-content", "personal", "foreign", "failure"])
def test_bad_markdown_preparation_blocks_second_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    original = Environment.prepare_markdown_repair

    def prepare(environment: Environment, plan: FileAlterationPlan, content: bytes) -> str | None:
        if mode == "no-change":
            return None
        reason = original(environment, plan, content)
        markdown = environment.project / _MARKDOWN
        if mode == "wrong-content":
            markdown.write_bytes(b"Wrong\n")
        elif mode == "personal":
            markdown.write_bytes(content.replace(b"Respond in English.", b"Lost"))
        elif mode == "foreign":
            (environment.home / "personal-notes.txt").write_bytes(b"Lost\n")
        return "Controlled preparation failure" if mode == "failure" else reason

    monkeypatch.setattr(Environment, "prepare_markdown_repair", prepare)
    local = MarkdownCase(tmp_path)
    result = local.run()
    assert result.status == "incomplete", result
    assert len(local.calls) == 1 and result.steps[1]["command"] is None
    assert read_result(local.output, local.retained_case()) == result


@pytest.mark.parametrize("stage", ["preparation", "final"])
def test_unobservable_markdown_is_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    local = MarkdownCase(tmp_path)
    original = Path.read_bytes
    original_prepare = Environment.prepare_markdown_repair
    prepared = False

    def prepare(environment: Environment, plan: FileAlterationPlan, content: bytes) -> str | None:
        nonlocal prepared
        reason = original_prepare(environment, plan, content)
        prepared = True
        return reason

    def read(path: Path) -> bytes:
        if path == tmp_path / "work/environment/project" / _MARKDOWN and (
            (stage == "preparation" and prepared) or (stage == "final" and len(local.calls) == 2)
        ):
            raise PermissionError("Controlled Markdown observation denied")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    monkeypatch.setattr(Environment, "prepare_markdown_repair", prepare)
    result = local.run()
    assert result.status == "incomplete", result
    assert len(local.calls) == (1 if stage == "preparation" else 2)
    assert read_result(local.output, local.retained_case()) == result


def test_failed_first_install_prevents_markdown_preparation(tmp_path: Path) -> None:
    local = MarkdownCase(tmp_path, "first-failure")
    result = local.run()
    assert result.status == "failed" and len(local.calls) == 1
    assert "preparation" not in result.steps[1]
    assert read_result(local.output, local.retained_case()) == result


@pytest.mark.parametrize(
    "relative",
    [
        "expected/graphify/always_on/claude-md.md",
        "steps/1/preparation/altered-content.bin",
        "steps/0/after/project/" + _MARKDOWN,
        "steps/1/before/project/" + _MARKDOWN,
        "steps/1/after/project/" + _MARKDOWN,
    ],
)
@pytest.mark.parametrize("missing", [False, True])
def test_markdown_requires_retained_evidence(tmp_path: Path, relative: str, missing: bool) -> None:
    local = MarkdownCase(tmp_path)
    assert local.run().status == "passed"
    evidence = local.output / relative
    if missing:
        evidence.unlink()
    else:
        evidence.write_bytes(b"Tampered\n")
    with pytest.raises((ValueError, OSError)):
        read_result(local.output, local.retained_case())


@pytest.mark.parametrize("phase", ["steps/0/after", "steps/1/before", "steps/1/after"])
def test_readback_rejects_self_consistent_false_success(tmp_path: Path, phase: str) -> None:
    local = MarkdownCase(tmp_path)
    assert local.run().status == "passed"
    snapshot_file = local.output / (phase + ".json")
    snapshot = json.loads(snapshot_file.read_bytes())
    entry = next(
        e for e in snapshot["entries"] if e["root"] == "project" and e["path"] == _MARKDOWN
    )
    content = b"Self-consistent forged Markdown\n"
    (local.output / entry["content_file"]).write_bytes(content)
    entry["sha256"] = hashlib.sha256(content).hexdigest()
    snapshot_file.write_text(json.dumps(snapshot))
    with pytest.raises(ValueError, match="contradicts"):
        read_result(local.output, local.retained_case())


def test_markdown_preparation_uses_declared_home_root(tmp_path: Path) -> None:
    local = MarkdownCase(tmp_path)
    path = ".codebuddy/CODEBUDDY.md"
    destinations = dict(local.case.spec.destinations or {})
    destinations["markdown"] = {"root": "home", "path": path}
    spec = replace(local.case.spec, destinations=destinations)
    case = replace(local.case, spec=spec, initial_files=first_install_files(spec, local.case.name))
    environment = Environment(case, tmp_path / "rooted")
    environment.prepare()
    personal = (environment.project / path).read_bytes()
    # The same relative path in the other root must not select the wrong witness.
    reordered = replace(case, initial_files=list(reversed(case.initial_files)))
    plan, content = markdown_repair_plan(reordered)
    assert content == _ALTERED
    (environment.home / path).write_bytes(_CONFORMING)
    assert environment.prepare_markdown_repair(plan, content) is None
    assert (environment.home / path).read_bytes() == _ALTERED
    assert (environment.project / path).read_bytes() == personal
    entries: list[SnapshotEntry] = [
        {"root": "home", "path": path, "kind": "file"},
        {"root": "project", "path": path, "kind": "file"},
    ]
    installed = FilesystemSnapshot(
        entries=entries,
        contents={("home", path): _CONFORMING, ("project", path): personal},
    )
    prepared = FilesystemSnapshot(
        entries=entries,
        contents={("home", path): _ALTERED, ("project", path): personal},
    )
    verification = InstallVerifier().verify_markdown_repair(
        case, plan, content, installed, prepared
    )
    assert verification.complete and not verification.mismatches
    prepared.contents[("project", path)] = b"Wrong root changed\n"
    verification = InstallVerifier().verify_markdown_repair(
        case, plan, content, installed, prepared
    )
    assert {m.type for m in verification.mismatches} == {"unexpected_change"}
