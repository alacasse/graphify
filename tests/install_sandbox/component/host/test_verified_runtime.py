"""The runtime admits cases only after independent installed preparation checks."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from tools.install_sandbox.contracts.effect_case import (
    EffectRules,
    SubjectContext,
    build_reinstall_case,
)
from tools.install_sandbox.contracts.effects import Destination, EffectSpec, SkillEffect
from tools.install_sandbox.host.docker_runtime import ContainerHarness

_FAKE = Path(__file__).with_name("fake_docker.py")


def arrange(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[EffectSpec, SubjectContext]:
    monkeypatch.setenv("FAKE_DOCKER_STATE", str(tmp_path / "runtime"))
    subject = tmp_path / "subject"
    references = subject / "graphify/skills/codebuddy/references"
    references.mkdir(parents=True)
    (references / "read.md").write_text("retained reference")
    (subject / "graphify/skill.md").write_text("retained skill")
    (subject / "pyproject.toml").write_text(
        '[project]\nname="graphifyy"\nversion="1.2.3"\n'
        '[project.scripts]\ngraphify="graphify.cli:main"\n'
    )
    context = SubjectContext(
        "candidate",
        ("/opt/install-sandbox/venv/bin/graphify",),
        "package-metadata",
        EffectRules(10, "persistent", ".graphify-bak", ".bak", False),
        package_root="graphify",
        revision="b" * 40,
    )
    effects = EffectSpec(
        (
            SkillEffect(
                "skill.md",
                "skills/codebuddy/references",
                Destination("project", ".skills/graphify"),
            ),
        )
    )
    build_reinstall_case(effects, context).write(tmp_path / "case.json")
    return effects, context


def test_verified_image_binds_expected_sources_and_subject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    effects, context = arrange(tmp_path, monkeypatch)
    with ContainerHarness(runtime_executable=_FAKE) as harness:
        try:
            prepared = harness.prepare(
                tmp_path / "subject", tmp_path / "proof", effects=effects, subject_context=context
            )
            assert prepared.state == "completed"
            assert harness.preparation_result is not None
            assert harness.preparation_result.status == "prepared"
            harness.run_case(case_file=tmp_path / "case.json", output_directory=tmp_path / "case")
            assert (tmp_path / "proof/expected/skill.md").read_text() == "retained skill"
            calls = [
                json.loads(path.read_text()) for path in (tmp_path / "runtime").glob("command-*")
            ]
            run = next(call for call in calls if "--reference-sources" in call)
            assert run[run.index("--reference-sources") + 1] == "/opt/install-sandbox/expected"
            assert "--network=none" in run
        finally:
            harness.cleanup()


@pytest.mark.parametrize("fault", ["version", "resource", "image_id", "missing-observation"])
def test_unverified_package_never_becomes_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    effects, context = arrange(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_PREPARATION_FAULT", fault)
    with ContainerHarness(runtime_executable=_FAKE) as harness:
        try:
            prepared = harness.prepare(
                tmp_path / "subject", tmp_path / "proof", effects=effects, subject_context=context
            )
            assert prepared.state == "incomplete"
            assert not harness.ready
            expected = (
                "incomplete" if fault in {"missing-observation", "image_id"} else "nonconformant"
            )
            assert harness.preparation_result is not None
            assert harness.preparation_result.status == expected
            with pytest.raises(ValueError, match="not available"):
                harness.run_case(
                    case_file=tmp_path / "case.json", output_directory=tmp_path / "case"
                )
        finally:
            harness.cleanup()


@pytest.mark.parametrize(
    "mismatch", ["identity", "revision", "image_id", "version_source", "invocation", "binding"]
)
def test_case_binding_mismatch_prevents_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mismatch: str
) -> None:
    effects, context = arrange(tmp_path, monkeypatch)
    with ContainerHarness(runtime_executable=_FAKE) as harness:
        try:
            harness.prepare(
                tmp_path / "subject", tmp_path / "proof", effects=effects, subject_context=context
            )
            if mismatch == "image_id":
                harness.image_id = "sha256:" + "f" * 64
            elif mismatch == "binding":
                assert harness.binding is not None
                harness.binding["subject_digest"] = "f" * 64
            else:
                values = {
                    "identity": "different",
                    "revision": "f" * 40,
                    "version_source": "other-metadata",
                    "invocation": ("different",),
                }
                altered = replace(context, **{mismatch: values[mismatch]})
                build_reinstall_case(effects, altered).write(tmp_path / "case.json")
            before = len(list((tmp_path / "runtime").glob("command-*")))
            with pytest.raises(ValueError, match="does not match"):
                harness.run_case(
                    case_file=tmp_path / "case.json", output_directory=tmp_path / "case"
                )
            assert len(list((tmp_path / "runtime").glob("command-*"))) == before
        finally:
            harness.cleanup()


@pytest.mark.parametrize("mode", ["daemon_fail", "build_fail", "verify_fail"])
def test_infrastructure_failure_is_retained_as_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    effects, context = arrange(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_MODE", mode)
    with ContainerHarness(runtime_executable=_FAKE) as harness:
        try:
            harness.prepare(
                tmp_path / "subject", tmp_path / "proof", effects=effects, subject_context=context
            )
            assert harness.preparation_result is not None
            assert harness.preparation_result.status == "incomplete"
            assert harness.preparation_result.binding is None
            assert not harness.ready
            assert (tmp_path / "proof/runtime.json").is_file()
            assert (
                json.loads((tmp_path / "proof/result.json").read_text())["status"] == "incomplete"
            )
        finally:
            harness.cleanup()
