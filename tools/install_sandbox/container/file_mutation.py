"""Apply observation-bound mutations and capture their physical result."""

import hashlib
import os
import secrets
import stat
from collections.abc import Generator
from contextlib import contextmanager, suppress
from pathlib import Path

from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.contracts.bound_mutation import (
    BoundFileAppend,
    BoundFileCreation,
    BoundFileRemoval,
    BoundFileReplacement,
    BoundMarkdownMutation,
    BoundMutation,
    PerformedMutation,
)
from tools.install_sandbox.contracts.effects import Destination, JsonHooksEffect, SkillEffect
from tools.install_sandbox.contracts.intermediate import (
    AlteredReferencePreparation,
    AlteredSkillPreparation,
    IntermediatePreparation,
    MissingJsonHookPreparation,
    PreserveSkillBackupPreparation,
)
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.rules.expectation_builder import (
    retained_bytes,
    selected_reference,
    selected_skill,
)
from tools.install_sandbox.rules.json_hook_repair import missing_hook_settings


def _path(operation: BoundMutation, environment: EffectEnvironment) -> Path:
    root = environment.project if operation.destination.root == "project" else environment.home
    path = root / operation.destination.path
    if path.resolve() != path:
        raise ValueError("Mutation path must not contain symlinks")
    return path


def _backup_destination(
    operation: BoundFileCreation,
    environment: EffectEnvironment,
    preparation: PreserveSkillBackupPreparation,
    sources: FilesystemSnapshot,
) -> Destination:
    skill = selected_skill(environment.case)
    destination = Destination(skill.root, skill.path + environment.case.subject.rules.skill_backup)
    effect = next(
        effect
        for effect in environment.case.effects.effects
        if isinstance(effect, SkillEffect) and effect.destination == preparation.destination
    )
    source = retained_bytes(sources, "subject", effect.source)
    if operation.content != source + preparation.suffix:
        raise ValueError("Operation content differs from retained source and backup witness")
    return destination


def _validate_destination(
    operation: BoundMutation, environment: EffectEnvironment, sources: FilesystemSnapshot
) -> None:
    preparation = environment.case.intermediate_preparation
    if isinstance(preparation, PreserveSkillBackupPreparation) or isinstance(
        operation, BoundFileCreation
    ):
        if not isinstance(operation, BoundFileCreation) or not isinstance(
            preparation, PreserveSkillBackupPreparation
        ):
            raise ValueError("Backup preparation requires a creation operation")
        destination = _backup_destination(operation, environment, preparation, sources)
        if destination != operation.destination:
            raise ValueError("Operation destination differs from case and retained sources")
        return
    _validate_existing_destination(operation, environment, sources)


def _validate_existing_destination(
    operation: BoundMutation, environment: EffectEnvironment, sources: FilesystemSnapshot
) -> None:
    preparation = environment.case.intermediate_preparation
    if isinstance(preparation, AlteredSkillPreparation):
        if not isinstance(operation, BoundFileAppend):
            raise ValueError("Skill preparation requires an append operation")
        destination = selected_skill(environment.case)
    elif isinstance(operation, (BoundFileRemoval, BoundFileAppend)):
        destination = selected_reference(environment.case, sources)
    else:
        if not isinstance(preparation, IntermediatePreparation):
            raise ValueError("Markdown mutation requires Markdown preparation")
        destination = preparation.destination
    if destination != operation.destination:
        raise ValueError("Operation destination differs from case and retained sources")
    if isinstance(operation, BoundFileAppend) and (
        not isinstance(preparation, (AlteredReferencePreparation, AlteredSkillPreparation))
        or operation.suffix != preparation.suffix
    ):
        raise ValueError("Operation suffix differs from case preparation")


