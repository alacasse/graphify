"""Transport-only validation tests; these documents do not prove installation."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import cast

import pytest

from tools.install_sandbox.case import InstallTestCase
from tools.install_sandbox.result_reader import read_result, safe_evidence_path
from tools.install_sandbox.results import InstallTestResult, VerificationResult

_CASE = Path(__file__).with_name("fixtures") / "first-install.json"


def _case() -> InstallTestCase:
    return InstallTestCase.from_json(_CASE.read_text(encoding="utf-8"))


def _document() -> dict[str, object]:
    case = _case()
    return asdict(
        InstallTestResult(
            {"name": case.name, "target": case.target, "scope": case.scope},
            {"ready": True, "reason": None, "log": "preparation.log", "source": "campaign"},
            [
                {
                    "operation": "install",
                    "skip_reason": None,
                    "command": {
                        "args": [
                            "/prepared/graphify",
                            "install",
                            "--platform",
                            case.target,
                            "--project",
                        ],
                        "cwd": "/work/project",
                        "state": "completed",
                        "exit_code": 0,
                        "reason": None,
                        "stdout_file": "steps/0/stdout.txt",
                        "stderr_file": "steps/0/stderr.txt",
                    },
                    "verification": VerificationResult(),
                    "observations": {
                        "before": "steps/0/before.json",
                        "after": "steps/0/after.json",
                    },
                }
            ],
            "passed",
            {"journal": "journal.log", "expected_contents": "expected/"},
        )
    )


def _write(output: Path, document: object) -> None:
    (output / "result.json").write_text(json.dumps(document), encoding="utf-8")


def _object(value: object) -> dict[str, object]:
    return cast(dict[str, object], value)


def _step(document: dict[str, object]) -> dict[str, object]:
    return _object(cast(list[object], document["steps"])[0])


def test_valid_passed_document_round_trips_without_recomputing_verification(tmp_path: Path) -> None:
    document = _document()
    _write(tmp_path, document)
    result = read_result(tmp_path, _case())
    assert asdict(result) == document
    assert isinstance(result.steps[0]["verification"], VerificationResult)
    assert list(tmp_path.iterdir()) == [tmp_path / "result.json"]


@pytest.mark.parametrize("status", ["failed", "incomplete"])
def test_diagnostics_are_reconstructed_and_retained(tmp_path: Path, status: str) -> None:
    document = _document()
    document["status"] = status
    verification = _object(_step(document)["verification"])
    mismatch = {
        "observed": "absent",
        "expected": "present",
        "path": "skill.md",
        "root": "project",
        "type": "missing_file",
    }
    verification["mismatches"] = [mismatch]
    if status == "incomplete":
        verification["complete"] = False
        verification["obstacles"] = [
            {
                "operation": "read_file",
                "root": "project",
                "path": "other.md",
                "reason": "Permission denied",
            }
        ]
    _write(tmp_path, document)
    result = read_result(tmp_path, _case())
    assert result.status == status
    assert asdict(result) == document
    restored = result.steps[0]["verification"]
    assert restored is not None
    assert restored.mismatches[0].observed == "absent"


def test_not_run_preserves_preparation_diagnostic(tmp_path: Path) -> None:
    document = _document()
    document["status"] = "not_run"
    document["preparation"] = {
        "ready": False,
        "reason": "Initial witness failed",
        "log": "preparation.log",
        "source": "campaign",
    }
    document["steps"] = [
        {
            "operation": "install",
            "skip_reason": "Initial witness failed",
            "command": None,
            "verification": None,
            "observations": None,
        }
    ]
    _write(tmp_path, document)
    assert asdict(read_result(tmp_path, _case())) == document


@pytest.mark.parametrize("payload", [b"{", b"null", b"[]", b"{}", b"\xff"])
def test_rejects_malformed_transport(tmp_path: Path, payload: bytes) -> None:
    (tmp_path / "result.json").write_bytes(payload)
    with pytest.raises(ValueError):
        read_result(tmp_path, _case())


@pytest.mark.parametrize("key", ["case", "preparation", "steps", "status", "evidence"])
def test_rejects_missing_required_fields(tmp_path: Path, key: str) -> None:
    document = _document()
    del document[key]
    _write(tmp_path, document)
    with pytest.raises(ValueError):
        read_result(tmp_path, _case())


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "success"),
        ("identity", "another-case"),
        ("ready", 1),
        ("exit_code", True),
        ("state", "unknown"),
        ("complete", "true"),
        ("mismatches", [None]),
        ("obstacles", [{"reason": "unknown"}]),
        ("stdout_file", "../outside"),
        ("observations", {}),
        ("operation", "uninstall"),
        ("command", None),
        ("skip_reason", "Skipped"),
    ],
)
def test_rejects_incompatible_nested_data(tmp_path: Path, field: str, value: object) -> None:
    document = _document()
    step = _step(document)
    locations = {
        "ready": _object(document["preparation"]),
        "exit_code": _object(step["command"]),
        "state": _object(step["command"]),
        "stdout_file": _object(step["command"]),
        "complete": _object(step["verification"]),
        "mismatches": _object(step["verification"]),
        "obstacles": _object(step["verification"]),
    }
    if field == "identity":
        _object(document["case"])["name"] = value
    elif field == "status":
        document[field] = value
    else:
        locations.get(field, step)[field] = value
    _write(tmp_path, document)
    with pytest.raises(ValueError):
        read_result(tmp_path, _case())


@pytest.mark.parametrize(
    "field,value",
    [
        ("exit_code", 1),
        ("state", "interrupted"),
        ("complete", False),
        (
            "mismatches",
            [
                {
                    "type": "missing_file",
                    "root": "project",
                    "path": "skill",
                    "expected": "present",
                    "observed": "absent",
                }
            ],
        ),
    ],
)
def test_passed_cannot_contradict_recorded_facts(tmp_path: Path, field: str, value: object) -> None:
    document = _document()
    step = _step(document)
    group = "command" if field in ("exit_code", "state") else "verification"
    _object(step[group])[field] = value
    _write(tmp_path, document)
    with pytest.raises(ValueError):
        read_result(tmp_path, _case())


def test_missing_or_unreadable_result_preserves_io_failure(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_result(tmp_path, _case())
    (tmp_path / "result.json").mkdir()
    with pytest.raises(IsADirectoryError):
        read_result(tmp_path, _case())


@pytest.mark.parametrize(
    "relative", ["/etc/passwd", "../outside", "x/../../outside", ".", "", "x\\y"]
)
def test_evidence_references_must_be_confined(tmp_path: Path, relative: str) -> None:
    with pytest.raises(ValueError):
        safe_evidence_path(tmp_path, relative)


def test_symlinks_cannot_escape_for_results_or_evidence(tmp_path: Path) -> None:
    output = tmp_path / "results"
    output.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(_document()), encoding="utf-8")
    (output / "result.json").symlink_to(outside)
    with pytest.raises(ValueError):
        read_result(output, _case())
    (output / "linked").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        safe_evidence_path(output, "linked/outside.json")
    assert safe_evidence_path(output, "expected/") == output / "expected"


@pytest.mark.parametrize("duplicate", ["status", "exit_code", "target"])
def test_duplicate_json_keys_are_rejected(tmp_path: Path, duplicate: str) -> None:
    payload = json.dumps(_document())
    replacements = {
        "status": ('"status": "passed"', '"status": "failed", "status": "passed"'),
        "exit_code": ('"exit_code": 0', '"exit_code": 1, "exit_code": 0'),
        "target": (
            '"target": "sandbox-reference"',
            '"target": "other", "target": "sandbox-reference"',
        ),
    }
    old, new = replacements[duplicate]
    (tmp_path / "result.json").write_text(payload.replace(old, new), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate result field"):
        read_result(tmp_path, _case())


@pytest.mark.parametrize(
    "reference",
    [
        "journal",
        "expected_contents",
        "before",
        "after",
        "stdout_file",
        "stderr_file",
    ],
)
def test_passed_requires_all_announced_evidence_references(tmp_path: Path, reference: str) -> None:
    document = _document()
    step = _step(document)
    groups = {
        "journal": document["evidence"],
        "expected_contents": document["evidence"],
        "before": step["observations"],
        "after": step["observations"],
        "stdout_file": step["command"],
        "stderr_file": step["command"],
    }
    _object(groups[reference])[reference] = None
    _write(tmp_path, document)
    with pytest.raises(ValueError, match="requires all evidence references"):
        read_result(tmp_path, _case())


@pytest.mark.parametrize("expected,observed", [("", "content"), ("content", ""), (" ", "\n")])
def test_mismatch_content_strings_are_preserved_verbatim(
    tmp_path: Path,
    expected: str,
    observed: str,
) -> None:
    document = _document()
    document["status"] = "failed"
    _object(_step(document)["verification"])["mismatches"] = [
        {
            "type": "content_mismatch",
            "root": "project",
            "path": "skill.md",
            "expected": expected,
            "observed": observed,
        }
    ]
    _write(tmp_path, document)
    assert asdict(read_result(tmp_path, _case())) == document


def _reinstall_document() -> tuple[InstallTestCase, dict[str, object]]:
    from dataclasses import replace

    case = replace(_case(), name="reinstall", operations=["install", "install"])
    document = _document()
    _object(document["case"])["name"] = "reinstall"
    first = _step(document)
    second = json.loads(json.dumps(first).replace("steps/0/", "steps/1/"))
    document["steps"] = [first, second]
    return case, document


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("defect", ["exit_code", "complete", "missing_evidence", "wrong_step"])
def test_passed_reinstall_validates_every_step(tmp_path: Path, index: int, defect: str) -> None:
    case, document = _reinstall_document()
    step = cast(list[dict[str, object]], document["steps"])[index]
    if defect == "exit_code":
        _object(step["command"])["exit_code"] = 7
    elif defect == "complete":
        _object(step["verification"])["complete"] = False
    elif defect == "missing_evidence":
        _object(step["observations"])["after"] = None
    else:
        _object(step["command"])["stdout_file"] = f"steps/{1 - index}/stdout.txt"
    _write(tmp_path, document)
    with pytest.raises(ValueError):
        read_result(tmp_path, case)


@pytest.mark.parametrize(
    "defect",
    [
        "continued_after_failure",
        "unnecessary_skip",
        "partial_skip",
        "missing_step",
        "extra_step",
        "wrong_status",
    ],
)
def test_reinstall_rejects_inconsistent_dependency_history(tmp_path: Path, defect: str) -> None:
    case, document = _reinstall_document()
    steps = cast(list[dict[str, object]], document["steps"])
    if defect == "continued_after_failure":
        _object(steps[0]["command"])["exit_code"] = 7
        document["status"] = "failed"
    elif defect == "unnecessary_skip":
        steps[1].update(command=None, verification=None, observations=None, skip_reason="Skipped")
    elif defect == "partial_skip":
        _object(steps[0]["command"])["exit_code"] = 7
        steps[1].update(command=None, skip_reason="Previous failed")
        document["status"] = "failed"
    elif defect == "missing_step":
        steps.pop()
    elif defect == "extra_step":
        steps.append(steps[1])
    else:
        document["status"] = "incomplete"
    _write(tmp_path, document)
    with pytest.raises(ValueError):
        read_result(tmp_path, case)
