"""Independent bytes exercise missing-section construction and its oracle."""

import hashlib
from dataclasses import replace

import pytest

from tools.install_sandbox.contracts.bound_mutation import BoundMarkdownMutation
from tools.install_sandbox.contracts.effect_case import (
    EffectInstallCase,
    EffectRules,
    SubjectContext,
    build_effect_cases,
)
from tools.install_sandbox.contracts.effects import (
    Destination,
    EffectSpec,
    MarkdownSectionEffect,
    SkillEffect,
)
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.rules.effect_verifier import EffectVerifier
from tools.install_sandbox.rules.expectation_builder import build_install_expectations
from tools.install_sandbox.rules.repair_scenario import (
    PreparationBlocked,
    PreparationPlan,
    repair_scenario_from_case,
)

ROOTS = {"home": "/sandbox/home", "project": "/sandbox/project"}
BEFORE = b"## Personal before\nKeep before.\n\n"
AFTER = b"## Personal after\nKeep after.\n\n"
SOURCE = b"## graphify\nManaged \xc3\xa9 bytes.\n### Detail\nPreserve body.\n\n"
KEY = ("project", "CODEBUDDY.md")


def snapshot(files: dict[tuple[str, str], bytes]) -> FilesystemSnapshot:
    return FilesystemSnapshot(
        entries=[
            {"root": "home", "path": ".", "kind": "directory", "listing_complete": True},
            {"root": "project", "path": ".", "kind": "directory", "listing_complete": True},
            *({"root": root, "path": path, "kind": "file"} for root, path in files),
        ],
        contents=files.copy(),
    )


def inputs(index: int = 1, source: bytes = SOURCE):
    spec = EffectSpec((MarkdownSectionEffect("section.md", Destination(*KEY)),))
    subject = SubjectContext(
        "test",
        ("install",),
        "VERSION",
        EffectRules(10, "persistent", ".graphify-bak", ".bak", False),
    )
    case = build_effect_cases(spec, subject).cases[index]
    initial = snapshot({(f["root"], f["path"]): f["content"].encode() for f in case.initial_files})
    sources = snapshot({("subject", "section.md"): source})
    installed = build_install_expectations(case, sources, initial, ROOTS)
    first = snapshot({**initial.contents, KEY: BEFORE + source + AFTER})
    validation = EffectVerifier().verify(installed, first)
    return case, sources, installed, first, validation


def plan():
    case, sources, installed, first, validation = inputs()
    result = repair_scenario_from_case(case, sources).bind(
        first, "steps/0/after.json", validation, installed, case.to_json().encode()
    )
    assert isinstance(result, PreparationPlan)
    return result, first


def test_case_bytes_round_trip_and_bound_operation() -> None:
    case, _, _, _, _ = inputs()
    archived = case.to_json().encode()
    assert EffectInstallCase.from_json(archived.decode()) == case
    prepared, first = plan()
    operation = prepared.operation
    assert isinstance(operation, BoundMarkdownMutation)
    assert operation.case_sha256 == hashlib.sha256(archived).hexdigest()
    assert operation.document_sha256 == hashlib.sha256(BEFORE + SOURCE + AFTER).hexdigest()
    assert (operation.start, operation.end) == (len(BEFORE), len(BEFORE + SOURCE))
    assert BoundMarkdownMutation.from_data(operation.to_data()) == operation
    assert first.contents[KEY][operation.start : operation.end] == SOURCE


def test_first_install_requires_exact_witness_position_and_bytes() -> None:
    _, _, installed, first, _ = inputs()
    first.contents[KEY] = BEFORE + AFTER + SOURCE
    assert EffectVerifier().verify(installed, first).mismatches


@pytest.mark.parametrize(
    "document", [SOURCE + BEFORE + AFTER, BEFORE + SOURCE + AFTER, BEFORE + AFTER + SOURCE]
)
def test_composed_repair_accepts_each_placement(document: bytes) -> None:
    prepared, first = plan()
    first.contents[KEY] = document
    result = EffectVerifier().verify(prepared.second_install_expectations, first)
    assert result.complete and not result.mismatches and not result.obstacles


