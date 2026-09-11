"""Execute preparation with controlled commands; no dependencies or network used."""

import json
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from tools.install_sandbox import prepare_dependencies

_PROGRAM = Path(prepare_dependencies.__file__)
_COMMAND = Path(__file__).with_name("fake_dependency_command.py")


def arrange(root: Path, monkeypatch: pytest.MonkeyPatch, *, lock: bool = True) -> Path:
    metadata = root / "metadata"
    metadata.mkdir()
    (metadata / "pyproject.toml").write_text(
        '[project]\nname = "candidate"\ndependencies = ["ordinary>=1", '
        '"conditional; sys_platform == \\"linux\\""]\n'
        '[project.optional-dependencies]\nextra = ["not-installed"]\n'
        '[dependency-groups]\ndev = ["also-not-installed"]\n'
    )
    if lock:
        (metadata / "uv.lock").write_text("captured lock\n")
    for name in ("uv", "pip-python"):
        target = root / name
        target.write_text(f"#!{sys.executable}\n" + _COMMAND.read_text())
        target.chmod(0o755)
    monkeypatch.setenv("PATH", str(root))
    monkeypatch.setenv("DEPENDENCY_TEST_ROOT", str(root))
    return metadata


def execute(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(_PROGRAM),
            str(root / "metadata"),
            str(root / "output"),
            str(root / "pip-python"),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )


def calls(root: Path) -> list[dict[str, object]]:
    path = root / "commands.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_locked_export_preserves_hashes_and_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    metadata = arrange(tmp_path, monkeypatch)
    before = {p.name: p.read_bytes() for p in metadata.iterdir()}
    result = execute(tmp_path)
    assert result.returncode == 0, result.stderr
    recorded = calls(tmp_path)
    assert [c["role"] for c in recorded] == ["uv", "pip-python"]
    arguments = recorded[0]["arguments"]
    assert isinstance(arguments, list)
    arguments = cast(list[str], arguments)
    assert {
        "--locked",
        "--offline",
        "--no-python-downloads",
        "--no-default-groups",
        "--no-emit-project",
    } <= set(arguments)
    assert arguments[arguments.index("--python") + 1] == sys.executable
    assert recorded[1]["requirements"] == (
        'locked-package==1.2; python_version >= "3.12" \\\n    --hash=sha256:abc123\n'
    )
    evidence = json.loads((tmp_path / "output/dependencies.json").read_text())
    assert evidence == {"mode": "locked", "warning": None, "diagnostic": None}
    assert {p.name: p.read_bytes() for p in metadata.iterdir()} == before


@pytest.mark.parametrize(
    "mode,lock", [("success", False), ("export_exit_1", True), ("export_exit_2", True)]
)
def test_fallback_keeps_diagnostic_and_installs_only_project_requirements(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    lock: bool,
):
    metadata = arrange(tmp_path, monkeypatch, lock=lock)
    before = {p.name: p.read_bytes() for p in metadata.iterdir()}
    monkeypatch.setenv("DEPENDENCY_TEST_MODE", mode)
    result = execute(tmp_path)
    assert result.returncode == 0, result.stderr
    recorded = calls(tmp_path)
    assert [c["role"] for c in recorded] == (["uv"] if lock else []) + ["pip-python"]
    assert recorded[-1]["requirements"] == 'ordinary>=1\nconditional; sys_platform == "linux"\n'
    evidence = json.loads((tmp_path / "output/dependencies.json").read_text())
    assert evidence["mode"] == "resolved" and evidence["warning"] in result.stderr
    assert "inconsistent" not in result.stderr
    diagnostic = (tmp_path / "output" / evidence["diagnostic"]).read_text()
    assert ("complete export diagnostic" if lock else "absent") in diagnostic
    assert {p.name: p.read_bytes() for p in metadata.iterdir()} == before


@pytest.mark.parametrize(
    "mode",
    [
        "export_signal",
        "parent_signal",
        "export_exit_130",
        "export_exit_143",
        "pip_fail",
        "missing_uv",
    ],
)
def test_technical_failures_abort_without_another_installation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
):
    arrange(tmp_path, monkeypatch)
    monkeypatch.setenv("DEPENDENCY_TEST_MODE", mode)
    if mode == "missing_uv":
        (tmp_path / "uv").unlink()
    result = execute(tmp_path)
    assert result.returncode != 0
    recorded = calls(tmp_path)
    assert sum(c["role"] == "pip-python" for c in recorded) == (1 if mode == "pip_fail" else 0)
    assert not (tmp_path / "output/dependencies.json").exists()
    assert "resolving from" not in result.stderr


@pytest.mark.parametrize(
    "project",
    [
        "",
        "[project]\nname='empty'",
        '[project]\ndependencies="bad"',
        '[project]\ndynamic=["dependencies"]\ndependencies=[]',
        "[project]\ndependencies=[3]",
        '[project]\ndependencies=["--index-url bad"]',
        '[project]\ndependencies=["a\\nb"]',
    ],
)
def test_invalid_static_metadata_never_installs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project: str,
):
    metadata = arrange(tmp_path, monkeypatch, lock=False)
    (metadata / "pyproject.toml").write_text(project)
    result = execute(tmp_path)
    assert result.returncode != 0 and not calls(tmp_path)
    assert not (tmp_path / "output/dependencies.json").exists()


def test_export_timeout_is_not_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    metadata = arrange(tmp_path, monkeypatch)

    def timed_out(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired("controlled uv", 0.1)

    monkeypatch.setattr(prepare_dependencies.subprocess, "run", timed_out)
    with pytest.raises(subprocess.TimeoutExpired):
        prepare_dependencies.prepare(metadata, tmp_path / "output", str(tmp_path / "pip-python"))
    assert not calls(tmp_path) and not (tmp_path / "output/dependencies.json").exists()


def test_fallback_install_failure_keeps_diagnostic_and_never_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange(tmp_path, monkeypatch, lock=False)
    monkeypatch.setenv("DEPENDENCY_TEST_MODE", "pip_fail")
    result = execute(tmp_path)
    assert result.returncode != 0
    assert [c["role"] for c in calls(tmp_path)] == ["pip-python"]
    assert "absent" in result.stderr
    assert (tmp_path / "output/dependencies.log").read_text() in result.stderr
    assert not (tmp_path / "output/dependencies.json").exists()


def test_silent_export_refusal_still_has_a_retained_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange(tmp_path, monkeypatch)
    monkeypatch.setenv("DEPENDENCY_TEST_MODE", "silent_refusal")
    result = execute(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "uv export exit code: 1" in (tmp_path / "output/dependencies.log").read_text()
    assert json.loads((tmp_path / "output/dependencies.json").read_text())["mode"] == "resolved"
