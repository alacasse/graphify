from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from . import agent_summary
from . import manifest_projection
from .manifest_projection import ManifestProjectionPlan
from . import reports
from .status import known_status_values


@dataclass(frozen=True)
class HarnessRunResult:
    harness_version: str
    python_version: str
    os_release: dict[str, object]
    architecture: str
    package_install: dict[str, object]
    source_snapshot: dict[str, object]
    preflight: dict[str, object]
    plan: ManifestProjectionPlan
    results: list[dict[str, object]]

    @property
    def passed(self) -> int:
        return sum(1 for result in self.results if result["passed"])

    @property
    def failed(self) -> int:
        return len(self.results) - self.passed

    def manifest(self) -> dict[str, object]:
        projected_plan = manifest_projection.validation_plan_manifest_projection(self.plan, self.results)
        return {
            "harness_version": self.harness_version,
            "python_version": self.python_version,
            "os_release": self.os_release,
            "architecture": self.architecture,
            "graphify_version": self.package_install.get("version"),
            "package_install": self.package_install,
            "source_snapshot": self.source_snapshot,
            "preflight": self.preflight,
            **projected_plan,
            "graphify_file_effect_pass_count": self.passed,
            "graphify_file_effect_fail_count": self.failed,
            "pass_count": self.passed,
            "fail_count": self.failed,
            "results": self.results,
            "risk_status_values": known_status_values(),
        }


def harness_run_result(
    *,
    harness_version: str,
    python_version: str,
    os_release: dict[str, object],
    architecture: str,
    package_install: dict[str, object],
    source_snapshot: dict[str, object],
    preflight: dict[str, object],
    plan: ManifestProjectionPlan,
    results: Iterable[dict[str, object]],
) -> HarnessRunResult:
    return HarnessRunResult(
        harness_version=harness_version,
        python_version=python_version,
        os_release=os_release,
        architecture=architecture,
        package_install=package_install,
        source_snapshot=source_snapshot,
        preflight=preflight,
        plan=plan,
        results=list(results),
    )


def write_harness_run_outputs(output: Path, run_result: HarnessRunResult) -> None:
    manifest = run_result.manifest()
    reports.write_manifest_json(output / "manifest.json", manifest)
    reports.write_report_md(output / "report.md", manifest)
    agent_summary.write_summary(output, agent_summary.summarize_output(output))
    reports.print_summary(output, passed=run_result.passed, failed=run_result.failed)
