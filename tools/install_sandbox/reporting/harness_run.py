from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from . import manifest_projection
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
    plan: object
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
    plan: object,
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
