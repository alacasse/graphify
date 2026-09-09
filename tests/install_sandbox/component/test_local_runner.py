"""Exercise local case conduct with literal file effects and the real verifier."""

import json
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tools.install_sandbox.driver import InstallerCommandResult, InstallerDriver, execute_command
from tools.install_sandbox.preparer import GraphifyPreparer
from tools.install_sandbox.results import EvidenceWriteError, InstallTestResult
from tools.install_sandbox.runner import InstallTestRunner

_CASE = Path(__file__).with_name("fixtures") / "first-install.json"
_INITIAL = (
    "# My project\n\n## Language\nRespond in English.\n\n## Changes\nExplain proposed changes.\n"
)
# Literal effects only: no installer parsing, merging, reference discovery or spec interpretation.
_FILES = {
    ".sandbox-reference/skills/graphify/SKILL.md": "# Local skill\n",
    ".sandbox-reference/skills/graphify/references/one.md": "Reference one.\n",
    ".sandbox-reference/skills/graphify/.graphify_version": "Any version\n",
    ".sandbox-reference/instructions.md": _INITIAL + "\n## graphify\nUse the graph.\n",
    ".sandbox-reference/settings.json": (
        '{"theme":"dark","instructions":["my-instructions.md","skills/graphify/SKILL.md"]}\n'
    ),
}


def controlled_script(mode: str) -> str:
    effects = dict(_FILES)
    if mode == "missing":
        del effects[".sandbox-reference/skills/graphify/references/one.md"]
    if mode == "no_effects":
        effects = {}
    ending = {
        "nonzero": "raise SystemExit(7)",
        "timeout": "import time; time.sleep(30)",
        "signal": "import signal; os.kill(os.getpid(), signal.SIGTERM)",
    }.get(mode, "")
    return (
        f"#!{sys.executable}\nimport os\nfrom pathlib import Path\n"
        f"for name, content in {effects!r}.items():\n"
        "    path = Path(name)\n    path.parent.mkdir(parents=True, exist_ok=True)\n"
        "    path.write_text(content, encoding='utf-8')\n"
        "print('controlled stdout', flush=True)\n"
        "print('controlled stderr', file=__import__('sys').stderr, flush=True)\n" + ending + "\n"
    )


