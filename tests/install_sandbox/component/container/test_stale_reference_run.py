"""A stale reference is repaired exactly, with retained evidence independent of inputs."""

import json
from pathlib import Path
from typing import Literal

import pytest

from tests.install_sandbox.component.container.stale_reference_support import (
    conduct_stale_reference,
)
from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.contracts.observation import FilesystemSnapshot


@pytest.mark.parametrize("skill_root", ["home", "project"])
def test_stale_reference_removes_witness_and_replays_after_cleanup(
    tmp_path: Path, skill_root: Literal["home", "project"]
) -> None:
    result, installer = conduct_stale_reference(tmp_path, skill_root=skill_root)
    assert result.status == "passed" and len(installer.calls) == 2
    assert installer.calls[0] == installer.calls[1]
    proof = tmp_path / "proof"
    witness_path = ".synthetic/skills/package/references/stale.md"
    operation = json.loads((proof / "intermediate/operation.json").read_text())
    assert operation["destination"] == {"root": skill_root, "path": witness_path}
    assert not (proof / "steps/0/after" / skill_root / witness_path).exists()
    assert not (proof / "steps/1/after" / skill_root / witness_path).exists()
    reinstall = json.loads((proof / "expectations/reinstall.json").read_text())
    assert [
        item["provenance"]
        for item in reinstall["expectations"]
        if (item["root"], item["path"])
        == (skill_root, ".synthetic/skills/package/references/nested/reference.md")
    ] == ["source:subject:reference-data/nested/reference.md"]
    assert (
        proof / "intermediate/after" / skill_root / witness_path
    ).read_bytes() == b"Stale reference.\n"
    assert not (tmp_path / "subject").exists() and not (tmp_path / "work").exists()


@pytest.mark.parametrize("fault", ["overlay", "reference", "skill", "personal"])
def test_success_exit_cannot_hide_stale_reference_or_collateral_damage(
    tmp_path: Path, fault: str
) -> None:
    result, installer = conduct_stale_reference(tmp_path, repair_fault=fault)
    assert result.status == "failed" and len(installer.calls) == 2
    assert result.steps[1].command is not None
    assert result.steps[1].command["exit_code"] == 0
    verification = result.steps[1].verification
    assert verification is not None and verification.complete
    expected_root, expected_path = {
        "overlay": ("home", ".synthetic/skills/package/references/stale.md"),
        "reference": ("home", ".synthetic/skills/package/references/nested/reference.md"),
        "skill": ("home", ".synthetic/skills/package/SKILL.md"),
        "personal": ("project", "personal-effect-1.txt"),
    }[fault]
    assert {(item.root, item.path) for item in verification.mismatches} == {
        (expected_root, expected_path)
    }


@pytest.mark.parametrize("fault", ["unchanged", "collateral", "incomplete"])
def test_invalid_stale_preparation_blocks_second_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    from tools.install_sandbox.container import intermediate_execution

    if fault == "unchanged":

        def leave_reference_absent(*args: object) -> None:
            pass

        monkeypatch.setattr(intermediate_execution, "apply_mutation", leave_reference_absent)
    else:
        original = EffectEnvironment.observe_intermediate

        def observe(environment: EffectEnvironment, phase: str) -> FilesystemSnapshot:
            if phase == "after" and fault == "collateral":
                (environment.home / ".synthetic/skills/package/SKILL.md").write_text("Damage\n")
            snapshot = original(environment, phase)
            if phase == "after" and fault == "incomplete":
                path = ".synthetic/skills/package/references/stale.md"
                snapshot.contents.pop(("home", path))
                snapshot.obstacles.append(
                    {
                        "root": "home",
                        "path": path,
                        "operation": "read_file",
                        "reason": "Controlled unavailable reference observation",
                    }
                )
            return snapshot

        monkeypatch.setattr(EffectEnvironment, "observe_intermediate", observe)
    result, installer = conduct_stale_reference(tmp_path)
    assert result.status == ("incomplete" if fault == "incomplete" else "failed")
    assert len(installer.calls) == 1 and result.steps[1].phase == "idle"
    verification = json.loads((tmp_path / "proof/intermediate/verification.json").read_text())
    if fault == "incomplete":
        assert verification["complete"] is False
        assert {(item["root"], item["path"]) for item in verification["obstacles"]} == {
            ("home", ".synthetic/skills/package/references/stale.md")
        }
    else:
        expected = "references/stale.md" if fault == "unchanged" else "SKILL.md"
        assert {(item["root"], item["path"]) for item in verification["mismatches"]} == {
            ("home", f".synthetic/skills/package/{expected}")
        }
