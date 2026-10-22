"""Independent in-memory data for construction, binding and comparison boundaries."""

import json
from dataclasses import replace

import pytest

from tools.install_sandbox.container.effect_verifier import EffectVerifier
from tools.install_sandbox.container.environment import FilesystemSnapshot
from tools.install_sandbox.container.expectation_builder import (
    bind_roots,
    build_initial_expectations,
    build_install_expectations,
    build_reinstall_expectations,
)
from tools.install_sandbox.contracts.effect_case import (
    EffectInstallCase,
    EffectRules,
    SubjectContext,
)
from tools.install_sandbox.contracts.effects import (
    Destination,
    EffectSpec,
    JsonHooksEffect,
    MarkdownSectionEffect,
    SkillEffect,
)
from tools.install_sandbox.contracts.expectations import Expectation, ExpectationSet
from tools.install_sandbox.contracts.results import SnapshotEntry, VerificationResult
from tools.install_sandbox.contracts.spec import HookExpectation

ROOTS = {"home": "/sandbox/home", "project": "/sandbox/project"}
HOOK = HookExpectation("audit", "Before", "Shell", {"command": "audit", "timeout": 10})


def _snapshot(
    files: dict[tuple[str, str], bytes], directories: tuple[tuple[str, str], ...]
) -> FilesystemSnapshot:
    entries: list[SnapshotEntry] = [
        {"root": root, "path": path, "kind": "directory", "listing_complete": True}
        for root, path in directories
    ]
    entries.extend({"root": root, "path": path, "kind": "file"} for root, path in files)
    return FilesystemSnapshot(entries=entries, contents=dict(files))


def _case() -> EffectInstallCase:
    return EffectInstallCase(
        "reinstall",
        "synthetic",
        "project",
        EffectSpec(
            (
                SkillEffect("skill.md", "references", Destination("project", "skills/graphify")),
                MarkdownSectionEffect("section.md", Destination("project", "AGENTS.md")),
                JsonHooksEffect(Destination("home", "settings.json"), (HOOK,)),
            )
        ),
        SubjectContext(
            "synthetic",
            ("python", "installer.py"),
            "VERSION",
            EffectRules(10, "persistent", ".graphify-bak", ".bak", False),
        ),
        [
            {"root": "project", "path": "AGENTS.md", "content": "# Personal\n"},
            {"root": "home", "path": "settings.json", "content": '{"theme":"dark"}\n'},
        ],
        ["install", "install"],
    )


def _sources() -> FilesystemSnapshot:
    return _snapshot(
        {
            ("subject", "skill.md"): b"Retained skill\n",
            ("subject", "section.md"): b"## graphify\nRetained section\n",
            ("subject", "VERSION"): b"Version: 4.2\n",
            ("subject", "references/nested/guide.md"): b"Nested reference\n",
        },
        (("subject", "references"), ("subject", "references/nested")),
    )


def _before() -> FilesystemSnapshot:
    return _snapshot(
        {
            ("project", "AGENTS.md"): b"# Personal\n",
            ("home", "settings.json"): b'{"theme":"dark"}\n',
            ("home", "notes.txt"): b"Keep me\n",
        },
        (("home", "."), ("project", ".")),
    )


def test_construction_captures_nested_references_and_original_bytes() -> None:
    sources = _sources()
    expected = build_install_expectations(_case(), sources, _before(), ROOTS)
    reference = next(
        e for e in expected.expectations if e.path.endswith("references/nested/guide.md")
    )
    assert reference == Expectation(
        "file",
        "project",
        "skills/graphify/references/nested/guide.md",
        "install",
        "source:subject:references/nested/guide.md",
        b"Nested reference\n",
    )
    assert (
        next(e for e in expected.expectations if e.path.endswith(".graphify_version")).content
        == b"4.2"
    )
    sources.contents[("subject", "references/nested/guide.md")] = b"Changed externally"
    assert reference.content == b"Nested reference\n"
    assert ("project", "skills/graphify/references/nested/guide.md") in expected.allowed_changes
    assert ("home", "notes.txt") not in expected.allowed_changes


def test_initial_construction_rejects_incomplete_sources() -> None:
    sources = _sources()
    del sources.contents[("subject", "references/nested/guide.md")]
    with pytest.raises(ValueError, match="Retained file unavailable"):
        build_initial_expectations(_case(), sources)


