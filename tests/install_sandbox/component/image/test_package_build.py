"""Run the candidate build shell with controlled pip, without Docker or installation."""

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

_CONTAINERFILE = Path(__file__).resolve().parents[4] / "tools/install_sandbox/image/Containerfile"


def instructions() -> list[str]:
    return _CONTAINERFILE.read_text().replace("\\\n", " ").splitlines()


def test_dependency_inputs_precede_candidate_and_runtime_sources() -> None:
    lines = instructions()
    metadata = next(i for i, line in enumerate(lines) if line.startswith("COPY metadata/"))
    dependencies = next(i for i, line in enumerate(lines) if line.startswith("RUN python -I"))
    sources = next(i for i, line in enumerate(lines) if line.startswith("COPY subject/"))
    package = next(i for i, line in enumerate(lines) if line.startswith("RUN cp -a"))
    runtime = next(
        i for i, line in enumerate(lines) if "COPY --chmod" in line and "contracts/" in line
    )
    assert metadata < dependencies < sources < package < runtime
    assert not any("subject" in line or "contracts/" in line for line in lines[:dependencies])
    assert any(
        line.startswith("COPY --from=ghcr.io/astral-sh/uv:0.11.6@sha256:")
        and line.endswith(" /uv /usr/local/bin/uv")
        for line in lines
    )


@pytest.mark.parametrize("failure", ["none", "install", "check"])
def test_package_build_uses_current_copy_and_propagates_pip_failure(
    tmp_path: Path, failure: str
) -> None:
    image = tmp_path / "image"
    reference = image / "reference"
    reference.mkdir(parents=True)
    (reference / "code.py").write_text("current captured sources")
    python = image / "venv/bin/python"
    python.parent.mkdir(parents=True)
    log = tmp_path / "pip.jsonl"
    python.write_text(
        f"#!{sys.executable}\nimport json, sys\nfrom pathlib import Path\n"
        f"with Path({str(log)!r}).open('a') as stream:\n"
        "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if sys.argv[3] == 'install':\n"
        "    assert '--no-deps' in sys.argv and '--no-build-isolation' not in sys.argv\n"
        "    source = Path(sys.argv[-1]) / 'code.py'\n"
        "    assert source.read_text() == 'current captured sources'\n"
        "    source.write_text('build modified its own copy')\n"
        f"raise SystemExit(9 if sys.argv[3] == {failure!r} else 0)\n"
    )
    python.chmod(0o755)
    command = next(line[4:] for line in instructions() if line.startswith("RUN cp -a"))
    command = command.replace("/opt/install-sandbox", shlex.quote(str(image)))
    command = command.replace("/tmp/package", shlex.quote(str(tmp_path / "package")))
    result = subprocess.run(["/bin/sh", "-c", command], check=False, capture_output=True, text=True)
    assert result.returncode == (0 if failure == "none" else 9), result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert [c[2] for c in calls] == (["install"] if failure == "install" else ["install", "check"])
    assert (reference / "code.py").read_text() == "current captured sources"
    if failure == "none":
        assert not (tmp_path / "package").exists()
