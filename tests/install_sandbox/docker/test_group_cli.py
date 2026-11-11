"""Group CLI acceptance against a literal package and an external fixture catalogue."""

import json
import shutil
import zipfile
from contextlib import suppress
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
                with suppress(json.JSONDecodeError):
                    lines.append(json.loads(line))
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


def assert_removed_members_preserve_personal_commands(final: dict[str, Any]) -> None:
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
    assert_removed_members_preserve_personal_commands(final)
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


def assert_interrupted_disk(observed: list[dict[str, Any]], fault: str) -> None:
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
    assert_interrupted_disk(observed, fault)
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


def test_group_replay_rejects_non_file_with_retained_json(tmp_path: Path) -> None:
    from tools.install_sandbox.host.campaign_replay import replay_campaign

    subject, spec, context, request, _ = arrange_group(tmp_path, "none")
    output = tmp_path / "output"
    result = cli(subject, spec, context, output, "--request", str(request))
    assert result.returncode == 0, result.stdout + result.stderr
    original = output / "evidence.zip"
    assert replay_campaign(original)["status"] == "partial_passed"
    tampered = tmp_path / "non-file.zip"
    observation = terminal_result(output)["steps"][-1]["retained"]["after"]
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(tampered, "w") as destination:
        (name,) = [name for name in source.namelist() if name.endswith("/" + observation)]
        snapshot_data = json.loads(source.read(name))
        (entry,) = [
            entry
            for entry in snapshot_data["entries"]
            if (entry["root"], entry["path"]) == ("project", ".birch/hooks.json")
        ]
        assert entry["kind"] == "file" and entry["content_file"]
        entry["kind"] = "other"
        for member in source.namelist():
            destination.writestr(
                member,
                json.dumps(snapshot_data).encode() if member == name else source.read(member),
            )
    with pytest.raises(
        ValueError,
        match=r"project/\.birch/hooks\.json kind other forbids fields: content_file, sha256$",
    ):
        replay_campaign(tampered)


def test_unreadable_birch_backup_keeps_known_group_removal_and_replays(tmp_path: Path) -> None:
    subject, spec, context, request, _ = arrange_group(tmp_path, "unreadable-birch-backup")
    output = tmp_path / "output"
    result = cli(subject, spec, context, output, "--request", str(request))
    assert result.returncode == 1, result.stdout + result.stderr
    case_result = terminal_result(output)
    assert case_result["status"] == "incomplete"
    terminal = case_result["steps"][-1]
    assert terminal["facts"]["command"]["exit_code"] == 0
    assessment = terminal["assessment"]
    birch = assessment["birch:project"]
    assert birch["summary"] == "all_removed"
    assert birch["preservation"] == "indeterminate" and not birch["complete"]
    backup = ".birch/hooks.json.graphify-bak"
    verification = terminal["facts"]["verification"]
    assert not verification["complete"]
    permission_error = next(
        o for o in verification["obstacles"] if o["path"] == backup and "Errno 13" in o["reason"]
    )
    assert any(
        d["path"] == backup and d["reason"] == permission_error["reason"]
        for d in birch["diagnostics"]
    )
    assert assessment["cedar:project"]["summary"] == "all_removed"
    assert assessment["cedar:project"]["preservation"] == "preserved"
    assert assessment["cedar:project"]["complete"]
    assert assessment["cedar:user"]["summary"] == "none_removed"
    assert assessment["cedar:user"]["preservation"] == "preserved"
    assert assessment["cedar:user"]["complete"]
    observed = [line["disk_oracle"] for line in evidence_lines(output) if "disk_oracle" in line]
    assert observed[-1]["birch:project:backup"] == {"error": 13}
    replay = replay_without_subject(tmp_path, subject, spec, context, request, output)
    replayed = replay["cases"][0]["result"]["test"]
    assert replayed["status"] == "incomplete"
    assert replayed["steps"][-1]["assessment"] == assessment
