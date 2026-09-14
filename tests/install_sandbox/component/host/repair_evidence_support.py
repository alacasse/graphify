"""Controlled arrangements shared by sandbox behavior tests."""

from pathlib import Path

import pytest


def corrupt_after_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    *,
    program_name: str = "controlled_repair_case.py",
) -> None:
    program = Path(__file__).resolve().parents[1] / "container" / program_name
    adapter = tmp_path / "corrupt-evidence.py"
    adapter.write_text(
        "import json, sys, subprocess\nfrom pathlib import Path\n"
        f"subprocess.run([sys.executable, {str(program)!r}, *sys.argv[1:]], check=True)\n"
        "output = Path(sys.argv[3])\n"
        'document = json.loads((output / "result.json").read_bytes())\n'
        '(output / "uncorrupted-result.json").write_text(json.dumps(document))\n' + code + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FAKE_DOCKER_CASE_PROGRAM", str(adapter))
