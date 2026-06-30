from __future__ import annotations

import ast
from pathlib import Path

from tools.install_sandbox.reference_resolution import (
    PackagedReferenceResolution,
    resolve_target_packaged_references,
)
from tools.install_sandbox.targets.install_target_models import InstallTargetSpec, ReferenceBundle


REPO_ROOT = Path(__file__).resolve().parents[2]


class GraphifyMain:
    def __init__(self, package_dir: Path, refs_dir: Path | None = None) -> None:
        self.__file__ = str(package_dir / "__main__.py")
        self._refs_dir = refs_dir

    def _packaged_skill_refs_dir(self, platform_name: str):
        assert platform_name == "unit"
        return self._refs_dir


def bundled_spec(*bundles: ReferenceBundle) -> InstallTargetSpec:
    return InstallTargetSpec(
        name="unit",
        uses_packaged_references=False,
        reference_bundles=bundles,
    )


def _call_sites(root: Path, function_name: str) -> set[str]:
    call_sites: set[str] = set()
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _CallSiteVisitor(path.relative_to(REPO_ROOT), function_name)
        visitor.visit(tree)
        call_sites.update(visitor.call_sites)
    return call_sites


class _CallSiteVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: Path, function_name: str) -> None:
        self.relative_path = relative_path
        self.function_name = function_name
        self.call_sites: set[str] = set()
        self._function_stack: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function_stack.append(node.name)
        self.generic_visit(node)
        self._function_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if _call_name(node.func) == self.function_name:
            scope = self._function_stack[-1] if self._function_stack else "<module>"
            self.call_sites.add(f"{self.relative_path}::{scope}")
        self.generic_visit(node)


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def test_runtime_uses_target_named_reference_resolver() -> None:
    runtime_call_sites = _call_sites(
        REPO_ROOT / "tools" / "install_sandbox" / "runtime",
        "resolve_target_packaged_references",
    )

    assert runtime_call_sites == {
        "tools/install_sandbox/runtime/sandbox_run_environment.py::packaged_reference_resolution",
    }


def test_reference_bundle_eligibility_comes_from_target_reference_facts(tmp_path: Path) -> None:
    package_dir = tmp_path / "graphify"
    guarded_refs = package_dir / "skills" / "guarded" / "references"
    fallback_refs = package_dir / "skills" / "fallback" / "references"
    guarded_refs.mkdir(parents=True)
    fallback_refs.mkdir(parents=True)
    (guarded_refs / "guarded.md").write_text("guarded\n", encoding="utf-8")
    (fallback_refs / "fallback.md").write_text("fallback\n", encoding="utf-8")

    resolution = resolve_target_packaged_references(
        "unit",
        graphify_main=GraphifyMain(package_dir),
        target_reference_facts=bundled_spec(
            ReferenceBundle("guarded", required_package_relative="skill-guarded.md"),
            ReferenceBundle("fallback"),
        ),
    )

    assert resolution.status == "available"
    assert isinstance(resolution, PackagedReferenceResolution)
    assert resolution.refs_dir == fallback_refs
    assert resolution.expected_names == ("fallback.md",)


def test_non_vscode_guarded_wins_when_guard_present(tmp_path: Path) -> None:
    package_dir = tmp_path / "graphify"
    guarded_refs = package_dir / "skills" / "guarded" / "references"
    fallback_refs = package_dir / "skills" / "fallback" / "references"
    guarded_refs.mkdir(parents=True)
    fallback_refs.mkdir(parents=True)
    (package_dir / "skill-guarded.md").write_text("guard exists\n", encoding="utf-8")
    (guarded_refs / "guarded.md").write_text("guarded\n", encoding="utf-8")
    (fallback_refs / "fallback.md").write_text("fallback\n", encoding="utf-8")

    resolution = resolve_target_packaged_references(
        "unit",
        graphify_main=GraphifyMain(package_dir),
        target_reference_facts=bundled_spec(
            ReferenceBundle("guarded", required_package_relative="skill-guarded.md"),
            ReferenceBundle("fallback"),
        ),
    )

    assert resolution.status == "available"
    assert resolution.refs_dir == guarded_refs
    assert resolution.expected_names == ("guarded.md",)