@dataclass
class LocalCase:
    root: Path
    mode: str = "passed"
    preparation_failure: int = 0
    calls: list[list[str]] = field(default_factory=list[list[str]])

    def __post_init__(self) -> None:
        sources = {
            "graphify/skill.md": "# Local skill\n",
            "graphify/always_on/agents-md.md": "## graphify\nUse the graph.\n",
            "graphify/skills/claude/references/one.md": "Reference one.\n",
            "local-untracked.txt": "Local uncommitted content.\n",
        }
        for name, content in sources.items():
            path = self.root / "subject" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        shutil.copyfile(_CASE, self.root / "case.json")

    def prepare_command(
        self, args: list[str], cwd: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        self.calls.append(args)
        assert cwd == self.root / "work/software/source"
        assert (cwd / "local-untracked.txt").read_text() == "Local uncommitted content.\n"
        # The seam runs only this controlled local Python, never venv/pip or Graphify.
        code = (
            "print('preparation output'); import sys; print('preparation error', file=sys.stderr)"
        )
        if self.preparation_failure == len(self.calls):
            code += "; raise SystemExit(9)"
        result = execute_command([sys.executable, "-c", code], cwd, environment, timeout)
        if len(self.calls) == 2 and self.mode != "not_started":
            executable = self.root / "work/software/venv/bin/graphify"
            executable.parent.mkdir(parents=True)
            executable.write_text(controlled_script(self.mode), encoding="utf-8")
            executable.chmod(0o755)
        return result

    def run(self, *, timeout: float = 5) -> InstallTestResult:
        return InstallTestRunner(
            GraphifyPreparer(self.prepare_command),
            InstallerDriver(timeout=timeout),
        ).run_case(
            subject_checkout=self.root / "subject",
            case_file=self.root / "case.json",
            work_directory=self.root / "work",
            output_directory=self.root / "results",
        )


def test_passed_result_and_all_contents_survive_workspace_removal(tmp_path: Path) -> None:
    local = LocalCase(tmp_path)
    result = local.run()
    assert result.status == "passed"
    assert result.preparation == {"ready": True, "reason": None, "log": "preparation.log"}
    command = result.steps[0]["command"]
    assert command is not None
    assert command["args"] == [
        str(tmp_path / "work/software/venv/bin/graphify"),
        "install",
        "--platform",
        "sandbox-reference",
        "--project",
    ]
    assert command["cwd"] == str(tmp_path / "work/environment/project")
    assert local.calls[0] == [sys.executable, "-m", "venv", str(tmp_path / "work/software/venv")]
    assert local.calls[1][-1] == str(tmp_path / "work/software/source")
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
    assert "preparation output" in (output / "preparation.log").read_text()
    assert "attempting install" in (output / "journal.log").read_text()
    assert not (output / "result.json.tmp").exists()


@pytest.mark.parametrize("failure", [1, 2])
def test_preparation_failure_skips_installation(tmp_path: Path, failure: int) -> None:
    local = LocalCase(tmp_path, preparation_failure=failure)
    result = local.run()
    assert result.status == "not_run"
    assert len(local.calls) == failure
    assert not result.preparation["ready"]
    assert result.steps[0]["command"] is None
    assert result.steps[0]["verification"] is None
    assert result.steps[0]["observations"] is None
    assert result.steps[0]["skip_reason"]
    assert "code 9" in (result.preparation["reason"] or "")
    assert "preparation error" in (tmp_path / "results/preparation.log").read_text()


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


def _deny_read(monkeypatch: pytest.MonkeyPatch, denied: Path) -> None:
    original = Path.read_bytes

    def read(path: Path) -> bytes:
        if path == denied:
            raise PermissionError("Controlled read denied")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)


@pytest.mark.parametrize("source", [True, False])
def test_initial_read_obstacle_prevents_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: bool
) -> None:
    local = LocalCase(tmp_path)
    denied = tmp_path / (
        "subject/graphify/skill.md" if source else "work/environment/home/personal-notes.txt"
    )
    _deny_read(monkeypatch, denied)
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
    assert not local.calls and not (tmp_path / "results").exists()


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
    original = local.prepare_command

    def execute(
        args: list[str], cwd: Path, env: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        assert "PYTHONPATH" not in env and "XDG_CONFIG_HOME" not in env
        assert env["HOME"] == str(tmp_path / "work/software/home")
        return original(args, cwd, env, timeout)

    result = InstallTestRunner(GraphifyPreparer(execute)).run_case(
        subject_checkout=tmp_path / "subject",
        case_file=tmp_path / "case.json",
        work_directory=tmp_path / "work",
        output_directory=tmp_path / "results",
    )
    assert result.status == "passed"


def test_source_copy_failure_prevents_any_command(tmp_path: Path) -> None:
    local = LocalCase(tmp_path)
    shutil.rmtree(tmp_path / "subject")
    result = local.run()
    assert result.status == "not_run"
    assert not local.calls
    assert "Software preparation failed" in (result.preparation["reason"] or "")
    assert result.evidence["expected_contents"] is None


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
        InstallTestRunner(
            GraphifyPreparer(local.prepare_command), InstallerDriver(execute)
        ).run_case(
            subject_checkout=tmp_path / "subject",
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
    assert not local.calls
    assert (output / "result.json").read_bytes() == b"Existing evidence\n"


def test_overlapping_work_and_subject_rejected_before_copy(tmp_path: Path) -> None:
    local = LocalCase(tmp_path)
    with pytest.raises(ValueError, match="must be separate"):
        InstallTestRunner(GraphifyPreparer(local.prepare_command)).run_case(
            subject_checkout=tmp_path / "subject",
            case_file=tmp_path / "case.json",
            work_directory=tmp_path / "subject/work",
            output_directory=tmp_path / "results",
        )
    assert not local.calls and not (tmp_path / "results").exists()


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
