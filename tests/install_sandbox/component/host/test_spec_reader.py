"""Verify sandbox behavior at its owning boundary."""

from pathlib import Path

import pytest

from tests.install_sandbox.component.contracts.case_support import REFERENCE
from tools.install_sandbox.contracts.case import InstallTestCase
from tools.install_sandbox.host.coordinator import InstallTestCoordinator
from tools.install_sandbox.host.spec_reader import InstallSpecReader


def test_discovers_multiple_yaml_and_derives_witness_destinations(tmp_path: Path) -> None:
    source = (REFERENCE / "sandbox-reference.yaml").read_text(encoding="utf-8")
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
    source = (REFERENCE / "sandbox-reference.yaml").read_text(encoding="utf-8")
    (tmp_path / "target.yaml").write_text(source.replace(before, after), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid spec"):
        InstallSpecReader().read(tmp_path)


def test_reports_missing_directory_and_target(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="directory"):
        InstallSpecReader().read(tmp_path / "missing")
    with pytest.raises(ValueError, match="Target not found"):
        InstallTestCoordinator().write_case(tmp_path, "missing", tmp_path / "case.json")
