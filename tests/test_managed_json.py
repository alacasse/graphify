"""Managed ownership, real persistence, interruption and exclusion evidence."""

import copy
import hashlib
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from graphify import managed_json as mj

EFFECT = {
    "id": "graphify.search",
    "event": "PreToolUse",
    "matcher": "Bash|Grep",
    "content": {"type": "command", "command": "graphify hook-guard search"},
}
PERSONAL = {"type": "command", "command": "echo personal", "timeout": 9}


def setup(tmp_path, settings=None):
    path = tmp_path / ".sandbox-reference/settings.json"
    path.parent.mkdir()
    if settings is not None:
        path.write_text(json.dumps(settings))
        path.chmod(0o640)
    return path


def apply(path, effects=None, resolution=None):
    mj.apply_managed_hooks(
        path,
        project_root=path.parent.parent,
        effects=effects or [copy.deepcopy(EFFECT)],
        instruction="skills/graphify/SKILL.md",
        resolution=resolution,
    )


def resolution(path, action="create", content=None):
    choice: dict[str, Any] = {"id": "graphify.search", "action": action}
    if action == "adopt":
        choice.update(
            event="PreToolUse", matcher="Bash|Grep", group_index=0, hook_index=0, content=content
        )
    return {
        "version": 1,
        "target": ".sandbox-reference/settings.json",
        "snapshot_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "registry_absent": True,
        "effects": [choice],
    }


def sides(path):
    return tuple(
        path.with_name(path.name + suffix)
        for suffix in (".graphify-state.json", ".graphify.lock", ".graphify-journal.json")
    )


def test_create_update_preserves_same_group_and_no_writes(tmp_path, monkeypatch):
    path = setup(tmp_path, {"personal": [True, 1], "instructions": ["mine"]})
    apply(path)
    state, lock, journal = sides(path)
    settings = json.loads(path.read_bytes())
    group = settings["hooks"]["PreToolUse"][0]
    group["hooks"].insert(0, PERSONAL)
    group["custom"] = {"keep": True}
    path.write_text(json.dumps(settings))
    desired = copy.deepcopy(EFFECT)
    desired["content"]["timeout"] = 10
    apply(path, [desired])
    result = json.loads(path.read_bytes())
    assert result["hooks"]["PreToolUse"][0] == {
        "matcher": "Bash|Grep",
        "hooks": [PERSONAL, desired["content"]],
        "custom": {"keep": True},
    }
    assert result["personal"] == [True, 1]
    assert path.stat().st_mode & 0o777 == 0o640
    assert state.stat().st_mode & 0o777 == lock.stat().st_mode & 0o777 == 0o600
    assert lock.read_bytes() == b"" and not journal.exists()
    monkeypatch.setattr(mj, "_write", lambda *_: pytest.fail("idempotence must not write"))
    apply(path, [desired])


@pytest.mark.parametrize("action", ["create", "adopt"])
def test_explicit_resolution_and_stale_or_consumed_rejection(tmp_path, action):
    content = EFFECT["content"] if action == "adopt" else PERSONAL
    path = setup(
        tmp_path, {"hooks": {"PreToolUse": [{"matcher": "Bash|Grep", "hooks": [content]}]}}
    )
    before = path.read_bytes()
    with pytest.raises(mj.ManagedJSONError, match="resolution"):
        apply(path)
    assert path.read_bytes() == before and not sides(path)[0].exists()
    consent = resolution(path, action, content)
    stale = copy.deepcopy(consent)
    stale["snapshot_sha256"] = "0" * 64
    with pytest.raises(mj.ManagedJSONError, match="stale"):
        apply(path, resolution=stale)
    apply(path, resolution=consent)
    with pytest.raises(mj.ManagedJSONError, match="absent registry"):
        apply(path, resolution=consent)


