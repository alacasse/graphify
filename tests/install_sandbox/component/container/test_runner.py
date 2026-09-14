"""Exercise local case conduct with literal file effects and the real verifier."""

import json
import shutil
import sys
import time
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.local_case import LocalCase, deny_read
from tools.install_sandbox.container.installer import (
    InstallerCommandResult,
    InstallerDriver,
    execute_command,
)
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.results import EvidenceWriteError

# Literal effects only: no product imports, reference discovery or spec interpretation.


def test_passed_result_and_all_contents_survive_workspace_removal(tmp_path: Path) -> None:
    local = LocalCase(tmp_path)
    result = local.run()
    assert result.status == "passed"
    assert result.preparation == {
        "ready": True,
        "reason": None,
        "log": "preparation.log",
        "source": "campaign",
    }
    command = result.steps[0]["command"]
    assert command is not None
    assert command["args"] == [
        str(tmp_path / "prepared/bin/graphify"),
        "install",
        "--platform",
        "sandbox-reference",
        "--project",
    ]
    assert command["cwd"] == str(tmp_path / "work/environment/project")
    shutil.rmtree(tmp_path / "work")
    shutil.rmtree(tmp_path / "subject")
    output = tmp_path / "results"
    saved = json.loads((output / "result.json").read_bytes())
    assert set(saved) == {"case", "preparation", "steps", "status", "evidence"}
    assert saved["status"] == "passed"
    assert command["stdout_file"] is not None and command["stderr_file"] is not None
    assert (output / command["stdout_file"]).read_bytes() == b"controlled stdout\n"
    assert (output / command["stderr_file"]).read_bytes() == b"controlled stderr\n"
    for relative in ("expected.json", "steps/0/before.json", "steps/0/after.json"):
        snapshot = json.loads((output / relative).read_bytes())
        for entry in snapshot["entries"]:
            if entry.get("content_file"):
                assert (output / entry["content_file"]).is_file()
    assert (output / "expected/graphify/skill.md").read_text() == "# Local skill\n"
    assert "inherited from campaign" in (output / "preparation.log").read_text()
    assert "attempting install" in (output / "journal.log").read_text()
    assert not (output / "result.json.tmp").exists()


@pytest.mark.parametrize(
    "mode, status",
    [
        ("not_started", "incomplete"),
        ("nonzero", "failed"),
        ("missing", "failed"),
        ("no_effects", "failed"),
        ("timeout", "incomplete"),
        ("signal", "incomplete"),
    ],
)
def test_command_states_preserve_effects_and_diagnostics(
    tmp_path: Path, mode: str, status: str
) -> None:
    result = LocalCase(tmp_path, mode).run(timeout=0.3 if mode == "timeout" else 5)
    assert result.status == status
    step = result.steps[0]
    command, verification = step["command"], step["verification"]
    assert step["skip_reason"] is None
    assert step["observations"] == {"before": "steps/0/before.json", "after": "steps/0/after.json"}
    assert command is not None and verification is not None
    assert verification.complete and not verification.obstacles
    if mode == "not_started":
        assert command["state"] == "not_started" and command["exit_code"] is None
        assert command["reason"] and verification.mismatches
    elif mode in {"timeout", "signal"}:
        assert command["state"] == "interrupted" and command["reason"]
    else:
        assert command["state"] == "completed"
        assert command["exit_code"] == (7 if mode == "nonzero" else 0)
        assert bool(verification.mismatches) == (mode in {"missing", "no_effects"})
    if mode != "not_started":
        assert (tmp_path / "results/steps/0/stdout.txt").read_bytes() == b"controlled stdout\n"
        assert (tmp_path / "results/steps/0/stderr.txt").read_bytes() == b"controlled stderr\n"


@pytest.mark.parametrize("source", [True, False])
def test_initial_read_obstacle_prevents_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: bool
) -> None:
    local = LocalCase(tmp_path)
    denied = tmp_path / (
        "subject/graphify/skill.md" if source else "work/environment/home/personal-notes.txt"
    )
    deny_read(monkeypatch, denied)
    result = local.run()
    assert result.status == "not_run" and not result.preparation["ready"]
    assert result.steps[0]["command"] is None
    assert "Controlled read denied" in (result.preparation["reason"] or "")
    assert not (tmp_path / "work/environment/project/.sandbox-reference/skills").exists()


def test_final_obstacle_keeps_known_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = LocalCase(tmp_path, "missing")
    original = Path.read_bytes
    config = tmp_path / "work/environment/project/.sandbox-reference/settings.json"

    def read(path: Path) -> bytes:
        if path == config and (tmp_path / "results/steps/0/stdout.txt").exists():
            raise PermissionError("Controlled final read denied")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    result = local.run()
    assert result.status == "incomplete"
    verification = result.steps[0]["verification"]
    assert verification is not None and not verification.complete
    assert any(
        m.type == "missing_file" and m.path.endswith("one.md") for m in verification.mismatches
    )
    assert any(o["reason"] == "Controlled final read denied" for o in verification.obstacles)


