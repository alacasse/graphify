"""Image evidence survives cached build logs and executable verification failures."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.install_sandbox.component.test_campaign import campaign, commands
from tests.install_sandbox.component.test_preserve_skill_backup import arrange_backup
from tools.install_sandbox import verify_preparation


def _cached_layer(root: Path, mode: str) -> None:
    layer = root / "runtime/dependency-layer"
    layer.mkdir(parents=True)
    value = {"mode": mode, "warning": None, "diagnostic": None}
    if mode == "resolved":
        value.update(warning="Lock not validated offline", diagnostic="dependencies.log")
        (layer / "dependencies.log").write_text("Full retained uv diagnostic\n")
    (layer / "dependencies.json").write_text(json.dumps(value))


@pytest.mark.parametrize("dependency_mode", ["locked", "resolved"])
def test_cached_build_retrieves_mode_for_json_and_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dependency_mode: str
) -> None:
    arrange_backup(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_MODE", "cached")
    _cached_layer(tmp_path, dependency_mode)
    # A rebuild would now fail validation; the stored layer must supply the evidence.
    monkeypatch.setenv("FAKE_DEPENDENCIES", "invalid")
    result = campaign(tmp_path)
    assert result.passed and result.preparation is not None
    preparation = result.preparation.dependency_preparation
    assert preparation is not None and preparation.mode == dependency_mode
    saved = json.loads((tmp_path / "campaign/campaign.json").read_text())
    text = (tmp_path / "campaign/campaign.txt").read_text()
    assert saved["preparation"]["dependency_preparation"]["mode"] == dependency_mode
    assert f"Dependency mode: {dependency_mode}" in text
    assert (
        "controlled package preparation"
        not in (tmp_path / "campaign/preparation/build.log").read_text()
    )
    assert "dependency_preparation" not in saved["cleanup"]
    assert all("dependency_preparation" not in c["result"]["container"] for c in saved["cases"])
    if dependency_mode == "resolved":
        path = Path(saved["preparation"]["dependency_preparation"]["diagnostic_path"])
        assert path.read_text() == "Full retained uv diagnostic\n"
        assert preparation.warning is not None
        assert preparation.warning in text and str(path) in text


@pytest.mark.parametrize("mode", ["missing", "invalid", "missing_diagnostic"])
def test_missing_or_invalid_evidence_blocks_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    arrange_backup(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DEPENDENCIES", mode)
    result = campaign(tmp_path)
    assert not result.passed and result.preparation is not None
    assert result.preparation.phase == "verify"
    assert "evidence unavailable or invalid" in result.preparation.detail
    assert result.preparation.dependency_preparation is None
    assert all(c.result is None for c in result.cases)
    assert len([c for c in commands(tmp_path) if c[0] == "run"]) == 1
    assert result.cleanup is not None and result.cleanup.cleanup_complete
    assert "Dependency mode: unavailable" in (tmp_path / "campaign/campaign.txt").read_text()


def test_failed_help_preserves_dependency_proof_without_ready_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange_backup(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_MODE", "verify_fail")
    monkeypatch.setenv("FAKE_DEPENDENCIES", "resolved")
    result = campaign(tmp_path)
    assert not result.passed and result.preparation is not None
    assert result.preparation.exit_code == 8
    evidence = result.preparation.dependency_preparation
    assert evidence is not None and evidence.diagnostic_path is not None
    assert evidence.diagnostic_path.read_text() == "Full retained uv diagnostic\n"
    assert all(c.result is None for c in result.cases)


@pytest.mark.parametrize("exit_code", [0, 7])
def test_verification_entrypoint_copies_evidence_then_runs_help(tmp_path: Path, exit_code: int):
    source, output = tmp_path / "image", tmp_path / "evidence"
    source.mkdir()
    output.mkdir()
    (source / "dependencies.json").write_text('{"mode":"resolved"}')
    (source / "dependencies.log").write_text("full diagnostic")
    executable = tmp_path / "graphify"
    executable.write_text(
        f"#!{sys.executable}\nimport sys\nfrom pathlib import Path\n"
        f"assert Path({str(output / 'dependencies.json')!r}).exists()\n"
        f"assert Path({str(output / 'dependencies.log')!r}).read_text() == 'full diagnostic'\n"
        "assert sys.argv[1:] == ['--help']\n"
        f"raise SystemExit({exit_code})\n"
    )
    executable.chmod(0o755)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            verify_preparation.__file__,
            str(source),
            str(output),
            str(executable),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == exit_code, result.stderr
    assert (output / "dependencies.json").read_bytes() == (
        source / "dependencies.json"
    ).read_bytes()
    assert (output / "dependencies.log").read_text() == "full diagnostic"
