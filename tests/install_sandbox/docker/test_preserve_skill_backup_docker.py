"""One real backup preservation proof, reread after owned Docker cleanup."""

import json
import os
from dataclasses import asdict

import pytest

from tests.install_sandbox.docker.test_first_install_docker import run_proof
from tools.install_sandbox.case import InstallTestCase
from tools.install_sandbox.coordinator import CoordinatedResult
from tools.install_sandbox.environment import destinations
from tools.install_sandbox.result_reader import read_result

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INSTALL_SANDBOX_DOCKER") != "1",
    reason="Set RUN_INSTALL_SANDBOX_DOCKER=1 to run one real Docker case",
)


def test_preserve_skill_backup_docker() -> None:
    run_proof("preserve-skill-backup", _check_case)


def _check_case(result: CoordinatedResult) -> None:
    output = result.output_directory
    case = InstallTestCase.from_json((output.parent / "case.json").read_text())
    reread = read_result(output, case)
    assert reread == result.test and result.passed, asdict(result)
    preparation = reread.steps[1].get("preparation")
    assert preparation is not None and preparation["ready"]
    assert "backup_content_file" in preparation["plan"]
    dest = destinations(case)
    skill, version = dest["skill"], dest["version"]
    source = (output / "expected" / case.spec.skill_source).read_bytes()
    backup = source + b"\nSandbox previous backup witness.\n"
    first = output / "steps/0/after/project"
    prepared = output / "steps/1/before/project"
    final = output / "steps/1/after/project"
    assert (first / skill).read_bytes() == source
    assert (prepared / skill).read_bytes() == source
    assert (prepared / (skill + ".bak")).read_bytes() == backup
    assert (final / skill).read_bytes() == source
    assert (final / (skill + ".bak")).read_bytes() == backup
    assert (output / preparation["plan"]["backup_content_file"]).read_bytes() == backup
    assert (
        (first / version).read_bytes()
        == (prepared / version).read_bytes()
        == (final / version).read_bytes()
    )
    snapshot = json.loads((output / "steps/0/after.json").read_bytes())
    assert not snapshot["obstacles"]
    assert not any(e["path"] == skill + ".bak" for e in snapshot["entries"])
