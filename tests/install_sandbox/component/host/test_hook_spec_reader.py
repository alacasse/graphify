"""Verify sandbox behavior at its owning boundary."""

from pathlib import Path

import pytest


def test_yaml_hooks_are_validated_before_case_output(tmp_path: Path) -> None:
    from tools.install_sandbox.host.coordinator import InstallTestCoordinator

    specs = tmp_path / "specs"
    specs.mkdir()
    source = (
        Path(__file__).resolve().parents[4]
        / "tools/install_sandbox/specs/reference/sandbox-reference.yaml"
    )
    invalid = source.read_text().replace("        type: command", "        type: .nan")
    (specs / "target.yaml").write_text(invalid)
    output = tmp_path / "case.json"
    with pytest.raises(ValueError, match="Invalid spec"):
        InstallTestCoordinator().write_case(specs, "target", output)
    assert not output.exists()
