"""Repair constraints retain every JSON value except the declared target object."""

import copy
import json
from typing import Any, cast

import pytest

from tools.install_sandbox.contracts.effects import Destination, JsonHooksEffect
from tools.install_sandbox.contracts.spec import HookExpectation
from tools.install_sandbox.rules.comparison import json_equal, read_json
from tools.install_sandbox.rules.json_hook_repair import (
    altered_hook_settings,
    altered_target_preserved,
    missing_hook_settings,
    prepared_hook_settings,
    removed_target_preserved,
    repaired_json_preserved,
    target_group_preserved,
    without_target,
)

TARGET = HookExpectation("target", "Before", "Read", {"type": "command", "command": "run"})
EFFECT = JsonHooksEffect(Destination("project", "settings.json"), (TARGET,))


def settings() -> dict[str, Any]:
    return {
        "hooks": {
            "Before": [
                {
                    "matcher": "Read",
                    "metadata": [True, 1, 1.0],
                    "hooks": [{**TARGET.content, "extra": 42}, {"command": "personal"}],
                }
            ]
        },
        "preferences": {"enabled": True},
    }


def test_removal_keeps_observed_values_and_repair_can_use_existing_or_new_group():
    original = settings()
    prepared = cast(
        dict[str, Any], read_json(missing_hook_settings(EFFECT, json.dumps(original).encode()))
    )
    assert prepared["hooks"]["Before"][0]["hooks"] == [{"command": "personal"}]
    assert repaired_json_preserved(prepared, original, TARGET)
    new_group = copy.deepcopy(prepared)
    new_group["hooks"]["Before"].append({"matcher": "Read", "hooks": [dict(TARGET.content)]})
    assert repaired_json_preserved(prepared, new_group, TARGET)
    assert not target_group_preserved(original, new_group, TARGET)


@pytest.mark.parametrize("mutation", ["duplicate", "personal", "metadata", "type", "group"])
def test_repair_rejects_duplicate_or_any_personal_structural_change(mutation: str):
    original = settings()
    prepared = cast(
        dict[str, Any], read_json(missing_hook_settings(EFFECT, json.dumps(original).encode()))
    )
    current = copy.deepcopy(original)
    group = current["hooks"]["Before"][0]
    if mutation == "duplicate":
        group["hooks"].append(dict(TARGET.content))
    elif mutation == "personal":
        group["hooks"][1]["command"] = "changed"
    elif mutation == "metadata":
        group["metadata"].reverse()
    elif mutation == "type":
        current["preferences"]["enabled"] = 1
    else:
        group.pop("metadata")
    if mutation == "duplicate":
        with pytest.raises(ValueError, match="exactly one"):
            repaired_json_preserved(prepared, current, TARGET)
    else:
        assert not repaired_json_preserved(prepared, current, TARGET)


def test_json_structure_is_typed_and_object_order_is_irrelevant():
    assert not json_equal(True, 1)
    assert not json_equal(1, 1.0)
    assert not json_equal(-0.0, 0.0)
    assert not json_equal([1, 2], [2, 1])
    assert json_equal({"a": 1, "b": 2}, {"b": 2, "a": 1})


@pytest.mark.parametrize("number", ["0.123456789123456789", "1e400", "1.000000000000000001"])
def test_preparation_and_oracle_preserve_arbitrary_json_precision(number: str):
    source = (
        '{"hooks":{"Before":[{"matcher":"Read","hooks":['
        '{"type":"command","command":"run"},'
        '{"command":"personal","number":' + number + '}]}]},"text":"\\ud800"}'
    ).encode()
    prepared = missing_hook_settings(EFFECT, source)
    # Build the expected mutation independently by removing the literal observed object.
    expected = source.replace(b'{"type":"command","command":"run"},', b"")
    assert json_equal(read_json(prepared), read_json(expected))
    assert b"\\ud800" in prepared

    assert removed_target_preserved(read_json(source), read_json(expected), TARGET)
    changed = expected.replace(number.encode(), b"0.12345678912345678")
    assert not removed_target_preserved(read_json(source), read_json(changed), TARGET)


