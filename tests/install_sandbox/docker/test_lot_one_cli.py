"""Acceptance of effect identity through the real CLI and Docker (no transport mocks)."""

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/lot_one_subject.py"
EXPECTED_MISSING = {
    ("birch", "project", "missing-json-hook", "editor-hooks", "run"),
    ("birch", "project", "missing-json-hook", "assistant-hooks", "run"),
    ("birch", "user", "missing-json-hook", "user-hooks", "run"),
    ("birch", "project", "missing-json-hook", "assistant-hooks", "layout"),
}


def isolated_git_environment() -> dict[str, str]:
    environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return {**environment, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}


def git(subject: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(subject), *args],
        check=True,
        text=True,
        capture_output=True,
        env=isolated_git_environment(),
    ).stdout.strip()


def arrange(root: Path, fault: str = "user") -> tuple[Path, Path, Path]:
    subject = root / "subject"
    package = subject / "birch"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "cli.py").write_text(FIXTURE.read_text())
    (package / "fault.txt").write_text(fault)
    (subject / "pyproject.toml").write_text(
        '[build-system]\nrequires=["setuptools"]\nbuild-backend="setuptools.build_meta"\n'
        '[project]\nname="birch-sandbox-fixture"\nversion="1.0.0"\ndependencies=[]\n'
        '[project.scripts]\ngraphify="birch.cli:main"\n'
        '[tool.setuptools.package-data]\nbirch=["fault.txt"]\n'
    )
    git(subject, "init", "-q")
    git(subject, "add", ".")
    git(
        subject,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.test",
        "commit",
        "-qm",
        "Independent synthetic installer",
    )
    context = root / "context.json"
    context.write_text(
        json.dumps(
            {
                "identity": "birch",
                "invocations": {
                    "birch:project": ["install", "--scope", "project"],
                    "birch:user": ["install", "--scope", "user"],
                },
                "version_source": "METADATA",
                "rules": {
                    "skill_lock": "persistent",
                    "json_backup": ".graphify-bak",
                    "skill_backup": ".bak",
                    "json_registry": False,
                },
                "package_root": "birch",
                "revision": git(subject, "rev-parse", "HEAD"),
            }
        )
    )

    def effect(identifier: str, root: str, path: str) -> dict[str, Any]:
        return {
            "effect_id": identifier,
            "family": "json-hooks",
            "root": root,
            "path": path,
            "hooks": [
                {
                    "id": "run",
                    "event": "SessionStart",
                    "matcher": "*",
                    "content": {"type": "command", "command": "birch run", "timeout": 10},
                }
            ],
        }

    assistant = effect("assistant-hooks", "HOME", ".birch/assistant.json")
    assistant["hooks"].append(
        {
            "id": "layout",
            "event": "SessionStart",
            "matcher": "FixtureLayout",
            "content": {"type": "command", "command": "birch layout", "timeout": 10},
        }
    )
    spec = root / "birch.yaml"
    spec.write_text(
        yaml.safe_dump(
            {
                "tool": "birch",
                "scopes": {
                    "project": [effect("editor-hooks", "PROJECT", ".birch/editor.json"), assistant],
                    "user": [effect("user-hooks", "HOME", ".birch/user.json")],
                },
            },
            sort_keys=False,
        )
    )
    return subject, spec, context


def cli(
    subject: Path, spec: Path, context: Path, output: Path, *arguments: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.install_sandbox",
            "--repo",
            str(subject),
            "--spec",
            str(spec),
            "--subject-context",
            str(context),
            "--output",
            str(output),
            *arguments,
        ],
        cwd=ROOT,
        env=isolated_git_environment(),
        capture_output=True,
        text=True,
        timeout=600,
    )


