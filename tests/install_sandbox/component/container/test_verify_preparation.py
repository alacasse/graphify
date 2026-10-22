"""Verify sandbox behavior at its owning boundary."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.install_sandbox.container import verify_preparation


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
    prefix = "INSTALL_SANDBOX_ENTRY_TIMINGS "
    trace = next(line for line in result.stderr.splitlines() if line.startswith(prefix))
    timing = json.loads(trace.removeprefix(prefix))
    assert timing["entry"] == "verification" and timing["evidence_copy_completed"]
    assert set(timing["seconds"]) == {"initial_imports", "evidence_copy"}
    assert all(value >= 0 for value in timing["seconds"].values())
    assert (output / "dependencies.json").read_bytes() == (
        source / "dependencies.json"
    ).read_bytes()
    assert (output / "dependencies.log").read_text() == "full diagnostic"


def test_failed_evidence_copy_is_timed_and_help_is_not_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(FileNotFoundError):
        verify_preparation.verify(tmp_path / "missing", tmp_path, "must-not-run")
    prefix = "INSTALL_SANDBOX_ENTRY_TIMINGS "
    timing = json.loads(capsys.readouterr().err.removeprefix(prefix))
    assert not timing["evidence_copy_completed"]
    assert timing["seconds"]["evidence_copy"] >= 0


def test_verified_entrypoint_runs_isolated_observer_without_invoking_product(
    tmp_path: Path,
) -> None:
    source, output, binary = tmp_path / "image", tmp_path / "evidence", tmp_path / "bin"
    for path in (source, output, binary):
        path.mkdir()
    (source / "dependencies.json").write_text('{"mode":"locked"}')
    (source / "inputs.json").write_text(
        json.dumps(
            {
                "distribution": "sandbox-intentionally-missing-package",
                "console": "candidate-cli",
                "entry_point": "candidate:main",
                "package_root": "candidate",
            }
        )
    )
    (binary / "python").symlink_to(sys.executable)
    executable = binary / "candidate-cli"
    executable.write_text(
        f"#!{binary / 'python'}\nimport re\nimport sys\nfrom candidate import main\n"
        "if __name__ == '__main__':\n"
        "    sys.argv[0] = re.sub(r'(-script\\.pyw|\\.exe)?$', '', sys.argv[0])\n"
        "    sys.exit(main())\n"
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
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    observed = json.loads((output / "observation.json").read_text())
    assert observed["executable_entry_point"] is True
    assert observed["executable_script"]
    assert "PackageNotFoundError" in observed["errors"][0]
    assert (output / "dependencies.json").read_bytes() == (
        source / "dependencies.json"
    ).read_bytes()
    assert not list(binary.glob("__pycache__"))
