"""Reference preparation permissions and source selection are explicit contracts."""

from dataclasses import replace

import pytest

from tests.install_sandbox.component.contracts.reference_support import (
    reference_case,
    reference_sources,
)
from tools.install_sandbox.contracts.effects import Destination
from tools.install_sandbox.contracts.expectations import Expectation, ExpectationSet
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import SnapshotEntry
from tools.install_sandbox.rules.effect_verifier import EffectVerifier
from tools.install_sandbox.rules.expectation_builder import (
    build_initial_expectations,
    selected_reference,
)


def test_selection_uses_nested_source_lexical_order_and_requires_complete_nonempty_bundle():
    case, sources = reference_case(), reference_sources()
    assert selected_reference(case, sources) == Destination(
        "project", "skill/references/a/nested.md"
    )
    build_initial_expectations(case, sources)
    sources.entries[1]["listing_complete"] = False
    with pytest.raises(ValueError, match="Incomplete"):
        build_initial_expectations(case, sources)
    sources = reference_sources()
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


@pytest.mark.parametrize("phase", ["intermediate", "reinstall"])
def test_removal_permissions_require_baseline_file_and_exact_absence(phase: str) -> None:
    absent = Expectation("absent", "project", "reference", phase, "case")
    original = Expectation("file", "project", "reference", phase, "prior", b"ref")
    expected = ExpectationSet(
        phase,
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
        {"allowed_changes": expected.allowed_removals},
    ):
        with pytest.raises(ValueError):
            replace(expected, **changes)


@pytest.mark.parametrize("phase", ["intermediate", "reinstall"])
def test_removal_allows_only_selected_file_and_requires_complete_observed_absence(
    phase: str,
) -> None:
    expected = ExpectationSet(
        phase,
        (Expectation("absent", "project", "reference", phase, "case"),),
        baseline=(
            Expectation("file", "project", "reference", phase, "prior", b"ref"),
            Expectation("file", "home", "personal", phase, "prior", b"keep"),
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


@pytest.mark.parametrize("content", [b"", b"\x00\xff", b"already\nSandbox repair witness.\n"])
def test_append_codec_and_binding_accept_exact_regular_bytes(content: bytes):
    import hashlib

    from tools.install_sandbox.contracts.bound_mutation import (
        BoundFileAppend,
        PerformedMutation,
        mutation_from_data,
    )

    case_bytes = b"retained case"
    snapshot = FilesystemSnapshot(
        entries=[{"root": "project", "path": "reference", "kind": "file"}],
        contents={("project", "reference"): content},
    )
    operation = BoundFileAppend(
        hashlib.sha256(case_bytes).hexdigest(),
        "steps/0/after.json",
        Destination("project", "reference"),
        hashlib.sha256(content).hexdigest(),
        b"\nwitness\n",
    )
    assert mutation_from_data(operation.to_data()) == operation
    assert operation.verify_binding(case_bytes, snapshot) == content
    resulting = content + operation.suffix
    performed = PerformedMutation(operation, hashlib.sha256(resulting).hexdigest())
    assert PerformedMutation.from_data(performed.to_data()) == performed
    snapshot.contents[("project", "reference")] = resulting
    performed.verify(operation, snapshot)
    with pytest.raises(ValueError, match="binding"):
        operation.verify_binding(case_bytes, snapshot)
    with pytest.raises(ValueError, match="digest"):
        operation.verify_binding(b"other", snapshot)
    with pytest.raises(ValueError, match="suffix"):
        replace(operation, suffix=b"")
    with pytest.raises(ValueError, match="observation"):
        replace(operation, observation_ref="steps/1/after.json")
    snapshot.entries[0]["kind"] = "symlink"
    snapshot.contents[("project", "reference")] = content
    with pytest.raises(ValueError, match="regular"):
        operation.verify_binding(case_bytes, snapshot)


@pytest.mark.parametrize("change", ["suffix", "selection", "destination", "version"])
def test_altered_reference_case_rejects_tampered_definition(change: str):
    import json

    from tools.install_sandbox.contracts.effect_case import EffectInstallCase
    from tools.install_sandbox.contracts.intermediate import AlteredReferencePreparation

    case = replace(
        reference_case(),
        name="altered-reference",
        intermediate_preparation=AlteredReferencePreparation(Destination("project", "skill")),
    )
    assert EffectInstallCase.from_json(case.to_json()) == case
    raw = json.loads(case.to_json())
    if change == "version":
        raw["format"] = "explicit-expectations-v6"
    elif change == "destination":
        raw["intermediate_preparation"][change]["root"] = "home"
    else:
        raw["intermediate_preparation"][change] = "YQ==" if change == "suffix" else "last"
    with pytest.raises(ValueError):
        EffectInstallCase.from_json(json.dumps(raw))


def test_altered_reference_shares_selection_and_source_preconditions():
    from tools.install_sandbox.contracts.intermediate import AlteredReferencePreparation

    case = replace(
        reference_case(),
        name="altered-reference",
        intermediate_preparation=AlteredReferencePreparation(Destination("project", "skill")),
    )
    sources = reference_sources()
    assert selected_reference(case, sources) == selected_reference(reference_case(), sources)
    build_initial_expectations(case, sources)
    sources.contents.pop(("subject", "refs/a/nested.md"))
    with pytest.raises(ValueError, match="unavailable"):
        build_initial_expectations(case, sources)


@pytest.mark.parametrize("phase", ["initial", "install"])
def test_removal_permission_is_rejected_before_first_install_even_with_matching_baseline(
    phase: str,
) -> None:
    with pytest.raises(ValueError, match="Removals"):
        ExpectationSet(
            phase,
            (Expectation("absent", "project", "reference", phase, "case"),),
            baseline=(Expectation("file", "project", "reference", phase, "prior", b"ref"),),
            allowed_removals=(("project", "reference"),),
        )
