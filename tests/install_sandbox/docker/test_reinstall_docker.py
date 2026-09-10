"""One opted-in real reinstall case, with both steps reread after Docker cleanup."""

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


def test_reinstall_docker() -> None:
    run_proof("reinstall", check_case)


def check_case(result: CoordinatedResult) -> None:
    output = result.output_directory
    case = InstallTestCase.from_json(
        (output.parents[1] / "inputs" / f"{output.name}.json").read_text()
    )
    assert case.operations == ["install", "install"]
    reread = read_result(output, case)
    assert result.test == reread and result.passed, asdict(result)
    dest = destinations(case)
    first, second = reread.steps
    assert first["command"] is not None and second["command"] is not None
    assert first["command"]["args"] == second["command"]["args"]
    assert first["command"]["cwd"] == second["command"]["cwd"]
    versions = [
        (output / f"steps/{i}/after/project" / dest["version"]).read_bytes() for i in (0, 1)
    ]
    assert versions[0] == versions[1]
    for relative in ("steps/0/before.json", "steps/0/after.json", "steps/1/after.json"):
        snapshot = json.loads((output / relative).read_bytes())
        assert not snapshot["obstacles"]
        assert not any(
            entry["root"] == "project" and entry["path"] == dest["skill"] + ".bak"
            for entry in snapshot["entries"]
        )