@pytest.mark.parametrize(
    "change", ["missing", "customized", "duplicate", "context", "identities", "collision"]
)
def test_registered_conflicts_preserve_pair(tmp_path, change):
    path = setup(tmp_path)
    apply(path)
    desired = copy.deepcopy(EFFECT)
    settings = json.loads(path.read_bytes())
    hooks = settings["hooks"]["PreToolUse"][0]["hooks"]
    if change == "missing":
        hooks.clear()
    elif change == "customized":
        hooks[0]["timeout"] = 10
    elif change == "duplicate":
        hooks.append(copy.deepcopy(hooks[0]))
    elif change == "context":
        desired["matcher"] = "Other"
    elif change == "identities":
        desired["id"] = "other"
    else:
        desired["content"]["timeout"] = 10
        hooks.append({**desired["content"], "personal": True})
    path.write_text(json.dumps(settings))
    state, _, journal = sides(path)
    before = path.read_bytes(), state.read_bytes()
    with pytest.raises(mj.ManagedJSONError):
        apply(path, [desired])
    assert (path.read_bytes(), state.read_bytes()) == before
    assert not journal.exists()


@pytest.mark.parametrize("action", ["create", "adopt"])
def test_final_collision_does_not_claim_neighbor(tmp_path, action):
    content = {**EFFECT["content"], "personal": True}
    hooks = [content] if action == "create" else [EFFECT["content"], content]
    path = setup(tmp_path, {"hooks": {"PreToolUse": [{"matcher": "Bash|Grep", "hooks": hooks}]}})
    consent = resolution(path, action, EFFECT["content"])
    before = path.read_bytes()
    with pytest.raises(mj.ManagedJSONError, match="collision"):
        apply(path, resolution=consent)
    assert path.read_bytes() == before and not sides(path)[0].exists()


@pytest.mark.parametrize(
    "raw",
    [
        b'{"hooks":{},"hooks":{}}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":1e400}',
        b"[]",
        b'{"hooks":{"event":{}}}',
        b'{"instructions":{}}',
        b"{",
    ],
)
def test_strict_configuration(tmp_path, raw):
    path = setup(tmp_path)
    path.write_bytes(raw)
    with pytest.raises(mj.ManagedJSONError):
        apply(path)
    assert path.read_bytes() == raw and not sides(path)[0].exists()


def test_typed_equality_and_registry_validation(tmp_path):
    assert not mj._exact(True, 1) and not mj._exact(1, 1.0)
    path = setup(tmp_path)
    apply(path)
    state = sides(path)[0]
    registry = json.loads(state.read_bytes())
    registry["version"] = True
    state.write_text(json.dumps(registry))
    before = path.read_bytes(), state.read_bytes()
    with pytest.raises(mj.ManagedJSONError):
        apply(path)
    assert (path.read_bytes(), state.read_bytes()) == before


@pytest.mark.parametrize(
    "suffix", ["", ".graphify-state.json", ".graphify.lock", ".graphify-journal.json"]
)
@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_reject_filesystem_types(tmp_path, suffix, kind):
    path = setup(tmp_path)
    target = path.with_name(path.name + suffix)
    if kind == "directory":
        target.mkdir()
    else:
        target.symlink_to(tmp_path / "missing")
    with pytest.raises(mj.ManagedJSONError):
        apply(path)


PROCESS = """
import json, os, signal, sys
from pathlib import Path
from typing import Any
from graphify import managed_json as mj
path, stage, ready, release, consent = sys.argv[1:]
def checkpoint(current):
    if current == stage:
        Path(ready).write_text(current)
        os.kill(os.getpid(), signal.SIGSTOP)
mj._checkpoint = checkpoint
mj.apply_managed_hooks(Path(path), project_root=Path(path).parent.parent, effects=[json.loads(%r)], instruction="skills/graphify/SKILL.md", resolution=json.loads(consent))
""" % json.dumps(EFFECT)


def stopped_process(path, stage, consent=None):
    ready = path.parent / "checkpoint"
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            PROCESS,
            str(path),
            stage,
            str(ready),
            "unused",
            json.dumps(consent),
        ],
        cwd=Path(__file__).parents[1],
    )
    pid, status = os.waitpid(process.pid, os.WUNTRACED)
    assert pid == process.pid and os.WIFSTOPPED(status)
    assert ready.read_text() == stage
    return process


def retain(path, name):
    directory = path.parent.parent / name
    directory.mkdir()
    observed = {}
    for item in (path, *sides(path)):
        if item.exists():
            (directory / item.name).write_bytes(item.read_bytes())
            observed[item.name] = {
                "mode": item.stat().st_mode & 0o777,
                "sha256": hashlib.sha256(item.read_bytes()).hexdigest(),
            }
        else:
            observed[item.name] = None
    (directory / "observed.json").write_text(json.dumps(observed, indent=2))


