"""Family facts retain known presence despite unrelated observation failures."""

import json
from typing import Any, cast

import pytest

from tools.install_sandbox.contracts.effects import (
    Destination,
    EffectSpec,
    FileEffect,
    JsonHooksEffect,
)
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import SnapshotEntry, VerificationResult
from tools.install_sandbox.contracts.spec import HookExpectation
from tools.install_sandbox.rules.group_assessment import assess_group_step as _assess_group_step
from tools.install_sandbox.rules.group_assessment import inspect


def assess_group_step(*args: Any) -> tuple[dict[str, Any], VerificationResult]:
    report, result = _assess_group_step(*args)
    return cast(dict[str, Any], report), result


def snapshot(
    files: tuple[tuple[str, str, bytes | None], ...] = (), missing_home: bool = False
) -> FilesystemSnapshot:
    result = FilesystemSnapshot(
        entries=[
            SnapshotEntry(root=root, path=".", kind="directory", listing_complete=True)
            for root in ("project",)
            if missing_home
        ]
        if missing_home
        else [
            SnapshotEntry(root=root, path=".", kind="directory", listing_complete=True)
            for root in ("home", "project")
        ]
    )
    for root, path, content in files:
        result.entries.append(SnapshotEntry(root=root, path=path, kind="file"))
        if content is not None:
            result.contents[root, path] = content
    return result


def hook_effect() -> JsonHooksEffect:
    return JsonHooksEffect(
        Destination("project", "settings.json"),
        tuple(
            HookExpectation(name, "Start", "*", dict(type="command", command=name, timeout=5))
            for name in ("one", "two")
        ),
        effect_id="hooks",
    )


def document(*commands: tuple[str, int]) -> bytes:
    return json.dumps(
        dict(
            hooks=dict(
                Start=[
                    dict(
                        matcher="*",
                        hooks=[
                            dict(type="command", command=command, timeout=timeout)
                            for command, timeout in commands
                        ],
                    )
                ]
            )
        )
    ).encode()


def test_file_lstat_presence_survives_unreadable_bytes() -> None:
    effect = FileEffect("expected", Destination("home", "literal"))
    facts = inspect(effect, snapshot(), snapshot((("home", "literal", None),)))
    assert facts.items[0].presence == "present"
    assert facts.items[0].conformity == "indeterminate"


def test_hook_identity_distinguishes_bad_timeout_and_duplicate() -> None:
    effect = hook_effect()
    facts = inspect(
        effect,
        snapshot(),
        snapshot((("project", "settings.json", document(("one", 9), ("two", 5), ("two", 5))),)),
    )
    assert [(i.presence, i.conformity) for i in facts.items] == [
        ("present", "invalid"),
        ("present", "invalid"),
    ]


def test_partial_removal_with_unreadable_file_and_personal_loss() -> None:
    effects = EffectSpec((hook_effect(), FileEffect("expected", Destination("home", "literal"))))
    initial = snapshot((("project", "settings.json", document(("personal", 7))),))
    before = snapshot(
        (
            ("project", "settings.json", document(("one", 5), ("two", 5), ("personal", 7))),
            ("home", "literal", b"expected"),
        )
    )
    after = snapshot((("project", "settings.json", b"{}"), ("home", "literal", None)))
    report, verdict = assess_group_step(
        {"tool:project": effects},
        ("tool:project",),
        ("tool:project",),
        True,
        initial,
        before,
        after,
    )
    assert report["tool:project"]["summary"] == "partially_removed"
    assert report["tool:project"]["preservation"] == "violated"
    assert verdict.mismatches and not verdict.complete


def test_missing_root_does_not_erase_known_hook_absence() -> None:
    effects = EffectSpec((hook_effect(), FileEffect("expected", Destination("home", "literal"))))
    after = snapshot((("project", "settings.json", b"{}"),), missing_home=True)
    report, verdict = assess_group_step(
        {"tool:project": effects},
        ("tool:project",),
        ("tool:project",),
        True,
        snapshot(),
        snapshot(),
        after,
    )
    state = report["tool:project"]
    assert state["summary"] == "indeterminate"
    assert [i["presence"] for i in state["items"]] == ["absent", "absent", "indeterminate"]
    assert not verdict.complete


