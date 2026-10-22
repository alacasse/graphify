"""Selected integration counterexamples joining the independently tested layers."""

import json
import shutil
from pathlib import Path

import pytest

from tests.install_sandbox.component.host.native_support import LiteralInstaller, arrange, write
from tools.install_sandbox.container.installer import InstallerCommandResult, InstallerDriver
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.effect_case import SubjectContext, build_reinstall_case
from tools.install_sandbox.host.effect_reader import EffectSpecReader
from tools.install_sandbox.host.result_reader import read_evidence


def prepared(root: Path) -> Path:
    subject, spec, context = arrange(root)
    case = build_reinstall_case(
        EffectSpecReader().read(spec), SubjectContext.from_data(json.loads(context.read_text()))
    )
    case.write(root / "case.json")
    return subject


def run(root: Path, driver: InstallerDriver):
    return InstallTestRunner(driver).run_case(
        reference_sources=root / "subject",
        prepared_executable=root / "fake-installer",
        case_file=root / "case.json",
        work_directory=root / "work",
        output_directory=root / "proof",
    )


def remove_inputs(root: Path) -> None:
    for name in ("subject", "work"):
        shutil.rmtree(root / name)
    for name in ("case.json", "effects.yaml", "context.json"):
        (root / name).unlink()


@pytest.mark.parametrize(
    "phase,root_name,path,content",
    [
        (1, "home", ".synthetic/skills/package/SKILL.md", "wrong skill"),
        (1, "home", ".synthetic/skills/package/.graphify_version", "9.9.9"),
        (1, "home", ".synthetic/skills/package/references/nested/reference.md", "wrong reference"),
        (2, "project", ".synthetic/config.json.graphify-bak", "replaced backup"),
        (2, "project", "GUIDE.md", "## graphify\nConsult the synthetic map.\n"),
        (2, "home", "foreign-file", "unannounced effect"),
    ],
)
def test_counterexamples_fail_and_replay_after_input_removal(
    tmp_path: Path, phase: int, root_name: str, path: str, content: str
) -> None:
    prepared(tmp_path)
    installer = LiteralInstaller()

    def execute(
        args: list[str], cwd: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        result = installer.execute(args, cwd, environment, timeout)
        if len(installer.calls) == phase:
            directory = cwd if root_name == "project" else Path(environment["HOME"])
            write(directory / path, content)
        return result

    result = run(tmp_path, InstallerDriver(execute))
    assert result.status == "failed"
    assert len(installer.calls) == phase
    verdict = result.steps[phase - 1]["verification"]
    assert verdict is not None and any(item.path == path for item in verdict.mismatches)
    remove_inputs(tmp_path)
    assert read_evidence(tmp_path / "proof") == result


def test_new_nested_source_is_required_without_yaml_change(tmp_path: Path) -> None:
    subject = prepared(tmp_path)
    write(subject / "reference-data/new/nested.md", "Additional source.\n")
    installer = LiteralInstaller()
    result = run(tmp_path, InstallerDriver(installer.execute))
    assert result.status == "failed" and len(installer.calls) == 1
    verdict = result.steps[0]["verification"]
    assert verdict is not None
    assert any(item.path.endswith("references/new/nested.md") for item in verdict.mismatches)
    remove_inputs(tmp_path)
    assert read_evidence(tmp_path / "proof") == result


def test_source_changes_after_capture_do_not_redefine_expected_bytes(tmp_path: Path) -> None:
    subject = prepared(tmp_path)
    installer = LiteralInstaller()

    def execute(
        args: list[str], cwd: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        (subject / "package.md").write_text("Changed after capture")
        return installer.execute(args, cwd, environment, timeout)

    result = run(tmp_path, InstallerDriver(execute))
    assert result.status == "passed" and len(installer.calls) == 2
    remove_inputs(tmp_path)
    assert read_evidence(tmp_path / "proof") == result
