from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Protocol

from tests.quality_gate_support import (
    PYRIGHT_CONFIG,
    copy_install_sandbox_gate_fixture,
    run_quality_gate,
)


class EnvironmentPatch(Protocol):
    def setenv(self, name: str, value: str) -> None: ...


def _add_replacement_production(repository: Path) -> None:
    source = repository / "tools/install_sandbox/control_plane/request.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def run() -> int:\n    return 0\n",
        encoding="utf-8",
    )

    config_path = repository / PYRIGHT_CONFIG.name
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["strict"].append("tools/install_sandbox/control_plane")
    config_path.write_text(json.dumps(config), encoding="utf-8")


def _add_evidence(repository: Path, evidence_class: str) -> None:
    test = repository / f"tests/install_sandbox/{evidence_class}/test_{evidence_class}_fixture.py"
    test.parent.mkdir(parents=True)
    test.write_text(
        f"def test_{evidence_class}_fixture() -> None:\n    assert True\n",
        encoding="utf-8",
    )


def _convert_to_atomic_cutover(repository: Path) -> None:
    production = repository / "tools/install_sandbox"
    for name in (
        "ci_result.py",
        "docker.py",
        "effects.py",
        "lifecycle.py",
        "models.py",
        "reporting.py",
        "run_artifacts.py",
        "sandbox_runner.py",
        "specs.py",
    ):
        (production / name).unlink()
    shutil.rmtree(production / "specs")
    (production / "Dockerfile").unlink()

    (production / "run.py").write_text(
        "from tools.install_sandbox.control_plane.request import run as run_request\n\n\n"
        "def main() -> int:\n"
        "    return run_request()\n\n\n"
        'if __name__ == "__main__":\n'
        "    raise SystemExit(main())\n",
        encoding="utf-8",
    )
    (production / "ci.py").write_text(
        "def main() -> int:\n    return 0\n",
        encoding="utf-8",
    )
    entrypoint = production / "container/entrypoint.py"
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text("def main() -> int:\n    return 0\n", encoding="utf-8")
    (production / "Containerfile").write_text(
        'ENTRYPOINT ["python", "-m", "tools.install_sandbox.container.entrypoint"]\n',
        encoding="utf-8",
    )

    workflow = repository / ".github/workflows/install-sandbox.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "tools.install_sandbox.ci_result",
            "tools.install_sandbox.ci",
        ),
        encoding="utf-8",
    )

    config_path = repository / PYRIGHT_CONFIG.name
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["strict"] = [
        "tools/install_sandbox",
        "tests/install_sandbox/unit",
        "tests/install_sandbox/component",
        "tests/install_sandbox/behavioral",
    ]
    config_path.write_text(json.dumps(config), encoding="utf-8")


def test_fast_gate_reports_replacement_evidence_not_applicable_during_gate_installation(
    tmp_path: Path,
) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)

    result = run_quality_gate(repository)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "repository state: gate installation" in result.stdout
    assert "[NOT APPLICABLE] unit-evidence" in result.stdout
    assert "[NOT APPLICABLE] component-evidence" in result.stdout
    assert "[NOT APPLICABLE] behavioral-evidence" in result.stdout
    assert "[NOT APPLICABLE] replacement-coverage" in result.stdout


def test_fast_gate_rejects_behavioral_evidence_during_gate_installation(
    tmp_path: Path,
) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    _add_evidence(repository, "behavioral")

    result = run_quality_gate(repository)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "Behavioral Evidence is prohibited before Atomic Cutover" in result.stderr


def test_fast_gate_requires_and_runs_construction_evidence(tmp_path: Path) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    _add_replacement_production(repository)
    _add_evidence(repository, "unit")
    _add_evidence(repository, "component")

    result = run_quality_gate(repository)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "repository state: replacement construction" in result.stdout
    assert "[PASS] unit-component-evidence (exit 0)" in result.stdout
    assert "[NOT APPLICABLE] behavioral-evidence" in result.stdout
    assert "[APPLICABLE] replacement-coverage" in result.stdout


def test_fast_gate_rejects_skipped_construction_evidence(tmp_path: Path) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    _add_replacement_production(repository)
    _add_evidence(repository, "unit")
    _add_evidence(repository, "component")
    unit_test = repository / "tests/install_sandbox/unit/test_unit_fixture.py"
    unit_test.write_text(
        "import pytest\n\n\n"
        '@pytest.mark.skip(reason="placeholder")\n'
        "def test_unit_fixture() -> None:\n"
        "    assert True\n",
        encoding="utf-8",
    )

    result = run_quality_gate(repository)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "[FAIL] unit-component-evidence (exit 1)" in result.stdout
    assert "required evidence produced a non-passing pytest outcome" in result.stderr