def test_binding_resolves_known_lock_and_round_trips() -> None:
    # The expected digest is independently retained, not computed by the builder.
    unbound = ExpectationSet(
        "install", (), lock_destination=Destination("project", "skills/graphify")
    )
    bound = bind_roots(unbound, ROOTS)
    assert bound.expectations == (
        Expectation(
            "file",
            "home",
            ".cache/graphify/skill-locks/43ef8806efbc5dfa.lock",
            "install",
            "rule:skill_lock",
            b"",
        ),
    )
    assert bound.roots == ROOTS
    assert ExpectationSet.from_data(bound.to_data()) == bound
    with pytest.raises(ValueError, match="different roots"):
        bind_roots(bound, {**ROOTS, "home": "/other/home"})


def test_transport_preserves_semantic_constraints() -> None:
    bundle = ExpectationSet(
        "install",
        (
            Expectation(
                "json-hooks",
                "home",
                "settings.json",
                "install",
                "explicit:test",
                baseline=b"{}",
                hooks=(HOOK,),
            ),
        ),
        roots=ROOTS,
    )
    assert ExpectationSet.from_data(json.loads(json.dumps(bundle.to_data()))) == bundle


def test_reinstall_only_accepts_validated_complete_prior_observation() -> None:
    installed = ExpectationSet("install", (), roots=ROOTS)
    prior = _before()
    for rejected in (
        VerificationResult(complete=False),
        VerificationResult(
            obstacles=[{"root": "home", "path": ".", "reason": "unreadable", "operation": "read"}]
        ),
    ):
        with pytest.raises(ValueError, match="conforming complete"):
            build_reinstall_expectations(installed, prior, rejected)
    result = build_reinstall_expectations(installed, prior, VerificationResult())
    assert result.phase == "reinstall" and result.allowed_changes == ()
    assert next(e for e in result.baseline if e.path == "notes.txt").content == b"Keep me\n"
    prior.contents[("home", "notes.txt")] = b"later change"
    assert next(e for e in result.baseline if e.path == "notes.txt").content == b"Keep me\n"


def _explicit() -> ExpectationSet:
    # Verifier inputs are authored directly; no builder or effects input is involved.
    return ExpectationSet(
        "install",
        (
            Expectation("file", "project", "managed.txt", "install", "explicit:bytes", b"managed"),
            Expectation("absent", "project", "forbidden.bak", "install", "explicit:absence"),
            Expectation(
                "markdown",
                "project",
                "guide.md",
                "install",
                "explicit:markdown",
                b"## managed\nInstructions\n",
                b"# Personal\n",
                "## managed",
            ),
            Expectation(
                "json-hooks",
                "home",
                "settings.json",
                "install",
                "explicit:json",
                baseline=b'{"theme":"dark"}',
                hooks=(HOOK,),
            ),
        ),
        (("project", "managed.txt"), ("project", "guide.md"), ("home", "settings.json")),
        (
            Expectation("directory", "home", ".", "install", "explicit:prior"),
            Expectation("directory", "project", ".", "install", "explicit:prior"),
            Expectation("file", "home", "notes.txt", "install", "explicit:prior", b"Keep me\n"),
        ),
        ROOTS,
    )


def _observation() -> FilesystemSnapshot:
    return _snapshot(
        {
            ("project", "managed.txt"): b"managed",
            ("project", "guide.md"): b"# Personal\n\n## managed\nInstructions\n",
            ("home", "notes.txt"): b"Keep me\n",
            ("home", "settings.json"): b'{"theme":"dark","hooks":{"Before":'
            b'[{"matcher":"Shell","hooks":[{"command":"audit","timeout":10}]}]}}',
        },
        (("home", "."), ("project", ".")),
    )


def test_explicit_verifier_accepts_semantic_markdown_and_json() -> None:
    result = EffectVerifier().verify(_explicit(), _observation())
    assert result.complete and not result.mismatches and not result.obstacles


@pytest.mark.parametrize(
    ("key", "content", "kind"),
    [
        (("project", "managed.txt"), b"wrong", "content_mismatch"),
        (("home", "notes.txt"), b"lost", "unexpected_change"),
        (("project", "guide.md"), b"## managed\nInstructions\n", "user_content_lost"),
        (("project", "guide.md"), b"## managed\nInstructions\n## managed\n", "section_count"),
        (("home", "settings.json"), b'{"theme":"light"}', "user_content_lost"),
        (("home", "settings.json"), b'{"theme":"dark","theme":"dark"}', "invalid_json"),
    ],
)
def test_explicit_verifier_detects_changes(key: tuple[str, str], content: bytes, kind: str) -> None:
    observed = _observation()
    observed.contents[key] = content
    result = EffectVerifier().verify(_explicit(), observed)
    assert kind in {m.type for m in result.mismatches}


