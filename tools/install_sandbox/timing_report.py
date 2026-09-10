"""Plain-language duration report; container details are never added to host totals."""

from tools.install_sandbox.coordinator import CoordinatedResult
from tools.install_sandbox.timings import Timing

_LABELS = {
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