def test_fast_gate_rejects_empty_component_evidence(tmp_path: Path) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    _add_replacement_production(repository)
    _add_evidence(repository, "unit")
    (repository / "tests/install_sandbox/component").mkdir(parents=True)

    result = run_quality_gate(repository)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "[PASS] unit-evidence-collection (exit 0)" in result.stdout
    assert "[FAIL] component-evidence-collection (exit 5)" in result.stdout


def test_fast_gate_reports_missing_construction_evidence_as_check_failure(
    tmp_path: Path,
) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    _add_replacement_production(repository)

    result = run_quality_gate(repository)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "[FAIL] unit-evidence-collection (exit 4)" in result.stdout
    assert "[FAIL] component-evidence-collection (exit 4)" in result.stdout


def test_fast_gate_reports_evidence_collection_errors_as_check_failure(
    tmp_path: Path,
) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    _add_replacement_production(repository)
    _add_evidence(repository, "unit")
    _add_evidence(repository, "component")
    unit_test = repository / "tests/install_sandbox/unit/test_unit_fixture.py"
    unit_test.write_text(
        'raise RuntimeError("broken collection")\n\n\n'
        "def test_unit_fixture() -> None:\n"
        "    assert True\n",
        encoding="utf-8",
    )

    result = run_quality_gate(repository)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "[FAIL] unit-evidence-collection (exit 2)" in result.stdout
    assert result.stdout.rstrip().endswith("fast: FAIL")


def test_fast_gate_rejects_behavioral_evidence_before_cutover(tmp_path: Path) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    _add_replacement_production(repository)
    _add_evidence(repository, "unit")
    _add_evidence(repository, "component")
    _add_evidence(repository, "behavioral")

    result = run_quality_gate(repository)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "[FAIL] behavioral-evidence (exit 1)" in result.stdout
    assert "Behavioral Evidence is prohibited before Atomic Cutover" in result.stderr


def test_fast_gate_recognizes_complete_atomic_cutover(tmp_path: Path) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    _add_replacement_production(repository)
    _convert_to_atomic_cutover(repository)
    _add_evidence(repository, "unit")
    _add_evidence(repository, "component")
    _add_evidence(repository, "behavioral")

    result = run_quality_gate(repository)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "repository state: atomic cutover" in result.stdout
    assert "[PASS] unit-component-evidence (exit 0)" in result.stdout
    assert "[APPLICABLE] behavioral-evidence" in result.stdout
    assert "[APPLICABLE] replacement-coverage" in result.stdout


def test_fast_gate_rejects_partial_legacy_deletion(tmp_path: Path) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    (repository / "tools/install_sandbox/effects.py").unlink()

    result = run_quality_gate(repository)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "[FAIL] repository-state (exit 1)" in result.stdout
    assert "mixed repository state" in result.stderr
    assert "legacy implementation paths remain" in result.stderr


def test_fast_gate_rejects_partial_caller_switch(tmp_path: Path) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    _add_replacement_production(repository)
    workflow = repository / ".github/workflows/install-sandbox.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(
            "tools.install_sandbox.ci_result",
            "tools.install_sandbox.ci",
        ),
        encoding="utf-8",
    )

    result = run_quality_gate(repository)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "mixed repository state" in result.stderr
    assert "workflow result caller does not point to the legacy classifier" in result.stderr


def test_fast_gate_rejects_changed_supported_workflow_arguments(tmp_path: Path) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    workflow = repository / ".github/workflows/install-sandbox.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace("--scope both", "--scope user"),
        encoding="utf-8",
    )

    result = run_quality_gate(repository)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "mixed repository state" in result.stderr
    assert "workflow sandbox caller does not use the supported arguments" in result.stderr


def test_fast_gate_rejects_comment_only_workflow_callers(tmp_path: Path) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    workflow = repository / ".github/workflows/install-sandbox.yml"
    workflow.write_text(
        "# python tools/install_sandbox/run.py --all --scope both --output out\n"
        "# python -m tools.install_sandbox.ci_result\n"
        "name: inert fixture\n",
        encoding="utf-8",
    )

    result = run_quality_gate(repository)

    assert result.returncode == 1, result.stdout + result.stderr
    assert (
        "workflow sandbox caller does not point to the supported host entrypoint" in result.stderr
    )
    assert "workflow result caller does not point to the legacy classifier" in result.stderr


