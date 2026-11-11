"""Group CLI acceptance against a literal package and an external fixture catalogue."""

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.install_sandbox.docker.test_lot_one_cli import arrange, cli, git

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/group_subject.py"
PREPARE = ["cedar:user", "cedar:project", "birch:project"]
REMOVE = ["birch:project", "cedar:project"]


def arrange_group(
    root: Path, fault: str, *, reverse: bool = False
) -> tuple[Path, Path, Path, Path, list[str]]:
    subject, spec, context = arrange(root, fault=fault)
    (subject / "birch/cli.py").write_text(FIXTURE.read_text())
    git(subject, "add", ".")
    git(
        subject,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.test",
        "commit",
        "-qm",
        "Install independent multi-participant product",
    )
    remove = list(reversed(REMOVE)) if reverse else REMOVE
    data = json.loads(context.read_text())
    data["revision"] = git(subject, "rev-parse", "HEAD")
    data["invocations"] = {participant: ["install", participant] for participant in PREPARE}
    data["removals"] = [
        {"action": "uninstall", "participants": remove, "argv": ["uninstall", *remove]}
    ]
    context.write_text(json.dumps(data))

    def effect(identifier: str, root: str, path: str, commands: list[str]) -> dict[str, Any]:
        return {
            "effect_id": identifier,
            "family": "json-hooks",
            "root": root,
            "path": path,
            "hooks": [
                {
                    "id": f"run-{index}",
                    "event": "SessionStart",
                    "matcher": "*",
                    "content": {"type": "command", "command": command, "timeout": 10},
                }
                for index, command in enumerate(commands)
            ],
        }

    spec.write_text(
        yaml.safe_dump(
            {
                "tool": "birch",
                "scopes": {
                    "project": [
                        effect(
                            "hooks", "PROJECT", ".birch/hooks.json", ["birch first", "birch second"]
                        )
                    ]
                },
            }
        )
    )
    (root / "cedar.yaml").write_text(
        yaml.safe_dump(
            {
                "tool": "cedar",
                "scopes": {
                    "user": [effect("user-hooks", "HOME", ".cedar/user.json", ["cedar run"])],
                    "project": [
                        effect("project-hooks", "PROJECT", ".cedar/project.json", ["cedar run"]),
                        {
                            "effect_id": "receipt",
                            "family": "file",
                            "root": "PROJECT",
                            "path": ".cedar/receipt.txt",
                            "content": "cedar installed\n",
                        },
                    ],
                },
            }
        )
    )
    request = root / "group.json"
    request.write_text(
        json.dumps(
            {
                "operation": "group-uninstall",
                "prepare": ([PREPARE[0], PREPARE[2], PREPARE[1]] if reverse else PREPARE),
                "remove": remove,
            }
        )
    )
    return subject, root / "cedar.yaml", context, request, remove


def evidence_lines(output: Path) -> list[dict[str, Any]]:
    with zipfile.ZipFile(output / "evidence.zip") as archive:
        stdout = [
            name
            for name in archive.namelist()
            if name.endswith("/stdout.txt") and "/steps/" in name
        ]
        lines: list[dict[str, Any]] = []
        for name in sorted(stdout):
            for line in archive.read(name).decode().splitlines():
                try:
                    lines.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return lines


def terminal_result(output: Path) -> dict[str, Any]:
    with zipfile.ZipFile(output / "evidence.zip") as archive:
        names = [
            name
            for name in archive.namelist()
            if "/cases/" in "/" + name and name.endswith("/result.json")
        ]
        assert len(names) == 1, names
        result = json.loads(archive.read(names[0]))
    return result


def terminal_assessment(output: Path) -> dict[str, Any]:
    return terminal_result(output)["steps"][-1]["assessment"]


def replay_without_subject(
    root: Path, subject: Path, spec: Path, context: Path, request: Path, output: Path
) -> dict[str, Any]:
    from tools.install_sandbox.host.campaign_replay import replay_campaign

    moved = root / "relocated.zip"
    shutil.copyfile(output / "evidence.zip", moved)
    shutil.rmtree(subject)
    for path in (spec, context, request, root / "birch.yaml"):
        path.unlink()
    return replay_campaign(moved)


