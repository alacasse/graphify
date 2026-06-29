from __future__ import annotations

from pathlib import Path

from tools.install_sandbox import install_surface_core
from tools.install_sandbox.reference_resolution import PackagedReferenceResolution
from tools.install_sandbox.surfaces import install_surface_models
from tools.install_sandbox.surfaces import install_surface_state
from tools.install_sandbox.surfaces.install_surface_models import ExpectedPath, InstallSurface
from tools.install_sandbox.targets import install_target_models


def resolution(status: str, names: tuple[str, ...] = (), detail: str = "test detail") -> PackagedReferenceResolution:
    return PackagedReferenceResolution(status, expected_names=names, detail=detail)


def expected_skill(root: str, relative: str) -> InstallSurface:
    return InstallSurface(root, relative, skill_sidecar_expectation=install_surface_models.SkillSidecarExpectation())


def section(root: str, relative: str, marker: str = install_target_models.GRAPHIFY_MARKER, *, preserve_user_content: bool = False) -> InstallSurface:
    return InstallSurface(
        root,
        relative,
        marker=marker,
        text_expectation=install_surface_models.TextExpectation(
            preserve_user_content=preserve_user_content,
            repair_stale_graphify_section=True,
            require_user_content_on_uninstall=preserve_user_content,
        ),
    )


def test_install_surface_state_derives_ordered_idempotency_state_plan() -> None:
    notes = section("project", "notes.md", preserve_user_content=True)
    skill = expected_skill("home", ".codex/skills/graphify/SKILL.md")

    plan = install_surface_state.planned_state_entries(
        (notes, skill),
        resolution("available", ("query.md",)),
        installed_skill_reference_relatives={
            ("home", ".codex/skills/graphify/SKILL.md"): {
                Path(".codex/skills/graphify/references/local.md"),
            },
        },
    )

    assert [entry.key for entry in plan] == [
        "project/notes.md",
        "home/.codex/skills/graphify/SKILL.md",
        "home/.codex/skills/graphify/.graphify_version",
        "home/.codex/skills/graphify/references",
        "home/.codex/skills/graphify/references.tmp",
        "home/.codex/skills/graphify/references/local.md",
        "home/.codex/skills/graphify/references/query.md",
    ]
    assert plan[0].root_name == "project"
    assert plan[0].relative == Path("notes.md")
    assert plan[0].marker == install_target_models.GRAPHIFY_MARKER
    assert plan[0].text_expectation is not None
    assert plan[0].text_expectation.preserve_user_content is True
    assert plan[1].root_name == "home"
    assert plan[1].relative == Path(".codex/skills/graphify/SKILL.md")
    assert plan[2].marker is None
    assert plan[2].text_expectation is None


def test_install_surface_state_derives_ordered_idempotency_state_changes() -> None:
    before = {
        "project/changed.md": {"exists": True, "sha256": "before"},
        "project/removed.md": {"exists": True, "sha256": "removed"},
        "project/stable.md": {"exists": True, "sha256": "same"},
    }
    after = {
        "project/added.md": {"exists": True, "sha256": "added"},
        "project/changed.md": {"exists": True, "sha256": "after"},
        "project/stable.md": {"exists": True, "sha256": "same"},
    }

    changes = install_surface_state.idempotency_state_changes(before, after)

    assert changes == (
        install_surface_state.IdempotencyStateChange("project/added.md", stable=False),
        install_surface_state.IdempotencyStateChange("project/changed.md", stable=False),
        install_surface_state.IdempotencyStateChange("project/removed.md", stable=False),
        install_surface_state.IdempotencyStateChange("project/stable.md", stable=True),
    )


def test_install_surface_state_derives_user_content_seed_plans() -> None:
    stale_section = section("project", "stale-notes.md", preserve_user_content=True)
    legacy_text_policy = ExpectedPath(
        "home",
        "legacy-notes.txt",
        text_expectation=install_surface_models.TextExpectation(preserve_user_content=True),
    )
    no_preserve_text_section = section("project", "no-preserve.md")
    plain_surface = ExpectedPath("project", "plain.txt")
    json_surface = ExpectedPath("project", "settings.json", content_kind="json", marker="graphify")

    plans = install_surface_state.user_content_seed_plans(
        (
            stale_section,
            legacy_text_policy,
            no_preserve_text_section,
            plain_surface,
            json_surface,
        )
    )

    assert plans == (
        install_surface_state.UserContentSeedPlan(
            root_name="project",
            relative=Path("stale-notes.md"),
            text=(
                f"# User Notes\n\n{install_surface_state.USER_SENTINEL}\n\n"
                f"{install_target_models.GRAPHIFY_MARKER}\n{install_surface_state.STALE_GRAPHIFY_SENTINEL}\n\n"
                "## User Section\nThis section should survive Graphify install and uninstall.\n"
            ),
        ),
        install_surface_state.UserContentSeedPlan(
            root_name="home",
            relative=Path("legacy-notes.txt"),
            text=f"# User Notes\n\n{install_surface_state.USER_SENTINEL}\n",
        ),
    )


