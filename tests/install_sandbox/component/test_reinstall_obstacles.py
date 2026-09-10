"""Initial and post-command obstacles must prevent dependent installations."""

from dataclasses import replace
from pathlib import Path

import pytest

from tests.install_sandbox.component.test_local_runner import LocalCase
from tools.install_sandbox.case import InstallTestCase
from tools.install_sandbox.driver import InstallerCommandResult, InstallerDriver, execute_command
from tools.install_sandbox.result_reader import read_result
from tools.install_sandbox.runner import InstallTestRunner


def _local(tmp_path: Path, mode: str = "passed") -> LocalCase:
    local = LocalCase(tmp_path, mode)
    path = tmp_path / "case.json"
    case = InstallTestCase.from_json(path.read_text())
    replace(case, name="reinstall", operations=["install", "install"]).write(path)
    return local


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("filename", [".graphify_version", "references/one.md"])
def test_observation_obstacle_preserves_known_mismatch_and_stops_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, index: int, filename: str
) -> None:
    local = _local(tmp_path)
    original = Path.read_bytes
    denied = tmp_path / "work/environment/project/.sandbox-reference/skills/graphify" / filename

    def read(path: Path) -> bytes:
        if path == denied and (tmp_path / f"results/steps/{index}/stdout.txt").exists():
            raise PermissionError("Controlled reinstall observation denied")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    result = local.run()
    assert result.status == "incomplete"
    verification = result.steps[index]["verification"]
    assert verification is not None and not verification.complete
    assert any(
        o["reason"] == "Controlled reinstall observation denied" for o in verification.obstacles
    )
    assert not any(m.type == "missing_file" for m in verification.mismatches)
    if index == 0:
        assert result.steps[1]["command"] is None and result.steps[1]["skip_reason"]
    case = InstallTestCase.from_json((tmp_path / "case.json").read_text())
    assert read_result(tmp_path / "results", case) == result


@pytest.mark.parametrize("index", [0, 1])
def test_launch_failure_still_observes_files_and_records_stop(tmp_path: Path, index: int) -> None:
    local = _local(tmp_path)
    attempts: list[list[str]] = []

    def execute(
        args: list[str], cwd: Path, env: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        if len(attempts) == index:
            Path(args[0]).unlink()
        attempts.append(args)
        return execute_command(args, cwd, env, timeout)

    result = InstallTestRunner(InstallerDriver(execute)).run_case(
        reference_sources=tmp_path / "subject",
        prepared_executable=local.prepare_executable(),
        case_file=tmp_path / "case.json",
        work_directory=tmp_path / "work",
        output_directory=tmp_path / "results",
    )
    assert result.status == "incomplete" and len(attempts) == index + 1
    step = result.steps[index]
    assert step["command"] is not None and step["command"]["state"] == "not_started"
    assert step["command"]["reason"] and step["verification"] is not None
    assert step["verification"].complete
    assert bool(step["verification"].mismatches) == (index == 0)
    assert (tmp_path / f"results/steps/{index}/after.json").exists()
    case = InstallTestCase.from_json((tmp_path / "case.json").read_text())
    assert read_result(tmp_path / "results", case) == result


@pytest.mark.parametrize(
    "filename", ["SKILL.md", "SKILL.md.bak", ".graphify_version", "references/x.md"]
)
def test_preinstalled_files_prevent_initial_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filename: str
) -> None:
    local = _local(tmp_path)
    original = Path.write_bytes

    def write(path: Path, data: bytes) -> int:
        count = original(path, data)
        if path == tmp_path / "work/environment/home/personal-notes.txt":
            installed = path.parent.parent / "project/.sandbox-reference/skills/graphify" / filename
            installed.parent.mkdir(parents=True, exist_ok=True)
            original(installed, b"Unexpected initial installation\n")
        return count

    monkeypatch.setattr(Path, "write_bytes", write)
    result = local.run()
    assert result.status == "not_run" and not result.preparation["ready"]
    assert "unexpected_entry" in (result.preparation["reason"] or "")
    assert all(step["command"] is None and step["skip_reason"] for step in result.steps)


def test_initial_obstacle_skips_both_steps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    local = _local(tmp_path)
    original = Path.read_bytes

    def read(path: Path) -> bytes:
        if path == tmp_path / "subject/graphify/skill.md":
            raise PermissionError("Controlled initial source unavailable")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    result = local.run()
    assert result.status == "not_run"
    assert "Controlled initial source unavailable" in (result.preparation["reason"] or "")
    assert all(step["command"] is None and step["skip_reason"] for step in result.steps)