@pytest.mark.parametrize(
    ("number", "replacement"),
    [(b"0.123456789123456789", b"0.12345678912345678"), (b"-0", b"0")],
)
def test_intermediate_verifier_uses_original_observation_instead_of_preparation_output(
    number: bytes,
    replacement: bytes,
):
    from tools.install_sandbox.contracts.expectations import Expectation, ExpectationSet
    from tools.install_sandbox.contracts.observation import FilesystemSnapshot
    from tools.install_sandbox.rules.effect_verifier import EffectVerifier

    source = (
        b'{"hooks":{"Before":[{"matcher":"Read","hooks":['
        b'{"type":"command","command":"run"},'
        b'{"command":"personal","precision":' + number + b"}]}]}}"
    )
    expected = ExpectationSet(
        "intermediate",
        (
            Expectation(
                "json-hook-removed",
                "project",
                "settings.json",
                "intermediate",
                "observation:original",
                baseline=source,
                hooks=(TARGET,),
            ),
        ),
        roots={"home": "/home", "project": "/project"},
    )
    corrupted = source.replace(b'{"type":"command","command":"run"},', b"").replace(
        number, replacement
    )
    observed = FilesystemSnapshot(
        entries=[
            {"root": "home", "path": ".", "kind": "directory", "listing_complete": True},
            {"root": "project", "path": ".", "kind": "directory", "listing_complete": True},
            {"root": "project", "path": "settings.json", "kind": "file"},
        ],
        contents={("project", "settings.json"): corrupted},
    )
    result = EffectVerifier().verify(expected, observed)
    assert result.complete
    assert [item.type for item in result.mismatches] == ["user_content_lost"]


def test_unsupported_decimal_exponent_is_a_verifiable_json_error():
    with pytest.raises(ValueError, match="supported range"):
        read_json(b'{"value":1e9999999999999999999999}')


def test_parser_supported_deep_hook_values_survive_preparation_and_reinstall():

    nested = b"[" * 600 + b"0.123456789123456789" + b"]" * 600
    source = (
        b'{"hooks":{"Before":[{"matcher":"Read","hooks":['
        b'{"type":"command","command":"run"},'
        b'{"command":"personal","nested":' + nested + b"}]}]}}"
    )
    original = read_json(source)
    prepared_bytes = missing_hook_settings(EFFECT, source)
    prepared = read_json(prepared_bytes)
    assert nested in prepared_bytes
    assert removed_target_preserved(original, prepared, TARGET)
    assert repaired_json_preserved(prepared, original, TARGET)
    assert target_group_preserved(original, read_json(source), TARGET)
    # The observation remains unchanged by shallow path mutations.
    assert json_equal(original, read_json(source))
    changed = read_json(prepared_bytes.replace(b"0.123456789123456789", b"0.1"))
    assert not removed_target_preserved(original, changed, TARGET)


def test_json_beyond_parser_nesting_limit_reports_controlled_error():
    depth = 10_000
    with pytest.raises(ValueError, match="parser depth"):
        read_json(b'{"nested":' + b"[" * depth + b"0" + b"]" * depth + b"}")


@pytest.mark.parametrize("ancestor", ["events", "group"])
def test_preparation_rejects_object_replaced_by_array_of_pairs(ancestor: str) -> None:
    original = settings()
    prepared = copy.deepcopy(original)
    groups = prepared["hooks"]["Before"]
    groups[0]["hooks"].pop(0)
    if ancestor == "group":
        groups[0] = list(groups[0].items())
    else:
        prepared["hooks"] = list(prepared["hooks"].items())
    assert not removed_target_preserved(original, prepared, TARGET)


def test_removing_search_preserves_integer_negative_zero_in_read_hook():
    search = HookExpectation(
        "search", "PreToolUse", "Bash|Grep", {"command": "graphify hook-guard search"}
    )
    read = HookExpectation(
        "read", "PreToolUse", "Read|Glob", {"command": "graphify hook-guard read"}
    )
    effect = JsonHooksEffect(Destination("project", "settings.json"), (search, read))
    source = (
        b'{"hooks":{"PreToolUse":['
        b'{"matcher":"Bash|Grep","hooks":[{"command":"graphify hook-guard search"},'
        b'{"command":"personal"}]},'
        b'{"matcher":"Read|Glob","hooks":[{"command":"graphify hook-guard read","offset":-0}]}]}}'
    )
    expected = source.replace(b'{"command":"graphify hook-guard search"},', b"")
    prepared = missing_hook_settings(effect, source)
    assert b'"offset":-0' in prepared
    assert removed_target_preserved(read_json(source), read_json(prepared), search)
    assert repaired_json_preserved(read_json(expected), read_json(source), search)
    for replacement in (b"0", b"-0.0", b"false"):
        changed = expected.replace(b'"offset":-0', b'"offset":' + replacement)
        assert not removed_target_preserved(read_json(source), read_json(changed), search)
        repaired = source.replace(b'"offset":-0', b'"offset":' + replacement)
        assert not repaired_json_preserved(read_json(expected), read_json(repaired), search)


def test_integer_negative_zero_is_distinct_from_other_json_zero_types():
    negative = read_json(b'{"value":-0}')
    for token in (b"0", b"-0.0", b"false"):
        assert not json_equal(negative, read_json(b'{"value":' + token + b"}"))


