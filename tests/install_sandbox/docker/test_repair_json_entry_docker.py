"""One real registration restoration proof, with retained JSON after cleanup."""

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


def test_repair_json_entry_docker() -> None:
    run_proof("repair-json-entry", check_case)


def check_case(result: CoordinatedResult) -> None:
    output = result.output_directory
    case = InstallTestCase.from_json(
        (output.parents[1] / "inputs" / f"{output.name}.json").read_text()
    )
    reread = read_result(output, case)
    assert reread == result.test and result.passed, asdict(result)
    preparation = reread.steps[1].get("preparation")
    assert preparation is not None and preparation["ready"]
    assert "altered_content_file" in preparation["plan"]
    dest = destinations(case)
    phases = ("steps/0/after", "steps/1/before", "steps/1/after")
    documents = [json.loads((output / p / "project" / dest["json"]).read_bytes()) for p in phases]
    personal = {"theme": "dark", "instructions": ["my-instructions.md", "team-guidelines.md"]}
    hooks = documents[0]["hooks"]
    assert documents[1] == {**personal, "hooks": hooks}
    for installed in (documents[0], documents[2]):
        assert installed["instructions"].count("skills/graphify/SKILL.md") == 1
        installed["instructions"].remove("skills/graphify/SKILL.md")
        assert installed == {**personal, "hooks": hooks}
    assert (
        json.loads((output / preparation["plan"]["altered_content_file"]).read_bytes()) == personal
    )
    versions = [(output / p / "project" / dest["version"]).read_bytes() for p in phases]
    assert versions[0] == versions[1] == versions[2]
    for witness in case.initial_files:
        if witness["path"] in {dest["json"], dest["markdown"]}:
            continue
        for phase in phases:
            assert (output / phase / witness["root"] / witness["path"]).read_bytes() == witness[
                "content"
            ].encode()