@pytest.mark.parametrize(
    "document",
    [
        BEFORE + AFTER,
        BEFORE + SOURCE + SOURCE + AFTER,
        BEFORE + SOURCE.replace(b"Managed", b"Wrong") + AFTER,
        AFTER + SOURCE + BEFORE,
        BEFORE[:-1] + SOURCE + AFTER,
    ],
)
def test_composed_repair_rejects_source_or_personal_changes(document: bytes) -> None:
    prepared, first = plan()
    first.contents[KEY] = document
    assert EffectVerifier().verify(prepared.second_install_expectations, first).mismatches


def test_removal_oracle_is_independent_of_range_and_preserves_other_files() -> None:
    prepared, first = plan()
    first.contents[KEY] = BEFORE + AFTER
    assert not EffectVerifier().verify(prepared.after_preparation_expectations, first).mismatches
    first.contents[KEY] = BEFORE + AFTER[1:]
    assert EffectVerifier().verify(prepared.after_preparation_expectations, first).mismatches
    first.contents[KEY] = BEFORE + AFTER
    first.contents[("project", "personal-effect-0.txt")] = b"changed"
    assert EffectVerifier().verify(prepared.after_preparation_expectations, first).mismatches


def test_preparation_rechecks_observation_and_exact_case_bytes() -> None:
    case, sources, installed, first, validation = inputs()
    first.contents[KEY] = BEFORE + b"changed" + AFTER
    blocked = repair_scenario_from_case(case, sources).bind(
        first, "steps/0/after.json", validation, installed, case.to_json().encode()
    )
    assert isinstance(blocked, PreparationBlocked)
    with pytest.raises(ValueError):
        replace(plan()[0].operation, start=True)


def test_case_derivation_reports_missing_markdown_capability() -> None:
    case, _, _, _, _ = inputs()
    empty = build_effect_cases(
        EffectSpec((SkillEffect("skill.md", "references", Destination("home", "skills")),)),
        case.subject,
    )
    assert [built.name for built in empty.cases] == [
        "reinstall",
        "missing-reference",
        "altered-reference",
        "altered-skill",
        "preserve-skill-backup",
    ]
    assert [(item.name, item.classification, item.reason) for item in empty.decisions] == [
        (name, "not_applicable", "No Markdown effect declared")
        for name in ("missing-section", "altered-section")
    ] + [
        (name, "not_applicable", "No JSON hooks effect declared")
        for name in ("missing-json-hook", "altered-json-hook", "duplicate-json-hook")
    ]


def test_operation_hashes_exact_archived_case_bytes() -> None:
    case, sources, installed, first, validation = inputs()
    archived = b"\n" + case.to_json().encode()
    prepared = repair_scenario_from_case(case, sources).bind(
        first, "steps/0/after.json", validation, installed, archived
    )
    assert isinstance(prepared, PreparationPlan)
    assert prepared.operation.case_sha256 == hashlib.sha256(archived).hexdigest()
    assert prepared.operation.case_sha256 != hashlib.sha256(case.to_json().encode()).hexdigest()


def test_altered_body_bounds_and_independent_oracle() -> None:
    case, sources, installed, first, validation = inputs(2)
    prepared = repair_scenario_from_case(case, sources).bind(
        first, "steps/0/after.json", validation, installed, case.to_json().encode()
    )
    assert isinstance(prepared, PreparationPlan)
    operation = prepared.operation
    assert isinstance(operation, BoundMarkdownMutation)
    header = b"## graphify\n"
    body = b"\nSandbox altered Markdown section.\n\n"
    assert operation.start == len(BEFORE + header)
    assert operation.end == len(BEFORE + SOURCE)
    assert operation.replacement == body
    assert b"### Detail" in first.contents[KEY][operation.start : operation.end]
    first.contents[KEY] = BEFORE + header + body + AFTER
    assert not EffectVerifier().verify(prepared.after_preparation_expectations, first).mismatches
    first.contents[KEY] = BEFORE + header[:-1] + body + AFTER
    assert EffectVerifier().verify(prepared.after_preparation_expectations, first).mismatches


@pytest.mark.parametrize(
    "source", [b"## graphify\n", b"## graphify\n\nSandbox altered Markdown section.\n\n"]
)
def test_altered_preparation_requires_a_real_body_change(source: bytes) -> None:
    case, sources, installed, first, validation = inputs(2, source)
    result = repair_scenario_from_case(case, sources).bind(
        first, "steps/0/after.json", validation, installed, case.to_json().encode()
    )
    assert isinstance(result, PreparationBlocked)
