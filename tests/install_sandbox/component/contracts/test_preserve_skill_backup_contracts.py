"""Backup witnesses require canonical case definitions and observed absence."""

import hashlib
import json
from dataclasses import FrozenInstanceError, replace

import pytest

from tests.install_sandbox.component.contracts.test_reference_contracts import reference_case
from tools.install_sandbox.contracts.bound_mutation import (
    BoundFileCreation,
    PerformedMutation,
    mutation_from_data,
)
from tools.install_sandbox.contracts.effect_case import EffectInstallCase, build_effect_cases
from tools.install_sandbox.contracts.effects import (
    Destination,
    EffectSpec,
    MarkdownSectionEffect,
    SkillEffect,
)
from tools.install_sandbox.contracts.intermediate import (
    PRESERVE_SKILL_BACKUP_SUFFIX,
    PreserveSkillBackupPreparation,
)
from tools.install_sandbox.contracts.observation import FilesystemSnapshot


def backup_case(root: str = "project"):
    original = reference_case()
    spec = EffectSpec((SkillEffect("skill.md", "refs", Destination(root, "skill")),))
    builds = build_effect_cases(spec, original.subject)
    assert [case.name for case in builds.cases][-2:] == ["altered-skill", "preserve-skill-backup"]
    return builds.cases[-1]


@pytest.mark.parametrize("root", ["home", "project"])
def test_backup_case_round_trip_and_fixed_witness(root: str) -> None:
    case = backup_case(root)
    assert case.intermediate_preparation == PreserveSkillBackupPreparation(
        Destination(root, "skill")
    )
    assert PRESERVE_SKILL_BACKUP_SUFFIX == b"\nSandbox previous backup witness.\n"
    assert json.loads(case.to_json())["format"] == "explicit-expectations-v9"
    assert EffectInstallCase.from_json(case.to_json()) == case


@pytest.mark.parametrize("change", ["suffix", "destination", "kind", "version"])
def test_backup_case_rejects_tampering(change: str) -> None:
    raw = json.loads(backup_case().to_json())
    if change == "version":
        raw["format"] = "explicit-expectations-v8"
    elif change == "destination":
        raw["intermediate_preparation"][change]["root"] = "home"
    else:
        raw["intermediate_preparation"][change] = "YQ==" if change == "suffix" else "altered-skill"
    with pytest.raises(ValueError):
        EffectInstallCase.from_json(json.dumps(raw))


def creation() -> BoundFileCreation:
    return BoundFileCreation(
        hashlib.sha256(b"exact case").hexdigest(),
        "steps/0/after.json",
        Destination("project", "skill/SKILL.md.bak"),
        b"\x00\xfforiginal" + PRESERVE_SKILL_BACKUP_SUFFIX,
    )


def absent_snapshot() -> FilesystemSnapshot:
    return FilesystemSnapshot(
        entries=[
            {"root": "project", "path": "skill", "kind": "directory", "listing_complete": True},
        ]
    )


def test_creation_binds_exact_case_bytes_and_round_trips_binary_content() -> None:
    operation = creation()
    assert mutation_from_data(operation.to_data()) == operation
    assert operation.to_data()["format"] == "prepared-mutation-v3"
    assert operation.verify_binding(b"exact case", absent_snapshot()) == operation.content
    with pytest.raises(ValueError, match="case digest"):
        operation.verify_binding(b"exact case\n", absent_snapshot())
    with pytest.raises(FrozenInstanceError):
        operation.content = b"changed"  # type: ignore[misc]
    with pytest.raises(ValueError, match="validated first observation"):
        replace(operation, observation_ref="steps/1/after.json")


