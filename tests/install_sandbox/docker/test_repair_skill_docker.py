"""One real skill repair and backup proof, reread after owned Docker cleanup."""

import json
import os
from dataclasses import asdict

import pytest

from tests.install_sandbox.docker.test_first_install_docker import run_proof
from tools.install_sandbox.contracts.case import InstallTestCase, destinations
from tools.install_sandbox.host.coordinator import CoordinatedResult
from tools.install_sandbox.host.result_reader import read_result

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INSTALL_SANDBOX_DOCKER") != "1",
    reason="Set RUN_INSTALL_SANDBOX_DOCKER=1 to run one real Docker case",
)


def test_repair_skill_docker() -> None:
    run_proof("repair-skill", check_case)


def check_case(result: CoordinatedResult) -> None:
    output = result.output_directory
    case = InstallTestCase.from_json(
        (output.parents[1] / "inputs" / f"{output.name}.json").read_text()
    )
    reread = read_result(output, case)
    assert reread == result.test and result.passed, asdict(result)
    preparation = reread.steps[1].get("preparation")
    assert preparation is not None and preparation["ready"]
    assert "deleted_path" not in preparation["plan"]
    assert "altered_content_file" in preparation["plan"]
    dest = destinations(case)
    skill, version = dest["skill"], dest["version"]
    source = (output / "expected" / case.spec.skill_source).read_bytes()
    altered = source + b"\nSandbox skill repair witness.\n"
    first = output / "steps/0/after/project"
    degraded = output / "steps/1/before/project"
    repaired = output / "steps/1/after/project"
    assert (first / skill).read_bytes() == source
    assert (degraded / skill).read_bytes() == altered
    assert (repaired / skill).read_bytes() == source
    assert (repaired / (skill + ".bak")).read_bytes() == altered
    assert (output / preparation["plan"]["altered_content_file"]).read_bytes() == altered
    assert (
        (first / version).read_bytes()
        == (degraded / version).read_bytes()
        == (repaired / version).read_bytes()
    )
    for relative in ("steps/0/after.json", "steps/1/before.json"):
        snapshot = json.loads((output / relative).read_bytes())
        assert not snapshot["obstacles"]
        assert not any(e["path"] == skill + ".bak" for e in snapshot["entries"])