@pytest.mark.parametrize("reverse", [False, True])
def test_group_exact_commands_order_disk_and_autonomous_replay(
    tmp_path: Path, reverse: bool
) -> None:
    subject, spec, context, request, remove = arrange_group(tmp_path, "none", reverse=reverse)
    output = tmp_path / "output"
    result = cli(subject, spec, context, output, "--request", str(request))
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((output / "campaign.json").read_text())
    assert report["status"] == "partial_passed" and report["passed"] is False
    lines = evidence_lines(output)
    assert [line["fixture_invocation"] for line in lines if "fixture_invocation" in line] == [
        *[
            ["install", participant]
            for participant in ([PREPARE[0], PREPARE[2], PREPARE[1]] if reverse else PREPARE)
        ],
        ["uninstall", *remove],
    ]
    observed = [line["disk_oracle"] for line in lines if "disk_oracle" in line]
    final = observed[-1]
    assert final["cedar:user"] == observed[0]["cedar:user"]
    assert observed[2 if reverse else 1]["cedar:receipt"] == "cedar installed\n"
    assert final["cedar:receipt"] is None
    for participant in PREPARE:
        assert final[participant + ":backup"] == observed[2][participant + ":backup"]
    for participant in REMOVE:
        document = json.loads(final[participant])
        members = [
            member
            for groups in document["hooks"].values()
            for group in groups
            for member in group["hooks"]
        ]
        assert any(
            member.get("command") == "python personal_graphify_audit.py" for member in members
        )
        assert not any(
            member.get("command", "").startswith(("cedar ", "birch ")) for member in members
        )
    assessment = terminal_assessment(output)
    assert assessment["cedar:user"]["preservation"] == "preserved"
    assert assessment["cedar:user"]["summary"] == "none_removed"
    for participant in REMOVE:
        assert assessment[participant]["summary"] == "all_removed"
        assert assessment[participant]["preservation"] == "preserved"
    replay = replay_without_subject(tmp_path, subject, spec, context, request, output)
    assert replay["status"] == report["status"]
    assert replay["cases"][0]["result"]["test"] == report["cases"][0]["result"]["test"]


@pytest.mark.parametrize(
    "fault", ["wrong-root", "missing-home", "wrong-backup", "forbidden-registry"]
)
def test_group_second_prepare_failure_prevents_dependents(tmp_path: Path, fault: str) -> None:
    subject, spec, context, request, _ = arrange_group(tmp_path, fault)
    output = tmp_path / "output"
    result = cli(subject, spec, context, output, "--request", str(request))
    assert result.returncode == 1, result.stdout + result.stderr
    lines = evidence_lines(output)
    assert [line["fixture_invocation"] for line in lines if "fixture_invocation" in line] == [
        ["install", "cedar:user"],
        ["install", "cedar:project"],
    ]
    if fault == "missing-home":
        observed = [line["disk_oracle"] for line in lines if "disk_oracle" in line]
        assert observed[-1]["cedar:user"] == {"error": 2}


@pytest.mark.parametrize(
    "fault",
    [
        "partial-signal",
        "between-signal",
        "lost-personal",
        "reformat-protected",
        "unreadable-home",
        "omitted-home",
    ],
)
def test_group_faults_preserve_observed_disk_and_fail(tmp_path: Path, fault: str) -> None:
    subject, spec, context, request, _ = arrange_group(tmp_path, fault)
    output = tmp_path / "output"
    result = cli(subject, spec, context, output, "--request", str(request))
    assert result.returncode == 1, result.stdout + result.stderr
    lines = evidence_lines(output)
    assert len([line for line in lines if "fixture_invocation" in line]) == 4
    observed = [line["disk_oracle"] for line in lines if "disk_oracle" in line]
    if fault in ("partial-signal", "between-signal"):
        assert observed[-1]["cedar:project"] == observed[2]["cedar:project"]
        assert observed[-1]["cedar:user"] == observed[2]["cedar:user"]
        members = [
            member
            for group in json.loads(observed[-1]["birch:project"])["hooks"].get("SessionStart", [])
            for member in group["hooks"]
        ]
        assert not any(member["command"] == "birch first" for member in members)
        assert any(member["command"] == "birch second" for member in members) == (
            fault == "partial-signal"
        )
    assessment = terminal_assessment(output)
    if fault in ("partial-signal", "between-signal"):
        command = terminal_result(output)["steps"][-1]["facts"]["command"]
        assert command["state"] == "interrupted"
        assert command["exit_code"] == -15
        assert assessment["birch:project"]["summary"] == (
            "partially_removed" if fault == "partial-signal" else "all_removed"
        )
        assert assessment["cedar:project"]["summary"] == "none_removed"
        assert assessment["cedar:user"]["preservation"] == "preserved"
    elif fault == "lost-personal":
        assert assessment["birch:project"]["preservation"] == "violated"
    elif fault == "reformat-protected":
        assert assessment["cedar:user"]["preservation"] == "violated"
    elif fault in ("unreadable-home", "omitted-home"):
        assert assessment["cedar:user"]["preservation"] == "indeterminate"
        assert assessment["birch:project"]["summary"] == "all_removed"
    report = json.loads((output / "campaign.json").read_text())
    replay = replay_without_subject(tmp_path, subject, spec, context, request, output)
    assert replay["status"] == report["status"]
    assert replay["cases"][0]["result"]["test"] == report["cases"][0]["result"]["test"]


def test_group_omitting_selected_tool_rejected_before_preparation(tmp_path: Path) -> None:
    subject, spec, context, request, _ = arrange_group(tmp_path, "none")
    request.write_text(
        json.dumps(
            {
                "operation": "group-uninstall",
                "prepare": ["birch:project"],
                "remove": ["birch:project"],
            }
        )
    )
    output = tmp_path / "output"
    result = cli(subject, spec, context, output, "--request", str(request))
    assert result.returncode == 2, result.stdout + result.stderr
    assert not (output / "preparation").exists()
    assert not (output / "evidence.zip").exists()
