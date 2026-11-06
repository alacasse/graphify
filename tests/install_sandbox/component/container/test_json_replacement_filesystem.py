"""Real-filesystem isolation of settings replacement."""

# pyright: reportPrivateUsage=false

import errno
import hashlib
import os
from pathlib import Path

import pytest

from tools.install_sandbox.container import file_mutation
from tools.install_sandbox.contracts.bound_mutation import BoundFileReplacement
from tools.install_sandbox.contracts.effects import Destination

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="requires POSIX dir_fd operations and O_DIRECTORY/O_NOFOLLOW",
)


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


@pytest.mark.parametrize("fault", ["open", "write"])
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
        if fault == "open" and str(target).startswith(".graphify-replacement-"):
            raise OSError("injected staging failure")
        return original_open(target, flags, mode, dir_fd=dir_fd)

    def fail_write(descriptor: int, content: bytes, mode: int) -> os.stat_result:
        if fault == "write":
            raise OSError("injected staging failure")
        return original_write(descriptor, content, mode)

    monkeypatch.setattr(os, "open", fail_open)
    monkeypatch.setattr(file_mutation, "_write_replacement", fail_write)
    with pytest.raises(OSError, match="injected staging failure"):
        file_mutation._replace_file(path, operation(), b"old")
    assert path.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root bypasses POSIX file mode restrictions",
)
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
        staged = next(tmp_path.glob(".graphify-replacement-*"))
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


@pytest.fixture
def opened_content(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    descriptors: list[int] = []
    original_open = os.open

    def track_open(
        target: str | os.PathLike[str], flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        fd = original_open(target, flags, mode, dir_fd=dir_fd)
        if str(target).startswith(".graphify-replacement-"):
            descriptors.append(fd)
        return fd

    monkeypatch.setattr(os, "open", track_open)
    return descriptors


def assert_closed(descriptors: list[int]) -> None:
    assert descriptors
    for descriptor in descriptors:
        with pytest.raises(OSError) as caught:
            os.fstat(descriptor)
        assert caught.value.errno == errno.EBADF


def test_staging_stat_failure_cleans_owned_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, opened_content: list[int]
) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"old")
    original_stat = os.stat
    error = OSError(errno.EIO, "injected staging stat failure")

    def fail_stat(
        target: str | os.PathLike[str] | int,
        *,
        dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> os.stat_result:
        if isinstance(target, str) and target.startswith(".graphify-replacement-"):
            monkeypatch.setattr(os, "stat", original_stat)
            raise error
        return original_stat(target, dir_fd=dir_fd, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(os, "stat", fail_stat)
    with pytest.raises(OSError) as caught:
        file_mutation._replace_file(path, operation(), b"old")
    assert caught.value is error
    assert path.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [path]
    assert_closed(opened_content)


@pytest.mark.parametrize("directory", [False, True], ids=["file", "directory"])
def test_substitution_before_initial_fstat_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, opened_content: list[int], directory: bool
) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"old")
    original_open = os.open
    substitute: Path | None = None
    identity: tuple[int, int] | None = None

    def substitute_open(
        target: str | os.PathLike[str], flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        nonlocal substitute, identity
        descriptor = original_open(target, flags, mode, dir_fd=dir_fd)
        if str(target).startswith(".graphify-replacement-"):
            substitute = tmp_path / target
            # Keep the staged inode linked so the substitution cannot be detected by nlink.
            substitute.rename(tmp_path / "detached")
            if directory:
                substitute.mkdir()
            else:
                substitute.write_bytes(b"substitute")
            info = substitute.stat()
            identity = (info.st_dev, info.st_ino)
        return descriptor

    monkeypatch.setattr(os, "open", substitute_open)
    with pytest.raises(ValueError, match="replacement changed"):
        file_mutation._replace_file(path, operation(), b"old")
    assert substitute is not None
    info = substitute.stat()
    assert (info.st_dev, info.st_ino) == identity
    if directory:
        assert list(substitute.iterdir()) == []
    else:
        assert substitute.read_bytes() == b"substitute"
    assert (tmp_path / "detached").read_bytes() == b""
    assert path.read_bytes() == b"old"
    assert_closed(opened_content)


@pytest.mark.parametrize("permanent", [False, True], ids=["retry", "no-identity"])
def test_initial_fstat_failure_preserves_error_and_closes_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, opened_content: list[int], permanent: bool
) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"old")
    original_fstat = os.fstat
    error = OSError(errno.EIO, "injected initial fstat failure")
    calls = 0

    def fail_fstat(fd: int) -> os.stat_result:
        nonlocal calls
        if fd in opened_content:
            calls += 1
            if permanent or calls == 1:
                raise error
        return original_fstat(fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fstat", fail_fstat)
        with pytest.raises(OSError) as caught:
            file_mutation._replace_file(path, operation(), b"old")
    assert caught.value is error
    assert path.read_bytes() == b"old"
    assert_closed(opened_content)
    staged = list(tmp_path.glob(".graphify-replacement-*"))
    assert len(staged) == int(permanent)
    if permanent:
        assert staged[0].read_bytes() == b""


def test_cached_identity_cleans_after_all_later_fstats_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, opened_content: list[int]
) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"old")
    original_fstat = os.fstat
    error = OSError(errno.EIO, "injected later fstat failure")
    calls = 0

    def fail_fstat(fd: int) -> os.stat_result:
        nonlocal calls
        if fd in opened_content:
            calls += 1
            if calls > 1:
                raise error
        return original_fstat(fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fstat", fail_fstat)
        with pytest.raises(OSError) as caught:
            file_mutation._replace_file(path, operation(), b"old")
    assert caught.value is error
    assert path.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [path]
    assert_closed(opened_content)


@pytest.mark.parametrize("write_fails", [False, True])
def test_content_close_failure_aborts_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, opened_content: list[int], write_fails: bool
) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"old")
    original_close = os.close
    close_error = OSError(errno.EIO, "injected content close failure")
    write_error = OSError(errno.ENOSPC, "injected write failure")

    def fail_close(fd: int) -> None:
        original_close(fd)
        if fd in opened_content:
            raise close_error

    def fail_write(descriptor: int, content: bytes, mode: int) -> os.stat_result:
        raise write_error

    if write_fails:
        monkeypatch.setattr(file_mutation, "_write_replacement", fail_write)
    monkeypatch.setattr(os, "close", fail_close)
    with pytest.raises(OSError) as caught:
        file_mutation._replace_file(path, operation(), b"old")
    assert caught.value is (write_error if write_fails else close_error)
    assert path.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [path]
    assert_closed(opened_content)


