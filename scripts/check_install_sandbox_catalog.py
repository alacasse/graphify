"""Check the staged sandbox catalog against its recovery baseline and the staged CLI."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

BASELINE = "33276a601ddbf1d96e151dbc325811b31d45aceb"
CATALOG = "tools/install_sandbox/specs"

# Run from a temporary checkout of the indexed package. Aliases and dedicated
# commands come from the same installer dispatcher used by the product CLI.
INVENTORY_PROBE = """
from contextlib import redirect_stdout
from io import StringIO
from graphify.install import _CLI_INSTALL_COMMANDS, _canonical_platform, _print_install_usage

usage = StringIO()
with redirect_stdout(usage):
    _print_install_usage()
platforms, = (line.removeprefix("Platforms:") for line in usage.getvalue().splitlines()
              if line.startswith("Platforms:"))
names = {name.strip() for name in platforms.split(",") if name.strip()}
names.update(_CLI_INSTALL_COMMANDS - {"install", "uninstall"})
for target in sorted({_canonical_platform(name) for name in names}):
    print(target)
"""


def git(*args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(["git", *args], input=data, stdout=subprocess.PIPE, check=True).stdout


def staged_files() -> dict[str, bytes]:
    # Diff against an empty tree to see every path the commit will contain,
    # including unchanged files, but excluding placeholders from git add -N.
    empty = git("hash-object", "-t", "tree", "--stdin", data=b"").decode().strip()
    records = git(
        "diff",
        "--cached",
        "--raw",
        "--no-renames",
        "--ita-invisible-in-index",
        "-z",
        empty,
        "--",
        "graphify",
        CATALOG,
    ).split(b"\0")
    modes = {}
    for index in range(0, len(records) - 1, 2):
        mode = records[index].split()[1]
        modes[os.fsdecode(records[index + 1])] = mode
    return modes


def published_targets(package_paths: list[str]) -> set[str]:
    files = b"".join(os.fsencode(path) + b"\0" for path in package_paths)
    with tempfile.TemporaryDirectory() as directory:
        git(
            "checkout-index",
            "--ignore-skip-worktree-bits",
            "-z",
            "--stdin",
            f"--prefix={Path(directory).as_posix()}/",
            data=files,
        )
        output = subprocess.check_output(
            [sys.executable, "-E", "-B", "-S", "-c", INVENTORY_PROBE], cwd=directory, text=True
        )
    return set(output.splitlines())


def main(baseline: str = BASELINE) -> int:
    suffixes = (".yaml", ".yml")
    reference = os.fsdecode(git("ls-tree", "-rz", "--name-only", baseline, "--", CATALOG))
    frozen = {path for path in reference.split("\0") if path.lower().endswith(suffixes)}
    modes = staged_files()
    staged = {p for p in modes if p.startswith(CATALOG + "/") and p.lower().endswith(suffixes)}
    tools = published_targets([p for p in modes if p.startswith("graphify/")])
    expected = {f"{CATALOG}/{target}.yaml" for target in tools}
    problems = []
    for path in sorted(staged - frozen):
        existing = f"{CATALOG}/{PurePosixPath(path).stem}.yaml"
        guidance = (
            f"Update {existing} for another scope."
            if existing in frozen
            else "For grouped operations, reuse the participating tools' specs."
        )
        problems.append(f"Added spec outside the frozen catalog: {path}. {guidance}")
    for path in sorted(frozen - staged):
        problems.append(f"Missing frozen spec: {path}")
    for path in sorted(expected - staged):
        problems.append(f"Missing spec for a supported tool: {path}")
    for path in sorted(staged - expected):
        problems.append(f"Spec without a matching canonical tool: {path}")
    for path in sorted(staged):
        if modes[path] not in {b"100644", b"100755"}:
            problems.append(f"Expected a regular spec file: {path}")
    for problem in problems:
        print(problem, file=sys.stderr)
    return int(bool(problems))


if __name__ == "__main__":
    sys.exit(main())
