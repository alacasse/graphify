"""Thin terminal for the integrated architecture evidence."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .scenarios import DemoFrame, ScenarioResult, interactive_frames, run_all


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the throwaway integrated install-sandbox architecture proof."
    )
    parser.add_argument(
        "--demo",
        choices=("all",),
        help="run deterministic assertions instead of the interactive walkthrough",
    )
    parser.add_argument(
        "--no-ansi",
        action="store_true",
        help="disable screen clearing and ANSI headings",
    )
    return parser


def _render_frame(frame: DemoFrame, *, ansi: bool) -> str:
    heading = f"FRAME {frame.number:02d} — {frame.action}"
    if ansi:
        heading = f"\033[1;36m{heading}\033[0m"
    sections = [heading]
    for label, values in frame.sections:
        sections.append(f"\n{label}:")
        sections.extend(f"  {value}" for value in values)
    return "\n".join(sections)


def _interactive(frames: Sequence[DemoFrame], *, ansi: bool) -> int:
    for index, frame in enumerate(frames):
        if ansi and sys.stdout.isatty():
            print("\033[2J\033[H", end="")
        print(_render_frame(frame, ansi=ansi))
        if index + 1 < len(frames) and sys.stdin.isatty():
            input("\nPress Enter for the next action...")
        elif index + 1 < len(frames):
            print("\n---")
    print("\nPREPARED — NOT RESOLVED; human architecture acceptance remains in #38")
    return 0


def _batch(results: Sequence[ScenarioResult]) -> int:
    failed = False
    for result in results:
        status = "OK" if result.passed else "FAIL"
        print(f"{status} {result.name}: {result.detail}")
        failed = failed or not result.passed
    print(f"{len(results)} deterministic architecture cases")
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the walkthrough or deterministic evidence suite."""

    args = _parser().parse_args(argv)
    if args.demo == "all":
        return _batch(run_all())
    return _interactive(interactive_frames(), ansi=not args.no_ansi)


if __name__ == "__main__":
    raise SystemExit(main())
