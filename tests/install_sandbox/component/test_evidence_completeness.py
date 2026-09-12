"""Host success requires retained sources after the observed roots are gone."""

import json
import shutil
from pathlib import Path

import pytest

from tests.install_sandbox.component.test_hook_evidence import (
    _run,  # pyright: ignore[reportPrivateUsage]
)
from tools.install_sandbox.result_reader import read_result


@pytest.mark.parametrize("name", ["first-install", "reinstall"])
@pytest.mark.parametrize(
    "missing",
    ["inventory", "directory", "skill", "markdown", "reference", "skill_entry", "skill_digest"],
)
def test_success_requires_retained_expected_sources(
    tmp_path: Path, name: str, missing: str
) -> None:
    case, output = _run(tmp_path, name)
    shutil.rmtree(tmp_path / "work")
    shutil.rmtree(tmp_path / "subject")
    assert read_result(output, case).status == "passed"

    if missing == "directory":
        shutil.rmtree(output / "expected")
    elif missing in {"skill_entry", "skill_digest"}:
        inventory = output / "expected.json"
        snapshot = json.loads(inventory.read_bytes())
        entry = next(e for e in snapshot["entries"] if e["path"] == case.spec.skill_source)
        (output / entry["content_file"]).unlink()
        if missing == "skill_entry":
            snapshot["entries"].remove(entry)
        else:
            entry.pop("content_file")
            entry["sha256"] = "a" * 64
        inventory.write_text(json.dumps(snapshot))
    else:
        paths = {
            "inventory": output / "expected.json",
            "skill": output / "expected" / case.spec.skill_source,
            "markdown": output / "expected" / case.spec.markdown_source,
            "reference": output / "expected" / case.spec.references_source / "one.md",
        }
        paths[missing].unlink()

    with pytest.raises((ValueError, FileNotFoundError)):
        read_result(output, case)