def test_fast_gate_rejects_workflow_callers_hidden_in_non_run_scalars(
    tmp_path: Path,
) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    workflow = repository / ".github/workflows/install-sandbox.yml"
    workflow.write_text(
        "name: inert # python tools/install_sandbox/run.py --all --scope both --output out\n"
        "description: inert # python -m tools.install_sandbox.ci_result\n"
        "jobs:\n"
        "  proof:\n"
        "    steps:\n"
        "      - run: echo inert\n",
        encoding="utf-8",
    )

    result = run_quality_gate(repository)

    assert result.returncode == 1, result.stdout + result.stderr
    assert (
        "workflow sandbox caller does not point to the supported host entrypoint" in result.stderr
    )
    assert "workflow result caller does not point to the legacy classifier" in result.stderr


def test_fast_gate_rejects_comment_only_container_caller(tmp_path: Path) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    dockerfile = repository / "tools/install_sandbox/Dockerfile"
    dockerfile.write_text(
        '# tools.install_sandbox.sandbox_runner\nENTRYPOINT ["python", "-m", "unrelated.module"]\n',
        encoding="utf-8",
    )

    result = run_quality_gate(repository)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "harness-image caller does not point to the legacy container entrypoint" in result.stderr


def test_fast_gate_rejects_cutover_without_behavioral_evidence(tmp_path: Path) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    _add_replacement_production(repository)
    _convert_to_atomic_cutover(repository)
    _add_evidence(repository, "unit")
    _add_evidence(repository, "component")

    result = run_quality_gate(repository)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "repository state: atomic cutover" in result.stdout
    assert "[FAIL] behavioral-evidence (exit 1)" in result.stdout
    assert "Atomic Cutover requires non-empty Behavioral Evidence" in result.stderr


def test_fast_gate_rejects_cutover_with_empty_behavioral_test_file(tmp_path: Path) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    _add_replacement_production(repository)
    _convert_to_atomic_cutover(repository)
    _add_evidence(repository, "unit")
    _add_evidence(repository, "component")
    behavioral = repository / "tests/install_sandbox/behavioral/test_empty.py"
    behavioral.parent.mkdir(parents=True)
    behavioral.write_text("", encoding="utf-8")

    result = run_quality_gate(repository)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "Atomic Cutover requires non-empty Behavioral Evidence" in result.stderr


def test_fast_gate_requires_run_to_invoke_replacement_control_plane(tmp_path: Path) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    _add_replacement_production(repository)
    _convert_to_atomic_cutover(repository)
    _add_evidence(repository, "unit")
    _add_evidence(repository, "component")
    _add_evidence(repository, "behavioral")
    run = repository / "tools/install_sandbox/run.py"
    run.write_text(
        "import tools.install_sandbox.control_plane.request as request\n\n"
        "CONTROL_PLANE = request\n",
        encoding="utf-8",
    )

    result = run_quality_gate(repository)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "operator caller does not invoke the replacement Host Control Plane" in result.stderr


def test_fast_gate_rejects_cutover_with_legacy_import(tmp_path: Path) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    _add_replacement_production(repository)
    _convert_to_atomic_cutover(repository)
    source = repository / "tools/install_sandbox/control_plane/request.py"
    source.write_text(
        "from tools.install_sandbox.effects import Effect\n\n\n"
        "def run() -> int:\n"
        "    return 0 if Effect else 1\n",
        encoding="utf-8",
    )

    result = run_quality_gate(repository)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "forbidden legacy import" in result.stderr
    assert "tools.install_sandbox.effects" in result.stderr


def test_fast_gate_rejects_cutover_with_repository_legacy_import(tmp_path: Path) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    _add_replacement_production(repository)
    _convert_to_atomic_cutover(repository)
    _add_evidence(repository, "unit")
    _add_evidence(repository, "component")
    _add_evidence(repository, "behavioral")
    consumer = repository / "graphify/legacy_consumer.py"
    consumer.parent.mkdir()
    consumer.write_text(
        "from tools.install_sandbox.effects import Effect\n\nVALUE = Effect\n",
        encoding="utf-8",
    )

    result = run_quality_gate(repository)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "forbidden legacy import in graphify/legacy_consumer.py" in result.stderr


def test_fast_gate_rejects_cutover_with_dynamic_legacy_invocation(tmp_path: Path) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    _add_replacement_production(repository)
    _convert_to_atomic_cutover(repository)
    _add_evidence(repository, "unit")
    _add_evidence(repository, "component")
    _add_evidence(repository, "behavioral")
    consumer = repository / "graphify/legacy_consumer.py"
    consumer.parent.mkdir()
    consumer.write_text(
        "import subprocess\n\n\n"
        "def invoke() -> subprocess.CompletedProcess[bytes]:\n"
        "    return subprocess.run(\n"
        '        ["python", "-m", "tools.install_sandbox.effects"], check=False\n'
        "    )\n",
        encoding="utf-8",
    )

    result = run_quality_gate(repository)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "forbidden legacy invocation in graphify/legacy_consumer.py" in result.stderr


