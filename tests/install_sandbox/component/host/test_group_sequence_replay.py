"""Retained ordered authority survives relocation and rejects fabricated continuations."""

import json
import shutil
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.install_sandbox.component.host.test_group_definition import composition
from tools.install_sandbox.container.evidence_writer import TestResultWriter as ResultWriter
from tools.install_sandbox.container.installer import InstallerCommandResult, InstallerDriver
from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.group_case import build_group_case
from tools.install_sandbox.contracts.results import CommandEvidence
from tools.install_sandbox.host.result_reader import MalformedEvidence, read_evidence


class LiteralCommands:
    def __init__(self, fail_second: bool = False, crash: str | None = None) -> None:
        self.calls: list[list[str]] = []
        self.side_effects = 0
        self.fail_second = fail_second
        self.crash = crash

    def execute(
        self, args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        self.calls.append(args[1:])
        if self.crash == "before" and args[1] == "uninstall":
            raise KeyboardInterrupt("before launch")
        self.side_effects += 1
        roots = {"project": project, "user": Path(environment["HOME"])}
        participants = args[2:]
        for participant in participants:
            tool, scope = participant.split(":")
            target = roots[scope] / (tool + ".txt")
            if args[1] == "install":
                target.write_text("managed")
            else:
                target.unlink()
        failed = self.fail_second and len(self.calls) == 2
        return InstallerCommandResult(
            args, str(project), "completed", 1 if failed else 0, None, duration_seconds=0.001
        )


def run_proof(
    tmp_path: Path, *, fail_second: bool = False, crash: str | None = None
) -> tuple[Path, LiteralCommands]:
    specs, prepare, remove, context = composition()
    case = build_group_case(specs, prepare, remove, context, "cedar")
    source = tmp_path / "subject"
    source.mkdir()
    (source / "METADATA").write_text("Version: 1.0\n")
    case_file = tmp_path / "input.json"
    case.write(case_file)
    output = tmp_path / "original-proof"
    commands = LiteralCommands(fail_second, crash)
    runner = InstallTestRunner(InstallerDriver(commands.execute))
    arguments = dict(
        reference_sources=source,
        prepared_executable=tmp_path / "literal",
        case_file=case_file,
        work_directory=tmp_path / "work",
        output_directory=output,
    )
    original_write = ResultWriter.write_command

    def write_command(
        writer: ResultWriter, command: InstallerCommandResult, *, step_index: int
    ) -> CommandEvidence:
        if command.args[1] == "uninstall":
            raise KeyboardInterrupt("returned before receipt")
        return original_write(writer, command, step_index=step_index)

    boundary = (
        patch.object(ResultWriter, "write_command", write_command)
        if crash == "after"
        else nullcontext()
    )
    with boundary:
        if crash:
            with pytest.raises(KeyboardInterrupt):
                runner.run_case(**arguments)
        else:
            runner.run_case(**arguments)
    moved = tmp_path / "moved-proof"
    output.rename(moved)
    shutil.rmtree(source)
    shutil.rmtree(tmp_path / "work")
    return moved, commands


def test_failed_second_prepare_stops_following_commands_and_replays(tmp_path: Path) -> None:
    output, commands = run_proof(tmp_path, fail_second=True)
    assert commands.calls == [["install", "cedar:user"], ["install", "cedar:project"]]
    result = read_evidence(output)
    assert result.status == "failed"
    assert result.steps[2].command is None and result.steps[3].command is None


@pytest.mark.parametrize(
    "fault", ["continuation", "order", "intent-argv", "command-argv", "assessment"]
)
def test_group_replay_rejects_fabricated_step_authority(tmp_path: Path, fault: str) -> None:
    output, _ = run_proof(tmp_path, fail_second=fault == "continuation")
    assert read_evidence(output).status in {"passed", "failed"}
    result_path = output / "result.json"
    document = json.loads(result_path.read_text())
    steps = document["steps"]
    if fault == "continuation":
        steps[2] = steps[0]
    elif fault == "order":
        steps[0], steps[1] = steps[1], steps[0]
    elif fault == "intent-argv":
        steps[1]["intent"]["argv"] = ["install", "birch:project"]
    elif fault == "command-argv":
        steps[1]["facts"]["command"]["args"][-1] = "birch:project"
    else:
        steps[-1]["assessment"] = {"forged": True}
    result_path.write_text(json.dumps(document))
    with pytest.raises(MalformedEvidence):
        read_evidence(output)


def test_crash_before_command_and_after_return_have_same_durable_intent(tmp_path: Path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    first, first_commands = run_proof(before, crash="before")
    second, second_commands = run_proof(after, crash="after")
    left, right = read_evidence(first), read_evidence(second)
    assert left.status == right.status == "incomplete"
    assert left.steps[3].intent == right.steps[3].intent
    assert left.steps[3].command is right.steps[3].command is None
    assert left.steps[3].intent is not None
    assert left.steps[3].intent["participants"] == ["birch:project", "cedar:project"]

    assert left.steps[3].assessment is right.steps[3].assessment is None
    assert first_commands.side_effects == 3 and second_commands.side_effects == 4
    assert left.steps[2].assessment == right.steps[2].assessment
    assert json.loads((first / "steps/2/after.json").read_text()) == json.loads(
        (second / "steps/2/after.json").read_text()
    )


@pytest.mark.parametrize("member", [None, [], 3, {"participant": [], "effects": {}}])
def test_malformed_group_participant_archive_is_rejected(tmp_path: Path, member: object) -> None:
    output, _ = run_proof(tmp_path)
    case_file = output / "case.json"
    document = json.loads(case_file.read_text())
    document["participants"] = [member]
    case_file.write_text(json.dumps(document))
    with pytest.raises(MalformedEvidence):
        read_evidence(output)


@pytest.mark.parametrize("key", [None, [], 3])
def test_malformed_case_key_archive_is_rejected(tmp_path: Path, key: object) -> None:
    output, _ = run_proof(tmp_path)
    case_file = output / "case.json"
    document = json.loads(case_file.read_text())
    document["key"] = key
    case_file.write_text(json.dumps(document))
    with pytest.raises(MalformedEvidence):
        read_evidence(output)
