"""Conduct the mounted JSON case with the sandbox embedded in the image."""

from __future__ import annotations

import time

# Deliberately bracket imports. Interpreter startup and importing time are outside this interval.
_IMPORTS_STARTED = time.monotonic_ns()
import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from contextlib import suppress  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import TYPE_CHECKING  # noqa: E402

_IMPORTS_SECONDS = (time.monotonic_ns() - _IMPORTS_STARTED) / 1_000_000_000

if TYPE_CHECKING:
    from tools.install_sandbox.container.runner import InstallTestRunner


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-sources", required=True, type=Path)
    parser.add_argument("--prepared-executable", required=True, type=Path)
    parser.add_argument("--case-file", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--work-directory", type=Path, default=Path("/sandbox/work/case"))
    return parser.parse_args(argv)


def _report_entry(phases: dict[str, float]) -> None:
    """Use stderr so measurement does not populate the runner's fresh output directory."""
    payload = {"version": 1, "entry": "case", "seconds": phases}
    with suppress(OSError):
        print("INSTALL_SANDBOX_ENTRY_TIMINGS " + json.dumps(payload), file=sys.stderr, flush=True)


def main(argv: list[str] | None = None, *, runner: InstallTestRunner | None = None) -> int:
    phases = {"initial_imports": _IMPORTS_SECONDS}
    try:
        try:
            started = time.monotonic_ns()
            args = _arguments(argv)
            phases["arguments"] = (time.monotonic_ns() - started) / 1_000_000_000
            started = time.monotonic_ns()
            # With python -I, resolve only the embedded sandbox, never the mounted subject.
            if __package__ in {None, ""}:
                sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
            from tools.install_sandbox.container.runner import InstallTestRunner

            phases["runner_import"] = (time.monotonic_ns() - started) / 1_000_000_000
            started = time.monotonic_ns()
            conductor = runner if runner is not None else InstallTestRunner()
            phases["runner_setup"] = (time.monotonic_ns() - started) / 1_000_000_000
        finally:
            _report_entry(phases)
        conductor.run_case(
            reference_sources=args.reference_sources,
            prepared_executable=args.prepared_executable,
            case_file=args.case_file,
            output_directory=args.output_directory,
            work_directory=args.work_directory,
        )
    except KeyboardInterrupt:
        print("Case execution interrupted", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"Case execution failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