def test_fast_gate_allows_legacy_commands_as_non_executed_fixture_text(tmp_path: Path) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    _add_replacement_production(repository)
    _convert_to_atomic_cutover(repository)
    _add_evidence(repository, "unit")
    _add_evidence(repository, "component")
    _add_evidence(repository, "behavioral")
    fixture_builder = repository / "graphify/fixture_builder.py"
    fixture_builder.parent.mkdir()
    fixture_builder.write_text(
        "from pathlib import Path\n\n\n"
        "def write_fixture(target: Path) -> None:\n"
        '    target.write_text("python -m tools.install_sandbox.effects\\n")\n',
        encoding="utf-8",
    )

    result = run_quality_gate(repository)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "repository state: atomic cutover" in result.stdout


def test_fast_gate_rejects_cutover_with_legacy_workflow_invocation(tmp_path: Path) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    _add_replacement_production(repository)
    _convert_to_atomic_cutover(repository)
    _add_evidence(repository, "unit")
    _add_evidence(repository, "component")
    _add_evidence(repository, "behavioral")
    workflow = repository / ".github/workflows/legacy.yml"
    workflow.write_text(
        "name: forbidden caller\n"
        "jobs:\n"
        "  invoke:\n"
        "    steps:\n"
        "      - run: python -m tools.install_sandbox.effects\n",
        encoding="utf-8",
    )

    result = run_quality_gate(repository)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "forbidden legacy invocation in .github/workflows/legacy.yml" in result.stderr


def test_fast_gate_does_not_confuse_third_party_module_name_with_legacy_import(
    tmp_path: Path,
) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    _add_replacement_production(repository)
    _convert_to_atomic_cutover(repository)
    _add_evidence(repository, "unit")
    _add_evidence(repository, "component")
    _add_evidence(repository, "behavioral")
    package = repository / "domain"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "models.py").write_text('VALUE: str = "fixture"\n', encoding="utf-8")
    source = repository / "tools/install_sandbox/control_plane/request.py"
    source.write_text(
        "import domain.models as domain_models\n\n\n"
        "def run() -> int:\n"
        "    return 0 if domain_models.VALUE else 1\n",
        encoding="utf-8",
    )

    result = run_quality_gate(repository)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "repository state: atomic cutover" in result.stdout


def test_fast_gate_does_not_select_state_from_marker_file(tmp_path: Path) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    (repository / ".install-sandbox-phase").write_text("atomic-cutover\n", encoding="utf-8")

    result = run_quality_gate(repository)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "repository state: gate installation" in result.stdout


def test_fast_gate_does_not_select_state_from_environment(
    tmp_path: Path,
    monkeypatch: EnvironmentPatch,
) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    monkeypatch.setenv("INSTALL_SANDBOX_PHASE", "atomic-cutover")

    result = run_quality_gate(repository)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "repository state: gate installation" in result.stdout


def test_fast_gate_does_not_treat_import_names_in_text_as_caller_relationships(
    tmp_path: Path,
) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    run = repository / "tools/install_sandbox/run.py"
    run.write_text(
        '"""tools.install_sandbox.docker\n'
        "tools.install_sandbox.run_artifacts\n"
        'tools.install_sandbox.specs"""\n\n\n'
        "def main() -> int:\n"
        "    return 0\n",
        encoding="utf-8",
    )
    config_path = repository / PYRIGHT_CONFIG.name
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["strict"].append("tools/install_sandbox/run.py")
    config_path.write_text(json.dumps(config), encoding="utf-8")

    result = run_quality_gate(repository)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "mixed repository state" in result.stderr
    assert "operator caller does not point to the complete legacy host entrypoint" in result.stderr


def test_fast_gate_lints_applicable_evidence_paths(tmp_path: Path) -> None:
    repository = copy_install_sandbox_gate_fixture(tmp_path)
    _add_replacement_production(repository)
    _add_evidence(repository, "unit")
    _add_evidence(repository, "component")
    unit_test = repository / "tests/install_sandbox/unit/test_unit_fixture.py"
    unit_test.write_text(
        "MESSAGE = 'not formatted'\n\n\ndef test_unit_fixture() -> None:\n    assert MESSAGE\n",
        encoding="utf-8",
    )

    result = run_quality_gate(repository)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "tests/install_sandbox/unit/test_unit_fixture.py" in result.stdout
    assert "[FAIL] ruff-format (exit 1)" in result.stdout
