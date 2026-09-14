"""Plain-language duration report; container details are never added to host totals."""

from tools.install_sandbox.contracts.results import InstallTestResult
from tools.install_sandbox.contracts.timings import Timing
from tools.install_sandbox.host.coordinator import CampaignResult, CoordinatedResult

_LABELS = {
    "inputs": "Prepare campaign inputs",
    "verify": "Verify the prepared package and clean its container",
    "case": "Prepare the case",
    "preflight": "Check Docker",
    "build": "Build the image",
    "run": "Run the container and wait for its exit",
    "cleanup": "Clean owned resources",
    "read": "Read and validate evidence",
    "copy_sources": "Copy product sources",
    "venv": "Create the Python environment",
    "pip": "Install the package and dependencies",
    "initial": "Prepare and check the initial state",
    "command": "Run the installation command",
    "checks": "Observe, verify and save evidence",
    "step_preparation": "Prepare and check the next step",
    "finalize": "Finalize the case result",
    "additional_checks": "Additional test checks",
}
_STATES = {
    "pending": "unavailable (not reached in saved measurements)",
    "running": "unavailable (started; end not recorded)",
    "not_run": "not run",
    "unavailable": "unavailable",
}


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unavailable"
    if 0 < seconds < 0.001:
        return "< 0.001 s"
    return f"{seconds:.3f} s"


def _line(record: Timing) -> str:
    label = _LABELS[record.phase]
    if record.step is not None:
        label = f"Step {record.step + 1}: {label}"
    value = (
        format_duration(record.duration_seconds)
        if record.state == "measured"
        else _STATES[record.state]
    )
    detail = f" — {record.diagnostic}" if record.diagnostic else ""
    return f"  {label}: {value}{detail}"


def _remainder(total: float | None, records: list[Timing]) -> str:
    if total is None or any(r.state not in {"measured", "not_run"} for r in records):
        return "unavailable (phase measurements incomplete)"
    remaining = total - sum(r.duration_seconds or 0 for r in records)
    return format_duration(max(0.0, remaining))


def render_timings(result: CoordinatedResult, additional_checks: Timing) -> str:
    case = result.test.case["name"] if result.test is not None else "unavailable"
    verdict = result.test.status if result.test is not None else "unavailable"
    internal = result.container_timings
    lines = [
        f"Case: {case} — {verdict}",
        f"Docker: {result.container.state}; cleanup complete: {result.container.cleanup_complete}",
        f"Timing evidence: {'incomplete' if internal.diagnostics else 'complete'}",
        "",
        f"Coordinator total: {format_duration(result.duration_seconds)}",
        *[_line(record) for record in result.timings],
        f"  Host time not detailed: {_remainder(result.duration_seconds, result.timings)}",
        "",
        "Container detail (included in container execution, never added to the host total):",
        *[_line(record) for record in internal.phases],
        f"  Measured container work: {format_duration(internal.duration_seconds)}",
        f"  Container work not detailed: {_remainder(internal.duration_seconds, internal.phases)}",
        "  Container startup and exit are not individually measured.",
        "",
        _line(additional_checks).strip(),
        "Helper setup and final report writing are outside the coordinator total.",
        "Durations include waiting; cache, network and machine load can change them.",
    ]
    lines.extend(f"Timing diagnostic: {message}" for message in internal.diagnostics)
    return "\n".join(lines) + "\n"


def render_campaign(result: CampaignResult) -> str:
    preparation = result.preparation
    cleanup = result.cleanup
    lines = [
        f"Campaign passed: {result.passed}",
        f"Interrupted: {result.interrupted}",
        f"Selection origin: {result.selection_origin}",
        f"Selected cases ({len(result.cases)}): {', '.join(result.selected_cases)}",
        f"Not selected: {', '.join(result.not_selected_cases) or 'none'}",
        f"Evidence: {result.output_directory}",
        f"Preparation: {preparation.state if preparation else 'not completed'}",
        f"Preparation diagnostic: {preparation.detail if preparation else 'unavailable'}",
        f"Image: {preparation.image_id if preparation else 'unavailable'}",
        f"Final cleanup: {cleanup.cleanup_complete if cleanup else 'not completed'}",
        f"Cleanup diagnostic: {cleanup.detail if cleanup else 'unavailable'}",
        f"Campaign total: {format_duration(result.duration_seconds)}",
        "Common phases (counted once):",
        *[_line(record) for record in result.timings],
    ]
    dependencies = preparation.dependency_preparation if preparation else None
    lines.append(f"Dependency mode: {dependencies.mode if dependencies else 'unavailable'}")
    if dependencies is not None and dependencies.warning is not None:
        lines.extend(
            [
                f"Warning: {dependencies.warning}",
                f"Dependency diagnostic: {dependencies.diagnostic_path}",
            ]
        )
    if result.error:
        lines.append(result.error)
    for entry in result.cases:
        lines.append(f"\nCase: {entry.name}")
        if entry.result is None:
            lines.append(
                f"  {entry.state}: {entry.not_run_reason or entry.error or 'awaiting result'}"
            )
        else:
            case = entry.result
            lines.extend(
                [
                    f"  Passed: {case.passed}; total: {format_duration(case.duration_seconds)}",
                    f"  Container: {case.container.state}; {case.container.detail}",
                    f"  Test: {case.test.status if case.test else 'unavailable'}",
                    f"  Evidence error: {case.result_error or 'none'}",
                    *_test_diagnostics(case.test),
                    *[_line(record) for record in case.timings],
                    "  Container details (included in run, never added to totals):",
                    *[_line(record) for record in case.container_timings.phases],
                    *[f"  Timing diagnostic: {d}" for d in case.container_timings.diagnostics],
                ]
            )
    return "\n".join(lines) + "\n"


def _test_diagnostics(test: InstallTestResult | None) -> list[str]:
    if test is None:
        return []
    lines = (
        [f"  Preparation reason: {test.preparation['reason']}"]
        if test.preparation["reason"]
        else []
    )
    for index, step in enumerate(test.steps):
        command = step["command"]
        reason = step["skip_reason"] or (command["reason"] if command else None)
        if reason:
            lines.append(f"  Step {index + 1}: {reason}")
        verification = step["verification"]
        if verification is not None:
            lines.extend(
                f"  Step {index + 1}: {m.type}: {m.root}/{m.path}" for m in verification.mismatches
            )
            lines.extend(f"  Step {index + 1}: {o['reason']}" for o in verification.obstacles)
    return lines
