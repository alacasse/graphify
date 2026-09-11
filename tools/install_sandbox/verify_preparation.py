"""Retrieve image-owned dependency evidence and check the common executable."""

import shutil
import subprocess
import sys
from pathlib import Path


def verify(source: Path, output: Path, executable: str) -> int:
    """Keep copied evidence even when the executable's help command fails."""
    shutil.copyfile(source / "dependencies.json", output / "dependencies.json")
    diagnostic = source / "dependencies.log"
    if diagnostic.is_file():
        shutil.copyfile(diagnostic, output / diagnostic.name)
    return subprocess.call([executable, "--help"])


if __name__ == "__main__":
    raise SystemExit(verify(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]))
