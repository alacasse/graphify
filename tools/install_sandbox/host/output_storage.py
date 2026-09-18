"""Private filesystem mechanisms for the local campaign lifecycle."""

from __future__ import annotations

import ctypes
import errno
import fcntl
import os
import stat
import sys
import tempfile
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path

from tools.install_sandbox.host.output_report import OutputReport, read_report


class FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        if not stat.S_ISREG(os.fstat(self.fd).st_mode) or os.fstat(self.fd).st_nlink != 1:
            os.close(self.fd)
            raise ValueError(f"Unsafe lock: {path}")

    def acquire(self, *, wait: bool = True) -> bool:
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
            return True
        except BlockingIOError:
            return False

    def remove_file(self, path: Path) -> None:
        if not path.exists():
            return
        current, held = path.lstat(), os.fstat(self.fd)
        if (current.st_dev, current.st_ino) != (held.st_dev, held.st_ino):
            raise ValueError(f"Activity lock changed: {path}")
        path.unlink()

    def close(self) -> None:
        os.close(self.fd)


@contextmanager
def coordination(root: Path) -> Generator[None]:
    lock = FileLock(root / ".lock")
    try:
        lock.acquire()
        yield
    finally:
        lock.close()


def safe_path(path: Path) -> Path:
    absolute = Path(os.path.abspath(path.expanduser()))
    if any(p.is_symlink() for p in (absolute, *absolute.parents)):
        raise ValueError(f"Output paths must not traverse symlinks: {path}")
    if "," in str(absolute):
        raise ValueError("Output mount paths must be comma-free")
    return absolute


def overlaps(first: Path, second: Path) -> bool:
    return first.is_relative_to(second) or second.is_relative_to(first)


def move_exclusive(source: Path, destination: Path) -> None:
    """Linux renameat2(int, char*, int, char*, unsigned), RENAME_NOREPLACE=1.

    No rename/copy fallback. Other hosts are refused until their native primitive
    has been verified; the current implementation and evidence cover Linux only.
    """
    if sys.platform != "linux":
        raise OSError(
            errno.ENOTSUP, "Exclusive directory publication requires verified Linux support"
        )
    library = ctypes.CDLL(None, use_errno=True)
    try:
        rename = library.renameat2
    except AttributeError as error:
        raise OSError(errno.ENOTSUP, "renameat2 is unavailable") from error
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1) != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number), str(destination))


def verify_publication(source_parent: Path, destination_parent: Path) -> None:
    """Probe both replacement refusal and a successful move on the actual filesystems."""
    with (
        tempfile.TemporaryDirectory(prefix=".publish-probe-", dir=source_parent) as first,
        tempfile.TemporaryDirectory(prefix=".publish-probe-", dir=destination_parent) as second,
    ):
        source, destination = Path(first) / "source", Path(second) / "occupied"
        source.mkdir()
        destination.mkdir()
        try:
            move_exclusive(source, destination)
        except FileExistsError:
            pass
        else:
            raise OSError("Native publication failed to refuse an existing directory")
        move_exclusive(source, Path(second) / "absent")


def campaign_directories(root: Path) -> Iterator[Path]:
    """Descend directory-only namespaces, never into recognized or foreign evidence."""
    pending = [root]
    while pending:
        current = pending.pop()
        for path in sorted(current.iterdir()):
            if path.name == ".lock" or path.name.startswith(".publish-probe-"):
                continue
            if path.is_symlink() or not path.is_dir() or (path / "campaign.json").exists():
                yield path
            elif path == root / "in-progress":
                yield from path.iterdir()
            elif any(path.iterdir()) and all(
                p.is_dir() and not p.is_symlink() for p in path.iterdir()
            ):
                pending.append(path)
            else:
                yield path


def reservations(root: Path) -> list[Path]:
    paths: list[Path] = []
    for directory in campaign_directories(root):
        paths.append(directory)
        try:
            report = read_report(directory, root)
            destination = safe_path(Path(report.destination))
            if destination.is_relative_to(root):
                paths.append(destination)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return paths


def choose_paths(root: Path, name: str, requested: Path | None) -> tuple[Path, Path]:
    reserved = reservations(root)
    if requested is not None:
        forbidden = (root / "in-progress", root / ".lock")
        if (
            requested == root
            or requested.name.startswith(".publish-probe-")
            or any(overlaps(requested, p) for p in forbidden)
        ):
            raise ValueError("Requested output overlaps lifecycle management paths")
        if requested.exists() or any(overlaps(requested, p) for p in reserved):
            raise ValueError(f"Managed destination must be absent and unreserved: {requested}")
    suffix = 1
    while True:
        candidate = name if suffix == 1 else f"{name}-{suffix:02d}"
        work, final = root / "in-progress" / candidate, requested or root / candidate
        if (
            not work.exists()
            and not (root / candidate).exists()
            and not any(overlaps(root / candidate, p) for p in reserved)
        ):
            return work, final
        suffix += 1


def identity_matches(directory: Path, report: OutputReport, root: Path) -> bool:
    if directory.is_symlink():
        return False
    try:
        return read_report(directory, root).payload() == report.payload()
    except (OSError, ValueError, KeyError, TypeError):
        return False
