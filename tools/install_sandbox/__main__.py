"""Run a native two-step reinstall from effect YAML and explicit subject context."""

import argparse
import sys
from pathlib import Path

from tools.install_sandbox.host.output_lifecycle import CampaignOutput


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--subject-context", type=Path, required=True)
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Verify package preparation without running installation cases",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Final result directory. Defaults to a UTC-named campaign under "
            "tools/install_sandbox/out (14-day retention). Managed destinations must "
            "be absent; outside out, retention belongs to the caller."
        ),
    )
    args = parser.parse_args(arguments)
    result = CampaignOutput().run(
        spec_file=args.spec,
        subject_context_file=args.subject_context,
        subject_checkout=args.repo,
        output_directory=args.output,
        prepare_only=args.prepare_only,
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
