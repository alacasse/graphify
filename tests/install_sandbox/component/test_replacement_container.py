from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path


def _run(*argv: str, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_replacement_image_emits_one_complete_fictional_diagnostic(tmp_path: Path) -> None:
    image = f"graphify-install-sandbox-replacement:pytest-{os.getpid()}"
    output = tmp_path / "diagnostic"
    output.mkdir()
    try:
        built = _run(
            "docker",
            "build",
            "--file",
            "tools/install_sandbox/Containerfile",
            "--tag",
            image,
            ".",
            timeout=300,
        )
        assert built.returncode == 0, built.stderr

        completed = _run(
            "docker",
            "run",
            "--rm",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--env",
            "GRAPHIFY_RUN_ID=component-run",
            "--env",
            "GRAPHIFY_IMAGE_ID=sha256:component-image",
            "--volume",
            f"{output}:/diagnostic:rw,Z",
            image,
            timeout=180,
        )
        assert completed.returncode == 0, completed.stderr

        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["selection"] == {
            "targets": ["fictional"],
            "scopes": ["user", "project"],
        }
        assert manifest["run"]["subject_identity"] == "graphify-fictional@1.0.0"
        assert manifest["subject"]["published_targets"] == ["fictional"]
        assert manifest["subject"]["version"] == "1.0.0"
        assert [Path(path).name for path in manifest["subject"]["commands"]] == [
            "00-build-subject.json",
            "01-create-environment.json",
            "02-install-subject.json",
            "03-probe-origins.json",
            "04-probe-version.json",
            "05-probe-targets.json",
        ]
        assert {item["kind"] for item in manifest["validation_plan"]["scenarios"]} == {
            "target-lifecycle",
            "aggregate-uninstall",
            "scope-isolation",
        }
        assert [item["status"] for item in manifest["scenarios"]] == [
            "PASS",
            "PASS",
            "PASS",
            "PASS",
            "PASS",
            "PASS",
        ]
        assert manifest["purge"]["status"] == "PASS"
        assert len(manifest["runtime_limitations"]) == 3
        for reference in manifest["evidence"]:
            payload = (output / reference["path"]).read_bytes()
            assert reference["sha256"] == hashlib.sha256(payload).hexdigest()

    finally:
        _run("docker", "image", "rm", "--force", image)
