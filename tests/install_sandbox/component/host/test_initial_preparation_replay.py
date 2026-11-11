"""Initial prefixes built from literal evidence, independently of runner publication."""

import json
from pathlib import Path
from typing import Any

import pytest

from tools.install_sandbox.host.result_reader import MalformedEvidence, read_evidence

# The accepted protocol's observable checkpoints, deliberately independent of its rules.
CHECKPOINTS = (
    "started",
    "environment_retained",
    "sources_retained",
    "expectations_retained",
    "observed",
    "verified",
    "ready",
)
GROUPS = (
    ("environment", "environment", "roots.json"),
    ("sources", "sources", "expected.json"),
    ("expectations", "expectations", "expectations/initial.json"),
    ("observation", "before", "initial/before.json"),
    ("verification", "verification", "initial-verification.json"),
    ("install_expectations", "install_expectations", "expectations/install.json"),
)


def archive(root: Path, published: int, retained: int) -> Path:
    fixture = Path(__file__).parents[2] / "fixtures/retained-markdown-proof.json"
    payload: dict[str, str] = json.loads(fixture.read_text())
    result: dict[str, Any] = json.loads(payload["result.json"])
    result["status"] = "incomplete"
    result["preparation"] = preparation(published)
    result["steps"] = [idle_step(), idle_step()]
    payload["result.json"] = json.dumps(result)
    finals = {reference for _, _, reference in GROUPS[:retained]}
    prefixes = [
        r.removesuffix(".json") + "/"
        for r in finals
        if r
        in {
            "expected.json",
            "initial/before.json",
        }
    ]
    for reference, content in payload.items():
        if reference not in finals | {
            "case.json",
            "result.json",
            "evidence-format.json",
        } and not any(reference.startswith(prefix) for prefix in prefixes):
            continue
        destination = root / reference
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)
    return root


def preparation(count: int) -> dict[str, Any]:
    return {
        "checkpoint": CHECKPOINTS[count],
        "facts": {
            "completed": [operation for operation, _, _ in GROUPS[:count]],
            "verification_passed": True if count >= 5 else None,
        },
        "retained": {
            **{
                name: reference if i < count else None
                for i, (_, name, reference) in enumerate(GROUPS)
            },
            "failure": None,
        },
        "stop": None,
        "previous_checkpoint": None,
    }


def idle_step() -> dict[str, Any]:
    return {
        "operation": "install",
        "phase": "idle",
        "intent": None,
        "assessment": None,
        "facts": {"prepared": False, "command": None, "verification": None},
        "retained": {
            "before": None,
            "before_usable": True,
            "expectations": None,
            "command": False,
            "after": None,
            "verification": None,
        },
        "stop": None,
    }


@pytest.mark.parametrize("published", range(7), ids=CHECKPOINTS)
@pytest.mark.parametrize("ahead", [False, True], ids=["exact-prefix", "next-operation-retained"])
def test_literal_initial_prefix_is_replayed_without_promoting_state(
    tmp_path: Path,
    published: int,
    ahead: bool,
) -> None:
    output = archive(tmp_path, published, min(published + int(ahead), 6))
    result = read_evidence(output)
    assert result.status == "incomplete"
    assert result.preparation.checkpoint == CHECKPOINTS[published]
    assert all(step.phase == "idle" for step in result.steps)


@pytest.mark.parametrize("published", range(5), ids=CHECKPOINTS[:5])
def test_literal_archive_cannot_cross_two_unpublished_checkpoints(
    tmp_path: Path,
    published: int,
) -> None:
    output = archive(tmp_path, published, published + 2)
    with pytest.raises(MalformedEvidence):
        read_evidence(output)


@pytest.mark.parametrize(
    "reference",
    [
        "roots.json",
        "expected.json",
        "expectations/initial.json",
        "initial/before.json",
        "initial-verification.json",
        "expectations/install.json",
    ],
)
def test_unpublished_final_artifact_is_still_validated(tmp_path: Path, reference: str) -> None:
    operation = next(i for i, (_, _, ref) in enumerate(GROUPS) if ref == reference)
    output = archive(tmp_path, operation, operation + 1)
    (output / reference).write_text("{}")
    with pytest.raises(MalformedEvidence):
        read_evidence(output)


@pytest.mark.parametrize("field", ["before", "expectations", "sources"])
def test_foreign_initial_reference_cannot_borrow_valid_evidence(
    tmp_path: Path,
    field: str,
) -> None:
    output = archive(tmp_path, 6, 6)
    path = output / "result.json"
    result = json.loads(path.read_text())
    result["preparation"]["retained"][field] = "steps/0/before.json"
    path.write_text(json.dumps(result))
    with pytest.raises(MalformedEvidence):
        read_evidence(output)


def test_retained_unpublished_verdict_does_not_authorize_installation(tmp_path: Path) -> None:
    output = archive(tmp_path, 4, 5)
    path = output / "result.json"
    result = json.loads(path.read_text())
    result["steps"][0]["phase"] = "preparation"
    path.write_text(json.dumps(result))
    with pytest.raises(MalformedEvidence):
        read_evidence(output)


@pytest.mark.parametrize("diagnostic", ["absent", "retained", "published"])
def test_intact_unusable_sources_support_deterministic_stop(
    tmp_path: Path,
    diagnostic: str,
) -> None:
    import hashlib

    output = archive(tmp_path, 2, 2)
    source = output / "expected/instructions.md"
    source.write_bytes(b"Plain instructions without the required marker.\n")
    manifest_path = output / "expected.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["entries"][0]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    stopped = preparation(2)
    stopped.update(checkpoint="stopped", previous_checkpoint="sources_retained")
    stopped["retained"]["failure"] = "initial/failure.json"
    stopped["stop"] = {
        "operation": "expectations",
        "category": "validation",
        "reason": "Retained Markdown source does not start with its marker",
        "facts": stopped["facts"],
    }
    if diagnostic != "absent":
        failure = output / "initial/failure.json"
        failure.parent.mkdir()
        failure.write_text(json.dumps(stopped))
    if diagnostic == "published":
        path = output / "result.json"
        result = json.loads(path.read_text())
        result.update(preparation=stopped, status="not_run")
        path.write_text(json.dumps(result))
    result = read_evidence(output)
    assert result.status == ("not_run" if diagnostic == "published" else "incomplete")
    # Altering the already retained bytes is corruption, not another valid builder rejection.
    source.write_bytes(b"Different invalid instructions.\n")
    with pytest.raises(MalformedEvidence, match="digest"):
        read_evidence(output)


@pytest.mark.parametrize("field", ["intent", "assessment"])
def test_incomplete_preparation_cannot_claim_command_authority(tmp_path: Path, field: str) -> None:
    output = archive(tmp_path, 1, 1)
    path = output / "result.json"
    document = json.loads(path.read_bytes())
    document["steps"][0][field] = {"fabricated": True}
    path.write_text(json.dumps(document))
    with pytest.raises(MalformedEvidence):
        read_evidence(output)
