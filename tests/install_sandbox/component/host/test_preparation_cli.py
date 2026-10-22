"""Exercise preparation allocation, archive, cleanup and the bound native engine."""

import json
import shutil
import subprocess
import zipfile
from dataclasses import asdict
from pathlib import Path

import pytest

from tests.install_sandbox.component.host.native_support import arrange
from tools.install_sandbox.__main__ import main
from tools.install_sandbox.host import output_lifecycle
from tools.install_sandbox.host.coordinator import InstallTestCoordinator
from tools.install_sandbox.host.output_lifecycle import CampaignOutput
from tools.install_sandbox.host.preparation_reader import read_preparation
from tools.install_sandbox.host.result_reader import read_evidence

RUNTIME = Path(__file__).with_name("fake_docker.py")


def git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def package(root: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    subject, spec, context = arrange(root)
    sources = subject / "graphify"
    sources.mkdir()
    for path in tuple(subject.iterdir()):
        if path != sources:
            shutil.move(path, sources / path.name)
    (subject / "pyproject.toml").write_text(
        '[project]\nname="graphifyy"\nversion="1.2.3"\n'
        '[project.scripts]\ngraphify="graphify.cli:main"\n'
    )
    git(subject, "init", "-q")
    git(subject, "add", ".")
    git(
        subject,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.test",
        "commit",
        "-qm",
        "Independent subject",
    )
    data = json.loads(context.read_text())
    data.update(package_root="graphify", revision=git(subject, "rev-parse", "HEAD"))
    context.write_text(json.dumps(data))
    monkeypatch.setenv("FAKE_DOCKER_STATE", str(root / "runtime"))
    return subject, spec, context


def restore(output: Path, destination: Path) -> Path:
    with zipfile.ZipFile(output / "evidence.zip") as archive:
        archive.extractall(destination)
    return destination / "evidence/preparation"


def test_prepare_cli_retains_replay_without_case_or_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject, spec, context = package(tmp_path, monkeypatch)
    output = tmp_path / "published"

    class LocalTransportCoordinator(InstallTestCoordinator):
        def run_campaign(self, **kwargs: object):  # type: ignore[no-untyped-def]
            kwargs["runtime_executable"] = RUNTIME
            return super().run_campaign(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(output_lifecycle, "InstallTestCoordinator", LocalTransportCoordinator)
    # The subject is pinned: later edits must never become expected assets.
    (subject / "graphify/package.md").write_text("Uncommitted change excluded.\n")
    assert (
        main(
            [
                "--prepare-only",
                "--repo",
                str(subject),
                "--spec",
                str(spec),
                "--subject-context",
                str(context),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    report = json.loads((output / "campaign.json").read_text())
    assert report["status"] == "prepared" and report["passed"] is False
    assert report["cases"] == []
    assert report["output_lifecycle"]["archive"] == "verified"
    assert not (output / "evidence").exists()
    assert not list((tmp_path / "runtime").glob("image-*"))
    assert not list((tmp_path / "runtime").glob("container-*"))
    commands = [json.loads(p.read_text()) for p in (tmp_path / "runtime").glob("command-*")]
    runs = [command for command in commands if command[0] == "run"]
    assert len(runs) == 1 and any(arg.endswith("/verify_preparation.py") for arg in runs[0])
    shutil.rmtree(subject)
    shutil.rmtree(tmp_path / "runtime")
    spec.unlink()
    context.unlink()
    proof = restore(output, tmp_path / "readback")
    assert read_preparation(proof).status == "prepared"
    assert (proof / "expected/package.md").read_text() == "# Synthetic package\n"
    assert (proof / "expected/METADATA").read_text() == "Version: 1.2.3\n"
    assert not (proof.parent / "cases").exists()


@pytest.mark.parametrize(
    "fault,status", [("version", "nonconformant"), ("missing-observation", "incomplete")]
)
def test_failed_preparation_is_archived_and_blocks_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str, status: str
) -> None:
    subject, spec, context = package(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_PREPARATION_FAULT", fault)
    result = CampaignOutput(managed_root=tmp_path / "out").run(
        spec_file=spec,
        subject_context_file=context,
        subject_checkout=subject,
        runtime_executable=RUNTIME,
        prepare_only=True,
    )
    assert result.exit_code == 1 and result.output_directory is not None
    assert result.report.execution["status"] == status
    assert result.report.execution["cases"] == []
    proof = restore(result.output_directory, tmp_path / "readback")
    assert read_preparation(proof).status == status


def test_bound_sources_feed_normal_engine_only_through_controlled_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject, spec, context = package(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_CASE_PROGRAM", str(Path(__file__).with_name("binding_case.py")))
    result = InstallTestCoordinator().run_campaign(
        spec_file=spec,
        subject_context_file=context,
        subject_checkout=subject,
        output_directory=tmp_path / "proof",
        runtime_executable=RUNTIME,
    )
    assert result.passed
    assert result.preparation_result is not None
    assert result.preparation_result.status == "prepared"
    reread = read_evidence(tmp_path / "proof/cases/reinstall")
    assert reread.status == "passed"
    saved = json.loads((tmp_path / "proof/cases/reinstall/result.json").read_text())
    assert asdict(reread)["status"] == saved["status"]
    assert all(step["command"] is not None for step in reread.steps)
