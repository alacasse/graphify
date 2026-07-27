"""Antigravity install lays down its full always-on layer, not just the skill.

Regression: project-scoped `install --project --platform antigravity` previously
went through the skill-only branch (grouped with copilot/pi/kimi), so it copied
the SKILL.md but never wrote `.agents/rules/graphify.md` or
`.agents/workflows/graphify.md` - even though the uninstall path removes them.
"""
import graphify.__main__ as m


def test_antigravity_project_install_writes_rules_and_workflows(tmp_path):
    m._project_install("antigravity", tmp_path)
    skill = tmp_path / ".agents" / "skills" / "graphify" / "SKILL.md"
    rules = tmp_path / ".agents" / "rules" / "graphify.md"
    workflow = tmp_path / ".agents" / "workflows" / "graphify.md"
    assert skill.exists(), "skill should be installed under .agents/skills/"
    assert rules.exists(), "antigravity rules (always-on) must be written"
    assert workflow.exists(), "antigravity workflow must be written"
    # native tool-discovery frontmatter is injected into the skill
    skill_text = skill.read_text(encoding="utf-8")
    assert skill_text.startswith("---\nname: graphify-manager\n")
    assert (
        "description: Rebuild the code graph or perform manual CLI queries "
        "when MCP server is offline."
    ) in skill_text.split("---", 2)[1]
    assert "\nname: graphify\n" not in skill_text.split("---", 2)[1]


def test_antigravity_metadata_replacement_preserves_extra_metadata_body_and_refs(
    tmp_path,
):
    skill_dir = tmp_path / ".agents" / "skills" / "graphify"
    refs = skill_dir / "references"
    refs.mkdir(parents=True)
    reference = refs / "query.md"
    reference.write_text("reference payload\n", encoding="utf-8")
    skill = skill_dir / "SKILL.md"
    body = "# Graphify body\n\n[Query](references/query.md)\n"
    skill.write_text(
        "---\n"
        "name: graphify\n"
        "description: generic description\n"
        "license: Apache-2.0\n"
        "allowed-tools: Bash\n"
        "---\n\n"
        + body,
        encoding="utf-8",
    )

    m._antigravity_finalize(skill, tmp_path)
    first = skill.read_text(encoding="utf-8")
    m._antigravity_finalize(skill, tmp_path)

    assert skill.read_text(encoding="utf-8") == first
    assert first.count("name: graphify-manager") == 1
    assert first.count("description: Rebuild the code graph") == 1
    assert "license: Apache-2.0" in first
    assert "allowed-tools: Bash" in first
    assert first.endswith(body)
    assert reference.read_text(encoding="utf-8") == "reference payload\n"


def test_antigravity_project_uninstall_clears_rules_and_workflows(tmp_path):
    m._project_install("antigravity", tmp_path)
    m._project_uninstall("antigravity", tmp_path)
    assert not (tmp_path / ".agents" / "rules" / "graphify.md").exists()
    assert not (tmp_path / ".agents" / "workflows" / "graphify.md").exists()
    assert not (tmp_path / ".agents" / "skills" / "graphify" / "SKILL.md").exists()