def test_explicit_verifier_detects_foreign_effect_and_forbidden_backup() -> None:
    observed = _observation()
    observed.entries.extend(
        [
            {"root": "home", "path": "foreign", "kind": "file"},
            {"root": "project", "path": "forbidden.bak", "kind": "file"},
        ]
    )
    observed.contents.update({("home", "foreign"): b"added", ("project", "forbidden.bak"): b"bad"})
    result = EffectVerifier().verify(_explicit(), observed)
    assert {m.type for m in result.mismatches} >= {"unexpected_change", "unexpected_entry"}


def test_explicit_verifier_reports_impossible_observation() -> None:
    observed = _observation()
    del observed.contents[("project", "managed.txt")]
    result = EffectVerifier().verify(_explicit(), observed)
    assert not result.complete
    assert any(o["path"] == "managed.txt" for o in result.obstacles)


def test_explicit_verifier_never_infers_phase_from_witnesses() -> None:
    bundle = _explicit()
    prior = Expectation("file", "project", "managed.txt", "reinstall", "explicit:prior", b"prior")
    reinstall = replace(bundle.in_phase("reinstall"), allowed_changes=(), baseline=(prior,))
    result = EffectVerifier().verify(reinstall, _observation())
    assert any(m.type == "unexpected_change" and m.path == "managed.txt" for m in result.mismatches)


def test_new_source_reference_extends_constraints_without_effect_change() -> None:
    sources = _sources()
    sources.entries.append({"root": "subject", "path": "references/extra.md", "kind": "file"})
    sources.contents[("subject", "references/extra.md")] = b"Extra source\n"
    expected = build_install_expectations(_case(), sources, _before(), ROOTS)
    assert next(e for e in expected.expectations if e.path.endswith("references/extra.md")) == (
        Expectation(
            "file",
            "project",
            "skills/graphify/references/extra.md",
            "install",
            "source:subject:references/extra.md",
            b"Extra source\n",
        )
    )


def test_duplicate_version_prevents_complete_construction() -> None:
    sources = _sources()
    sources.contents[("subject", "VERSION")] = b"Version: 4.2\nVersion: 5.0\n"
    with pytest.raises(ValueError, match="exactly one"):
        build_initial_expectations(_case(), sources)


@pytest.mark.parametrize("content", [None, b"altered reference"])
def test_explicit_nested_reference_cannot_be_omitted_or_altered(content: bytes | None) -> None:
    expected = ExpectationSet(
        "install",
        (
            Expectation(
                "file",
                "project",
                "references/nested/readme.md",
                "install",
                "explicit:reference",
                b"Original reference",
            ),
        ),
        roots=ROOTS,
    )
    observed = _snapshot(
        {},
        (
            ("home", "."),
            ("project", "."),
            ("project", "references"),
            ("project", "references/nested"),
        ),
    )
    if content is not None:
        observed.entries.append(
            {"root": "project", "path": "references/nested/readme.md", "kind": "file"}
        )
        observed.contents[("project", "references/nested/readme.md")] = content
    result = EffectVerifier().verify(expected, observed)
    assert result.complete and result.mismatches
    assert result.mismatches[0].type == ("missing_file" if content is None else "content_mismatch")


def test_explicit_json_rejects_duplicate_managed_hooks() -> None:
    observed = _observation()
    observed.contents[("home", "settings.json")] = (
        b'{"theme":"dark","hooks":{"Before":[{"matcher":"Shell","hooks":'
        b'[{"command":"audit","timeout":10},{"command":"audit","timeout":10}]}]}}'
    )
    result = EffectVerifier().verify(_explicit(), observed)
    assert any(m.type == "hook_count" and m.observed == "2" for m in result.mismatches)


def test_explicit_backup_bytes_must_be_preserved() -> None:
    expected = ExpectationSet(
        "reinstall",
        (
            Expectation(
                "file",
                "home",
                "settings.json.graphify-bak",
                "reinstall",
                "explicit:backup",
                b"Original backup",
            ),
        ),
        roots=ROOTS,
    )
    observed = _snapshot(
        {("home", "settings.json.graphify-bak"): b"Replaced backup"},
        (("home", "."), ("project", ".")),
    )
    result = EffectVerifier().verify(expected, observed)
    assert [m.type for m in result.mismatches] == ["content_mismatch"]


def test_incomplete_first_observation_cannot_supply_reinstall_preservation() -> None:
    installed = ExpectationSet("install", (), roots=ROOTS)
    observed = _before()
    observed.entries[0]["listing_complete"] = False
    with pytest.raises(ValueError, match="Incomplete retained inventory"):
        build_reinstall_expectations(installed, observed, VerificationResult())
