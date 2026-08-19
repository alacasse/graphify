"""Validate Diagnostic Manifest structure, bindings, and raw outcomes."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

LEGACY_MANIFEST_IDENTITY = "graphify-install-sandbox-v8"


class ScenarioOutcome(StrEnum):
    PASS = "PASS"
    FINDING = "FAIL"
    UNSUPPORTED = "UNSUPPORTED"


class PhaseOutcome(StrEnum):
    PASS = "PASS"
    FINDING = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class PurgeOutcome(StrEnum):
    PASS = "PASS"
    FINDING = "FAIL"


@dataclass(frozen=True)
class ProductFinding:
    identifier: str
    evidence_sha256: str


@dataclass(frozen=True)
class ScenarioIdentity:
    name: str
    target: str
    scope: str


@dataclass(frozen=True)
class ScenarioExpectation:
    identity: ScenarioIdentity
    unsupported: bool


@dataclass(frozen=True)
class _ScenarioEvidence:
    identity: ScenarioIdentity
    outcome: ScenarioOutcome
    findings: tuple[ProductFinding, ...]


@dataclass(frozen=True)
class _ScenarioHeader:
    identity: ScenarioIdentity
    outcome: ScenarioOutcome


def load_artifact_object(path: Path, *, kind: str) -> Mapping[str, object]:
    """Read a non-empty regular JSON object without following a final symlink."""

    try:
        details = path.lstat()
        if path.is_symlink() or not path.is_file() or details.st_size == 0:
            raise ValueError("is not a non-empty regular file")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"cannot read {kind} {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{kind} root is not an object")
    return value


def _required_mapping(value: object, *, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"Diagnostic Manifest {name} is not an object")
    return value


def _required_list(value: object, *, name: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"Diagnostic Manifest {name} is not an array")
    return value


def _evidence_digest(value: Mapping[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _bound_result(
    bundle: Path,
    relative_text: str,
    expected: Mapping[str, object],
    *,
    kind: str,
) -> None:
    relative = PurePosixPath(relative_text)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe {kind} evidence path: {relative_text!r}")
    actual = load_artifact_object(bundle.joinpath(*relative.parts), kind=kind)
    if actual != expected:
        raise ValueError(f"{kind} evidence disagrees with the Diagnostic Manifest")


def _validated_command(value: object, *, name: str, required: bool) -> bool | None:
    if value is None and not required:
        return None
    command = _required_mapping(value, name=f"{name} command")
    argv = _required_list(command.get("argv"), name=f"{name} command argv")
    if not argv or not all(isinstance(argument, str) for argument in argv):
        raise ValueError(f"Diagnostic Manifest {name} command argv is invalid")
    if not isinstance(command.get("cwd"), str):
        raise ValueError(f"Diagnostic Manifest {name} command cwd is invalid")
    if type(command.get("exit_code")) is not int:
        raise ValueError(f"Diagnostic Manifest {name} command exit is invalid")
    if type(command.get("timed_out")) is not bool:
        raise ValueError(f"Diagnostic Manifest {name} command timeout is invalid")
    return command["exit_code"] == 0 and command["timed_out"] is False


def _validation_findings(
    scenario_name: str,
    phase_name: str,
    raw_validations: object,
) -> tuple[ProductFinding, ...]:
    validations = _required_list(raw_validations, name="phase validations")
    findings: list[ProductFinding] = []
    for index, value in enumerate(validations):
        validation = _required_mapping(value, name="phase validation")
        if not isinstance(validation.get("check"), str):
            raise ValueError("Diagnostic Manifest validation check is not a string")
        if type(validation.get("passed")) is not bool:
            raise ValueError("Diagnostic Manifest validation result is not a boolean")
        if not isinstance(validation.get("detail"), str):
            raise ValueError("Diagnostic Manifest validation detail is not a string")
        if validation["passed"] is False:
            identifier = f"scenario:{scenario_name}:phase:{phase_name}:validation:{index}"
            findings.append(ProductFinding(identifier, _evidence_digest(validation)))
    return tuple(findings)


def _validate_phase_coherence(
    scenario_name: str,
    phase_name: str,
    outcome: PhaseOutcome,
    command_passed: bool | None,
    findings: list[ProductFinding],
) -> None:
    if outcome is PhaseOutcome.NOT_APPLICABLE and command_passed is not None:
        raise ValueError(f"not-applicable phase {scenario_name}/{phase_name} contains a command")
    if outcome is PhaseOutcome.PASS and findings:
        raise ValueError(f"passing phase {scenario_name}/{phase_name} contains failed validations")
    if outcome is PhaseOutcome.PASS and command_passed is not True:
        raise ValueError(f"passing phase {scenario_name}/{phase_name} contains a failed command")


def _phase_findings(scenario_name: str, raw_phases: object) -> tuple[ProductFinding, ...]:
    phases = _required_list(raw_phases, name="scenario phases")
    names: set[str] = set()
    findings: list[ProductFinding] = []
    for value in phases:
        phase = _required_mapping(value, name="scenario phase")
        name = phase.get("name")
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("Diagnostic Manifest phase names must be unique non-empty strings")
        names.add(name)
        raw_outcome = phase.get("status")
        if not isinstance(raw_outcome, str):
            raise ValueError(f"unsupported phase outcome for {scenario_name}/{name}")
        try:
            outcome = PhaseOutcome(raw_outcome)
        except ValueError as error:
            raise ValueError(f"unsupported phase outcome for {scenario_name}/{name}") from error
        phase_findings = list(_validation_findings(scenario_name, name, phase.get("validations")))
        command_passed = _validated_command(
            phase.get("command"),
            name=f"phase {scenario_name}/{name}",
            required=outcome is not PhaseOutcome.NOT_APPLICABLE,
        )
        if outcome is PhaseOutcome.FINDING and not phase_findings:
            phase_findings.append(
                ProductFinding(f"scenario:{scenario_name}:phase:{name}", _evidence_digest(phase))
            )
        _validate_phase_coherence(
            scenario_name,
            name,
            outcome,
            command_passed,
            phase_findings,
        )
        findings.extend(phase_findings)
    return tuple(findings)


def _validated_scenario_header(scenario: Mapping[str, object]) -> _ScenarioHeader:
    name = scenario.get("scenario")
    if not isinstance(name, str) or not name:
        raise ValueError("Diagnostic Manifest scenario name is not a non-empty string")
    target = scenario.get("target")
    if not isinstance(target, str) or not target:
        raise ValueError(f"Diagnostic Manifest scenario {name} target is not a string")
    scope = scenario.get("scope")
    if scope not in {"user", "project"}:
        raise ValueError(f"Diagnostic Manifest scenario {name} scope is unsupported")
    assert isinstance(scope, str)
    limitations = _required_list(scenario.get("limitations"), name="scenario limitations")
    if not all(isinstance(limitation, str) for limitation in limitations):
        raise ValueError(f"Diagnostic Manifest scenario {name} limitations are invalid")
    raw_outcome = scenario.get("status")
    if not isinstance(raw_outcome, str):
        raise ValueError(f"unsupported scenario outcome for {name}")
    try:
        outcome = ScenarioOutcome(raw_outcome)
    except ValueError as error:
        raise ValueError(f"unsupported scenario outcome for {name}") from error
    return _ScenarioHeader(ScenarioIdentity(name, target, scope), outcome)


def _scenario_evidence(bundle: Path, value: object) -> _ScenarioEvidence:
    scenario = _required_mapping(value, name="scenario")
    header = _validated_scenario_header(scenario)
    identity = header.identity
    artifact_dir = scenario.get("artifact_dir")
    if header.outcome is ScenarioOutcome.UNSUPPORTED:
        if artifact_dir is not None or scenario.get("phases") != []:
            raise ValueError(f"unsupported scenario {identity.name} contains materialized evidence")
        return _ScenarioEvidence(identity, header.outcome, ())
    findings = _phase_findings(identity.name, scenario.get("phases"))
    if artifact_dir != f"scenarios/{identity.name}":
        raise ValueError(
            f"Diagnostic Manifest scenario {identity.name} has an invalid evidence path"
        )
    _bound_result(bundle, f"{artifact_dir}/result.json", scenario, kind="scenario result")
    if header.outcome is ScenarioOutcome.PASS and findings:
        raise ValueError(f"passing scenario {identity.name} contains Product Findings")
    if header.outcome is ScenarioOutcome.FINDING and not findings:
        findings = (ProductFinding(f"scenario:{identity.name}", _evidence_digest(scenario)),)
    return _ScenarioEvidence(identity, header.outcome, findings)


def _validated_scenarios(
    bundle: Path,
    manifest: Mapping[str, object],
    expectations: frozenset[ScenarioExpectation],
) -> tuple[ProductFinding, ...]:
    raw_scenarios = _required_list(manifest.get("scenarios"), name="scenarios")
    if type(manifest.get("scenario_count")) is not int:
        raise ValueError("Diagnostic Manifest scenario_count is not an integer")
    if manifest["scenario_count"] != len(raw_scenarios):
        raise ValueError("Diagnostic Manifest scenario_count disagrees with scenarios")
    scenarios = tuple(_scenario_evidence(bundle, raw) for raw in raw_scenarios)
    actual_identities = {scenario.identity for scenario in scenarios}
    expected_by_identity = {expectation.identity: expectation for expectation in expectations}
    if actual_identities != set(expected_by_identity) or len(actual_identities) != len(scenarios):
        raise ValueError("Diagnostic Manifest scenarios do not cover the requested catalog scope")
    for scenario in scenarios:
        expected = expected_by_identity[scenario.identity]
        unsupported = scenario.outcome is ScenarioOutcome.UNSUPPORTED
        if unsupported != expected.unsupported:
            raise ValueError(
                f"Diagnostic Manifest scenario {scenario.identity.name} "
                "disagrees with YAML scope support"
            )
    summary = _required_mapping(manifest.get("summary"), name="summary")
    expected_summary = Counter(scenario.outcome.value for scenario in scenarios)
    if summary != dict(sorted(expected_summary.items())):
        raise ValueError("Diagnostic Manifest summary disagrees with scenario outcomes")
    return tuple(finding for scenario in scenarios for finding in scenario.findings)


def _validated_purge(bundle: Path, manifest: Mapping[str, object]) -> ProductFinding | None:
    purge = _required_mapping(manifest.get("purge"), name="purge")
    raw_outcome = purge.get("status")
    if not isinstance(raw_outcome, str):
        raise ValueError("Diagnostic Manifest purge outcome is unsupported")
    try:
        outcome = PurgeOutcome(raw_outcome)
    except ValueError as error:
        raise ValueError("Diagnostic Manifest purge outcome is unsupported") from error
    command_passed = _validated_command(purge.get("command"), name="purge", required=True)
    for field in ("graphify_out_removed", "unrelated_content_preserved"):
        if type(purge.get(field)) is not bool:
            raise ValueError(f"Diagnostic Manifest purge {field} is invalid")
    _bound_result(bundle, "purge/result.json", purge, kind="purge result")
    if outcome is PurgeOutcome.PASS and not (
        command_passed is True
        and purge["graphify_out_removed"]
        and purge["unrelated_content_preserved"]
    ):
        raise ValueError("passing purge contains failed observations")
    return (
        ProductFinding("purge", _evidence_digest(purge))
        if outcome is PurgeOutcome.FINDING
        else None
    )


def validated_package_targets(manifest: Mapping[str, object]) -> tuple[str, ...]:
    package = _required_mapping(manifest.get("package"), name="package")
    raw_targets = _required_list(
        package.get("public_install_targets"),
        name="package public_install_targets",
    )
    if not raw_targets:
        raise ValueError("Diagnostic Manifest package target catalog is invalid")
    targets: list[str] = []
    for target in raw_targets:
        if not isinstance(target, str) or not target:
            raise ValueError("Diagnostic Manifest package target catalog is invalid")
        targets.append(target)
    if len(targets) != len(set(targets)):
        raise ValueError("Diagnostic Manifest package target catalog contains duplicates")
    return tuple(targets)


def validate_manifest_findings(
    bundle: Path,
    manifest: Mapping[str, object],
    expected_selection: Mapping[str, object],
    expectations: frozenset[ScenarioExpectation],
) -> tuple[ProductFinding, ...]:
    """Validate a manifest and return its exact Product Finding evidence keys."""

    if manifest.get("harness") != LEGACY_MANIFEST_IDENTITY:
        raise ValueError("Diagnostic Manifest identity is missing or unsupported")
    if manifest.get("selection") != expected_selection:
        raise ValueError("Run Record and Diagnostic Manifest selections disagree")
    if not isinstance(manifest.get("generated_at"), str):
        raise ValueError("Diagnostic Manifest generated_at is missing")
    if not isinstance(manifest.get("repo"), str):
        raise ValueError("Diagnostic Manifest repository is missing")
    validated_package_targets(manifest)
    scenario_findings = _validated_scenarios(bundle, manifest, expectations)
    purge_finding = _validated_purge(bundle, manifest)
    return scenario_findings + (() if purge_finding is None else (purge_finding,))