@pytest.mark.parametrize("write_fails", [False, True])
def test_parent_close_failure_preserves_primary_write_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, opened_content: list[int], write_fails: bool
) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"old")
    original_close = os.close
    parent = tmp_path.stat()
    write_error = OSError(errno.ENOSPC, "injected write failure")
    closed: list[int] = []
    close_error = OSError(errno.EIO, "injected parent close failure")

    def fail_close(fd: int) -> None:
        is_parent = os.path.samestat(os.fstat(fd), parent)
        original_close(fd)
        if is_parent:
            closed.append(fd)
            raise close_error

    def fail_write(descriptor: int, content: bytes, mode: int) -> os.stat_result:
        raise write_error

    monkeypatch.setattr(os, "close", fail_close)
    if write_fails:
        monkeypatch.setattr(file_mutation, "_write_replacement", fail_write)
    with pytest.raises(OSError) as caught:
        file_mutation._replace_file(path, operation(), b"old")
    assert caught.value is (write_error if write_fails else close_error)
    assert len(closed) == 1
    assert path.read_bytes() == (b"old" if write_fails else b"new")
    assert list(tmp_path.iterdir()) == [path]
    assert_closed([*opened_content, *closed])


def test_traversal_close_failure_closes_each_opened_descriptor_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_open = os.open
    original_close = os.close
    opened: list[int] = []
    closed: list[int] = []
    error = OSError(errno.EIO, "injected traversal close failure")

    def track_open(
        target: str | os.PathLike[str], flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        descriptor = original_open(target, flags, mode, dir_fd=dir_fd)
        opened.append(descriptor)
        return descriptor

    def fail_close(fd: int) -> None:
        closed.append(fd)
        original_close(fd)
        if len(closed) == 1:
            raise error

    monkeypatch.setattr(os, "open", track_open)
    monkeypatch.setattr(os, "close", fail_close)
    with pytest.raises(OSError) as caught, file_mutation._pinned_parent(tmp_path / "settings.json"):
        pytest.fail("traversal must fail before yielding")
    assert caught.value is error
    assert sorted(closed) == sorted(opened)
    assert len(closed) == len(set(closed))
    assert_closed(opened)
