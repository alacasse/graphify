"""Local evidence for discovery, first-install assembly and JSON transport."""

import json
from pathlib import Path
from typing import cast

import pytest

from tools.install_sandbox.case import InstallTestCase
from tools.install_sandbox.coordinator import InstallTestCoordinator
from tools.install_sandbox.spec_reader import InstallSpecReader

_REFERENCE = Path(__file__).parents[3] / "tools/install_sandbox/specs/reference"
_EXPECTED = Path(__file__).with_name("fixtures") / "first-install.json"


def test_reference_case_matches_approved_example(tmp_path: Path) -> None:
    output = tmp_path / "case.json"
    results = tmp_path / "results"
    results.mkdir()
    case = InstallTestCoordinator().write_case(_REFERENCE, "sandbox-reference", output)
    expected = _EXPECTED.read_text(encoding="utf-8")
    assert json.loads(output.read_text(encoding="utf-8")) == json.loads(expected)
    assert InstallTestCase.from_json(output.read_text(encoding="utf-8")) == case
    assert list(results.iterdir()) == []
    assert len(case.initial_files) == 4
    assert all(item["content"].endswith("\n") for item in case.initial_files)


def test_discovers_multiple_yaml_and_derives_witness_destinations(tmp_path: Path) -> None:
    source = (_REFERENCE / "sandbox-reference.yaml").read_text(encoding="utf-8")
    (tmp_path / "alpha.yaml").write_text(source, encoding="utf-8")
    changed = (
        source.replace(".sandbox-reference", ".other-target")
        .replace("file: settings.json", "file: config/preferences.json")
        .replace("file: instructions.md", "file: docs/user.md")
    )
    (tmp_path / "beta.yaml").write_text(changed, encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("not YAML", encoding="utf-8")
    assert set(InstallSpecReader().read(tmp_path)) == {"alpha", "beta"}
    output = tmp_path / "case.json"
    case = InstallTestCoordinator().write_case(tmp_path, "beta", output)
    assert case.target == "beta"
    assert [item["path"] for item in case.initial_files] == [
        ".other-target/docs/user.md",
        ".other-target/config/preferences.json",
        ".other-target/config/my-instructions.md",
        "personal-notes.txt",
    ]
    assert InstallTestCase.from_json(output.read_text(encoding="utf-8")) == case


@pytest.mark.parametrize(
    "replacement",
    [
        "",
        "[]",
        "scopes: [project]",
        "scopes: [invalid]\n",
    ],
)
def test_rejects_incomplete_yaml_before_writing(tmp_path: Path, replacement: str) -> None:
    (tmp_path / "target.yaml").write_text(replacement, encoding="utf-8")
    output = tmp_path / "case.json"
    with pytest.raises(ValueError, match="Invalid spec"):
        InstallTestCoordinator().write_case(tmp_path, "target", output)
    assert not output.exists()


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("scopes: [user, project]", "scopes: [project, project]"),
        ("scopes: [user, project]", "scopes: [other]"),
        ("directory: .sandbox-reference", "directory: /absolute"),
        ("source: graphify/skill.md", "source: ../skill.md"),
        ("file: settings.json", "file: 123"),
        ('marker: "## graphify"', 'marker: ""'),
    ],
)
def test_rejects_invalid_target_facts(tmp_path: Path, before: str, after: str) -> None:
    source = (_REFERENCE / "sandbox-reference.yaml").read_text(encoding="utf-8")
    (tmp_path / "target.yaml").write_text(source.replace(before, after), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid spec"):
        InstallSpecReader().read(tmp_path)


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
    data = cast(dict[str, object], json.loads(_EXPECTED.read_text(encoding="utf-8")))
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
    data = cast(dict[str, object], json.loads(_EXPECTED.read_text(encoding="utf-8")))
    files = cast(list[dict[str, object]], data["initial_files"])
    files[0][field] = value
    with pytest.raises(ValueError):
        InstallTestCase.from_json(json.dumps(data))


def test_rejects_missing_witness_and_unsupported_scope(tmp_path: Path) -> None:
    data = cast(dict[str, object], json.loads(_EXPECTED.read_text(encoding="utf-8")))
    cast(list[object], data["initial_files"]).pop()
    with pytest.raises(ValueError, match="definition"):
        InstallTestCase.from_json(json.dumps(data))
    source = (_REFERENCE / "sandbox-reference.yaml").read_text(encoding="utf-8")
    (tmp_path / "target.yaml").write_text(
        source.replace("[user, project]", "[user]"), encoding="utf-8"
    )
    output = tmp_path / "case.json"
    output.write_text("Preserve existing output", encoding="utf-8")
    with pytest.raises(ValueError, match="project scope"):
        InstallTestCoordinator().write_case(tmp_path, "target", output)
    assert output.read_text(encoding="utf-8") == "Preserve existing output"


def test_reports_missing_directory_and_target(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="directory"):
        InstallSpecReader().read(tmp_path / "missing")
    with pytest.raises(ValueError, match="Target not found"):
        InstallTestCoordinator().write_case(tmp_path, "missing", tmp_path / "case.json")
