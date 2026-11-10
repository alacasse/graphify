"""Exercise the catalog guard through Git's real commit/index boundary."""

import shlex
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_install_sandbox_catalog.py"
SPECS = "tools/install_sandbox/specs"


def install_module(platforms=("alpha",), commands=("alpha", "install", "uninstall")):
    return (
        f"_CLI_INSTALL_COMMANDS = frozenset({commands!r})\n"
        "def _canonical_platform(name):\n"
        "    return {'shortcut': 'alpha'}.get(name, name)\n"
        "def _print_install_usage():\n"
        f"    print('Platforms: {', '.join(platforms)}')\n"
    )


@pytest.fixture
def catalog_repo(tmp_path):
    def git(*args, check=True):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, text=True, capture_output=True, check=check
        )

    def write(path, content):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    git("init", "-q")
    git("config", "core.hooksPath", str(tmp_path / ".git/hooks"))
    git("config", "user.name", "Catalog Test")
    git("config", "user.email", "catalog@example.invalid")
    git("config", "commit.gpgsign", "false")
    write("graphify/__init__.py", "")
    write("graphify/install.py", install_module())
    write(f"{SPECS}/alpha.yaml", "scopes: {}\n")
    git("add", ".")
    git("commit", "-qm", "baseline")
    baseline = git("rev-parse", "HEAD").stdout.strip()
    guard = tmp_path / "guard.py"
    guard.write_text(
        "import runpy\n"
        f"namespace = runpy.run_path({str(SCRIPT)!r})\n"
        f"raise SystemExit(namespace['main']({baseline!r}))\n"
    )
    hook = tmp_path / ".git/hooks/pre-commit"
    hook.write_text(
        "#!/bin/sh\nexec " + shlex.quote(sys.executable) + " " + shlex.quote(str(guard)) + "\n"
    )
    hook.chmod(0o755)
    return tmp_path, git, write


def commit(git):
    return git("commit", "-qm", "candidate", check=False)


def assert_rejected(result, diagnostic):
    assert result.returncode != 0
    assert diagnostic in result.stderr, result.stderr


def test_existing_spec_contents_may_change(catalog_repo):
    _, git, write = catalog_repo
    write(f"{SPECS}/alpha.yaml", "scopes: {user: {}}\n")
    git("add", SPECS)
    result = commit(git)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("path", [f"{SPECS}/nested/alpha.yaml", f"{SPECS}/scenario.YML"])
def test_added_yaml_is_rejected_by_real_commit(catalog_repo, path):
    _, git, write = catalog_repo
    write(path, "scopes: {}\n")
    git("add", path)
    assert_rejected(commit(git), f"Added spec outside the frozen catalog: {path}")


def test_equal_count_spec_swap_is_rejected(catalog_repo):
    root, git, write = catalog_repo
    (root / SPECS / "alpha.yaml").unlink()
    write(f"{SPECS}/replacement.yaml", "scopes: {}\n")
    git("add", SPECS)
    result = commit(git)
    assert_rejected(result, f"Missing frozen spec: {SPECS}/alpha.yaml")
    assert f"Added spec outside the frozen catalog: {SPECS}/replacement.yaml" in result.stderr


@pytest.mark.parametrize("surface", ["platform", "command"])
def test_new_public_tool_without_spec_is_rejected(catalog_repo, surface):
    _, git, write = catalog_repo
    write(
        "graphify/install.py",
        install_module(platforms=("alpha", "beta"))
        if surface == "platform"
        else install_module(commands=("alpha", "beta", "install", "uninstall")),
    )
    git("add", "graphify/install.py")
    assert_rejected(commit(git), f"Missing spec for a supported tool: {SPECS}/beta.yaml")


def test_alias_uses_canonical_spec(catalog_repo):
    _, git, write = catalog_repo
    write(
        "graphify/install.py",
        install_module(
            platforms=("alpha", "shortcut"), commands=("alpha", "shortcut", "install", "uninstall")
        ),
    )
    git("add", "graphify/install.py")
    result = commit(git)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("staged_is_valid", [True, False])
def test_index_controls_verdict_when_worktree_diverges(catalog_repo, staged_is_valid):
    _, git, write = catalog_repo
    valid = install_module(commands=("alpha", "shortcut", "install", "uninstall"))
    invalid = install_module(platforms=("alpha", "beta"))
    write("graphify/install.py", valid if staged_is_valid else invalid)
    git("add", "graphify/install.py")
    write("graphify/install.py", invalid if staged_is_valid else valid)
    result = commit(git)
    if staged_is_valid:
        assert result.returncode == 0, result.stderr
    else:
        assert_rejected(result, f"Missing spec for a supported tool: {SPECS}/beta.yaml")


def test_full_index_is_checked_beyond_current_diff(catalog_repo):
    _, git, write = catalog_repo
    write(f"{SPECS}/extra.yaml", "scopes: {}\n")
    git("add", SPECS)
    # Simulate history created before this hook was installed.
    git("-c", "core.hooksPath=/dev/null", "commit", "-qm", "earlier addition")
    write("README.md", "An unrelated change.\n")
    git("add", "README.md")
    assert_rejected(commit(git), f"Added spec outside the frozen catalog: {SPECS}/extra.yaml")


def test_spec_replaced_by_symlink_is_rejected(catalog_repo):
    root, git, write = catalog_repo
    write("elsewhere.yaml", "scopes: {}\n")
    spec = root / SPECS / "alpha.yaml"
    spec.unlink()
    spec.symlink_to(root / "elsewhere.yaml")
    git("add", SPECS)
    assert_rejected(commit(git), f"Expected a regular spec file: {SPECS}/alpha.yaml")


def test_removed_tool_leaves_an_orphaned_spec(catalog_repo):
    _, git, write = catalog_repo
    write("graphify/install.py", install_module(platforms=(), commands=("install", "uninstall")))
    git("add", "graphify/install.py")
    assert_rejected(commit(git), f"Spec without a matching canonical tool: {SPECS}/alpha.yaml")


def test_intent_to_add_is_outside_candidate(catalog_repo):
    _, git, write = catalog_repo
    write(f"{SPECS}/draft.yaml", "draft\n")
    git("add", "-N", f"{SPECS}/draft.yaml")
    write("README.md", "Commit only this file.\n")
    git("add", "README.md")
    result = commit(git)
    assert result.returncode == 0, result.stderr
    assert "draft.yaml" not in git("ls-tree", "-r", "--name-only", "HEAD").stdout


def test_sparse_checkout_reads_staged_product(catalog_repo):
    root, git, write = catalog_repo
    git("sparse-checkout", "set", "--cone", "tools")
    assert not (root / "graphify/install.py").exists()
    write(f"{SPECS}/alpha.yaml", "scopes: {project: {}}\n")
    git("add", SPECS)
    result = commit(git)
    assert result.returncode == 0, result.stderr