TIMED_TARGET = HookExpectation(
    "target", "Before", "Read", {"type": "command", "command": "run", "timeout": 10}
)
TIMED_EFFECT = JsonHooksEffect(Destination("project", "settings.json"), (TIMED_TARGET,))


def timed_source() -> bytes:
    return (
        b'{"hooks":{"Before":[{"matcher":"Read","metadata":[true,1,1.0],"hooks":['
        b'{"type":"command","command":"run","timeout":10,"extra":42},'
        b'{"command":"personal","precision":0.123456789123456789,"offset":-0}]}]},'
        b'"preferences":{"enabled":true}}'
    )


def test_alteration_changes_only_observed_timeout_and_retains_position():
    source = timed_source()
    expected = source.replace(b'"timeout":10', b'"timeout":11')
    prepared = altered_hook_settings(TIMED_EFFECT, source)
    assert json_equal(read_json(prepared), read_json(expected))
    assert prepared_hook_settings(TIMED_EFFECT, source, "altered-json-hook") == prepared
    assert altered_target_preserved(read_json(source), read_json(expected), TIMED_TARGET)
    with pytest.raises(ValueError, match="Unsupported"):
        prepared_hook_settings(TIMED_EFFECT, source, "unknown")


@pytest.mark.parametrize("timeout", [None, True, 10.0, "10"])
def test_alteration_requires_declared_integer_timeout(timeout: object):
    target = HookExpectation("target", "Before", "Read", {**TARGET.content, "timeout": timeout})
    effect = JsonHooksEffect(EFFECT.destination, (target,))
    with pytest.raises(ValueError, match="integer timeout"):
        altered_hook_settings(effect, timed_source())


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (b'"timeout":11', b'"timeout":11.0'),
        (b'"timeout":11', b'"timeout":true'),
        (b'"extra":42', b'"extra":43'),
        (b'"offset":-0', b'"offset":0'),
        (b"0.123456789123456789", b"0.12345678912345678"),
        (b"[true,1,1.0]", b"[1,true,1.0]"),
    ],
)
def test_alteration_oracle_rejects_collateral_and_typed_changes(old: bytes, new: bytes):
    source = timed_source()
    altered = source.replace(b'"timeout":10', b'"timeout":11')
    assert not altered_target_preserved(
        read_json(source), read_json(altered.replace(old, new)), TIMED_TARGET
    )


def test_alteration_oracle_rejects_moved_target_before_reinstall():
    source = timed_source()
    altered = cast(dict[str, Any], read_json(source.replace(b'"timeout":10', b'"timeout":11')))
    altered["hooks"]["Before"][0]["hooks"].reverse()
    assert not altered_target_preserved(read_json(source), altered, TIMED_TARGET)


def test_altered_expectation_verifies_independently_from_preparation_output():
    from tools.install_sandbox.contracts.expectations import Expectation, ExpectationSet
    from tools.install_sandbox.contracts.observation import FilesystemSnapshot
    from tools.install_sandbox.rules.effect_verifier import EffectVerifier

    item = Expectation(
        "json-hook-altered",
        "project",
        "settings.json",
        "intermediate",
        "observation:first",
        baseline=timed_source(),
        hooks=(TIMED_TARGET,),
    )
    assert Expectation.from_data(item.to_data()) == item
    expected = ExpectationSet(
        "intermediate", (item,), roots={"home": "/home", "project": "/project"}
    )
    altered = timed_source().replace(b'"timeout":10', b'"timeout":11')
    for current, valid in (
        (altered, True),
        (altered.replace(b'"offset":-0', b'"offset":0'), False),
    ):
        observed = FilesystemSnapshot(
            entries=[
                {"root": "home", "path": ".", "kind": "directory", "listing_complete": True},
                {"root": "project", "path": ".", "kind": "directory", "listing_complete": True},
                {"root": "project", "path": "settings.json", "kind": "file"},
            ],
            contents={("project", "settings.json"): current},
        )
        result = EffectVerifier().verify(expected, observed)
        assert result.complete
        assert (not result.mismatches) == valid


def test_final_repair_allows_move_but_rejects_altered_remnants_anywhere():
    original = read_json(timed_source())
    prepared = without_target(original, TIMED_TARGET)
    moved = cast(dict[str, Any], read_json(timed_source()))
    group = moved["hooks"]["Before"][0]
    hook = group["hooks"].pop(0)
    moved["hooks"]["Before"].append({"matcher": "Read", "hooks": [hook]})
    assert repaired_json_preserved(prepared, moved, TIMED_TARGET)
    moved["hooks"]["Other"] = [{"matcher": "Elsewhere", "hooks": [{**hook, "timeout": 11}]}]
    assert not repaired_json_preserved(prepared, moved, TIMED_TARGET)


