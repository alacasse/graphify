from __future__ import annotations

from pathlib import Path

import pytest

from tools.install_sandbox.validation.catalog import CatalogDocuments, CatalogReadError, Scope
from tools.install_sandbox.validation.engine import ValidationCompleted, validate
from tools.install_sandbox.validation.plan_types import HarnessPolicy, ValidationRequest
from tools.install_sandbox.validation.protocol import (
    ActionFailureFact,
    ActionKind,
    CommandRequest,
    ObservationRequest,
    OperationEvent,
    OperationKind,
    RawFact,
)


def test_catalog_directory_drives_the_same_validation_interface(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir()
    for target in ("second", "first"):
        (catalog_dir / f"{target}.yaml").write_text(
            """
scopes:
  user:
    supported: false
    reason: User scope is unavailable in this fixture.
    runtime_limitations: []
  project:
    supported: true
    runtime_limitations: []
    surfaces:
      - kind: owned_file
        root: project
        path: .fictional/config.txt
        source: fixtures/config.txt
""".lstrip(),
            encoding="utf-8",
        )

    documents = CatalogDocuments.from_directory(catalog_dir)

    def fulfil(request: CommandRequest | ObservationRequest) -> RawFact:
        assert isinstance(request, CommandRequest)
        sequence = request.action_id.ordinal * 2
        chronology = (
            OperationEvent(sequence, OperationKind.COMMAND_STARTED, sequence),
            OperationEvent(sequence + 1, OperationKind.COMMAND_FAILED, sequence + 1),
        )
        return ActionFailureFact(
            request.action_id,
            ActionKind.COMMAND,
            "fixture_stop",
            "catalog component test does not execute product commands",
            chronology,
        )

    result = validate(
        ValidationRequest(targets=("first", "second"), scopes=(Scope.PROJECT,)),
        documents,
        HarnessPolicy(),
        fulfil,
    )

    assert isinstance(result, ValidationCompleted)
    assert tuple(target.name for target in result.catalog.targets) == ("first", "second")


def test_catalog_directory_rejects_a_symlinked_target_document(tmp_path: Path) -> None:
    outside = tmp_path / "outside.yaml"
    outside.write_text("scopes: {}\n", encoding="utf-8")
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir()
    (catalog_dir / "fictional.yaml").symlink_to(outside)

    with pytest.raises(CatalogReadError, match="regular file"):
        CatalogDocuments.from_directory(catalog_dir)


def test_catalog_directory_rejects_a_symlinked_catalog_root(tmp_path: Path) -> None:
    real_catalog = tmp_path / "real-catalog"
    real_catalog.mkdir()
    linked_catalog = tmp_path / "linked-catalog"
    linked_catalog.symlink_to(real_catalog, target_is_directory=True)

    with pytest.raises(CatalogReadError, match="real directory"):
        CatalogDocuments.from_directory(linked_catalog)


def test_catalog_directory_rejects_a_yaml_named_directory(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir()
    (catalog_dir / "fictional.yaml").mkdir()

    with pytest.raises(CatalogReadError, match="regular file"):
        CatalogDocuments.from_directory(catalog_dir)
