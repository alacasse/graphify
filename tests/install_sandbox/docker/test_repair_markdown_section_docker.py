"""One real Markdown repair proof, with retained source and personal text after cleanup."""

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


def test_repair_markdown_section_docker() -> None:
    run_proof("repair-markdown-section", check_case)


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
    source = (output / "expected" / case.spec.markdown_source).read_bytes()
    first = (output / "steps/0/after/project" / dest["markdown"]).read_bytes()
    degraded = (output / "steps/1/before/project" / dest["markdown"]).read_bytes()
    repaired = (output / "steps/1/after/project" / dest["markdown"]).read_bytes()
    prefix = b"# My project\n\n## Language\nRespond in English.\n\n"
    suffix = b"## Changes\nExplain proposed changes.\n"
    assert first == repaired == prefix + source.rstrip(b"\n") + b"\n\n" + suffix
    assert (
        degraded
        == prefix
        + case.spec.markdown_marker.encode()
        + b"\nSandbox altered Markdown section.\n\n"
        + suffix
    )
    assert degraded != first
    assert (output / preparation["plan"]["altered_content_file"]).read_bytes() == degraded
    versions = [
        (output / phase / "project" / dest["version"]).read_bytes()
        for phase in (
            "steps/0/after",
            "steps/1/before",
            "steps/1/after",
        )
    ]
    assert versions[0] == versions[1] == versions[2]
