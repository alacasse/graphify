"""Reference inputs for case and spec tests."""

from pathlib import Path

REFERENCE = Path(__file__).parents[4] / "tools/install_sandbox/specs/reference"
EXPECTED = Path(__file__).resolve().parents[1] / "fixtures" / "first-install.json"