def test_same_user_defect_is_partial_project_success_and_complete_failure(tmp_path: Path) -> None:
    subject, spec, context = arrange(tmp_path)
    request = tmp_path / "one-hook.json"
    request.write_text(
        json.dumps(
            {
                "operation": "missing-json-hook",
                "target": {
                    "participant": "birch:project",
                    "effect_id": "assistant-hooks",
                    "member": "run",
                },
            }
        )
    )
    selected = cli(subject, spec, context, tmp_path / "selected", "--request", str(request))
    assert selected.returncode == 0, selected.stdout + selected.stderr
    report = json.loads((tmp_path / "selected/campaign.json").read_text())
    assert report["status"] == "partial_passed" and report["passed"] is False
    assert_targeted_mutation(tmp_path / "selected/evidence.zip", report)
    complete = cli(subject, spec, context, tmp_path / "complete")
    assert complete.returncode == 1, complete.stdout + complete.stderr
    full = json.loads((tmp_path / "complete/campaign.json").read_text())
    assert full["status"] == "failed" and full["passed"] is False
    assert full["scope_results"]["project"]["status"] == "passed"
    assert full["scope_results"]["user"]["status"] == "failed"
    assert missing_keys(full) == EXPECTED_MISSING
    missing = [case for case in full["cases"] if case["key"]["operation"] == "missing-json-hook"]
    assert len({case["output_directory"] for case in missing}) == 4
    for case in missing:
        assert case["result"]["test"]["status"] == (
            "failed" if case["key"]["scope"] == "user" else "passed"
        )
    assert [
        case["key"]
        for case in full["cases"]
        if case["result"] is not None and case["result"]["test"]["status"] == "failed"
    ] == [
        {
            "tool": "birch",
            "scope": "user",
            "operation": "missing-json-hook",
            "effect_id": "user-hooks",
            "member": "run",
        }
    ]
    assert_failed_repair_first_install(
        tmp_path / "complete/evidence.zip", full, "user", "user-hooks", "run"
    )
    assert_moved_replay(tmp_path, subject, spec, context, request, full)


def assert_moved_replay(
    tmp_path: Path, subject: Path, spec: Path, context: Path, request: Path, full: dict[str, Any]
) -> None:
    moved = tmp_path / "moved.zip"
    shutil.copyfile(tmp_path / "complete/evidence.zip", moved)
    selected_moved = tmp_path / "selected-moved.zip"
    shutil.copyfile(tmp_path / "selected/evidence.zip", selected_moved)
    shutil.rmtree(subject)
    context.unlink()
    spec.unlink()
    request.unlink()
    from tools.install_sandbox.host.campaign_replay import replay_campaign

    replayed = replay_campaign(moved)
    assert replayed["scope_results"] == full["scope_results"]
    assert missing_keys(replayed) == EXPECTED_MISSING
    projected = replay_campaign(selected_moved)
    assert projected["status"] == "partial_passed" and projected["passed"] is False
    assert missing_keys(projected) == {
        ("birch", "project", "missing-json-hook", "assistant-hooks", "run")
    }


def missing_keys(report: dict[str, Any]) -> set[tuple[str, ...]]:
    return {
        tuple(case["key"][field] for field in ("tool", "scope", "operation", "effect_id", "member"))
        for case in report["cases"]
        if case["key"]["operation"] == "missing-json-hook"
    }


def assert_targeted_mutation(archive_path: Path, report: dict[str, Any]) -> None:
    """Read literal files, without the sandbox expectation or mutation helpers."""
    cases = [case for case in report["cases"] if case.get("construction") == "constructed"]
    assert len(cases) == 1
    case_id = Path(cases[0]["output_directory"]).name
    with zipfile.ZipFile(archive_path) as archive:

        def blob(suffix: str) -> bytes:
            names = [name for name in archive.namelist() if name.endswith(f"/{case_id}/{suffix}")]
            assert len(names) == 1, (suffix, names)
            return archive.read(names[0])

        target = "home/.birch/assistant.json"
        before = json.loads(blob(f"steps/0/after/{target}"))
        prepared = json.loads(blob(f"intermediate/after/{target}"))

        def count(document: dict[str, Any]) -> int:
            return sum(
                hook.get("command") == "birch run"
                for entry in document["hooks"]["SessionStart"]
                for hook in entry["hooks"]
            )

        repaired = json.loads(blob(f"steps/1/after/{target}"))
        assert (count(before), count(prepared), count(repaired)) == (1, 0, 1)
        for step in (0, 1):
            assert json.loads(blob(f"steps/{step}/stdout.txt")) == {
                "fixture_invocation": ["install", "--scope", "project"]
            }
        assert blob("steps/0/after/project/.birch/editor.json") == blob(
            "intermediate/after/project/.birch/editor.json"
        )
        for document in (before, prepared):
            assert document["metadata"] == {"owner": "personal"}
            assert document["theme"] == "dark"
            assert any(
                hook.get("command") == "python personal_graphify_audit.py"
                for entry in document["hooks"]["SessionStart"]
                for hook in entry["hooks"]
            )


