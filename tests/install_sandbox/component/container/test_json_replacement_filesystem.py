"""Real-filesystem isolation of settings replacement."""

# pyright: reportPrivateUsage=false

import hashlib
import os
from pathlib import Path

import pytest

from tools.install_sandbox.container import file_mutation
from tools.install_sandbox.contracts.bound_mutation import BoundFileReplacement
from tools.install_sandbox.contracts.effects import Destination


def operation() -> BoundFileReplacement:
    return BoundFileReplacement(
        "0" * 64,
        "steps/0/after.json",
        Destination("project", "nested/settings.json"),
        hashlib.sha256(b"old").hexdigest(),
        b"new",
    )


def test_replacement_leaves_external_hardlink_untouched(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"old")
    external = tmp_path / "external.json"
    os.link(path, external)
    file_mutation._replace_file(path, operation(), b"old")
    assert path.read_bytes() == b"new"
    assert external.read_bytes() == b"old"


def test_parent_swap_cannot_redirect_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    path = nested / "settings.json"
    path.write_bytes(b"old")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "settings.json").write_bytes(b"old")
    original_open = os.open
    swapped = False

    def swap(
        target: str | os.PathLike[str], flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        nonlocal swapped
        if not swapped:
            swapped = True
            nested.rename(tmp_path / "detached")
            nested.symlink_to(outside, target_is_directory=True)
        return original_open(target, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swap)
    with pytest.raises(OSError):
        file_mutation._replace_file(path, operation(), b"old")
    assert (outside / "settings.json").read_bytes() == b"old"


def test_normal_replacement_preserves_mode(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"old")
    path.chmod(0o640)
    file_mutation._replace_file(path, operation(), b"old")
    assert path.read_bytes() == b"new"
    assert path.stat().st_mode & 0o777 == 0o640


def test_hardlink_added_after_validation_is_not_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"old")
    external = tmp_path / "external.json"
    read = file_mutation._regular_bytes

    def add_link(parent: int, name: str, *, writable: bool = False) -> tuple[os.stat_result, bytes]:
        result = read(parent, name, writable=writable)
        if not external.exists():
            os.link(path, external)
        return result

    monkeypatch.setattr(file_mutation, "_regular_bytes", add_link)
    file_mutation._replace_file(path, operation(), b"old")
    assert path.read_bytes() == b"new"
    assert external.read_bytes() == b"old"


def test_stale_original_aborts_and_cleans_private_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"old")
    read = file_mutation._regular_bytes
    calls = 0

    def change(parent: int, name: str, *, writable: bool = False) -> tuple[os.stat_result, bytes]:
        nonlocal calls
        calls += 1
        if calls == 2:
            other = tmp_path / "other"
            other.write_bytes(b"old")
            other.replace(path)
        return read(parent, name, writable=writable)

    monkeypatch.setattr(file_mutation, "_regular_bytes", change)
    with pytest.raises(ValueError, match="File changed"):
        file_mutation._replace_file(path, operation(), b"old")
    assert path.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [path]


def test_fifo_replacement_is_rejected_without_opening_for_write(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    os.mkfifo(path)
    with pytest.raises(ValueError, match="regular file"):
        file_mutation._replace_file(path, operation(), b"old")


def test_capture_uses_pinned_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.install_sandbox.container.effect_environment import EffectEnvironment

    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "settings.json").write_bytes(b"new")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "settings.json").write_bytes(b"new")
    environment = object.__new__(EffectEnvironment)
    environment.project = tmp_path
    read = file_mutation._regular_bytes

    def swap(parent: int, name: str) -> tuple[os.stat_result, bytes]:
        nested.rename(tmp_path / "detached")
        nested.symlink_to(outside, target_is_directory=True)
        (outside / "settings.json").write_bytes(b"outside")
        return read(parent, name)

    monkeypatch.setattr(file_mutation, "_regular_bytes", swap)
    captured = file_mutation.capture_performed_mutation(operation(), environment)
    assert captured.document_sha256 == hashlib.sha256(b"new").hexdigest()


@pytest.mark.parametrize("fault", ["open-directory", "open-content", "write"])
def test_staging_failure_cleans_owned_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"old")
    original_open = os.open
    original_write = file_mutation._write_replacement

    def fail_open(
        target: str | os.PathLike[str], flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        if (fault == "open-directory" and str(target).startswith(".graphify-replacement-")) or (
            fault == "open-content" and target == "content"
        ):
            raise OSError("injected staging failure")
        return original_open(target, flags, mode, dir_fd=dir_fd)

    def fail_write(descriptor: int, content: bytes, mode: int) -> os.stat_result:
        if fault == "write":
            os.close(descriptor)
            raise OSError("injected staging failure")
        return original_write(descriptor, content, mode)

    monkeypatch.setattr(os, "open", fail_open)
    monkeypatch.setattr(file_mutation, "_write_replacement", fail_write)
    with pytest.raises(OSError, match="injected staging failure"):
        file_mutation._replace_file(path, operation(), b"old")
    assert path.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses file mode restrictions")
def test_readonly_original_is_not_replaced(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"old")
    path.chmod(0o444)
    with pytest.raises(PermissionError):
        file_mutation._replace_file(path, operation(), b"old")
    assert path.read_bytes() == b"old"


@pytest.mark.parametrize("when", ["before-write", "before-publication"])
def test_shared_staging_file_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"old")
    alias = tmp_path / "alias"
    write = file_mutation._write_replacement

    def linked_write(descriptor: int, content: bytes, mode: int) -> os.stat_result:
        staged = next(tmp_path.glob(".graphify-replacement-*/content"))
        if when == "before-write":
            os.link(staged, alias)
        info = write(descriptor, content, mode)
        if when == "before-publication":
            os.link(staged, alias)
        return info

    monkeypatch.setattr(file_mutation, "_write_replacement", linked_write)
    with pytest.raises(ValueError, match="shared"):
        file_mutation._replace_file(path, operation(), b"old")
    assert path.read_bytes() == b"old"
    if when == "before-write":
        assert alias.read_bytes() == b""
