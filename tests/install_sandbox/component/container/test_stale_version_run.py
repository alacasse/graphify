"""A stale version is repaired exactly, with retained evidence independent of inputs."""

import json
from pathlib import Path
from typing import Literal

import pytest

from tests.install_sandbox.component.container.stale_version_support import conduct_stale_version
from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.contracts.observation import FilesystemSnapshot


@pytest.mark.parametrize("skill_root", ["home", "project"])
def test_stale_version_restores_exact_bytes_and_replays_after_cleanup(
    tmp_path: Path, skill_root: Literal["home", "project"]
) -> None:
    result, installer = conduct_stale_version(tmp_path, skill_root=skill_root)
    assert result.status == "passed" and len(installer.calls) == 2
    assert installer.calls[0] == installer.calls[1]
    proof = tmp_path / "proof"
    version_path = ".synthetic/skills/package/.graphify_version"
    reinstall = json.loads((proof / "expectations/reinstall.json").read_text())
    assert [
        item["provenance"]
        for item in reinstall["expectations"]
        if (item["root"], item["path"]) == (skill_root, version_path)
    ] == ["version:subject:METADATA"]
    operation = json.loads((proof / "intermediate/operation.json").read_text())
    assert operation["destination"] == {"root": skill_root, "path": version_path}
    assert (proof / "steps/1/after" / skill_root / version_path).read_bytes() == b"8.7.6"
    assert (proof / "intermediate/after" / skill_root / version_path).read_bytes() == b"0.0.0-stale"
    assert not (tmp_path / "subject").exists() and not (tmp_path / "work").exists()


@pytest.mark.parametrize("fault", ["unchanged", "newline", "reference", "backup"])
def test_success_exit_cannot_hide_stale_version_or_collateral_damage(
    tmp_path: Path, fault: str
) -> None:
    result, installer = conduct_stale_version(tmp_path, repair_fault=fault)
    assert result.status == "failed" and len(installer.calls) == 2
    verification = result.steps[1].verification
    assert verification is not None and verification.complete
    expected_path = {
        "unchanged": ".synthetic/skills/package/.graphify_version",
        "newline": ".synthetic/skills/package/.graphify_version",
        "reference": ".synthetic/skills/package/references/nested/reference.md",
        "backup": ".synthetic/skills/package/SKILL.md.bak",
    }[fault]
    assert {(item.root, item.path) for item in verification.mismatches} == {("home", expected_path)}


@pytest.mark.parametrize("fault", ["unchanged", "collateral", "incomplete"])
def test_invalid_stale_preparation_blocks_second_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    from tools.install_sandbox.container import intermediate_execution

    if fault == "unchanged":

        def leave_version_untouched(*args: object) -> None:
            pass

        monkeypatch.setattr(intermediate_execution, "apply_mutation", leave_version_untouched)
    else:
        original = EffectEnvironment.observe_intermediate

        def observe(environment: EffectEnvironment, phase: str) -> FilesystemSnapshot:
            if phase == "after" and fault == "collateral":
                (environment.home / ".synthetic/skills/package/SKILL.md").write_text("Damage\n")
            snapshot = original(environment, phase)
            if phase == "after" and fault == "incomplete":
                path = ".synthetic/skills/package/.graphify_version"
                snapshot.contents.pop(("home", path))
                snapshot.obstacles.append(
                    {
                        "root": "home",
                        "path": path,
                        "operation": "read_file",
                        "reason": "Controlled unavailable version observation",
                    }
                )
            return snapshot

        monkeypatch.setattr(EffectEnvironment, "observe_intermediate", observe)
    result, installer = conduct_stale_version(tmp_path)
    assert result.status == ("incomplete" if fault == "incomplete" else "failed")
    assert len(installer.calls) == 1 and result.steps[1].phase == "idle"
    verification = json.loads((tmp_path / "proof/intermediate/verification.json").read_text())
    if fault == "incomplete":
        assert verification["complete"] is False
        assert {(item["root"], item["path"]) for item in verification["obstacles"]} == {
            ("home", ".synthetic/skills/package/.graphify_version")
        }
    else:
        expected = ".graphify_version" if fault == "unchanged" else "SKILL.md"
        assert {(item["root"], item["path"]) for item in verification["mismatches"]} == {
            ("home", f".synthetic/skills/package/{expected}")
        }
