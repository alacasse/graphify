"""Exercise source selection through the real filesystem copy boundary."""

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from tools.install_sandbox.preparer import prepare_context


def _write(root: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_archive_without_ignore_file_preserves_current_content_and_metadata(tmp_path: Path) -> None:
    subject = tmp_path / "subject"
    _write(subject, {"local.py": "old content", "new.txt": "new", ".settings": "hidden file"})
    current = subject / "local.py"
    current.write_text("edited content", encoding="utf-8")
    current.chmod(0o755)
    os.utime(current, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))

    copied = prepare_context(subject, tmp_path) / "subject"

    assert (copied / "local.py").read_text() == "edited content"
    assert (copied / "local.py").stat().st_mode == current.stat().st_mode
    assert (copied / "local.py").stat().st_mtime_ns == current.stat().st_mtime_ns
    assert (copied / "new.txt").read_text() == "new"
    assert (copied / ".settings").read_text() == "hidden file"


@pytest.mark.parametrize("with_ignore", [False, True])
def test_generated_and_hidden_directories_are_always_excluded(
    tmp_path: Path, with_ignore: bool
) -> None:
    subject = tmp_path / "subject"
    excluded = [".github", ".opencode", ".venv", "__pycache__", "graphify-out"]
    if not with_ignore:
        excluded.append(".gitignore")
    for base in ("", "nested/"):
        _write(subject, {f"{base}{name}/data": "excluded" for name in excluded})
    _write(subject, {"nested/keep": "keep"})
    # Invalid contents must never be read inside an excluded directory.
    (subject / ".opencode/.gitignore").write_bytes(b"\xff")
    if with_ignore:
        _write(subject, {".gitignore": "!**/\n!**/*\n"})

    copied = prepare_context(subject, tmp_path) / "subject"

    assert (copied / "nested/keep").read_text() == "keep"
    assert all(not (copied / base / name).exists() for base in ("", "nested") for name in excluded)


@pytest.mark.parametrize(
    "rules,excluded",
    [
        ("*.log\n!keep.log\n", {"drop.log", "nested/drop.log"}),
        ("/root.txt\n", {"root.txt"}),
        ("cache/\n", {"cache/item", "nested/cache/item"}),
        ("nested/**/secret.txt\n", {"nested/secret.txt", "nested/deep/secret.txt"}),
        ("# comment\n\\#literal\n\\!literal\n", {"#literal", "!literal"}),
        ("space\\ \n", {"space "}),
        ("*.log\n!keep.log\nkeep.log\n", {"drop.log", "nested/drop.log", "keep.log"}),
    ],
)
def test_gitignore_patterns_select_the_copied_files(
    tmp_path: Path, rules: str, excluded: set[str]
) -> None:
    subject = tmp_path / "subject"
    names = {
        "drop.log",
        "keep.log",
        "nested/drop.log",
        "root.txt",
        "nested/root.txt",
        "cache/item",
        "nested/cache/item",
        "nested/secret.txt",
        "nested/deep/secret.txt",
        "secret.txt",
        "#literal",
        "!literal",
        "space ",
        "keep.txt",
    }
    _write(subject, {name: name for name in names})
    _write(subject, {".gitignore": rules})

    copied = prepare_context(subject, tmp_path) / "subject"

    assert {p.relative_to(copied).as_posix() for p in copied.rglob("*") if p.is_file()} == (
        names - excluded
    ) | {".gitignore"}