@pytest.mark.parametrize(
    "condition",
    ["missing-parent", "incomplete", "file", "symlink", "obstacle", "existing", "stray-bytes"],
)
def test_creation_rejects_unproven_absence(condition: str) -> None:
    observed = absent_snapshot()
    if condition == "missing-parent":
        observed.entries.clear()
    elif condition == "incomplete":
        observed.entries[0]["listing_complete"] = False
    elif condition in ("file", "symlink"):
        observed.entries[0]["kind"] = condition
    elif condition == "obstacle":
        observed.obstacles.append(
            {"root": "project", "path": "skill", "operation": "list_directory", "reason": "denied"}
        )
    elif condition == "existing":
        observed.entries.append({"root": "project", "path": "skill/SKILL.md.bak", "kind": "file"})
    else:
        observed.contents[("project", "skill/SKILL.md.bak")] = b"already exists"
    with pytest.raises(ValueError, match="positively observed absent"):
        creation().verify_binding(b"exact case", observed)


def test_performed_creation_records_actual_bytes_and_rejects_old_transport() -> None:
    operation = creation()
    performed = PerformedMutation(operation, hashlib.sha256(operation.content).hexdigest())
    assert performed.to_data()["format"] == "performed-mutation-v3"
    assert PerformedMutation.from_data(performed.to_data()) == performed
    observed = FilesystemSnapshot(contents={("project", "skill/SKILL.md.bak"): operation.content})
    performed.verify(operation, observed)
    observed.contents[("project", "skill/SKILL.md.bak")] = b"truncated"
    with pytest.raises(ValueError, match="contradicts"):
        performed.verify(operation, observed)
    raw = operation.to_data()
    raw["format"] = "prepared-mutation-v2"
    with pytest.raises(ValueError):
        mutation_from_data(raw)


def test_no_skill_is_not_applicable_and_multiskill_stays_construction_restriction() -> None:
    subject = reference_case().subject
    markdown = MarkdownSectionEffect("guide.md", Destination("project", "GUIDE.md"))
    build = build_effect_cases(EffectSpec((markdown,)), subject)
    decision = next(item for item in build.decisions if item.name == "preserve-skill-backup")
    assert decision.classification == "not_applicable"
    assert all(case.name != "preserve-skill-backup" for case in build.cases)
    skills = (
        SkillEffect("skill.md", "refs", Destination("project", "first")),
        SkillEffect("skill.md", "refs", Destination("home", "second")),
    )
    with pytest.raises(ValueError, match="Multiple skill effects"):
        build_effect_cases(EffectSpec(skills), subject)


def test_multiple_markdown_effects_do_not_block_backup_case() -> None:
    case = reference_case()
    spec = EffectSpec(
        (
            *case.effects.effects,
            MarkdownSectionEffect("one.md", Destination("project", "ONE.md")),
            MarkdownSectionEffect("two.md", Destination("project", "TWO.md")),
        )
    )
    build = build_effect_cases(spec, case.subject)
    assert build.cases[-1].name == "preserve-skill-backup"
    assert [(item.name, item.classification) for item in build.decisions] == [
        ("missing-section", "unconstructible"),
        ("altered-section", "unconstructible"),
        ("missing-json-hook", "not_applicable"),
        ("altered-json-hook", "not_applicable"),
    ]


@pytest.mark.parametrize("kind", ["absent", "symlink", "directory", "unobservable"])
def test_performed_creation_without_bytes_preserves_observed_failure(kind: str) -> None:
    operation = creation()
    performed = PerformedMutation(operation, None)
    assert PerformedMutation.from_data(performed.to_data()) == performed
    observed = absent_snapshot()
    if kind in ("symlink", "directory"):
        observed.entries.append({"root": "project", "path": "skill/SKILL.md.bak", "kind": kind})
    elif kind == "unobservable":
        observed.entries.clear()
        observed.obstacles.append(
            {"root": "project", "path": "skill", "operation": "list_directory", "reason": "denied"}
        )
    performed.verify(operation, observed)
    observed.contents[("project", "skill/SKILL.md.bak")] = b"actual regular bytes"
    with pytest.raises(ValueError, match="contradicts"):
        performed.verify(operation, observed)


def test_performed_creation_without_bytes_rejects_unexplained_missing_observation() -> None:
    with pytest.raises(ValueError, match="contradicts"):
        PerformedMutation(creation(), None).verify(creation(), FilesystemSnapshot())
