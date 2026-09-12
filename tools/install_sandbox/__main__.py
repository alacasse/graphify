"""Run a configured installation campaign from the repository checkout."""

import argparse
import sys
from pathlib import Path

from tools.install_sandbox.coordinator import InstallTestCoordinator
from tools.install_sandbox.timing_report import render_campaign


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--specs", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", action="append", dest="cases", metavar="NAME")
    args = parser.parse_args(arguments)
    try:
        result = InstallTestCoordinator().run_campaign(
            specs_directory=args.specs,
            target=args.target,
            case_names=args.cases,
            subject_checkout=args.repo,
            output_directory=args.output,
        )
    except (OSError, ValueError) as error:
        print(f"Campaign request refused: {error}", file=sys.stderr)
        print(f"Evidence destination: {args.output}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(f"Campaign interrupted; evidence destination: {args.output}", file=sys.stderr)
        return 130
    print(render_campaign(result), end="")
    if result.interrupted:
        return 130
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