def test_alteration_uses_declared_integer_instead_of_fixed_timeout():
    target = HookExpectation("target", "Before", "Read", {**TARGET.content, "timeout": 23})
    source = timed_source().replace(b'"timeout":10', b'"timeout":23')
    effect = JsonHooksEffect(EFFECT.destination, (target,))
    assert json_equal(
        read_json(altered_hook_settings(effect, source)),
        read_json(source.replace(b'"timeout":23', b'"timeout":24')),
    )


def duplicate_source() -> dict[str, Any]:
    document = settings()
    document["hooks"]["Before"].append(
        {
            "matcher": "Read",
            "sandbox_personal": "duplicate-destination",
            "hooks": [{"command": "personal A"}, {"command": "personal B"}],
        }
    )
    return document


def test_duplication_copies_complete_observed_hook_between_witnesses():
    from tools.install_sandbox.rules.json_hook_repair import duplicated_target_preserved

    source = duplicate_source()
    original = copy.deepcopy(source)
    prepared = prepared_hook_settings(EFFECT, json.dumps(source).encode(), "duplicate-json-hook")
    expected = copy.deepcopy(source)
    expected["hooks"]["Before"][1]["hooks"].insert(
        1, copy.deepcopy(source["hooks"]["Before"][0]["hooks"][0])
    )
    assert json_equal(read_json(prepared), expected)
    assert duplicated_target_preserved(source, expected, TARGET)
    assert source == original


def mutate_duplicate_candidate(current: dict[str, Any], mutation: str) -> None:
    groups = current["hooks"]["Before"]
    copied = groups[1]["hooks"][1]
    if mutation == "missing":
        groups[1]["hooks"].pop(1)
    elif mutation == "triple":
        groups[0]["hooks"].append(copy.deepcopy(copied))
    else:
        mutate_duplicate_structure(current, mutation)


def mutate_duplicate_structure(current: dict[str, Any], mutation: str) -> None:
    groups = current["hooks"]["Before"]
    copied = groups[1]["hooks"][1]
    if mutation == "lost-extra":
        copied.pop("extra")
    elif mutation == "typed-extra":
        copied["extra"] = 42.0
    elif mutation == "moved-original":
        groups[0]["hooks"].reverse()
    elif mutation == "reversed":
        groups[1]["hooks"].reverse()
    elif mutation == "wrong-group":
        groups[0]["hooks"].append(groups[1]["hooks"].pop(1))
    elif mutation == "other":
        current["preferences"]["enabled"] = 1
    else:
        assert mutation == "none"


@pytest.mark.parametrize(
    ("mutation", "mismatch"),
    [
        ("none", None),
        ("lost-extra", "user_content_lost"),
        ("typed-extra", "user_content_lost"),
        ("moved-original", "user_content_lost"),
        ("reversed", "user_content_lost"),
        ("wrong-group", "user_content_lost"),
        ("other", "user_content_lost"),
        ("missing", "hook_count"),
        ("triple", "hook_count"),
    ],
)
def test_duplication_verifier_independently_checks_full_copy_and_inverse(
    mutation: str, mismatch: str | None
):
    from tools.install_sandbox.contracts.expectations import Expectation, ExpectationSet
    from tools.install_sandbox.contracts.observation import FilesystemSnapshot
    from tools.install_sandbox.rules.effect_verifier import EffectVerifier

    source = duplicate_source()
    # Construct the observed candidate without using the preparation mutator.
    current = copy.deepcopy(source)
    groups = current["hooks"]["Before"]
    groups[1]["hooks"].insert(1, copy.deepcopy(groups[0]["hooks"][0]))
    mutate_duplicate_candidate(current, mutation)
    item = Expectation(
        "json-hook-duplicated",
        "project",
        "settings.json",
        "intermediate",
        "observation:first",
        baseline=json.dumps(source).encode(),
        hooks=(TARGET,),
    )
    assert Expectation.from_data(item.to_data()) == item
    expected = ExpectationSet(
        "intermediate", (item,), roots={"home": "/home", "project": "/project"}
    )
    observed = FilesystemSnapshot(
        entries=[
            {"root": "home", "path": ".", "kind": "directory", "listing_complete": True},
            {"root": "project", "path": ".", "kind": "directory", "listing_complete": True},
            {"root": "project", "path": "settings.json", "kind": "file"},
        ],
        contents={("project", "settings.json"): json.dumps(current).encode()},
    )
    result = EffectVerifier().verify(expected, observed)
    assert result.complete
    assert [item.type for item in result.mismatches] == ([] if mismatch is None else [mismatch])