def test_install_surface_state_derives_stale_sidecar_seed_plans() -> None:
    skill = expected_skill("home", ".codex/skills/graphify/SKILL.md")
    plain_surface = ExpectedPath("project", "AGENTS.md")

    plans = install_surface_state.stale_sidecar_seed_plans(
        (plain_surface, skill),
        resolution("available", ("query.md",)),
    )

    assert plans == (
        install_surface_state.StaleSidecarSeedPlan(
            root_name="home",
            relative=Path(".codex/skills/graphify/references/stale-sandbox-fragment.md"),
            text="stale sandbox reference fragment\n",
            kind="stale_reference_fragment",
        ),
        install_surface_state.StaleSidecarSeedPlan(
            root_name="home",
            relative=Path(".codex/skills/graphify/references.tmp/partial.md"),
            text="partial staged reference fragment\n",
            kind="staged_reference_fragment",
        ),
    )
    assert install_surface_state.stale_sidecar_seed_plans((skill,), resolution("empty")) == plans
    assert install_surface_state.stale_sidecar_seed_plans((skill,), resolution("missing")) == plans
    assert install_surface_state.stale_sidecar_seed_plans((skill,), resolution("not_directory")) == plans
    assert install_surface_state.stale_sidecar_seed_plans((skill,), resolution("intentionally_absent")) == ()
    assert install_surface_state.stale_sidecar_seed_plans((skill,), resolution("no_eligible_bundle")) == ()
    assert install_surface_state.stale_sidecar_seed_plans((plain_surface,), resolution("available", ("query.md",))) == ()


def test_expected_generated_keys_reuse_generated_state_plan() -> None:
    notes = section("project", "notes.md", preserve_user_content=True)
    skill = expected_skill("home", ".codex/skills/graphify/SKILL.md")

    plan = install_surface_state.planned_state_entries(
        (notes, skill),
        resolution("available", ("query.md",)),
    )

    assert install_surface_state.expected_generated_relative_keys((notes, skill), resolution("available", ("query.md",))) == {
        (entry.root_name, entry.relative.as_posix()) for entry in plan
    }


def test_install_surface_state_derives_expected_manifest_relatives_for_root() -> None:
    project_notes = InstallSurface("project", "AGENTS.md")
    project_skill = expected_skill("project", ".claude/skills/graphify/SKILL.md")
    home_skill = expected_skill("home", ".codex/skills/graphify/SKILL.md")

    assert install_surface_state.expected_manifest_relatives(
        (project_notes, project_skill, home_skill),
        resolution("available", ("query.md", "update.md")),
        "project",
    ) == {
        Path("AGENTS.md"),
        Path(".claude/skills/graphify/SKILL.md"),
        Path(".claude/skills/graphify/.graphify_version"),
        Path(".claude/skills/graphify/references.tmp"),
        Path(".claude/skills/graphify/references"),
        Path(".claude/skills/graphify/references/query.md"),
        Path(".claude/skills/graphify/references/update.md"),
    }
    assert install_surface_state.expected_manifest_relatives(
        (project_notes, project_skill, home_skill),
        resolution("intentionally_absent"),
        "home",
    ) == {
        Path(".codex/skills/graphify/SKILL.md"),
        Path(".codex/skills/graphify/.graphify_version"),
        Path(".codex/skills/graphify/references.tmp"),
    }


def test_temporary_install_surface_core_facade_reexports_state_planning_names() -> None:
    assert install_surface_core.planned_state_entries is install_surface_state.planned_state_entries
    assert install_surface_core.IdempotencyStateChange is install_surface_state.IdempotencyStateChange
    assert install_surface_core.user_content_seed_plans is install_surface_state.user_content_seed_plans
    assert install_surface_core.stale_sidecar_seed_plans is install_surface_state.stale_sidecar_seed_plans
    assert install_surface_core.expected_manifest_relatives is install_surface_state.expected_manifest_relatives
