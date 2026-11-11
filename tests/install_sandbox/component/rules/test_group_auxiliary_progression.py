"""A successful process cannot advance after corrupting JSON auxiliary artifacts."""

import json
from pathlib import Path

import pytest

from tools.install_sandbox.container.installer import InstallerCommandResult, InstallerDriver
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.effect_case import EffectRules, StepInvocation, SubjectContext
from tools.install_sandbox.contracts.effects import Destination, EffectSpec, JsonHooksEffect
from tools.install_sandbox.contracts.group_case import build_group_case
from tools.install_sandbox.contracts.spec import HookExpectation


@pytest.mark.parametrize("fault", ["backup", "registry"])
def test_bad_second_prepare_stops_third_command(tmp_path: Path, fault: str) -> None:
    participants = ("first:project", "second:project", "third:project")
    hook = HookExpectation("run", "SessionStart", "*", {"type": "command", "command": "managed"})
    specs = {
        p: EffectSpec(
            (JsonHooksEffect(Destination("project", p.split(":")[0] + ".json"), (hook,)),)
        )
        for p in participants
    }
    context = SubjectContext(
        "fixture",
        (),
        "METADATA",
        EffectRules(10, "persistent", ".graphify-bak", ".bak", False),
        invocations={p: ("install", p) for p in participants},
        removals=(StepInvocation("uninstall", participants, ("uninstall", *participants)),),
    )
    case = build_group_case(specs, participants, participants, context, "first")
    calls: list[list[str]] = []

    def execute(
        args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        calls.append(args[1:])
        target = project / (args[-1].split(":")[0] + ".json")
        backup = Path(str(target) + ".graphify-bak")
        backup.write_bytes(target.read_bytes())
        document = json.loads(target.read_text())
        document.setdefault("hooks", {}).setdefault("SessionStart", []).append(
            {"matcher": "*", "hooks": [hook.content]}
        )
        target.write_text(json.dumps(document))
        if len(calls) == 2:
            if fault == "backup":
                backup.write_text("corrupted")
            else:
                Path(str(target) + ".graphify-state.json").write_text("{}")
        return InstallerCommandResult(
            args, str(project), "completed", 0, None, duration_seconds=0.001
        )

    source = tmp_path / "subject"
    source.mkdir()
    (source / "METADATA").write_text("Version: 1.0\n")
    case_file = tmp_path / "case.json"
    case.write(case_file)
    result = InstallTestRunner(InstallerDriver(execute)).run_case(
        reference_sources=source,
        prepared_executable=tmp_path / "literal",
        case_file=case_file,
        work_directory=tmp_path / "work",
        output_directory=tmp_path / "proof",
    )
    assert calls == [["install", "first:project"], ["install", "second:project"]]
    assert result.status == "failed"
    assert result.steps[1].command is not None and result.steps[1].command["exit_code"] == 0
    assert result.steps[2].command is None