@pytest.mark.parametrize("permuted", [False, True])
def test_conformant_subject_and_permuted_declarations(tmp_path: Path, permuted: bool) -> None:
    subject, spec, context = arrange(tmp_path, fault="permuted" if permuted else "layout")
    data = yaml.safe_load(spec.read_text())
    if permuted:
        data["scopes"]["project"][1]["hooks"].reverse()
        data["scopes"]["project"].reverse()
    spec.write_text(yaml.safe_dump(data))
    result = cli(subject, spec, context, tmp_path / "complete")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / "complete/campaign.json").read_text())
    assert report["status"] == "passed" and report["passed"] is True
    assert report["preservation_check_roots"] == ["home", "project"]
    verdict = (
        "Campaign passed: True\n"
        "Filesystem preservation checks cover the isolated HOME and PROJECT directories."
    )
    assert verdict in result.stdout
    assert verdict in (tmp_path / "complete/campaign.txt").read_text()
    assert missing_keys(report) == EXPECTED_MISSING
    assert len([case for case in report["cases"] if case["construction"] == "constructed"]) == 6
    archive_path = tmp_path / "complete/evidence.zip"
    assert_permuted_target_archive(archive_path, report, permuted)
    from tools.install_sandbox.host.campaign_replay import replay_campaign

    replayed = replay_campaign(archive_path)
    assert replayed["status"] == "passed"
    assert replayed["preservation_check_roots"] == ["home", "project"]
    if not permuted:
        assert_campaign_rejects_missing_substituted_and_retargeted_proof(
            archive_path, report, tmp_path
        )


def assert_permuted_target_archive(
    archive_path: Path, report: dict[str, Any], permuted: bool
) -> None:
    """Restore the literal missing member and verify all other bytes semantically."""
    case = next(
        case
        for case in report["cases"]
        if case["key"]
        == {
            "tool": "birch",
            "scope": "project",
            "operation": "missing-json-hook",
            "effect_id": "assistant-hooks",
            "member": "run",
        }
    )
    prefix = case["output_directory"].rstrip("/") + "/"
    with zipfile.ZipFile(archive_path) as archive:
        target = "home/.birch/assistant.json"
        before = json.loads(archive.read(prefix + f"steps/0/after/{target}"))
        prepared = json.loads(archive.read(prefix + f"intermediate/after/{target}"))
    locations = [
        (group_index, member_index)
        for group_index, group in enumerate(before["hooks"]["SessionStart"])
        for member_index, member in enumerate(group["hooks"])
        if member.get("command") == "birch run"
    ]
    assert len(locations) == 1
    group_index, member_index = locations[0]
    if permuted:
        # Seeded group is retained with only its personal witness; managed member moved.
        seeded = next(
            group
            for group in before["hooks"]["SessionStart"]
            if group.get("sandbox_personal") == "preserve"
        )
        assert all(member.get("command") != "birch run" for member in seeded["hooks"])
        assert before["hooks"]["SessionStart"][group_index] is not seeded
    else:
        assert locations == [(0, 0)]
    observed = before["hooks"]["SessionStart"][group_index]["hooks"][member_index]
    assert not any(
        member.get("command") == "birch run"
        for group in prepared["hooks"]["SessionStart"]
        for member in group["hooks"]
    )
    prepared["hooks"]["SessionStart"][group_index]["hooks"].insert(member_index, observed)
    assert prepared == before


