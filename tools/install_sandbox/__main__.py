"""Run a configured installation campaign from the repository checkout."""

import argparse
import sys
from pathlib import Path

from tools.install_sandbox.host.output_lifecycle import CampaignOutput


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--specs", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Final result directory. Defaults to a UTC-named campaign under "
            "tools/install_sandbox/out (14-day retention). Managed destinations must "
            "be absent; outside out, retention belongs to the caller."
        ),
    )
    parser.add_argument("--case", action="append", dest="cases", metavar="NAME")
    args = parser.parse_args(arguments)
    result = CampaignOutput().run(
        specs_directory=args.specs,
        target=args.target,
        case_names=args.cases,
        subject_checkout=args.repo,
        output_directory=args.output,
    )
    report = result.report.render()
    if result.exit_code:
        for diagnostic in result.report.diagnostics:
            print(diagnostic, file=sys.stderr)
    if result.output_directory is not None:
        print(f"Result available at: {result.output_directory}")
    else:
        print("No output directory allocated.", file=sys.stderr)
    print(report, end="")
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
