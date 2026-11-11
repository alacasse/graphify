"""A repair edits its addressed member and preserves other physical destinations."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from tests.install_sandbox.component.host.native_support import LiteralInstaller, arrange
from tools.install_sandbox.container.installer import InstallerCommandResult, InstallerDriver
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.effect_case import SubjectContext, build_effect_cases
from tools.install_sandbox.contracts.effects import Destination, EffectSpec, JsonHooksEffect
from tools.install_sandbox.host.effect_reader import EffectSpecReader
from tools.install_sandbox.host.result_reader import read_evidence


@pytest.mark.parametrize(
    "operation", ["missing-json-hook", "altered-json-hook", "duplicate-json-hook"]
)
@pytest.mark.parametrize("neighbor_changed", [False, True])
def test_second_effect_second_member_binds_through_mutation_and_replay(
    tmp_path: Path, operation: str, neighbor_changed: bool
) -> None:
    subject, spec_path, context_path = arrange(tmp_path, skill=False, markdown=False)
    original = EffectSpecReader().read(spec_path).scopes[0].effects
    assert original is not None
    first = original.effects[0]
    assert isinstance(first, JsonHooksEffect)
    second = replace(
        first,
        effect_id="secondary",
        destination=Destination("project", ".secondary/.synthetic/config.json"),
    )
    context = SubjectContext.from_data(json.loads(context_path.read_text()))
    case = next(
        case
        for case in build_effect_cases(EffectSpec((first, second)), context).cases
        if case.key.operation == operation
        and case.key.effect_id == "secondary"
        and case.key.member == "PreToolUse-read"
    )
    case.write(tmp_path / "case.json")
    installer = LiteralInstaller(skill=False, markdown=False)
    calls = 0

    def execute(
        args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        nonlocal calls
        calls += 1
        installer.execute(args, project, environment, timeout)
        installer.execute(args, project / ".secondary", environment, timeout)
        if calls == 2 and neighbor_changed:
            neighbor = project / ".synthetic/config.json"
            # Semantically equivalent bytes still violate physical preservation.
            neighbor.write_bytes(neighbor.read_bytes() + b" ")
        return InstallerCommandResult(args, str(project), "completed", 0, None)

    proof = tmp_path / "proof"
    result = InstallTestRunner(InstallerDriver(execute)).run_case(
        reference_sources=subject,
        prepared_executable=tmp_path / "executable",
        case_file=tmp_path / "case.json",
        work_directory=tmp_path / "work",
        output_directory=proof,
    )
    assert calls == 2
    assert result.status == ("failed" if neighbor_changed else "passed")
    mutation = json.loads((proof / "intermediate/operation.json").read_text())
    assert mutation["target"] == case.key.to_data()
    assert mutation["destination"] == {
        "root": "project",
        "path": ".secondary/.synthetic/config.json",
    }
    assert read_evidence(proof) == result
    _assert_member_counts(proof, operation)
    _reject_wrong_mutation_target(proof)
    _reject_wrong_argv(proof)


def _assert_member_counts(proof: Path, operation: str) -> None:
    # The mutation removes/changes/copies read, even though search was declared first.
    prepared = json.loads(
        (proof / "intermediate/after/project/.secondary/.synthetic/config.json").read_text()
    )
    hooks = [hook for group in prepared["hooks"]["PreToolUse"] for hook in group["hooks"]]
    assert sum(hook.get("command") == "graphify hook-guard search" for hook in hooks) == 1
    assert sum(
        hook.get("command") == "graphify hook-guard read" and hook.get("timeout") == 10
        for hook in hooks
    ) == (2 if operation == "duplicate-json-hook" else 0)


def _reject_wrong_mutation_target(proof: Path) -> None:
    operation_path = proof / "intermediate/operation.json"
    original_operation = operation_path.read_text()
    for field, value in (
        ("effect_id", "json-hooks"),
        ("member", "PreToolUse-search"),
        ("scope", "user"),
    ):
        substituted = json.loads(original_operation)
        substituted["target"][field] = value
        operation_path.write_text(json.dumps(substituted))
        with pytest.raises(ValueError):
            read_evidence(proof)
    operation_path.write_text(original_operation)


def _reject_wrong_argv(proof: Path) -> None:
    original = (proof / "result.json").read_text()
    for index in (0, 1):
        stored = json.loads(original)
        stored["steps"][index]["facts"]["command"]["args"].append("--substituted")
        (proof / "result.json").write_text(json.dumps(stored))
        with pytest.raises(ValueError):
            read_evidence(proof)
        (proof / "result.json").write_text(original)
