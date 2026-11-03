"""Apply observation-bound mutations and capture their physical result."""

import hashlib
import os
import stat
from pathlib import Path

from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.contracts.bound_mutation import (
    BoundFileRemoval,
    BoundMutation,
    PerformedMutation,
)
from tools.install_sandbox.contracts.intermediate import IntermediatePreparation
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.rules.expectation_builder import selected_reference


def _path(operation: BoundMutation, environment: EffectEnvironment) -> Path:
    root = environment.project if operation.destination.root == "project" else environment.home
    path = root / operation.destination.path
    if path.resolve() != path:
        raise ValueError("Mutation path must not contain symlinks")
    return path


def apply_mutation(
    operation: BoundMutation,
    environment: EffectEnvironment,
    case_bytes: bytes,
    first_after: FilesystemSnapshot,
    sources: FilesystemSnapshot,
) -> None:
    preparation = environment.case.intermediate_preparation
    if isinstance(operation, BoundFileRemoval):
        destination = selected_reference(environment.case, sources)
    else:
        if not isinstance(preparation, IntermediatePreparation):
            raise ValueError("Markdown mutation requires Markdown preparation")
        destination = preparation.destination
    if destination != operation.destination:
        raise ValueError("Operation destination differs from case and retained sources")
    retained = operation.verify_binding(case_bytes, first_after)
    path = _path(operation, environment)
    if not path.is_file():
        raise ValueError("Operation requires original regular file")
    flags = os.O_RDONLY if isinstance(operation, BoundFileRemoval) else os.O_RDWR
    mode = "rb" if isinstance(operation, BoundFileRemoval) else "r+b"
    with os.fdopen(os.open(path, flags | os.O_NOFOLLOW), mode) as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode) or stream.read() != retained:
            raise ValueError("File changed since validated observation")
        if isinstance(operation, BoundFileRemoval):
            path.unlink()
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
    if isinstance(operation, BoundFileRemoval):
        if os.path.lexists(path):
            raise ValueError("Performed removal requires an absent file")
        return PerformedMutation(operation, None)
    if not path.is_file():
        raise ValueError("Performed mutation requires a regular document")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        return PerformedMutation(operation, hashlib.sha256(stream.read()).hexdigest())
