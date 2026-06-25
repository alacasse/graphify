from __future__ import annotations

from typing import Iterable


def validation_plan_manifest_projection(plan: object, results: Iterable[dict[str, object]]) -> dict[str, object]:
    """Project planner-owned data into manifest-ready primitive fields."""
    result_list = list(results)
    coverage_summary = dict(getattr(plan, "platform_coverage_summary"))
    coverage_summary["universal_scenario_count"] = max(0, len(result_list) - len(getattr(plan, "standard_scenarios")))
    return {
        "target_runtime_verification": dict(getattr(plan, "target_runtime_verification")),
        "target_runtime_validation_sections": list(getattr(plan, "target_runtime_validation_sections")),
        "platform_coverage": list(getattr(plan, "coverage_records")),
        "platform_coverage_summary": coverage_summary,
        "scenario_count": len(result_list),
    }
