"""Exercise the embedded entry with real case conduct and controlled commands."""

import fnmatch
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.local_case import LocalCase
from tools.install_sandbox.container.__main__ import main
from tools.install_sandbox.container.installer import InstallerCommandResult, InstallerDriver
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.host.build_context import prepare_context


def _arguments(root: Path) -> list[str]:
    return [
        "--reference-sources",
        str(root / "subject"),
        "--prepared-executable",
        str(root / "prepared/bin/graphify"),
        "--case-file",
        str(root / "case.json"),
        "--output-directory",
        str(root / "results"),
        "--work-directory",
        str(root / "work"),
    ]


@pytest.mark.parametrize(
    "mode,status",
    [
        ("passed", "passed"),
        ("missing", "failed"),
        ("not_started", "incomplete"),
    ],
)
def test_saved_case_status_is_separate_from_program_exit(
    tmp_path: Path,
    mode: str,
    status: str,
) -> None:
    local = LocalCase(tmp_path, mode)
    local.prepare_executable()
    runner = InstallTestRunner()
    assert main(_arguments(tmp_path), runner=runner) == 0
    output = tmp_path / "results"
    assert json.loads((output / "result.json").read_bytes())["status"] == status
    assert "inherited from campaign" in (output / "preparation.log").read_text()
    if status == "failed":
        saved = json.loads((output / "steps/0/verification.json").read_bytes())
        assert any(item["type"] == "missing_file" for item in saved["mismatches"])


def test_result_write_failure_keeps_evidence_and_returns_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local = LocalCase(tmp_path)
    original = Path.replace

    def replace(path: Path, target: Path) -> Path:
        if path.name == "result.json.tmp":
            raise PermissionError("Controlled result rename denied")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", replace)
    local.prepare_executable()
    runner = InstallTestRunner()
    assert main(_arguments(tmp_path), runner=runner) == 1
    assert "Cannot finalize result.json" in capsys.readouterr().err
    assert not (tmp_path / "results/result.json").exists()
    assert (tmp_path / "results/steps/0/after.json").is_file()
    assert (tmp_path / "results/result.json.tmp").is_file()


@pytest.mark.parametrize("interrupted", [False, True])
def test_unexpected_stop_is_not_success(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    interrupted: bool,
) -> None:
    LocalCase(tmp_path)

    def execute(
        args: list[str],
        cwd: Path,
        environment: dict[str, str],
        timeout: float,
    ) -> InstallerCommandResult:
        if interrupted:
            raise KeyboardInterrupt
        raise RuntimeError("Controlled unexpected stop")

    runner = InstallTestRunner(InstallerDriver(execute))
    assert main(_arguments(tmp_path), runner=runner) == (130 if interrupted else 1)
    diagnostic = capsys.readouterr().err
    assert ("interrupted" if interrupted else "Controlled unexpected stop") in diagnostic
    assert not (tmp_path / "results/result.json").exists()
    assert (tmp_path / "results/preparation.log").is_file()


def test_invalid_case_fails_before_commands(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local = LocalCase(tmp_path)
    (tmp_path / "case.json").write_text("{}", encoding="utf-8")
    local.prepare_executable()
    runner = InstallTestRunner()
    assert main(_arguments(tmp_path), runner=runner) == 1
    assert "ValueError" in capsys.readouterr().err


def _embed_sandbox(tmp_path: Path) -> str:
    embedded = tmp_path / "image/tools/install_sandbox"
    embedded.mkdir(parents=True)
    subject = tmp_path / "candidate"
    subject.mkdir()
    context = prepare_context(subject, tmp_path)
    containerfile = (context / "Containerfile").read_text().replace("\\\n", " ")
    rules = (context / "Containerfile.dockerignore").read_text().splitlines()
    for line in containerfile.splitlines():
        if line.startswith("COPY --chmod=") and "/tools/install_sandbox/" in line:
            _, _, source_dir, destination = shlex.split(line)
            for source_file in (context / source_dir).rglob("*.py"):
                relative = source_file.relative_to(context).as_posix()
                assert _admitted(relative, rules)
            target = tmp_path / "image" / destination.removeprefix("/opt/install-sandbox/")
            shutil.copytree(context / source_dir, target)
    return containerfile


def test_restricted_embedded_payload_runs_from_foreign_cwd(tmp_path: Path) -> None:
    containerfile = _embed_sandbox(tmp_path)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    for module in ("tools", "graphify", "yaml"):
        (foreign / f"{module}.py").write_text("raise RuntimeError('Foreign import')\n")
    shutil.copyfile(
        Path(__file__).resolve().parents[1] / "fixtures" / "first-install.json",
        tmp_path / "case.json",
    )
    # Missing subject stops the real preparer before it can execute venv or pip.
    entrypoint = json.loads(
        next(
            line.removeprefix("ENTRYPOINT ")
            for line in containerfile.splitlines()
            if line.startswith("ENTRYPOINT ")
        )
    )
    entrypoint[0] = sys.executable
    entrypoint[-1] = str(tmp_path / "image" / entrypoint[-1].removeprefix("/opt/install-sandbox/"))
    result = subprocess.run(
        [*entrypoint, *_arguments(tmp_path)],
        cwd=foreign,
        env={**os.environ, "PYTHONPATH": str(foreign)},
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()
    prefix = "INSTALL_SANDBOX_ENTRY_TIMINGS "
    trace = next(line for line in result.stderr.decode().splitlines() if line.startswith(prefix))
    timing = json.loads(trace.removeprefix(prefix))
    assert timing["entry"] == "case" and timing["version"] == 1
    assert set(timing["seconds"]) == {
        "initial_imports",
        "arguments",
        "runner_import",
        "runner_setup",
    }
    assert all(value >= 0 for value in timing["seconds"].values())
    saved = json.loads((tmp_path / "results/result.json").read_bytes())
    assert saved["status"] == "not_run"
    assert "Initial verification failed" in saved["preparation"]["reason"]
    assert not (tmp_path / "work/software/venv").exists()


def _admitted(filename: str, rules: list[str]) -> bool:
    included = True
    for rule in rules:
        if fnmatch.fnmatchcase(filename, rule.removeprefix("!")):
            included = rule.startswith("!")
    return included


def test_unwritable_timing_stderr_does_not_prevent_case_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = LocalCase(tmp_path)
    local.prepare_executable()

    class Unwritable:
        def write(self, value: str) -> int:
            raise OSError("Controlled timing output failure")

        def flush(self) -> None:
            raise OSError("Controlled timing flush failure")

    monkeypatch.setattr(sys, "stderr", Unwritable())
    assert main(_arguments(tmp_path)) == 0
    assert json.loads((tmp_path / "results/result.json").read_text())["status"] == "passed"
