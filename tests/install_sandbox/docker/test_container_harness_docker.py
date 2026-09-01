from __future__ import annotations

import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from tools.install_sandbox.container_harness import (
    ContainerHarness,
    ContainerProbeRequest,
    ContainerProbeResult,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("INSTALL_SANDBOX_RUN_DOCKER_TESTS") != "1",
    reason="set INSTALL_SANDBOX_RUN_DOCKER_TESTS=1 to run Docker Evidence",
)


def test_live_docker_probe_attests_isolation_and_caller_ownership(tmp_path: Path) -> None:
    subject = _subject(tmp_path)
    output = tmp_path / "output"

    result = ContainerHarness().run_probe(_request(subject, output))

    assert result.state == "passed", result
    assert result.phase == "complete"
    assert result.exit_code == 0
    assert result.cleanup_complete
    assert result.image_id is not None and result.image_id.startswith("sha256:")
    assert result.attestation_path == output / "infrastructure-probe.json"
    assert result.attestation_path is not None
    document = json.loads(result.attestation_path.read_text(encoding="utf-8"))
    assert document["checks"] == {
        "output_write_succeeded": True,
        "roots_distinct": True,
        "subject_mount_read_only": True,
        "subject_write_rejected": True,
    }
    assert document["image_payload"] == ["probe.py"]
    result.attestation_path.write_text("caller-owned", encoding="utf-8")
    result.attestation_path.unlink()


def test_two_live_processes_keep_their_resources_and_outputs_separate(tmp_path: Path) -> None:
    subject = _subject(tmp_path)
    start_at = time.monotonic() + 1.0
    requests = [
        _request(subject, tmp_path / "output-a"),
        _request(subject, tmp_path / "output-b"),
    ]

    with ProcessPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(_run_at, requests, [start_at, start_at]))

    assert all(result.state == "passed" for result in results), results
    assert all(result.cleanup_complete for result in results)
    assert len({result.run_id for result in results}) == 2
    for result in results:
        assert result.attestation_path is not None
        document = json.loads(result.attestation_path.read_text(encoding="utf-8"))
        assert document["run_id"] == result.run_id


def _subject(tmp_path: Path) -> Path:
    subject = tmp_path / "subject"
    subject.mkdir()
    (subject / "README.md").write_text("read-only subject", encoding="utf-8")
    return subject


def _request(subject: Path, output: Path) -> ContainerProbeRequest:
    return ContainerProbeRequest(subject_checkout=subject, output_directory=output)


def _run_at(request: ContainerProbeRequest, start_at: float) -> ContainerProbeResult:
    while time.monotonic() < start_at:
        time.sleep(0.01)
    return ContainerHarness().run_probe(request)