def public_recover(path, consent):
    project = path.parent.parent
    isolated = project.parent / (project.name + "-cli-environment")
    isolated.mkdir()
    env = os.environ.copy()
    for key, directory in (
        ("HOME", "home"),
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_CACHE_HOME", "cache"),
        ("XDG_DATA_HOME", "data"),
        ("TMPDIR", "tmp"),
    ):
        location = isolated / directory
        location.mkdir()
        env[key] = str(location)
    env["PYTHONPATH"] = str(Path(__file__).parents[1])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    args = [
        sys.executable,
        "-B",
        "-m",
        "graphify",
        "install",
        "--platform",
        "sandbox-reference",
        "--project",
    ]
    if consent is not None:
        document = isolated / "resolution.json"
        document.write_text(json.dumps(consent))
        args.extend(["--managed-hooks-resolution", str(document)])
    result = subprocess.run(args, cwd=project, env=env, text=True, capture_output=True, timeout=30)
    (isolated / "command.json").write_text(
        json.dumps({"argv": args, "cwd": str(project), "returncode": result.returncode}, indent=2)
    )
    (isolated / "stdout.txt").write_text(result.stdout)
    (isolated / "stderr.txt").write_text(result.stderr)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "stage", ["journal_published", "target_replaced", "registry_replaced", "before_journal_remove"]
)
@pytest.mark.parametrize(
    "variant", ["create", "adoption_unchanged_target", "repair_unchanged_registry"]
)
def test_real_process_interrupt_recovery(tmp_path, stage, variant):
    path = setup(tmp_path)
    consent = None
    if variant == "adoption_unchanged_target":
        path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [{"matcher": "Bash|Grep", "hooks": [EFFECT["content"]]}]
                    },
                    "instructions": ["skills/graphify/SKILL.md"],
                }
            )
        )
        consent = resolution(path, "adopt", EFFECT["content"])
    elif variant == "repair_unchanged_registry":
        apply(path)
        value = json.loads(path.read_bytes())
        value["instructions"] = []
        path.write_text(json.dumps(value))
    process = stopped_process(path, stage, consent)
    retain(path, "interrupted")
    process.kill()
    process.wait(timeout=10)
    public_recover(path, consent)
    retain(path, "recovered")
    assert not sides(path)[2].exists()
    assert json.loads(sides(path)[0].read_bytes())["effects"] == [EFFECT]
    assert json.loads(path.read_bytes())["instructions"] == ["skills/graphify/SKILL.md"]


def test_process_lock_busy_then_success(tmp_path):
    path = setup(tmp_path)
    process = stopped_process(path, "journal_published")
    try:
        before = path.exists(), sides(path)[0].exists(), sides(path)[2].read_bytes()
        with pytest.raises(mj.ManagedJSONError, match="busy"):
            apply(path)
        assert (path.exists(), sides(path)[0].exists(), sides(path)[2].read_bytes()) == before
        retain(path, "busy")
    finally:
        process.kill()
        process.wait(timeout=10)
    apply(path)


def test_foreign_bytes_and_modes_preserve_journal(tmp_path):
    path = setup(tmp_path, {})
    process = stopped_process(path, "journal_published")
    process.kill()
    process.wait(timeout=10)
    path.chmod(0o600)
    before = path.read_bytes(), sides(path)[2].read_bytes()
    with pytest.raises(mj.ManagedJSONError, match="foreign"):
        apply(path)
    assert (path.read_bytes(), sides(path)[2].read_bytes()) == before
    path.chmod(0o640)
    path.write_text('{"foreign":true}')
    with pytest.raises(mj.ManagedJSONError, match="foreign"):
        apply(path)