def _create_file(operation: BoundFileCreation, environment: EffectEnvironment) -> None:
    """Open every parent without following links, then create exclusively."""
    root = environment.project if operation.destination.root == "project" else environment.home
    parts = Path(operation.destination.path).parts
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent = os.open(root, directory_flags)
    try:
        for part in parts[:-1]:
            child = os.open(part, directory_flags, dir_fd=parent)
            os.close(parent)
            parent = child
        descriptor = os.open(
            parts[-1],
            os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_RDWR,
            0o600,
            dir_fd=parent,
        )
        with os.fdopen(descriptor, "w+b") as stream:
            if stream.write(operation.content) != len(operation.content):
                raise ValueError("Incomplete backup creation")
            stream.flush()
            stream.seek(0)
            if stream.read() != operation.content:
                raise ValueError("Created backup differs from intended bytes")
    finally:
        os.close(parent)


def _validate_hook_removal(
    operation: BoundMutation, environment: EffectEnvironment, retained: bytes
) -> None:
    preparation = environment.case.intermediate_preparation
    if not isinstance(operation, BoundFileReplacement) or not isinstance(
        preparation, MissingJsonHookPreparation
    ):
        raise ValueError("Hook removal requires a replacement of the selected settings")
    effect = next(e for e in environment.case.effects.effects if isinstance(e, JsonHooksEffect))
    if operation.destination != effect.destination or preparation.destination != effect.destination:
        raise ValueError("Hook removal destination differs from selected settings")
    if operation.content != missing_hook_settings(effect, retained):
        raise ValueError("Replacement differs from the selected hook removal")


def apply_mutation(
    operation: BoundMutation,
    environment: EffectEnvironment,
    case_bytes: bytes,
    first_after: FilesystemSnapshot,
    sources: FilesystemSnapshot,
) -> None:
    retained = operation.verify_binding(case_bytes, first_after)
    if isinstance(operation, BoundFileReplacement) or isinstance(
        environment.case.intermediate_preparation, MissingJsonHookPreparation
    ):
        _validate_hook_removal(operation, environment, retained)
    else:
        _validate_destination(operation, environment, sources)
    if isinstance(operation, BoundFileReplacement):
        root = environment.project if operation.destination.root == "project" else environment.home
        _replace_file(root / operation.destination.path, operation, retained)
        return
    path = _path(operation, environment)
    if isinstance(operation, BoundFileCreation):
        _create_file(operation, environment)
        return
    _mutate_existing(path, operation, retained)


def _mutate_existing(
    path: Path,
    operation: BoundFileRemoval | BoundFileAppend | BoundMarkdownMutation,
    retained: bytes,
) -> None:
    if not path.is_file():
        raise ValueError("Operation requires original regular file")
    flags = os.O_RDONLY if isinstance(operation, BoundFileRemoval) else os.O_RDWR
    mode = "rb" if isinstance(operation, BoundFileRemoval) else "r+b"
    with os.fdopen(os.open(path, flags | os.O_NOFOLLOW), mode) as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode) or stream.read() != retained:
            raise ValueError("File changed since validated observation")
        if isinstance(operation, BoundFileRemoval):
            path.unlink()
        elif isinstance(operation, BoundFileAppend):
            stream.seek(0, os.SEEK_END)
            stream.write(operation.suffix)
        else:
            stream.seek(0)
            stream.write(
                retained[: operation.start] + operation.replacement + retained[operation.end :]
            )
            stream.truncate()


@contextmanager
def _pinned_parent(path: Path) -> Generator[int]:
    """Traverse from the filesystem root without following any directory links."""
    path = path.absolute()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:-1]:
            previous = parent
            parent = os.open(part, flags, dir_fd=previous)
            os.close(previous)
        yield parent
    except BaseException:
        with suppress(OSError):
            os.close(parent)
        raise
    else:
        os.close(parent)


def _regular_bytes(
    parent: int, name: str, *, writable: bool = False
) -> tuple[os.stat_result, bytes]:
    # NONBLOCK makes a concurrent replacement with a FIFO fail without hanging.
    flags = os.O_RDWR if writable else os.O_RDONLY
    descriptor = os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Operation requires original regular file")
        return info, stream.read()


