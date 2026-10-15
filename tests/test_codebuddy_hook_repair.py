"""Synthetic regressions for bounded CodeBuddy search-hook repairs."""

import copy
import json

import pytest

from graphify.install import codebuddy_install


SEARCH = {"type": "command", "command": "graphify hook-guard search", "timeout": 10}
READ = {"type": "command", "command": "graphify hook-guard read", "timeout": 10}


def _seed(tmp_path):
    personal = {
        "theme": "dark",
        "metadata": {"order": ["second", "first"]},
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash|Grep",
                    "personal_group": "first",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python personal_graphify_audit.py",
                            "timeout": 17,
                        },
                    ],
                },
                {
                    "matcher": "Bash|Grep",
                    "personal_group": "second",
                    "hooks": [
                        {"type": "command", "command": "echo before"},
                        {"type": "command", "command": "echo after"},
                    ],
                },
            ],
            "PostToolUse": [{"matcher": "Bash|Grep", "hooks": [dict(SEARCH)]}],
        },
    }
    settings = tmp_path / ".codebuddy/settings.json"
    settings.parent.mkdir()
    initial = (json.dumps(personal, indent=4) + "\n").encode()
    settings.write_bytes(initial)
    (tmp_path / "personal.txt").write_bytes(b"Personal notes\n")
    codebuddy_install(tmp_path)
    installed = json.loads(settings.read_bytes())
    assert installed == {
        **personal,
        "hooks": {
            **personal["hooks"],
            "PreToolUse": personal["hooks"]["PreToolUse"]
            + [
                {"matcher": "Bash|Grep", "hooks": [SEARCH]},
                {"matcher": "Read|Glob", "hooks": [READ]},
            ],
        },
    }
    return settings, initial, installed


def _write_prepared(settings, prepared):
    content = (json.dumps(prepared, indent=4) + "\n").encode()
    settings.write_bytes(content)
    # Retain the exact input alongside pytest's temporary outputs for before/after evidence.
    settings.with_name("prepared.json").write_bytes(content)


@pytest.mark.parametrize("repair", ["altered", "duplicate", "same-group-duplicate", "mixed"])
@pytest.mark.parametrize("backup_bytes", [None, b"", b"Earlier personal backup\r\n"])
def test_search_hook_repair_preserves_personal_state(tmp_path, repair, backup_bytes):
    settings, initial, installed = _seed(tmp_path)
    backup = settings.with_name("settings.json.graphify-bak")
    if backup_bytes is not None:
        backup.write_bytes(backup_bytes)
    expected_backup = initial if backup_bytes is None else backup_bytes
    prepared = copy.deepcopy(installed)
    groups = prepared["hooks"]["PreToolUse"]
    if repair == "altered":
        groups[2]["hooks"][0]["timeout"] = 11
    else:
        groups[1 if repair == "duplicate" else 2]["hooks"].insert(1, dict(SEARCH))
    if repair == "mixed":
        groups[2]["hooks"][0]["timeout"] = 11
    _write_prepared(settings, prepared)
    other_files = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file() and p != settings}

    codebuddy_install(tmp_path)

    actual = json.loads(settings.read_bytes())
    matches = [
        h
        for g in actual["hooks"]["PreToolUse"]
        if g["matcher"] == "Bash|Grep"
        for h in g["hooks"]
        if h == SEARCH
    ]
    assert len(matches) == 1

    # Allow either duplicate to survive, while checking every group, attribute and personal order.
    def without_search(data):
        result = copy.deepcopy(data)
        for group in result["hooks"]["PreToolUse"]:
            if group["matcher"] == "Bash|Grep":
                group["hooks"] = [h for h in group["hooks"] if h != SEARCH]
        return result

    assert without_search(actual) == without_search(installed)
    assert backup.read_bytes() == expected_backup
    assert all(p.read_bytes() == content for p, content in other_files.items())
    repaired_bytes = settings.read_bytes()
    codebuddy_install(tmp_path)
    assert settings.read_bytes() == repaired_bytes
    assert backup.read_bytes() == expected_backup


@pytest.mark.parametrize(
    "neighbor",
    [
        {**SEARCH, "timeout": 11, "personal": True},
        {**SEARCH, "command": "graphify hook-guard search --personal", "timeout": 11},
        {**SEARCH, "command": "/personal/bin/graphify hook-guard search", "timeout": 11},
        {**SEARCH, "type": "personal", "timeout": 11},
        {**SEARCH, "timeout": 12},
        {**SEARCH, "timeout": "11"},
        {**SEARCH, "timeout": 11.0},
        {"type": "command", "command": "graphify hook-guard search"},
    ],
)
def test_search_repair_preserves_neighboring_personal_hooks(tmp_path, neighbor):
    settings, initial, installed = _seed(tmp_path)
    prepared = copy.deepcopy(installed)
    prepared["hooks"]["PreToolUse"][2]["hooks"][0]["timeout"] = 11
    prepared["hooks"]["PreToolUse"][1]["hooks"].insert(1, neighbor)
    prepared["hooks"]["PreToolUse"].append(
        {"matcher": "Bash", "hooks": [{**SEARCH, "timeout": 11}]}
    )
    _write_prepared(settings, prepared)
    expected = copy.deepcopy(prepared)
    expected["hooks"]["PreToolUse"][2]["hooks"][0]["timeout"] = 10

    codebuddy_install(tmp_path)

    assert json.loads(settings.read_bytes()) == expected
    assert settings.with_name("settings.json.graphify-bak").read_bytes() == initial


@pytest.mark.parametrize("extra_timeout", [10, 11])
def test_search_repair_refuses_enriched_ambiguity_without_writes(tmp_path, capsys, extra_timeout):
    settings, _, installed = _seed(tmp_path)
    prepared = copy.deepcopy(installed)
    prepared["hooks"]["PreToolUse"][2]["hooks"][0]["timeout"] = extra_timeout
    prepared["hooks"]["PreToolUse"][1]["hooks"].append({**SEARCH, "personal": True})
    _write_prepared(settings, prepared)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    capsys.readouterr()

    with pytest.raises(SystemExit) as exc:
        codebuddy_install(tmp_path)

    assert exc.value.code == 1
    assert "ambiguous" in capsys.readouterr().err
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_read_ambiguity_does_not_persist_search_repair(tmp_path):
    settings, _, installed = _seed(tmp_path)
    prepared = copy.deepcopy(installed)
    prepared["hooks"]["PreToolUse"][2]["hooks"][0]["timeout"] = 11
    prepared["hooks"]["PreToolUse"][3]["hooks"].append(dict(READ))
    _write_prepared(settings, prepared)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    with pytest.raises(SystemExit) as exc:
        codebuddy_install(tmp_path)

    assert exc.value.code == 1
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