def assert_campaign_rejects_missing_substituted_and_retargeted_proof(
    archive_path: Path, report: dict[str, Any], root: Path
) -> None:
    from tools.install_sandbox.host.campaign_replay import replay_campaign

    targets = {
        case["key"]["effect_id"]: case
        for case in report["cases"]
        if case["key"]["operation"] == "missing-json-hook"
        and case["key"]["scope"] == "project"
        and case["key"]["member"] == "run"
    }
    victim = targets["assistant-hooks"]["output_directory"].rstrip("/") + "/"
    donor = targets["editor-hooks"]["output_directory"].rstrip("/") + "/"
    with zipfile.ZipFile(archive_path) as archive:
        original = {name: archive.read(name) for name in archive.namelist()}
    assert any(name.startswith(victim) for name in original)
    for fault in ("missing", "substituted", "retargeted", "tampered"):
        entries = dict(original)
        if fault in ("missing", "substituted"):
            entries = {name: data for name, data in entries.items() if not name.startswith(victim)}
        if fault == "substituted":
            entries.update(
                {
                    victim + name.removeprefix(donor): data
                    for name, data in original.items()
                    if name.startswith(donor)
                }
            )
        if fault == "tampered":
            snapshot = victim + "intermediate/after/home/.birch/assistant.json"
            document = json.loads(entries[snapshot])
            document["theme"] = "tampered"
            entries[snapshot] = json.dumps(document).encode()
        if fault == "retargeted":
            operation_file = victim + "intermediate/operation.json"
            operation = json.loads(entries[operation_file])
            operation["target"]["effect_id"] = "editor-hooks"
            entries[operation_file] = json.dumps(operation).encode()
        altered = root / f"{fault}.zip"
        with zipfile.ZipFile(altered, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in entries.items():
                archive.writestr(name, data)
        with pytest.raises(ValueError):
            replay_campaign(altered)


def test_second_project_file_defect_fails_full_campaign(tmp_path: Path) -> None:
    subject, spec, context = arrange(tmp_path, fault="second-project")
    result = cli(subject, spec, context, tmp_path / "complete")
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads((tmp_path / "complete/campaign.json").read_text())
    assert report["scope_results"]["project"]["status"] == "failed"
    assert report["scope_results"]["user"]["status"] == "passed"
    failing = [
        case["key"]
        for case in report["cases"]
        if case["result"] is not None and case["result"]["test"]["status"] == "failed"
    ]
    assert failing == [
        {
            "tool": "birch",
            "scope": "project",
            "operation": "missing-json-hook",
            "effect_id": "assistant-hooks",
            "member": "layout",
        }
    ]

    assert_failed_repair_first_install(
        tmp_path / "complete/evidence.zip", report, "project", "assistant-hooks", "layout"
    )


def assert_failed_repair_first_install(
    archive_path: Path, report: dict[str, Any], scope: str, effect: str, member: str
) -> None:
    case = next(
        case
        for case in report["cases"]
        if case["key"]
        == {
            "tool": "birch",
            "scope": scope,
            "operation": "missing-json-hook",
            "effect_id": effect,
            "member": member,
        }
    )
    prefix = case["output_directory"].rstrip("/") + "/"
    target = "home/.birch/" + ("user.json" if scope == "user" else "assistant.json")
    command = "birch " + member
    with zipfile.ZipFile(archive_path) as archive:
        documents = [
            json.loads(archive.read(prefix + suffix + target))
            for suffix in ("steps/0/after/", "intermediate/after/", "steps/1/after/")
        ]
    counts = [
        sum(
            hook.get("command") == command
            for group in document["hooks"]["SessionStart"]
            for hook in group["hooks"]
        )
        for document in documents
    ]
    assert counts == [1, 0, 0]
    if scope == "project":
        assert all(
            sum(
                hook.get("command") == "birch run"
                for group in document["hooks"]["SessionStart"]
                for hook in group["hooks"]
            )
            == 1
            for document in documents
        )


def test_moved_destination_keeps_key_and_requires_corrected_subject(tmp_path: Path) -> None:
    subject, spec, context = arrange(tmp_path, fault="none")
    data = yaml.safe_load(spec.read_text())
    data["scopes"]["project"][1]["path"] = ".birch/moved-assistant.json"
    spec.write_text(yaml.safe_dump(data))
    request = tmp_path / "one-hook.json"
    request.write_text(
        json.dumps(
            {
                "operation": "missing-json-hook",
                "target": {
                    "participant": "birch:project",
                    "effect_id": "assistant-hooks",
                    "member": "run",
                },
            }
        )
    )
    broken = cli(subject, spec, context, tmp_path / "old-path", "--request", str(request))
    assert broken.returncode == 1, broken.stdout + broken.stderr
    before = json.loads((tmp_path / "old-path/campaign.json").read_text())
    installer = subject / "birch/cli.py"
    installer.write_text(
        installer.read_text().replace(
            'home / ".birch/assistant.json"', 'home / ".birch/moved-assistant.json"'
        )
    )
    git(subject, "add", ".")
    git(
        subject,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.test",
        "commit",
        "-qm",
        "Move literal fixture destination",
    )
    raw = json.loads(context.read_text())
    raw["revision"] = git(subject, "rev-parse", "HEAD")
    context.write_text(json.dumps(raw))
    corrected = cli(subject, spec, context, tmp_path / "new-path", "--request", str(request))
    assert corrected.returncode == 0, corrected.stdout + corrected.stderr
    after = json.loads((tmp_path / "new-path/campaign.json").read_text())
    assert (
        missing_keys(before)
        == missing_keys(after)
        == {("birch", "project", "missing-json-hook", "assistant-hooks", "run")}
    )