@contextmanager
def _staged_replacement(
    parent: int, content: bytes, mode: int
) -> Generator[tuple[str, os.stat_result]]:
    name = ".graphify-replacement-" + secrets.token_hex(16)
    descriptor = os.open(
        name, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=parent
    )
    identity = None
    try:
        identity = os.fstat(descriptor)
        _validate_staged_file(parent, name, identity)
        prepared = _write_replacement(descriptor, content, mode)
    except BaseException:
        try:
            # Retry only if the first fstat failed. The open fd still identifies
            # our inode even if someone already substituted the directory entry.
            with suppress(OSError):
                if identity is None:
                    identity = os.fstat(descriptor)
                _unlink_owned(parent, name, identity)
        finally:
            with suppress(OSError):
                os.close(descriptor)
        raise

    try:
        os.close(descriptor)
        yield name, prepared
    except BaseException:
        with suppress(OSError):
            _unlink_owned(parent, name, identity)
        raise


def _replace_file(path: Path, operation: BoundFileReplacement, retained: bytes) -> None:
    """Publish a new inode; never write through a possibly shared original inode."""
    with _pinned_parent(path) as parent:
        original, content = _regular_bytes(parent, path.name, writable=True)
        if content != retained:
            raise ValueError("File changed since validated observation")
        with _staged_replacement(parent, operation.content, original.st_mode) as (name, prepared):
            _validate_publication(parent, path.name, original, retained, name, prepared)
            # rename is atomic, but is not a compare-and-swap against an adversarial writer.
            os.replace(name, path.name, src_dir_fd=parent, dst_dir_fd=parent)


def _validate_publication(
    parent: int,
    name: str,
    original: os.stat_result,
    retained: bytes,
    staged_name: str,
    prepared: os.stat_result,
) -> None:
    current, content = _regular_bytes(parent, name)
    if (current.st_dev, current.st_ino) != (
        original.st_dev,
        original.st_ino,
    ) or content != retained:
        raise ValueError("File changed since validated observation")
    _validate_staged_file(parent, staged_name, prepared)


def _validate_staged_file(parent: int, name: str, expected: os.stat_result) -> None:
    staged = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if not os.path.samestat(staged, expected):
        raise ValueError("Prepared replacement changed")
    if staged.st_nlink != 1:
        raise ValueError("Prepared replacement is shared")


def _write_replacement(descriptor: int, content: bytes, mode: int) -> os.stat_result:
    with os.fdopen(descriptor, "w+b", buffering=0, closefd=False) as stream:
        if os.fstat(stream.fileno()).st_nlink != 1:
            raise ValueError("Prepared replacement is shared")
        if stream.write(content) != len(content):
            raise ValueError("Incomplete settings replacement")
        os.fchmod(stream.fileno(), stat.S_IMODE(mode))
        stream.seek(0)
        if stream.read() != content:
            raise ValueError("Replacement differs from intended bytes")
        return os.fstat(stream.fileno())


def _unlink_owned(parent: int, name: str, expected: os.stat_result) -> None:
    current = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if os.path.samestat(current, expected):
        os.unlink(name, dir_fd=parent)


def capture_performed_mutation(
    operation: BoundMutation, environment: EffectEnvironment
) -> PerformedMutation:
    if isinstance(operation, BoundFileReplacement):
        root = environment.project if operation.destination.root == "project" else environment.home
        path = root / operation.destination.path
        with _pinned_parent(path) as parent:
            _, content = _regular_bytes(parent, path.name)
        return PerformedMutation(operation, hashlib.sha256(content).hexdigest())
    path = _path(operation, environment)
    if isinstance(operation, BoundFileCreation) and not os.path.lexists(path):
        return PerformedMutation(operation, None)
    if isinstance(operation, BoundFileRemoval):
        if os.path.lexists(path):
            raise ValueError("Performed removal requires an absent file")
        return PerformedMutation(operation, None)
    if not path.is_file():
        raise ValueError("Performed mutation requires a regular document")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        return PerformedMutation(operation, hashlib.sha256(stream.read()).hexdigest())
