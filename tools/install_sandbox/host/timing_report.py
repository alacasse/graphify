"""Plain-language duration report; container details are never added to host totals."""

from tools.install_sandbox.contracts.results import InstallTestResult
from tools.install_sandbox.contracts.timings import Timing
from tools.install_sandbox.host.coordinator import CampaignResult

_LABELS = {
    "construction": "Read inputs and construct campaign cases (before coordinator)",
    "materialization": "Materialize campaign inputs",
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


def render_campaign(result: CampaignResult) -> str:
    preparation = result.preparation
    cleanup = result.cleanup
    lines = [
        f"Preparation result: {result.status}"
        if result.prepare_only
        else f"Campaign passed: {result.passed}",
        f"Interrupted: {result.interrupted}",
        "Operation: prepare-only (zero installation steps)"
        if result.prepare_only
        else "Operation: reinstall (two installation steps)",
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
        if entry.construction != "constructed":
            label = (
                "not applicable"
                if entry.construction == "not_applicable"
                else "applicable but not constructible"
            )
            lines.append(f"  {label}: {entry.construction_reason}")
            continue
        lines.append(f"  Construction: constructed; execution: {entry.state}")
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
    initial = test.preparation
    reason = (
        initial.stop.reason
        if initial.stop
        else ("Initial verification failed" if initial.checkpoint == "blocked" else None)
    )
    lines = [f"  Preparation reason: {reason}"] if reason else []
    for index, step in enumerate(test.steps):
        command = step.command
        reason = (step.stop.reason if step.stop else None) or (
            command["reason"] if command else None
        )
        if reason:
            lines.append(f"  Step {index + 1}: {reason}")
        verification = step.verification
        if verification is not None:
            lines.extend(
                f"  Step {index + 1}: {m.type}: {m.root}/{m.path}" for m in verification.mismatches
            )
            lines.extend(f"  Step {index + 1}: {o['reason']}" for o in verification.obstacles)
    return lines