def test_protected_reformat_is_violation_even_with_other_unknown_path() -> None:
    effects = EffectSpec((hook_effect(), FileEffect("expected", Destination("home", "literal"))))
    content = document(("one", 5), ("two", 5))
    before = snapshot((("project", "settings.json", content), ("home", "literal", b"expected")))
    after = snapshot((("project", "settings.json", content + b"\n"),), missing_home=True)
    report, verdict = assess_group_step(
        {"protected": effects}, ("protected",), (), True, snapshot(), before, after
    )
    assert report["protected"]["preservation"] == "violated"
    assert verdict.mismatches and not verdict.complete


def test_literal_file_yaml_transport_and_wrong_bytes() -> None:
    from tools.install_sandbox.host.effect_reader import EffectSpecReader

    declaration = EffectSpecReader().from_yaml("""tool: sample
scopes:
  user:
    - effect_id: config
      family: file
      root: HOME
      path: config.txt
      content: "literal bytes"
""")
    spec = declaration.scopes[0].effects
    assert spec is not None
    assert EffectSpec.from_data(spec.to_data()) == spec
    result = inspect(spec.effects[0], snapshot(), snapshot((("home", "config.txt", b"wrong"),)))
    assert result.items[0].presence == "present"
    assert result.items[0].conformity == "invalid"


def test_two_hooks_and_remaining_literal_are_partially_removed() -> None:
    effects = EffectSpec((hook_effect(), FileEffect("expected", Destination("home", "literal"))))
    after = snapshot((("project", "settings.json", b"{}"), ("home", "literal", b"expected")))
    report, verdict = assess_group_step(
        {"target": effects}, ("target",), ("target",), True, snapshot(), snapshot(), after
    )
    assert report["target"]["summary"] == "partially_removed"
    assert [item["presence"] for item in report["target"]["items"]] == [
        "absent",
        "absent",
        "present",
    ]
    assert verdict.mismatches


def test_partial_removal_within_one_json_document() -> None:
    effects = EffectSpec((hook_effect(),))
    after = snapshot((("project", "settings.json", document(("two", 5))),))
    report, verdict = assess_group_step(
        {"target": effects}, ("target",), ("target",), True, snapshot(), snapshot(), after
    )
    assert report["target"]["summary"] == "partially_removed"
    assert [item["member"] for item in report["target"]["items"]] == ["one", "two"]
    assert verdict.mismatches


def test_all_removed_still_fails_when_personal_command_lost() -> None:
    initial = snapshot((("project", "settings.json", document(("personal", 7))),))
    report, verdict = assess_group_step(
        {"target": EffectSpec((hook_effect(),))},
        ("target",),
        ("target",),
        True,
        initial,
        initial,
        snapshot((("project", "settings.json", b"{}"),)),
    )
    assert report["target"]["summary"] == "all_removed"
    assert report["target"]["preservation"] == "violated"
    assert verdict.mismatches


def test_invalid_json_is_indeterminate_but_bad_file_is_present() -> None:
    facts = inspect(hook_effect(), snapshot(), snapshot((("project", "settings.json", b"[bad"),)))
    assert all(i.presence == i.conformity == "indeterminate" for i in facts.items)
    assert facts.diagnostics


def test_collateral_write_and_incomplete_non_target_bytes_prevent_success() -> None:
    effects = EffectSpec((FileEffect("expected", Destination("home", "literal")),))
    before = snapshot((("project", "personal.txt", b"personal"),))
    after = snapshot((("project", "personal.txt", None), ("project", "surprise.txt", b"new")))
    report, verdict = assess_group_step(
        {"target": effects}, ("target",), ("target",), True, snapshot(), before, after
    )
    assert report["target"]["summary"] == "all_removed"
    assert any(
        m.type == "unexpected_change" and m.path == "surprise.txt" for m in verdict.mismatches
    )
    assert not verdict.complete


def test_preparation_rejects_invalid_hook_with_valid_identity() -> None:
    effects = EffectSpec((hook_effect(),))
    after = snapshot((("project", "settings.json", document(("one", 9), ("two", 5))),))
    _, verdict = assess_group_step(
        {"target": effects}, (), ("target",), False, snapshot(), snapshot(), after
    )
    assert verdict.mismatches


def test_unknown_lstat_does_not_establish_presence_and_report_is_json_native() -> None:
    effects = EffectSpec((FileEffect("expected", Destination("home", "literal")),))
    after = snapshot()
    after.entries.append(SnapshotEntry(root="home", path="literal", kind="unknown"))
    report, verdict = assess_group_step(
        {"target": effects}, ("target",), ("target",), True, snapshot(), snapshot(), after
    )
    assert report == json.loads(json.dumps(report))
    assert report["target"]["items"][0]["presence"] == "indeterminate"
    assert not verdict.complete


