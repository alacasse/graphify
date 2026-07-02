from __future__ import annotations

import importlib
from pathlib import Path


INSTALL_SANDBOX_ROOT = Path(__file__).parents[2] / "tools" / "install_sandbox"
TESTS_ROOT = Path(__file__).parents[2] / "tests"

ARTIFACT_VOCABULARY_DOCS = (
    INSTALL_SANDBOX_ROOT / "README.md",
    INSTALL_SANDBOX_ROOT / "specs" / "README.md",
)

PUBLIC_ARTIFACT_OUTPUT_PATHS = (
    INSTALL_SANDBOX_ROOT / "reporting",
    TESTS_ROOT / "install_sandbox" / "test_agent_summary.py",
    TESTS_ROOT / "install_sandbox" / "test_reports.py",
    TESTS_ROOT / "install_sandbox" / "test_sandbox_runner.py",
    TESTS_ROOT / "install_sandbox" / "test_validation_plan_compatibility.py",
)

ARTIFACT_OUTPUT_LEGACY_VOCABULARY = {
    "platform_coverage",
    "platform_coverage_summary",
    "Platform Coverage",
}

TARGET_NAMED_ARTIFACT_VOCABULARY = {
    "target_coverage",
    "target_coverage_summary",
    "Target Coverage",
}

ALLOWED_ARTIFACT_LEGACY_VOCABULARY_LINES = {
    'coverage_source = manifest.get("target_coverage") if "target_coverage" in manifest else manifest.get("platform_coverage")',
    "legacy_platform_coverage_input_only_manifest,",
    'def test_report_reads_legacy_platform_coverage_as_transitional_input_only() -> None:',
    "manifest = legacy_platform_coverage_input_only_manifest()",
    "markdown = reports.render_report_md(legacy_platform_coverage_input_only_manifest())",
    '"platform_coverage": [',
    'assert "## Platform Coverage" not in markdown',
    'def test_report_prefers_explicit_empty_target_coverage_over_stale_legacy_rows() -> None:',
    '"platform_coverage" not in manifest',
    '"platform_coverage_summary" not in manifest',
    '"platform_coverage" not in projected',
    '"platform_coverage_summary" not in projected',
    '"platform_coverage",',
    '"platform_coverage_summary",',
    'platform_coverage = ({"platform": "legacy-alias", "status": "must-not-project"},)',
    'platform_coverage = ({"platform": "internal-alias", "status": "must-not-project"},)',
    'platform_coverage_summary = {"requested_scope": "legacy"}',
    'kwargs[alias_name] = () if alias_name != "platform_coverage" else ()',
}

DEFERRED_PRODUCT_PLATFORM_VOCABULARY = {
    "--platform": "LR-B9 product CLI flag",
    "platforms": "YAML",
}


def _text_files(paths: tuple[Path, ...]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(child for child in path.rglob("*") if child.suffix in {".py", ".md"}))
        else:
            files.append(path)
    return files


def test_current_generated_artifact_docs_use_target_vocabulary() -> None:
    for path in ARTIFACT_VOCABULARY_DOCS:
        text = path.read_text(encoding="utf-8")
        assert "target_coverage" in text
        assert "target_coverage_summary" in text
        assert "Target Coverage" in text or path.name == "README.md" and path.parent.name == "specs"
        assert "Platform Coverage" not in text


def test_legacy_platform_coverage_stays_out_of_current_artifact_outputs() -> None:
    offenders: list[str] = []

    for path in _text_files(PUBLIC_ARTIFACT_OUTPUT_PATHS):
        relative = path.relative_to(Path(__file__).parents[2]).as_posix()
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not any(term in line for term in ARTIFACT_OUTPUT_LEGACY_VOCABULARY):
                continue
            stripped = line.strip()
            if stripped in ALLOWED_ARTIFACT_LEGACY_VOCABULARY_LINES:
                continue
            if "transitional input" in stripped or "must-not-project" in stripped:
                continue
            if "not in" in stripped:
                continue
            offenders.append(f"{relative}:{lineno}: {stripped}")

    assert offenders == []


def test_public_platform_vocabulary_remains_documented_as_product_edge_contract() -> None:
    docs_text = "\n".join(path.read_text(encoding="utf-8") for path in ARTIFACT_VOCABULARY_DOCS)

    for vocabulary, classification in DEFERRED_PRODUCT_PLATFORM_VOCABULARY.items():
        assert vocabulary in docs_text
        assert classification in docs_text


def test_harness_run_projects_target_named_validation_plan_manifest_fields() -> None:
    harness_run = importlib.import_module("tools.install_sandbox.reporting.harness_run")

    class Plan:
        standard_validation_count = 1
        coverage_records = ({"target": "codex", "scope": "project", "status": "runnable"},)
        target_runtime_validation_sections = ({"section_title": "Runtime Boundary", "status": "declared"},)
        target_coverage_summary = {"requested_scope": "project", "universal_scenario_count": 0}
        target_runtime_verification = {"performed": False}

    manifest = harness_run.harness_run_result(
        harness_version="test",
        python_version="3.12",
        os_release={},
        architecture="x86_64",
        package_install={"version": "9.9.9"},
        source_snapshot={},
        preflight={},
        plan=Plan(),
        results=[{"id": "codex-project", "passed": True}, {"id": "universal-cleanup", "passed": True}],
    ).manifest()

    assert set(TARGET_NAMED_ARTIFACT_VOCABULARY) == {
        "target_coverage",
        "target_coverage_summary",
        "Target Coverage",
    }
    assert manifest["target_runtime_verification"] == {"performed": False}
    assert manifest["target_runtime_validation_sections"] == [{"section_title": "Runtime Boundary", "status": "declared"}]
    assert manifest["target_coverage"] == [{"target": "codex", "scope": "project", "status": "runnable"}]
    assert manifest["target_coverage_summary"]["universal_scenario_count"] == 1
    assert manifest["scenario_count"] == 2