def test_write_and_journal_remove_failures_recover(tmp_path, monkeypatch):
    path = setup(tmp_path)
    write = mj._write

    def failing(target, snapshot, transaction=None):
        if target == path:
            raise OSError("controlled write failure")
        write(target, snapshot, transaction)

    monkeypatch.setattr(mj, "_write", failing)
    with pytest.raises(OSError):
        apply(path)
    assert sides(path)[2].exists() and not path.exists()
    monkeypatch.setattr(mj, "_write", write)
    unlink = Path.unlink

    def refuse(target, *args, **kwargs):
        if target == sides(path)[2]:
            raise OSError("controlled unlink failure")
        return unlink(target, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", refuse)
    with pytest.raises(OSError):
        apply(path)
    assert sides(path)[2].exists() and sides(path)[0].exists()
    monkeypatch.setattr(Path, "unlink", unlink)
    apply(path)
    assert not sides(path)[2].exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_after",
        "null_after",
        "wrong_registry",
        "wrong_hook",
        "registry_mode",
        "instruction_type",
        "instruction_missing",
        "target_name",
        "unknown_version",
        "null_record",
    ],
)
def test_malformed_or_inconsistent_journal_preserves_pair(tmp_path, mutation):
    path = setup(tmp_path)
    process = stopped_process(path, "journal_published")
    process.kill()
    process.wait(timeout=10)
    journal_path = sides(path)[2]
    journal = json.loads(journal_path.read_bytes())
    if mutation == "missing_after":
        journal["target"] = {}
    elif mutation == "null_after":
        journal["target"]["after"] = None
    elif mutation == "wrong_registry":
        snapshot = mj._decoded(journal["registry"]["after"])
        assert snapshot is not None
        state = json.loads(snapshot[0])
        state["effects"][0]["content"]["timeout"] = 11
        journal["registry"]["after"] = mj._encoded((mj._bytes(state), 0o600))
    elif mutation == "wrong_hook":
        snapshot = mj._decoded(journal["target"]["after"])
        assert snapshot is not None
        settings = json.loads(snapshot[0])
        settings["hooks"]["PreToolUse"][0]["hooks"][0]["timeout"] = 11
        journal["target"]["after"] = mj._encoded((mj._bytes(settings), 0o600))
    elif mutation == "registry_mode":
        journal["registry"]["after"]["mode"] = 0o644
    elif mutation == "instruction_type":
        journal["request"]["instruction"] = 3
    elif mutation == "instruction_missing":
        journal["request"]["instruction"] = "other"
    elif mutation == "target_name":
        journal["target_name"] = "foreign.json"
    elif mutation == "unknown_version":
        journal["version"] = 2
    else:
        journal = None
    journal_path.write_text(json.dumps(journal))
    before = mj._snapshot(path), mj._snapshot(sides(path)[0]), journal_path.read_bytes()
    with pytest.raises(mj.ManagedJSONError):
        apply(path)
    assert (mj._snapshot(path), mj._snapshot(sides(path)[0]), journal_path.read_bytes()) == before


@pytest.mark.parametrize(
    "raw", [b"null", b"[]", b'{"version":2}', b'{"version":1,"version":1}', b"{"]
)
def test_invalid_registry_never_treated_as_absent(tmp_path, raw):
    path = setup(tmp_path)
    state = sides(path)[0]
    state.write_bytes(raw)
    state.chmod(0o600)
    with pytest.raises(mj.ManagedJSONError):
        apply(path)
    assert not path.exists() and state.read_bytes() == raw


def test_recovery_then_different_request_replans(tmp_path):
    path = setup(tmp_path)
    process = stopped_process(path, "target_replaced")
    process.kill()
    process.wait(timeout=10)
    desired = copy.deepcopy(EFFECT)
    desired["content"]["timeout"] = 10
    apply(path, [desired])
    assert json.loads(path.read_bytes())["hooks"]["PreToolUse"][0]["hooks"] == [desired["content"]]
    assert json.loads(sides(path)[0].read_bytes())["effects"] == [desired]


def test_scope_normalizes_parent_traversal(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    target = project / "../outside/settings.json"
    with pytest.raises(mj.ManagedJSONError, match="outside project"):
        mj.apply_managed_hooks(
            target, project_root=project, effects=[EFFECT], instruction="skills/graphify/SKILL.md"
        )
    assert not (tmp_path / "outside").exists()


def test_integer_decoder_limit_is_controlled(tmp_path):
    path = setup(tmp_path)
    path.write_bytes(b'{"huge":' + b"1" * 5000 + b"}")
    before = path.read_bytes()
    with pytest.raises(mj.ManagedJSONError, match="invalid JSON"):
        apply(path)
    assert path.read_bytes() == before