def test_protected_backup_bytes_are_preserved() -> None:
    effects = EffectSpec((hook_effect(),))
    content = document(("one", 5), ("two", 5))
    before = snapshot(
        (
            ("project", "settings.json", content),
            ("project", "settings.json.graphify-bak", b"personal"),
        )
    )
    after = snapshot(
        (
            ("project", "settings.json", content),
            ("project", "settings.json.graphify-bak", b"changed"),
        )
    )
    report, verdict = assess_group_step(
        {"protected": effects}, ("protected",), (), True, snapshot(), before, after
    )
    assert report["protected"]["preservation"] == "violated"
    assert verdict.mismatches


def test_unknown_or_unreadable_protected_file_is_not_a_proven_change() -> None:
    effects = EffectSpec((FileEffect("expected", Destination("home", "literal")),))
    before = snapshot((("home", "literal", b"expected"),))
    for kind in ("unknown", "file"):
        after = snapshot((("home", "literal", None),))
        after.entries[-1]["kind"] = kind
        report, verdict = assess_group_step(
            {"protected": effects}, ("protected",), (), True, snapshot(), before, after
        )
        assert report["protected"]["preservation"] == "indeterminate"
        assert not any(m.type == "unexpected_change" for m in verdict.mismatches)
        assert not verdict.complete


def test_home_obstacle_preserves_project_participant_coverage() -> None:
    participants = {
        "home": EffectSpec((FileEffect("home", Destination("home", "literal")),)),
        "project": EffectSpec((FileEffect("project", Destination("project", "literal")),)),
    }
    before = snapshot((("home", "literal", b"home"), ("project", "literal", b"project")))
    after = snapshot((("home", "literal", None), ("project", "literal", b"project")))
    after.obstacles.append(
        {"operation": "read", "root": "home", "path": "literal", "reason": "denied"}
    )
    report, verdict = assess_group_step(
        participants, ("home", "project"), (), True, snapshot(), before, after
    )
    assert not report["home"]["complete"]
    assert report["project"]["complete"]
    assert not verdict.complete
    assert not any(
        o["operation"] == "inspect_group" and o["path"] == "." for o in verdict.obstacles
    )


def test_malformed_event_keeps_other_event_member_facts() -> None:
    first = HookExpectation("first", "First", "*", dict(type="command", command="first"))
    second = HookExpectation("second", "Second", "*", dict(type="command", command="second"))
    effect = JsonHooksEffect(Destination("project", "settings.json"), (first, second))
    content = json.dumps(
        {"hooks": {"First": [{"matcher": "*", "hooks": [first.content]}], "Second": "malformed"}}
    ).encode()
    facts = inspect(effect, snapshot(), snapshot((("project", "settings.json", content),)))
    assert [(i.member, i.presence, i.conformity) for i in facts.items] == [
        ("first", "present", "valid"),
        ("second", "indeterminate", "indeterminate"),
    ]
    assert any(d.member == "second" for d in facts.diagnostics)


def test_active_json_backup_and_forbidden_registry_are_verified() -> None:
    effects = EffectSpec((hook_effect(),))
    initial = snapshot((("project", "settings.json", b"{}"),))
    content = document(("one", 5), ("two", 5))
    for suffix, payload in ((".graphify-bak", b"corrupted"), (".graphify-state.json", b"{}")):
        files = [
            ("project", "settings.json", content),
            ("project", "settings.json.graphify-bak", b"{}"),
        ]
        files = [f for f in files if f[1] != "settings.json" + suffix]
        files.append(("project", "settings.json" + suffix, payload))
        _, verdict = assess_group_step(
            {"target": effects}, (), ("target",), False, initial, initial, snapshot(tuple(files))
        )
        assert verdict.mismatches
        assert any(m.path == "settings.json" + suffix for m in verdict.mismatches)


def test_removal_preserves_previously_verified_backup_bytes() -> None:
    effects = EffectSpec((hook_effect(),))
    before = snapshot(
        (
            ("project", "settings.json", document(("one", 5), ("two", 5))),
            ("project", "settings.json.graphify-bak", b"{}"),
        )
    )
    after = snapshot(
        (
            ("project", "settings.json", b"{}"),
            ("project", "settings.json.graphify-bak", b"corrupted"),
        )
    )
    report, verdict = assess_group_step(
        {"target": effects},
        ("target",),
        ("target",),
        True,
        snapshot((("project", "settings.json", b"{}"),)),
        before,
        after,
    )
    assert report["target"]["summary"] == "all_removed"
    assert report["target"]["preservation"] == "violated"
    assert any(m.path == "settings.json.graphify-bak" for m in verdict.mismatches)


