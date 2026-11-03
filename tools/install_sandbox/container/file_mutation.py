"""Apply observation-bound mutations and capture their physical result."""

import hashlib
import os
import stat
from pathlib import Path

from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.contracts.bound_mutation import (
    BoundFileAppend,
    BoundFileCreation,
    BoundFileRemoval,
    BoundMutation,
    PerformedMutation,
)
from tools.install_sandbox.contracts.effects import Destination, SkillEffect
from tools.install_sandbox.contracts.intermediate import (
    AlteredReferencePreparation,
    AlteredSkillPreparation,
    IntermediatePreparation,
    PreserveSkillBackupPreparation,
)
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.rules.expectation_builder import (
    retained_bytes,
    selected_reference,
    selected_skill,
)


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


def apply_mutation(
    operation: BoundMutation,
    environment: EffectEnvironment,
    case_bytes: bytes,
    first_after: FilesystemSnapshot,
    sources: FilesystemSnapshot,
) -> None:
    _validate_destination(operation, environment, sources)
    retained = operation.verify_binding(case_bytes, first_after)
    path = _path(operation, environment)
    if isinstance(operation, BoundFileCreation):
        _create_file(operation, environment)
        return
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


def capture_performed_mutation(
    operation: BoundMutation, environment: EffectEnvironment
) -> PerformedMutation:
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
