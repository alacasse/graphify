"""Reference preparation permissions and source selection are explicit contracts."""

from dataclasses import replace

import pytest

from tools.install_sandbox.contracts.effect_case import (
    EffectRules,
    SubjectContext,
    build_effect_cases,
)
from tools.install_sandbox.contracts.effects import Destination, EffectSpec, SkillEffect
from tools.install_sandbox.contracts.expectations import Expectation, ExpectationSet
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import SnapshotEntry
from tools.install_sandbox.rules.effect_verifier import EffectVerifier
from tools.install_sandbox.rules.expectation_builder import (
    build_initial_expectations,
    selected_reference,
)


def _case():
    builds = build_effect_cases(
        EffectSpec((SkillEffect("skill.md", "refs", Destination("project", "skill")),)),
        SubjectContext(
            "synthetic",
            ("python", "installer.py"),
            "VERSION",
            EffectRules(10, "persistent", ".graphify-bak", ".bak", False),
        ),
    )
    return next(case for case in builds.cases if case.name == "missing-reference")


def _sources():
    files = {
        ("subject", "skill.md"): b"skill",
        ("subject", "VERSION"): b"Version: 1\n",
        ("subject", "refs/z.md"): b"z",
        ("subject", "refs/a/nested.md"): b"a",
    }
    result = FilesystemSnapshot(contents=files)
    for path in ("refs", "refs/a"):
        result.entries.append(
            {"root": "subject", "path": path, "kind": "directory", "listing_complete": True}
        )
    for root, path in files:
        result.entries.append({"root": root, "path": path, "kind": "file"})
    return result


def test_selection_uses_nested_source_lexical_order_and_requires_complete_nonempty_bundle():
    case, sources = _case(), _sources()
    assert selected_reference(case, sources) == Destination(
        "project", "skill/references/a/nested.md"
    )
    build_initial_expectations(case, sources)
    sources.entries[1]["listing_complete"] = False
    with pytest.raises(ValueError, match="Incomplete"):
        build_initial_expectations(case, sources)
    sources = _sources()
    sources.entries = [
        entry
        for entry in sources.entries
        if not (entry["kind"] == "file" and entry["path"].startswith("refs/"))
    ]
    sources.contents = {
        key: value for key, value in sources.contents.items() if not key[1].startswith("refs/")
    }
    with pytest.raises(ValueError, match="nonempty"):
        build_initial_expectations(case, sources)


def test_removal_permissions_require_intermediate_baseline_file_and_exact_absence():
    absent = Expectation("absent", "project", "reference", "intermediate", "case")
    original = Expectation("file", "project", "reference", "intermediate", "prior", b"ref")
    expected = ExpectationSet(
        "intermediate",
        (absent,),
        baseline=(original,),
        roots={"home": "/home", "project": "/project"},
        allowed_removals=(("project", "reference"),),
    )
    assert ExpectationSet.from_data(expected.to_data()) == expected
    for changes in (
        {"phase": "install"},
        {"baseline": ()},
        {"expectations": ()},
        {"baseline": (replace(original, kind="directory", content=None),)},
        {"allowed_changes": expected.allowed_removals},
    ):
        with pytest.raises(ValueError):
            replace(expected, **changes)


def test_removal_allows_only_selected_file_and_requires_complete_observed_absence():
    expected = ExpectationSet(
        "intermediate",
        (Expectation("absent", "project", "reference", "intermediate", "case"),),
        baseline=(
            Expectation("file", "project", "reference", "intermediate", "prior", b"ref"),
            Expectation("file", "home", "personal", "intermediate", "prior", b"keep"),
        ),
        roots={"home": "/home", "project": "/project"},
        allowed_removals=(("project", "reference"),),
    )
    entries: list[SnapshotEntry] = [
        {"root": root, "path": ".", "kind": "directory", "listing_complete": True}
        for root in ("home", "project")
    ]
    observed = FilesystemSnapshot(entries=entries)
    verdict = EffectVerifier().verify(expected, observed)
    assert any(item.path == "personal" for item in verdict.mismatches)
    assert not any(item.path == "reference" for item in verdict.mismatches)
    observed.entries[1]["listing_complete"] = False
    assert not EffectVerifier().verify(expected, observed).complete
