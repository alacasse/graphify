"""Conduct the mounted JSON case with the sandbox embedded in the image."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tools.install_sandbox.runner import InstallTestRunner


def main(argv: list[str] | None = None, *, runner: InstallTestRunner | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-sources", required=True, type=Path)
    parser.add_argument("--prepared-executable", required=True, type=Path)
    parser.add_argument("--case-file", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--work-directory", type=Path, default=Path("/sandbox/work/case"))
    args = parser.parse_args(argv)
    try:
        # With python -I, resolve only the embedded sandbox, never the mounted subject.
        if __package__ in {None, ""}:
            sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from tools.install_sandbox.runner import InstallTestRunner

        conductor = runner if runner is not None else InstallTestRunner()
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
