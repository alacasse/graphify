"""A single source-selected reference alteration, restoration and autonomous replay."""

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.install_sandbox.component.container.codebuddy_support import (
    CodeBuddyReinstallCase,
)
from tests.install_sandbox.component.container.local_case import LocalCase
from tools.install_sandbox.container.environment import TestEnvironment as Environment
from tools.install_sandbox.container.installer import InstallerCommandResult
from tools.install_sandbox.host.coordinator import InstallTestCoordinator
from tools.install_sandbox.host.result_reader import read_result

_REFERENCE = ".codebuddy/skills/graphify/references/one.md"
_SECOND = ".codebuddy/skills/graphify/references/two.md"
_SOURCE = "graphify/skills/claude/references"


def _tree_bytes(project: Path, home: Path) -> dict[str, bytes]:
    return {
        f"{label}/{path.relative_to(root)}": path.read_bytes()
        for label, root in (("project", project), ("home", home))
        for path in root.rglob("*")
        if path.is_file()
    }


class AlteredReferenceCase(CodeBuddyReinstallCase):
    """Restore only the altered file, with literal bytes independent of source reads."""

    def __init__(self, root: Path, mode: str = "passed") -> None:
        super().__init__(root, mode, case_name="repair-altered-reference")

    def execute(
        self, args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        if self.calls:
            home = Path(environment["HOME"])
            self.degraded_files = _tree_bytes(project, home)
            if self.mode != "missing-restore":
                (home / _REFERENCE).write_bytes(
                    b"Wrong restored bytes.\n"
                    if self.mode == "incorrect-restore"
                    else b"Synthetic reference one.\n"
                )
            if self.mode == "extra-reference-backup":
                (home / (_REFERENCE + ".bak")).write_bytes(b"Unexpected reference backup.\n")
            elif self.mode == "lost-personal-file":
                (home / "personal-notes.txt").unlink()
        return super().execute(args, project, environment, timeout)


def _clean_and_read(local: AlteredReferenceCase):
    shutil.rmtree(local.root / "work")
    shutil.rmtree(local.root / "subject")
    return read_result(local.output, local.retained_case())


def test_single_home_alteration_restores_without_other_changes_and_replays(tmp_path: Path) -> None:
    local = AlteredReferenceCase(tmp_path)
    result = local.run()
    assert result.status == "passed", result
    assert len(local.calls) == 2 and local.calls[0] == local.calls[1]
    assert local.degraded_files == {
        **local.first_files,
        "home/" + _REFERENCE: b"Synthetic reference one.\n\nSandbox repair witness.\n",
    }
    assert local.degraded_files["home/" + _SECOND] == b"Synthetic reference two.\n"
    assert local.repeated_files == local.first_files
    prep = result.steps[1].get("preparation")
    assert prep is not None and prep["ready"]
    assert prep["plan"] == {
        "root": "home",
        "altered_path": _REFERENCE,
        "altered_content_file": "steps/1/preparation/altered-content.bin",
    }
    first = local.output / "steps/0/after"
    last = local.output / "steps/1/after"
    for path, content in local.first_files.items():
        assert (last / path).read_bytes() == content
        assert (first / path).read_bytes() == content
    settings = "project/.codebuddy/settings.json"
    assert (last / (settings + ".graphify-bak")).read_bytes() == (
        local.output / "steps/0/before" / settings
    ).read_bytes()
    assert not any("graphify-state" in name for name in local.first_files)
    assert _clean_and_read(local) == result


@pytest.mark.parametrize(
    "mode",
    [
        "missing-restore",
        "incorrect-restore",
        "lost-personal",
        "json-format",
        "rolling-backup",
        "altered-backup",
        "missing-backup",
        "wrong-skill",
        "duplicate-markdown",
        "extra-reference-backup",
        "lost-personal-file",
    ],
)
def test_exit_zero_does_not_hide_bad_repair(tmp_path: Path, mode: str) -> None:
    local = AlteredReferenceCase(tmp_path, mode)
    result = local.run()
    assert result.status == "failed", result
    assert len(local.calls) == 2
    command = result.steps[1]["command"]
    assert command is not None and command["exit_code"] == 0
    first, last = (step["verification"] for step in result.steps)
    assert first is not None and first.complete and not first.mismatches
    assert last is not None and last.complete and last.mismatches
    assert _clean_and_read(local) == result


def test_first_failure_stops_alteration_and_second_call(tmp_path: Path) -> None:
    local = AlteredReferenceCase(tmp_path, "first-failure")
    result = local.run()
    assert result.status == "failed" and len(local.calls) == 1
    second = result.steps[1]
    assert second["command"] is None and second["verification"] is None
    assert second["skip_reason"] and "preparation" not in second
    assert (tmp_path / "work/environment/home" / _REFERENCE).exists()
    assert _clean_and_read(local) == result


@pytest.mark.parametrize(
    "mode", ["no-alter", "wrong-bytes", "extra-mutation", "wrong-root", "exception"]
)
def test_preparation_failure_stops_second_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    local = AlteredReferenceCase(tmp_path)
    original = Environment.prepare_altered_reference

    def prepare(environment: Environment, plan: Any, content: bytes) -> str | None:
        if mode == "no-alter":
            return None
        if mode == "wrong-bytes":
            return original(environment, plan, b"Wrong preparation bytes.\n")
        if mode == "exception":
            return "Controlled alteration failure"
        if mode == "wrong-root":
            wrong = environment.project / _REFERENCE
            wrong.parent.mkdir(parents=True, exist_ok=True)
            wrong.write_bytes(b"Wrong root mutation.\n")
            return None
        reason = original(environment, plan, content)
        (environment.home / _SECOND).write_bytes(b"Unapproved second mutation.\n")
        return reason

    monkeypatch.setattr(Environment, "prepare_altered_reference", prepare)
    result = local.run()
    assert result.status == "incomplete" and len(local.calls) == 1
    second = result.steps[1]
    assert second["command"] is None and second["verification"] is None
    assert second["skip_reason"]
    preparation = second.get("preparation")
    assert preparation is not None and not preparation["ready"]
    assert _clean_and_read(local) == result


@pytest.mark.parametrize("mode", ["missing-directory", "empty-directory"])
def test_source_inventory_required_before_any_install(tmp_path: Path, mode: str) -> None:
    local = AlteredReferenceCase(tmp_path)
    source = tmp_path / "subject" / _SOURCE
    shutil.rmtree(source)
    if mode == "empty-directory":
        source.mkdir()
    result = local.run()
    assert result.status == "not_run", result
    assert not local.calls
    assert all(step["command"] is None and step["skip_reason"] for step in result.steps)
    assert _clean_and_read(local) == result


@pytest.mark.parametrize(
    "change",
    ["missing-proof", "root", "path", "content", "extra-mutation", "witness", "verification"],
)
def test_retained_preparation_proof_cannot_be_forged(tmp_path: Path, change: str) -> None:
    local = AlteredReferenceCase(tmp_path)
    assert local.run().status == "passed"
    shutil.rmtree(tmp_path / "work")
    shutil.rmtree(tmp_path / "subject")
    if change == "missing-proof":
        (local.output / "steps/1/before.json").unlink()
    elif change == "witness":
        (local.output / "steps/1/preparation/altered-content.bin").write_bytes(b"Forged witness.\n")
    elif change == "verification":
        result_file = local.output / "result.json"
        document = json.loads(result_file.read_bytes())
        document["steps"][1]["verification"]["mismatches"].append(
            {
                "code": "forged",
                "root": "home",
                "path": _REFERENCE,
                "expected": "forged",
                "actual": "forged",
            }
        )
        result_file.write_text(json.dumps(document))
    elif change in {"root", "path"}:
        result_file = local.output / "result.json"
        document = json.loads(result_file.read_bytes())
        plan = document["steps"][1]["preparation"]["plan"]
        plan["root" if change == "root" else "altered_path"] = (
            "project" if change == "root" else _SECOND
        )
        result_file.write_text(json.dumps(document))
    else:
        path = local.output / "steps/1/before/home" / _SECOND
        path.write_bytes(b"Forged preparation content.\n")
        if change == "extra-mutation":
            snapshot_file = local.output / "steps/1/before.json"
            document = json.loads(snapshot_file.read_bytes())
            # Keep the altered snapshot internally consistent; cross-phase proof must still fail.
            for entry in document["entries"]:
                if entry["root"] == "home" and entry["path"] == _SECOND:
                    entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            snapshot_file.write_text(json.dumps(document))
    with pytest.raises((ValueError, FileNotFoundError)):
        read_result(local.output, local.retained_case())


def test_project_root_registry_repair_replays_after_cleanup(tmp_path: Path) -> None:
    local = LocalCase(tmp_path)
    specs = Path(__file__).resolve().parents[4] / "tools/install_sandbox/specs/reference"
    case = InstallTestCoordinator().write_case(
        specs, "sandbox-reference", tmp_path / "case.json", case_name="repair-altered-reference"
    )
    result = local.run()
    assert result.status == "passed", result
    preparation = result.steps[1].get("preparation")
    assert preparation is not None and preparation["ready"]
    reference = ".sandbox-reference/skills/graphify/references/one.md"
    assert preparation["plan"] == {
        "root": "project",
        "altered_path": reference,
        "altered_content_file": "steps/1/preparation/altered-content.bin",
    }
    output = tmp_path / "results"
    first = _tree_bytes(output / "steps/0/after/project", output / "steps/0/after/home")
    prepared = _tree_bytes(output / "steps/1/before/project", output / "steps/1/before/home")
    final = _tree_bytes(output / "steps/1/after/project", output / "steps/1/after/home")
    assert prepared == {
        **first,
        "project/" + reference: b"Reference one.\n\nSandbox repair witness.\n",
    }
    assert final == first
    assert "project/.sandbox-reference/settings.json.graphify-state.json" in final
    shutil.rmtree(tmp_path / "work")
    shutil.rmtree(tmp_path / "subject")
    assert read_result(output, case) == result
