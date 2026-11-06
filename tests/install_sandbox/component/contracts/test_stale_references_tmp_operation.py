"""The temporary-reference operation binds absent paths and preserves partial creation."""

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest

from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.container.file_mutation import (
    apply_mutation,
    capture_performed_mutation,
)
from tools.install_sandbox.contracts.bound_mutation import (
    BoundStaleReferencesTmpCreation,
    PerformedMutation,
    mutation_from_data,
)
from tools.install_sandbox.contracts.effects import Destination
from tools.install_sandbox.contracts.intermediate import (
    STALE_REFERENCE_CONTENT,
    StaleReferencesTmpPreparation,
)
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import SnapshotEntry


def environment_for(root: Path) -> EffectEnvironment:
    preparation = StaleReferencesTmpPreparation(Destination("home", "skill"))
    return cast(
        EffectEnvironment,
        SimpleNamespace(
            home=root, project=root, case=SimpleNamespace(intermediate_preparation=preparation)
        ),
    )


def operation() -> BoundStaleReferencesTmpCreation:
    return BoundStaleReferencesTmpCreation(
        hashlib.sha256(b"case").hexdigest(),
        "steps/0/after.json",
        Destination("home", "skill/references.tmp/stale.md"),
        STALE_REFERENCE_CONTENT,
    )


def snapshot(*, temporary: bool = False) -> FilesystemSnapshot:
    entries: list[SnapshotEntry] = [
        {"root": "home", "path": "skill", "kind": "directory", "listing_complete": True}
    ]
    if temporary:
        entries.append(
            {
                "root": "home",
                "path": "skill/references.tmp",
                "kind": "directory",
                "listing_complete": True,
            }
        )
    return FilesystemSnapshot(entries=entries)


def test_operation_roundtrip_and_existing_directory_rejection() -> None:
    prepared = operation()
    assert mutation_from_data(prepared.to_data()) == prepared
    assert prepared.verify_binding(b"case", snapshot()) == STALE_REFERENCE_CONTENT
    with pytest.raises(ValueError, match="absent directory"):
        prepared.verify_binding(b"case", snapshot(temporary=True))
    with pytest.raises(ValueError):
        prepared.verify_binding(b"case", FilesystemSnapshot())


def test_partial_directory_result_roundtrips_and_replays() -> None:
    performed = PerformedMutation(operation(), None)
    retained = PerformedMutation.from_data(performed.to_data())
    retained.verify(operation(), snapshot(temporary=True))
    observed = snapshot(temporary=True)
    observed.contents[("home", "skill/references.tmp/stale.md")] = b"unexpected"
    with pytest.raises(ValueError):
        retained.verify(operation(), observed)


def test_exclusive_creation_preserves_foreign_directory(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    temporary = skill / "references.tmp"
    temporary.mkdir()
    foreign = temporary / "personal"
    foreign.write_bytes(b"keep")
    environment = environment_for(tmp_path)
    with pytest.raises(FileExistsError):
        apply_mutation(operation(), environment, b"case", snapshot(), FilesystemSnapshot())
    assert foreign.read_bytes() == b"keep"
    assert not (temporary / "stale.md").exists()


def test_failed_file_creation_retains_empty_directory(tmp_path: Path) -> None:
    (tmp_path / "skill").mkdir()
    environment = environment_for(tmp_path)
    import os

    original = os.open

    def fail_file(path: str, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        if path == "stale.md":
            raise PermissionError("injected creation failure")
        return original(path, flags, mode, dir_fd=dir_fd)

    with (
        patch("tools.install_sandbox.container.file_mutation.os.open", side_effect=fail_file),
        pytest.raises(PermissionError),
    ):
        apply_mutation(operation(), environment, b"case", snapshot(), FilesystemSnapshot())
    assert list((tmp_path / "skill/references.tmp").iterdir()) == []
    assert capture_performed_mutation(operation(), environment).document_sha256 is None


def test_symlink_skill_never_receives_witness(tmp_path: Path) -> None:
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (tmp_path / "skill").symlink_to(foreign, target_is_directory=True)
    environment = environment_for(tmp_path)
    with pytest.raises((OSError, ValueError)):
        apply_mutation(operation(), environment, b"case", snapshot(), FilesystemSnapshot())
    assert list(foreign.iterdir()) == []


def test_successful_creation_captures_actual_bytes(tmp_path: Path) -> None:
    (tmp_path / "skill").mkdir()
    environment = environment_for(tmp_path)
    prepared = operation()
    apply_mutation(prepared, environment, b"case", snapshot(), FilesystemSnapshot())
    witness = tmp_path / prepared.destination.path
    assert witness.read_bytes() == prepared.content
    assert (
        capture_performed_mutation(prepared, environment).document_sha256
        == hashlib.sha256(prepared.content).hexdigest()
    )