def test_invalid_case_rejected_before_preparation(tmp_path: Path) -> None:
    local = LocalCase(tmp_path)
    (tmp_path / "case.json").write_text("{}")
    with pytest.raises(ValueError):
        local.run()
    assert not (tmp_path / "results").exists()


def test_writer_failure_does_not_claim_saved_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = LocalCase(tmp_path)
    original = Path.replace

    def replace(path: Path, target: Path) -> Path:
        if path.name == "result.json.tmp":
            raise PermissionError("Controlled result rename denied")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", replace)
    with pytest.raises(EvidenceWriteError, match=r"Cannot finalize result\.json"):
        local.run()
    assert not (tmp_path / "results/result.json").exists()
    assert (tmp_path / "results/steps/0/after.json").exists()


def test_caller_environment_cannot_override_isolated_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = LocalCase(tmp_path)
    monkeypatch.setenv("PYTHONPATH", "/caller/python")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/caller/config")

    def execute(
        args: list[str], cwd: Path, env: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        assert "PYTHONPATH" not in env and "XDG_CONFIG_HOME" not in env
        assert env["HOME"] == str(tmp_path / "work/environment/home")
        return execute_command(args, cwd, env, timeout)

    result = InstallTestRunner(InstallerDriver(execute)).run_case(
        reference_sources=tmp_path / "subject",
        prepared_executable=local.prepare_executable(),
        case_file=tmp_path / "case.json",
        work_directory=tmp_path / "work",
        output_directory=tmp_path / "results",
    )
    assert result.status == "passed"


def test_initial_witness_is_verified_before_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = LocalCase(tmp_path)
    original = Path.write_bytes

    def write(path: Path, data: bytes) -> int:
        if path == tmp_path / "work/environment/home/personal-notes.txt":
            data = b"Wrong initial content\n"
        return original(path, data)

    monkeypatch.setattr(Path, "write_bytes", write)
    result = local.run()
    assert result.status == "not_run"
    assert result.steps[0]["command"] is None
    assert "personal-notes.txt" in (result.preparation["reason"] or "")


@pytest.mark.parametrize("relative", ["steps/0/stdout.txt", "steps/0/after.json"])
def test_evidence_write_failure_is_explicit(tmp_path: Path, relative: str) -> None:
    local = LocalCase(tmp_path)

    def execute(
        args: list[str], cwd: Path, env: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        result = execute_command(args, cwd, env, timeout)
        (tmp_path / "results" / relative).mkdir(parents=True)
        return result

    with pytest.raises(EvidenceWriteError, match="Cannot write evidence"):
        InstallTestRunner(InstallerDriver(execute)).run_case(
            reference_sources=tmp_path / "subject",
            prepared_executable=local.prepare_executable(),
            case_file=tmp_path / "case.json",
            work_directory=tmp_path / "work",
            output_directory=tmp_path / "results",
        )
    assert not (tmp_path / "results/result.json").exists()
    assert (tmp_path / "results/steps/0/before.json").exists()


def test_existing_evidence_is_never_overwritten(tmp_path: Path) -> None:
    local = LocalCase(tmp_path)
    output = tmp_path / "results"
    output.mkdir()
    (output / "result.json").write_bytes(b"Existing evidence\n")
    with pytest.raises(ValueError, match="fresh or empty"):
        local.run()
    assert (output / "result.json").read_bytes() == b"Existing evidence\n"


def test_overlapping_work_and_subject_rejected_before_copy(tmp_path: Path) -> None:
    local = LocalCase(tmp_path)
    with pytest.raises(ValueError, match="must be separate"):
        InstallTestRunner().run_case(
            reference_sources=tmp_path / "subject",
            prepared_executable=local.prepare_executable(),
            case_file=tmp_path / "case.json",
            work_directory=tmp_path / "subject/work",
            output_directory=tmp_path / "results",
        )
    assert not (tmp_path / "results").exists()


def test_signal_interruption_stops_children_before_final_observation(tmp_path: Path) -> None:
    child = (
        "from pathlib import Path; import time; "
        "Path('child-ready').touch(); time.sleep(0.5); Path('late-effect').touch()"
    )
    parent = (
        "import os, signal, subprocess, sys, time\nfrom pathlib import Path\n"
        f"subprocess.Popen([sys.executable, '-c', {child!r}], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "while not Path('child-ready').exists(): time.sleep(0.005)\n"
        "print('before signal', flush=True)\n"
        "os.kill(os.getpid(), signal.SIGTERM)\n"
    )
    result = execute_command([sys.executable, "-c", parent], tmp_path, {}, 5)
    assert result.state == "interrupted" and result.exit_code == -15
    assert result.stdout == b"before signal\n"
    assert (tmp_path / "child-ready").exists()
    time.sleep(0.7)
    assert not (tmp_path / "late-effect").exists()