def test_nested_rules_override_parents_only_within_their_directory(tmp_path: Path) -> None:
    subject = tmp_path / "subject"
    _write(
        subject,
        {
            ".gitignore": (
                "*.log\nblocked/\n!blocked/keep.txt\n"
                "skills/\n!graphify/skills/\n!graphify/skills/**\n"
            ),
            "nested/.gitignore": "!keep.log\n/local.txt\n",
            "nested/keep.log": "included by child",
            "nested/drop.log": "excluded by parent",
            "sibling/keep.log": "excluded by parent",
            "nested/local.txt": "excluded by child",
            "nested/deep/local.txt": "outside anchored rule",
            "blocked/.gitignore": "!keep.txt\n",
            "blocked/keep.txt": "excluded parent directory",
            "graphify/skills/claude/references/guide.md": "packaged reference",
            "skills/local.md": "local installation",
        },
    )

    copied = prepare_context(subject, tmp_path) / "subject"

    assert (copied / "nested/keep.log").read_text() == "included by child"
    assert (copied / "nested/deep/local.txt").is_file()
    assert (copied / "graphify/skills/claude/references/guide.md").is_file()
    for name in ("nested/drop.log", "sibling/keep.log", "nested/local.txt", "blocked", "skills"):
        assert not (copied / name).exists()


def test_only_subject_gitignore_files_supply_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject = tmp_path / "subject"
    _write(tmp_path, {".gitignore": "*", "global-ignore": "*"})
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.excludesFile")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(tmp_path / "global-ignore"))
    monkeypatch.setenv("PATH", "")
    _write(subject, {".git/info/exclude": "*", ".git/index": "not a Git index", "keep": "current"})

    copied = prepare_context(subject, tmp_path) / "subject"

    assert (copied / "keep").read_text() == "current"
    assert not (copied / ".git").exists()


def test_links_are_copied_without_traversing_their_targets(tmp_path: Path) -> None:
    subject = tmp_path / "subject"
    _write(subject, {"file": "content", ".gitignore": "directory-link/\nignored-link\n"})
    _write(tmp_path, {"outside/secret": "outside", "external-ignore": "*"})
    links = {"file-link": "file", "directory-link": "../outside", "broken-link": "absent"}
    for name, target in links.items():
        (subject / name).symlink_to(target)
    (subject / "ignored-link").symlink_to("file")
    (subject / "nested").mkdir()
    (subject / "nested/.gitignore").symlink_to(tmp_path / "external-ignore")
    (subject / "nested/keep").write_text("kept", encoding="utf-8")

    copied = prepare_context(subject, tmp_path) / "subject"

    for name, target in links.items():
        assert (copied / name).is_symlink()
        assert os.readlink(copied / name) == target
    assert not (copied / "ignored-link").is_symlink()
    assert (copied / "nested/.gitignore").is_symlink()
    assert (copied / "nested/keep").read_text() == "kept"


def test_unreadable_ignore_file_is_a_copy_error(tmp_path: Path) -> None:
    subject = tmp_path / "subject"
    _write(subject, {"keep": "content"})
    (subject / ".gitignore").write_bytes(b"\xff")

    with pytest.raises(UnicodeDecodeError):
        prepare_context(subject, tmp_path)


@pytest.mark.parametrize("lock", [False, True])
def test_metadata_comes_from_same_filtered_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lock: bool
) -> None:
    import shutil

    subject = tmp_path / "subject"
    files = {"pyproject.toml": '[project]\ndependencies=["original"]', "code.py": "original"}
    if lock:
        files["uv.lock"] = "original lock"
    _write(subject, files)
    copytree = shutil.copytree

    def capture(
        src: Path, dst: Path, *, symlinks: bool, ignore: Callable[[str, list[str]], set[str]]
    ) -> Path:
        result = copytree(src, dst, symlinks=symlinks, ignore=ignore)
        _write(subject, {name: "checkout changed after capture" for name in files})
        return result

    monkeypatch.setattr(shutil, "copytree", capture)
    context = prepare_context(subject, tmp_path)
    for name in ("pyproject.toml", "uv.lock"):
        if name in files:
            assert (context / "metadata" / name).read_text() == files[name]
            assert (context / "subject" / name).read_text() == files[name]
        else:
            assert not (context / "metadata" / name).exists()
    assert (context / "subject/code.py").read_text() == "original"
