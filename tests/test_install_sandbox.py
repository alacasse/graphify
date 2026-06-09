from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_install_sandbox_selftest() -> None:
    repo = Path(__file__).resolve().parents[1]
    subprocess.run(
        [sys.executable, str(repo / "tools" / "install_sandbox" / "selftest.py")],
        cwd=repo,
        check=True,
    )
