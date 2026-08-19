from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from scripts.install_sandbox_quality_docker import (
    LegacyFindingException,
    ProductFinding,
    approved_advisory_findings,
)
from scripts.install_sandbox_quality_evidence import (
    FailedEvidence,
    PassedEvidence,
    TargetedDockerSelection,
    consume_terminal_evidence,
)
from scripts.install_sandbox_quality_phase import GatePhase, policy_for_phase


def _command() -> dict[str, object]:
    return {
        "argv": ["graphify", "install", "fixture"],
        "cwd": "/tmp/project",
        "exit_code": 0,
        "timed_out": False,
    }


def _write_target_spec(path: Path) -> None:
    path.write_text(
        """scopes:
  user:
    effects:
      - root: home
        path: .fixture
  project:
    effects:
      - root: project
        path: .fixture
""",
        encoding="utf-8",
    )


def _scenario(
    scope: str,
    *,
    command_exit: int = 0,
    phase_status: str = "PASS",
) -> dict[str, object]:
    name = f"fixture-{scope}"
    command = _command()
    command["exit_code"] = command_exit
    return {
        "scenario": name,
        "target": "fixture",
        "scope": scope,
        "status": "PASS",
        "limitations": [],
        "artifact_dir": f"scenarios/{name}",
        "phases": [
            {
                "name": "install",
                "status": phase_status,
                "command": command,
                "validations": [],
            }
        ],
    }


def _write_bound_results(
    bundle: Path,
    scenarios: list[dict[str, object]],
    purge: dict[str, object],
) -> None:
    for scenario in scenarios:
        artifact_dir = scenario["artifact_dir"]
        if artifact_dir is None:
            continue
        artifact = bundle / str(artifact_dir)
        artifact.mkdir(parents=True)
        (artifact / "result.json").write_text(json.dumps(scenario), encoding="utf-8")
    purge_dir = bundle / "purge"
    purge_dir.mkdir()
    (purge_dir / "result.json").write_text(json.dumps(purge), encoding="utf-8")


def _write_catalog(repository: Path, mode: str) -> list[str]:
    catalog = repository / "tools" / "install_sandbox" / "specs"
    catalog.mkdir(parents=True)
    _write_target_spec(catalog / "fixture.yaml")
    if mode == "catalog-omission":
        _write_target_spec(catalog / "omitted.yaml")
    if mode == "stem-order":
        _write_target_spec(catalog / "fixture-windows.yaml")
        return ["fixture", "fixture-windows"]
    return ["fixture"]


def _write_bundle(tmp_path: Path, mode: str = "valid") -> tuple[Path, Path]:
    repository = tmp_path / "repository"
    repository.mkdir()
    package_targets = _write_catalog(repository, mode)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    user_exit = 1 if mode == "failed-phase-command" else 0
    user_phase = "NOT_APPLICABLE" if mode == "na-command" else "PASS"
    scenarios = [
        _scenario("user", command_exit=user_exit, phase_status=user_phase),
        _scenario("project"),
    ]
    if mode == "unsupported-supported-scope":
        scenarios[0] = {
            "scenario": "fixture-user",
            "target": "fixture",
            "scope": "user",
            "status": "UNSUPPORTED",
            "limitations": ["fixture limitation"],
            "artifact_dir": None,
            "phases": [],
        }
    purge_command = _command()
    if mode == "timed-out-purge":
        purge_command["timed_out"] = True
    purge = {
        "status": "PASS",
        "command": purge_command,
        "graphify_out_removed": True,
        "unrelated_content_preserved": True,
    }
    if mode == "partial-coverage":
        scenarios.pop()

    selection = TargetedDockerSelection("fixture").evidence_value()
    run_record = {
        "schema_version": 1,
        "run_id": "fixture-run",
        "managed": False,
        "started_at": "2026-08-18T00:00:00Z",
        "updated_at": "2026-08-18T00:01:00Z",
        "finished_at": "2026-08-18T00:01:00Z",
        "repository": str(repository),
        "output": str(bundle),
        "selection": selection,
        "phase": "container_run",
        "state": "passed",
        "exit_code": 0,
    }
    if mode == "missing-run-field":
        run_record.pop("phase")
    summary = {"PASS": len(scenarios)}
    if mode == "unsupported-supported-scope":
        summary = {"PASS": 1, "UNSUPPORTED": 1}
    manifest = {
        "harness": "graphify-install-sandbox-v8",
        "generated_at": "2026-08-18T00:00:00+00:00",
        "repo": "/tmp/repo",
        "selection": selection,
        "package": {"public_install_targets": package_targets},
        "summary": summary,
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "purge": purge,
    }
    (bundle / "run.json").write_text(json.dumps(run_record), encoding="utf-8")
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    _write_bound_results(bundle, scenarios, purge)
    return repository, bundle


def test_evidence_consumer_returns_a_typed_passed_variant(tmp_path: Path) -> None:
    repository, bundle = _write_bundle(tmp_path)

    evidence = consume_terminal_evidence(
        repository,
        bundle,
        TargetedDockerSelection("fixture"),
        0,
    )

    assert isinstance(evidence, PassedEvidence)


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("partial-coverage", "requested catalog scope"),
        ("catalog-omission", "disagree with the catalog authority"),
        ("missing-run-field", "Run Record phase is missing"),
        ("failed-phase-command", "contains a failed command"),
        ("na-command", "not-applicable phase"),
        ("unsupported-supported-scope", "disagrees with YAML scope support"),
        ("timed-out-purge", "passing purge contains failed observations"),
    ],
)
def test_evidence_consumer_rejects_incoherent_bundle_rules_directly(
    tmp_path: Path,
    mode: str,
    message: str,
) -> None:
    repository, bundle = _write_bundle(tmp_path, mode)

    with pytest.raises(ValueError, match=message):
        consume_terminal_evidence(
            repository,
            bundle,
            TargetedDockerSelection("fixture"),
            0,
        )


def test_boundary_variants_reject_invalid_states() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        TargetedDockerSelection(" ")
    with pytest.raises(ValueError, match="at least one"):
        FailedEvidence(())


def test_catalog_comparison_uses_canonical_stem_order(tmp_path: Path) -> None:
    repository, bundle = _write_bundle(tmp_path, "stem-order")

    evidence = consume_terminal_evidence(
        repository,
        bundle,
        TargetedDockerSelection("fixture"),
        0,
    )

    assert isinstance(evidence, PassedEvidence)


def test_advisory_policy_requires_exact_current_construction_approval() -> None:
    finding = ProductFinding("scenario:fixture", "a" * 64)
    exception = LegacyFindingException(
        finding=finding,
        approved_in="decision-123",
        expires_on=date(2026, 8, 31),
    )

    assert approved_advisory_findings(
        policy_for_phase(GatePhase.REPLACEMENT_CONSTRUCTION),
        (finding,),
        (exception,),
        date(2026, 8, 18),
    ) == (finding,)
    assert not approved_advisory_findings(
        policy_for_phase(GatePhase.GATE_INSTALLATION),
        (finding,),
        (exception,),
        date(2026, 8, 18),
    )
    assert not approved_advisory_findings(
        policy_for_phase(GatePhase.REPLACEMENT_CONSTRUCTION),
        (finding,),
        (exception,),
        date(2026, 9, 1),
    )
    assert not approved_advisory_findings(
        policy_for_phase(GatePhase.REPLACEMENT_CONSTRUCTION),
        (ProductFinding("scenario:fixture", "b" * 64),),
        (exception,),
        date(2026, 8, 18),
    )