def test_reference_bundles_take_precedence_over_uses_packaged_references(tmp_path: Path) -> None:
    package_dir = tmp_path / "graphify"
    bundle_refs = package_dir / "skills" / "bundle" / "references"
    legacy_refs = tmp_path / "legacy-refs"
    bundle_refs.mkdir(parents=True)
    legacy_refs.mkdir()
    (bundle_refs / "bundle.md").write_text("bundle\n", encoding="utf-8")
    (legacy_refs / "legacy.md").write_text("legacy\n", encoding="utf-8")

    resolution = resolve_target_packaged_references(
        "unit",
        graphify_main=GraphifyMain(package_dir, legacy_refs),
        target_reference_facts=InstallTargetSpec(
            name="unit",
            uses_packaged_references=True,
            reference_bundles=(ReferenceBundle("bundle"),),
        ),
    )

    assert resolution.status == "available"
    assert resolution.refs_dir == bundle_refs
    assert resolution.expected_names == ("bundle.md",)


def test_selected_bundle_with_no_markdown_refs_returns_empty(tmp_path: Path) -> None:
    package_dir = tmp_path / "graphify"
    refs_dir = package_dir / "skills" / "guarded" / "references"
    refs_dir.mkdir(parents=True)
    (refs_dir / "notes.txt").write_text("ignored\n", encoding="utf-8")

    resolution = resolve_target_packaged_references(
        "unit",
        graphify_main=GraphifyMain(package_dir),
        target_reference_facts=bundled_spec(ReferenceBundle("guarded")),
    )

    assert resolution.status == "empty"
    assert resolution.refs_dir == refs_dir
    assert resolution.expected_names == ()
    assert resolution.expects_references is True


def test_no_eligible_guarded_bundle_returns_no_eligible_bundle(tmp_path: Path) -> None:
    package_dir = tmp_path / "graphify"
    package_dir.mkdir()

    resolution = resolve_target_packaged_references(
        "unit",
        graphify_main=GraphifyMain(package_dir),
        target_reference_facts=bundled_spec(ReferenceBundle("guarded", required_package_relative="skill-guarded.md")),
    )

    assert resolution.status == "no_eligible_bundle"
    assert resolution.refs_dir is None
    assert resolution.expected_names == ()
    assert resolution.expects_references is False


def test_legacy_packaged_skill_refs_dir_path_returns_available_names(tmp_path: Path) -> None:
    package_dir = tmp_path / "graphify"
    refs_dir = tmp_path / "refs"
    refs_dir.mkdir()
    (refs_dir / "b.md").write_text("b\n", encoding="utf-8")
    (refs_dir / "a.md").write_text("a\n", encoding="utf-8")

    resolution = resolve_target_packaged_references(
        "unit",
        graphify_main=GraphifyMain(package_dir, refs_dir),
        target_reference_facts=InstallTargetSpec(name="unit", uses_packaged_references=True),
    )

    assert resolution.status == "available"
    assert resolution.refs_dir == refs_dir
    assert resolution.expected_names == ("a.md", "b.md")


def test_legacy_packaged_skill_refs_dir_none_returns_intentionally_absent(tmp_path: Path) -> None:
    package_dir = tmp_path / "graphify"

    resolution = resolve_target_packaged_references(
        "unit",
        graphify_main=GraphifyMain(package_dir, None),
        target_reference_facts=InstallTargetSpec(name="unit", uses_packaged_references=True),
    )

    assert resolution.status == "intentionally_absent"
    assert resolution.refs_dir is None
    assert resolution.expected_names == ()
    assert resolution.expects_references is False


def test_refs_path_as_file_returns_not_directory(tmp_path: Path) -> None:
    package_dir = tmp_path / "graphify"
    refs_path = package_dir / "skills" / "guarded" / "references"
    refs_path.parent.mkdir(parents=True)
    refs_path.write_text("not a dir\n", encoding="utf-8")

    resolution = resolve_target_packaged_references(
        "unit",
        graphify_main=GraphifyMain(package_dir),
        target_reference_facts=bundled_spec(ReferenceBundle("guarded")),
    )

    assert resolution.status == "not_directory"
    assert resolution.refs_dir == refs_path
    assert resolution.expected_names == ()
    assert resolution.expects_references is True


def test_eligible_bundle_dir_with_missing_references_child_returns_missing(tmp_path: Path) -> None:
    package_dir = tmp_path / "graphify"
    bundle_dir = package_dir / "skills" / "guarded"
    bundle_dir.mkdir(parents=True)

    resolution = resolve_target_packaged_references(
        "unit",
        graphify_main=GraphifyMain(package_dir),
        target_reference_facts=bundled_spec(ReferenceBundle("guarded")),
    )

    assert resolution.status == "missing"
    assert resolution.refs_dir == bundle_dir / "references"
    assert resolution.expected_names == ()
    assert resolution.expects_references is True
