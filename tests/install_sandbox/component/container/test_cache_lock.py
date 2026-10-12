"""Declared cache effects stay exact, observable and independently specified."""

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from tests.install_sandbox.component.container.observations_verifier_support import (
    assert_passed,
    put,
    scenario,
)
from tools.install_sandbox.container.verifier import InstallVerifier
from tools.install_sandbox.contracts.spec import InstallTestSpec


def test_lock_uses_skill_directory_and_home_despite_xdg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "elsewhere"))
    local = scenario(tmp_path, renamed=True)
    skill = local.path("skill").parent.resolve()
    digest = hashlib.sha256(str(skill).encode("utf-8")).hexdigest()[:16]
    assert local.expected.skill_lock == f".cache/graphify/skill-locks/{digest}.lock"
    assert local.expected.skill_lock == local.environment.skill_lock
    local.effects()
    assert_passed(local.verify())
    assert not (tmp_path / "elsewhere").exists()


def test_preexisting_binary_lock_and_neighbors_preserved(tmp_path: Path) -> None:
    local = scenario(tmp_path)
    assert local.expected.skill_lock is not None
    lock = local.environment.home / local.expected.skill_lock
    witnesses = {
        lock: b"\x00persistent\xff",
        lock.parent / "foreign.lock": b"foreign",
        lock.parent / "personal.txt": b"personal",
    }
    for path, content in witnesses.items():
        put(path, content)
    local.before = local.environment.observe(local.writer, "before")
    local.effects()
    assert_passed(local.verify())
    local.before = local.environment.observe(local.writer, "before", step_index=1)
    assert_passed(local.verify())
    assert all(path.read_bytes() == content for path, content in witnesses.items())


@pytest.mark.parametrize(
    "damage", ["missing", "wrong_name", "extra", "content", "symlink", "foreign", "personal"]
)
def test_rejects_cache_counterexamples(tmp_path: Path, damage: str) -> None:
    local = scenario(tmp_path)
    assert local.expected.skill_lock is not None
    lock = local.environment.home / local.expected.skill_lock
    for name in ("foreign.lock", "personal.txt"):
        put(lock.parent / name, b"keep")
    local.before = local.environment.observe(local.writer, "before")
    local.effects()
    if damage == "missing":
        lock.unlink()
    elif damage == "wrong_name":
        lock.rename(lock.parent / "wrong.lock")
    elif damage == "extra":
        put(lock.parent / "extra.lock", b"")
    elif damage == "content":
        lock.write_bytes(b"unexpected")
    elif damage == "symlink":
        lock.unlink()
        lock.symlink_to(lock.parent / "foreign.lock")
    else:
        (lock.parent / ("foreign.lock" if damage == "foreign" else "personal.txt")).write_bytes(
            b"changed"
        )
    result = local.verify()
    assert result.mismatches or not result.complete
    if damage == "symlink":
        assert not result.complete


def test_undeclared_lock_effect_is_rejected(tmp_path: Path) -> None:
    local = scenario(tmp_path)
    local.case = replace(local.case, spec=replace(local.case.spec, skill_lock=None))
    local.expected.skill_lock = None
    local.effects()
    assert any(item.root == "home" for item in local.verify().mismatches)


@pytest.mark.parametrize("value", [None, "temporary", True, {}, []])
def test_unsupported_lock_declaration_is_rejected(tmp_path: Path, value: object) -> None:
    data = scenario(tmp_path).case.spec.to_data()
    cast(dict[str, object], data["skill"])["lock"] = value
    with pytest.raises(ValueError, match="persistent"):
        InstallTestSpec.from_data(data)


def test_unobservable_lock_cannot_pass(tmp_path: Path) -> None:
    local = scenario(tmp_path)
    local.effects()
    after = local.environment.observe(local.writer, "after")
    assert local.expected.skill_lock is not None
    del after.contents[("home", local.expected.skill_lock)]
    result = InstallVerifier().verify(local.case, local.expected, local.before, after)
    assert not result.complete
    assert any(obstacle["operation"] == "read_lock" for obstacle in result.obstacles)


def test_absent_declaration_allows_installation_without_cache(tmp_path: Path) -> None:
    local = scenario(tmp_path)
    local.case = replace(local.case, spec=replace(local.case.spec, skill_lock=None))
    local.environment.skill_lock = None
    local.expected.skill_lock = None
    local.effects()
    assert_passed(local.verify())
    assert "lock" not in cast(dict[str, object], local.case.spec.to_data()["skill"])