@pytest.mark.parametrize(
    "lock_kind,preservation",
    [("unknown", "indeterminate"), ("file", "violated"), (None, "preserved")],
)
def test_removal_distinguishes_uncertain_present_and_absent_lock(
    lock_kind: str | None, preservation: str
) -> None:
    lock = "settings.json.graphify.lock"
    backup = ("project", "settings.json.graphify-bak", b"{}")
    settings = ("project", "settings.json", b"{}")
    initial = snapshot((settings,))
    before = snapshot((("project", "settings.json", document(("one", 5), ("two", 5))), backup))
    after = snapshot((settings, backup))
    if lock_kind is not None:
        after.entries.append(SnapshotEntry(root="project", path=lock, kind=lock_kind))
    if lock_kind == "file":
        after.contents["project", lock] = b""
    elif lock_kind == "unknown":
        after.obstacles.append(
            {"operation": "stat", "root": "project", "path": lock, "reason": "Permission denied"}
        )

    report, verdict = assess_group_step(
        {"target": EffectSpec((hook_effect(),))},
        ("target",),
        ("target",),
        True,
        initial,
        before,
        after,
    )
    state = report["target"]
    assert [item["presence"] for item in state["items"]] == ["absent", "absent"]
    assert state["summary"] == "all_removed"
    assert state["preservation"] == preservation
    assert state["complete"] == verdict.complete == (lock_kind != "unknown")
    if lock_kind == "file":
        assert any(m.type == "unexpected_entry" and m.path == lock for m in verdict.mismatches)
    else:
        assert not verdict.mismatches
    if lock_kind == "unknown":
        assert after.obstacles[0] in verdict.obstacles
        assert any(
            o["operation"] == "verify_absence" and o["path"] == lock for o in verdict.obstacles
        )
        assert any(
            d["path"] == lock and d["reason"] == "Permission denied" for d in state["diagnostics"]
        )


def test_hook_inspection_does_not_trust_bytes_for_non_file() -> None:
    initial = snapshot((("project", "settings.json", document(("personal", 7))),))
    observed = snapshot((("project", "settings.json", document(("personal", 7))),))
    observed.entries[-1]["kind"] = "other"
    facts = inspect(hook_effect(), initial, observed)
    assert all(item.presence == "indeterminate" for item in facts.items)
    assert facts.preservation == "indeterminate"


@pytest.mark.parametrize(
    "lose_personal,unknown_kind", [(False, False), (True, False), (False, True)]
)
def test_unreadable_active_backup_keeps_known_removal_and_prior_violation(
    lose_personal: bool, unknown_kind: bool
) -> None:
    effects = EffectSpec((hook_effect(),))
    initial = snapshot((("project", "settings.json", document(("personal", 7))),))
    before = snapshot(
        (
            ("project", "settings.json", document(("one", 5), ("two", 5), ("personal", 7))),
            ("project", "settings.json.graphify-bak", b"{}"),
        )
    )
    after = snapshot(
        (
            ("project", "settings.json", b"{}" if lose_personal else document(("personal", 7))),
            ("project", "settings.json.graphify-bak", None),
        )
    )
    if unknown_kind:
        after.entries[-1]["kind"] = "unknown"
    report, verdict = assess_group_step(
        {"target": effects}, ("target",), ("target",), True, initial, before, after
    )
    state = report["target"]
    assert state["summary"] == "all_removed"
    assert state["preservation"] == ("violated" if lose_personal else "indeterminate")
    assert not state["complete"] and not verdict.complete
    assert any(o["path"] == "settings.json.graphify-bak" for o in verdict.obstacles)
    assert any(d["path"] == "settings.json.graphify-bak" for d in state["diagnostics"])
    if lose_personal:
        assert any(d["path"] == "settings.json" for d in state["diagnostics"])


def test_file_only_auxiliaries_keep_not_applicable_preservation() -> None:
    effects = EffectSpec((FileEffect("expected", Destination("project", "literal")),))
    report, verdict = assess_group_step(
        {"target": effects}, ("target",), ("target",), True, snapshot(), snapshot(), snapshot()
    )
    assert report["target"]["preservation"] == "not_applicable"
    assert verdict.complete and not verdict.mismatches
