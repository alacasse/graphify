"""Retrieve image-owned dependency evidence and check the common executable."""

import time

# Deliberately bracket imports; this does not measure interpreter startup.
_IMPORTS_STARTED = time.monotonic_ns()
import json  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from contextlib import suppress  # noqa: E402
from pathlib import Path  # noqa: E402

_IMPORTS_SECONDS = (time.monotonic_ns() - _IMPORTS_STARTED) / 1_000_000_000


def _report_entry(copy_seconds: float, completed: bool) -> None:
    payload = {
        "version": 1,
        "entry": "verification",
        "seconds": {"initial_imports": _IMPORTS_SECONDS, "evidence_copy": copy_seconds},
        "evidence_copy_completed": completed,
    }
    with suppress(OSError):
        print("INSTALL_SANDBOX_ENTRY_TIMINGS " + json.dumps(payload), file=sys.stderr, flush=True)


def verify(source: Path, output: Path, executable: str) -> int:
    """Keep copied evidence even when the executable's help command fails."""
    started = time.monotonic_ns()
    completed = False
    try:
        shutil.copyfile(source / "dependencies.json", output / "dependencies.json")
        diagnostic = source / "dependencies.log"
        if diagnostic.is_file():
            shutil.copyfile(diagnostic, output / diagnostic.name)
        completed = True
    finally:
        _report_entry((time.monotonic_ns() - started) / 1_000_000_000, completed)
    return subprocess.call([executable, "--help"])


if __name__ == "__main__":
    raise SystemExit(verify(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]))
