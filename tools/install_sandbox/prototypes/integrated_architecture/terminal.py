"""Thin terminal for the integrated architecture evidence."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .scenarios import DemoFrame, ScenarioResult, run_all, stream_interactive_frames


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


def _interactive(*, ansi: bool) -> int:
    emitted = 0

    def render(frame: DemoFrame) -> None:
        nonlocal emitted
        if ansi and sys.stdout.isatty():
            print("\033[2J\033[H", end="")
        elif emitted:
            print("\n---")
        print(_render_frame(frame, ansi=ansi), flush=True)
        emitted += 1

    streamed = stream_interactive_frames(render)
    print("\nPREPARED — NOT RESOLVED; human architecture acceptance remains in #38")
    if streamed.presentation_failures:
        print(
            f"interactive presentation incomplete: "
            f"{len(streamed.presentation_failures)} callback failure(s)",
            file=sys.stderr,
        )
        return 1
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
    return _interactive(ansi=not args.no_ansi)


if __name__ == "__main__":
    raise SystemExit(main())
