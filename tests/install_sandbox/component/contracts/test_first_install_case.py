"""Local evidence for discovery, first-install assembly and JSON transport."""

import json
from pathlib import Path
from typing import cast

import pytest

from tests.install_sandbox.component.contracts.case_support import EXPECTED, REFERENCE
from tools.install_sandbox.contracts.case import InstallTestCase
from tools.install_sandbox.host.coordinator import InstallTestCoordinator


def test_reference_case_matches_approved_example(tmp_path: Path) -> None:
    output = tmp_path / "case.json"
    results = tmp_path / "results"
    results.mkdir()
    case = InstallTestCoordinator().write_case(REFERENCE, "sandbox-reference", output)
    expected = EXPECTED.read_text(encoding="utf-8")
    assert json.loads(output.read_text(encoding="utf-8")) == json.loads(expected)
    assert InstallTestCase.from_json(output.read_text(encoding="utf-8")) == case
    assert list(results.iterdir()) == []
    assert len(case.initial_files) == 4
    assert all(item["content"].endswith("\n") for item in case.initial_files)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "reinstall"),
        ("scope", "user"),
        ("target", ""),
        ("operations", []),
        ("operations", ["install", "uninstall"]),
        ("initial_files", []),
        ("spec", {}),
    ],
)
def test_rejects_invalid_json_case(field: str, value: object) -> None:
    data = cast(dict[str, object], json.loads(EXPECTED.read_text(encoding="utf-8")))
    data[field] = value
    with pytest.raises(ValueError):
        InstallTestCase.from_json(json.dumps(data))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("root", "subject"),
        ("path", "../outside"),
        ("content", 123),
        ("content", "Changed witness\n"),
    ],
)
def test_rejects_invalid_witness(field: str, value: object) -> None:
    data = cast(dict[str, object], json.loads(EXPECTED.read_text(encoding="utf-8")))
    files = cast(list[dict[str, object]], data["initial_files"])
    files[0][field] = value
    with pytest.raises(ValueError):
        InstallTestCase.from_json(json.dumps(data))


def test_rejects_missing_witness_and_unsupported_scope(tmp_path: Path) -> None:
    data = cast(dict[str, object], json.loads(EXPECTED.read_text(encoding="utf-8")))
    cast(list[object], data["initial_files"]).pop()
    with pytest.raises(ValueError, match="definition"):
        InstallTestCase.from_json(json.dumps(data))
    source = (REFERENCE / "sandbox-reference.yaml").read_text(encoding="utf-8")
    (tmp_path / "target.yaml").write_text(
        source.replace("[user, project]", "[user]"), encoding="utf-8"
    )
    output = tmp_path / "case.json"
    output.write_text("Preserve existing output", encoding="utf-8")
    with pytest.raises(ValueError, match="project scope"):
        InstallTestCoordinator().write_case(tmp_path, "target", output)
    assert output.read_text(encoding="utf-8") == "Preserve existing output"
