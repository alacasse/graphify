"""Import fallback tests for validation-plan direct script usage."""

from __future__ import annotations

import subprocess
import sys


def test_validation_plan_supports_direct_script_import_fallback() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, 'tools/install_sandbox'); "
            "from validation_plan import ValidationWorkItem, build_validation_plan; "
            "print(build_validation_plan.__name__, ValidationWorkItem.__name__)",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "build_validation_plan ValidationWorkItem"
