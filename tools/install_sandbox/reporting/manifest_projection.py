from __future__ import annotations

from typing import Iterable, Protocol, Sequence


class ManifestProjectionPlan(Protocol):
    standard_validation_count: int
    coverage_records: Sequence[dict[str, object]]
    target_runtime_validation_sections: Sequence[dict[str, object]]
    platform_coverage_summary: dict[str, object]
    target_runtime_verification: dict[str, object]


def validation_plan_manifest_projection(plan: ManifestProjectionPlan, results: Iterable[dict[str, object]]) -> dict[str, object]:
    """Project planner-owned data into manifest-ready primitive fields."""
    result_list = list(results)
    coverage_summary = dict(plan.platform_coverage_summary)
    coverage_summary["universal_scenario_count"] = max(0, len(result_list) - plan.standard_validation_count)
    return {
        "target_runtime_verification": dict(plan.target_runtime_verification),
        "target_runtime_validation_sections": list(plan.target_runtime_validation_sections),
        "platform_coverage": list(plan.coverage_records),
        "platform_coverage_summary": coverage_summary,
        "scenario_count": len(result_list),
    }
