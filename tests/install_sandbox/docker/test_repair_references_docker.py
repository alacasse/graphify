"""One opted-in repair proof, with all three states reread after real Docker cleanup."""

import json
import os
from dataclasses import asdict

import pytest

from tests.install_sandbox.docker.test_first_install_docker import run_proof
from tools.install_sandbox.case import InstallTestCase
from tools.install_sandbox.environment import destinations
from tools.install_sandbox.result_reader import read_result

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INSTALL_SANDBOX_DOCKER") != "1",
    reason="Set RUN_INSTALL_SANDBOX_DOCKER=1 to run one real Docker case",
)


def test_repair_references_docker() -> None:
    result = run_proof("repair-references")
    output = result.output_directory
    case = InstallTestCase.from_json((output.parent / "case.json").read_text())
    reread = read_result(output, case)
    assert result.test == reread and result.passed, asdict(result)
    preparation = reread.steps[1].get("preparation")
    assert preparation is not None and preparation["ready"]
    plan = preparation["plan"]
    first = output / "steps/0/after/project"
    degraded = output / "steps/1/before/project"
    repaired = output / "steps/1/after/project"
    assert (first / plan["deleted_path"]).read_bytes() == (
        repaired / plan["deleted_path"]
    ).read_bytes()
    assert not (degraded / plan["deleted_path"]).exists()
    expected = (first / plan["altered_path"]).read_bytes()
    assert (
        degraded / plan["altered_path"]
    ).read_bytes() == expected + b"\nSandbox repair witness.\n"
    assert (repaired / plan["altered_path"]).read_bytes() == expected
    version = destinations(case)["version"]
    assert (
        (first / version).read_bytes()
        == (degraded / version).read_bytes()
        == (repaired / version).read_bytes()
    )
    snapshot = json.loads((output / "steps/1/before.json").read_bytes())
    assert not snapshot["obstacles"]
    assert not any(e["path"] == plan["deleted_path"] for e in snapshot["entries"])
