from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FAST_WORKFLOW = PROJECT_ROOT / ".github/workflows/install-sandbox-fast.yml"
COMPLETE_WORKFLOW = PROJECT_ROOT / ".github/workflows/install-sandbox.yml"
CI_WORKFLOW = PROJECT_ROOT / ".github/workflows/ci.yml"
SANDBOX_README = PROJECT_ROOT / "tools/install_sandbox/README.md"
SANDBOX_AGENTS = PROJECT_ROOT / "tools/install_sandbox/AGENTS.md"
CHANGELOG = PROJECT_ROOT / "CHANGELOG.md"
QUALITY_COMMAND = "uv run --frozen --python 3.12 python scripts/install_sandbox_quality.py"
DOCUMENTED_QUALITY_COMMANDS = (
    f"{QUALITY_COMMAND} fast",
    f"{QUALITY_COMMAND} complete",
    f"{QUALITY_COMMAND} prove",
    f"{QUALITY_COMMAND} docker --target <target>",
    f"{QUALITY_COMMAND} docker --all",
)


def _mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, Mapping)
    return cast(Mapping[str, object], value)


def _workflow(path: Path) -> Mapping[str, object]:
    document = cast(
        object,
        yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader),
    )
    return _mapping(document)


def _run_blocks(job: Mapping[str, object]) -> tuple[str, ...]:
    steps = job.get("steps")
    assert isinstance(steps, list)
    return tuple(
        run
        for step in steps
        if isinstance(step, Mapping)
        for run in (step.get("run"),)
        if isinstance(run, str)
    )


def _steps(job: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    steps = job.get("steps")
    assert isinstance(steps, list)
    return tuple(_mapping(step) for step in steps)


def _command_owner_alignment_problems(repository: Path) -> tuple[str, ...]:
    problems = []
    workflow_commands = {
        FAST_WORKFLOW.relative_to(PROJECT_ROOT): f"{QUALITY_COMMAND} fast",
        COMPLETE_WORKFLOW.relative_to(PROJECT_ROOT): f"{QUALITY_COMMAND} complete",
    }
    for relative_path, expected in workflow_commands.items():
        jobs = _mapping(_workflow(repository / relative_path)["jobs"])
        commands = tuple(
            command
            for job in jobs.values()
            for command in _run_blocks(_mapping(job))
        )
        if expected not in commands:
            problems.append(f"{relative_path} does not invoke {expected}")

    for source in (SANDBOX_README, SANDBOX_AGENTS):
        relative_path = source.relative_to(PROJECT_ROOT)
        normalized = " ".join((repository / relative_path).read_text(encoding="utf-8").split())
        for expected in DOCUMENTED_QUALITY_COMMANDS:
            if expected not in normalized:
                problems.append(f"{relative_path} does not document {expected}")
    return tuple(problems)


def test_every_pull_request_runs_the_canonical_fast_gate() -> None:
    workflow = _workflow(FAST_WORKFLOW)
    assert workflow["name"] == "Install sandbox fast"

    triggers = _mapping(workflow["on"])
    assert set(triggers) == {"pull_request"}
    pull_request = _mapping(triggers["pull_request"])
    assert not pull_request

    jobs = _mapping(workflow["jobs"])
    fast = _mapping(jobs["install-sandbox-fast"])
    assert fast["name"] == "Install sandbox fast"
    assert "if" not in fast
    assert "continue-on-error" not in fast

    commands = _run_blocks(fast)
    assert f"{QUALITY_COMMAND} fast" in commands
    fast_steps = tuple(
        step for step in _steps(fast) if step.get("run") == f"{QUALITY_COMMAND} fast"
    )
    assert len(fast_steps) == 1
    assert "if" not in fast_steps[0]
    assert "continue-on-error" not in fast_steps[0]
    assert not any(
        duplicate in "\n".join(commands)
        for duplicate in (
            "ruff ",
            "pyright ",
            "bandit ",
            "pip-audit ",
            "tools/install_sandbox/run.py",
        )
    )


def test_complete_gate_owns_merge_manual_and_nightly_evidence() -> None:
    workflow = _workflow(COMPLETE_WORKFLOW)
    triggers = _mapping(workflow["on"])
    assert "pull_request" not in triggers

    push = _mapping(triggers["push"])
    assert push["branches"] == ["v8", "main"]
    assert "paths" not in push
    assert "paths-ignore" not in push
    assert "workflow_dispatch" in triggers
    assert triggers["schedule"] == [{"cron": "27 5 * * *"}]

    jobs = _mapping(workflow["jobs"])
    complete = _mapping(jobs["install-sandbox-complete"])
    assert complete["name"] == "Install sandbox complete"
    assert "if" not in complete
    assert "continue-on-error" not in complete

    commands = _run_blocks(complete)
    assert f"{QUALITY_COMMAND} complete" in commands
    assert not any(
        duplicate in "\n".join(commands)
        for duplicate in (
            "ruff ",
            "pyright ",
            "bandit ",
            "pip-audit ",
            "tools/install_sandbox/run.py",
            "tools.install_sandbox.ci_result",
        )
    )

    steps = complete["steps"]
    assert isinstance(steps, list)
    artifact_steps = [
        step
        for step in steps
        if isinstance(step, Mapping)
        and isinstance(step.get("uses"), str)
        and step["uses"].startswith("actions/upload-artifact@")
    ]
    assert len(artifact_steps) == 1
    assert artifact_steps[0]["if"] == "always()"


def test_complete_gate_defers_runner_context_until_a_step_runs() -> None:
    workflow = _workflow(COMPLETE_WORKFLOW)
    jobs = _mapping(workflow["jobs"])
    complete = _mapping(jobs["install-sandbox-complete"])

    job_environment = _mapping(complete.get("env", {}))
    assert not any(
        "${{ runner." in value
        for value in job_environment.values()
        if isinstance(value, str)
    )

    gate_step = next(
        step
        for step in _steps(complete)
        if step.get("run") == f"{QUALITY_COMMAND} complete"
    )
    gate_environment = _mapping(gate_step["env"])
    assert gate_environment["TMPDIR"] == "${{ runner.temp }}"


def test_python_310_feedback_excludes_python_312_install_sandbox_tests() -> None:
    workflow = _workflow(CI_WORKFLOW)
    jobs = _mapping(workflow["jobs"])
    test_job = _mapping(jobs["test"])
    matrix = _mapping(_mapping(test_job["strategy"])["matrix"])
    assert matrix["python-version"] == ["3.10", "3.12"]

    steps = _steps(test_job)
    python_310 = next(step for step in steps if step.get("name") == "Run tests on Python 3.10")
    assert python_310["if"] == "matrix.python-version == '3.10'"
    command = python_310["run"]
    assert isinstance(command, str)
    assert "uv run --frozen --python 3.10 pytest tests/" in command
    assert "--ignore=tests/install_sandbox" in command
    assert "--ignore=tests/quality_gate" in command
    assert "-W error" not in command

    python_312 = next(step for step in steps if step.get("name") == "Run tests on Python 3.12")
    assert python_312["if"] == "matrix.python-version == '3.12'"
    assert "--ignore=tests/install_sandbox" not in cast(str, python_312["run"])

    all_commands = "\n".join(run for job in jobs.values() for run in _run_blocks(_mapping(job)))
    assert "pyright --warnings tools/install_sandbox" not in all_commands
    assert "pip-audit" not in all_commands


def test_contributor_guidance_describes_the_same_quality_gate_contract() -> None:
    assert not _command_owner_alignment_problems(PROJECT_ROOT)
    required_fragments = (
        *DOCUMENTED_QUALITY_COMMANDS,
        "Gate installation",
        "Replacement construction",
        "Atomic cutover",
        "NOT APPLICABLE",
        "exit `0`",
        "exit `1`",
        "exit `2`",
        "exit `124`",
        "every pull request",
        "nightly",
        "exact commit",
    )
    for path in (SANDBOX_README, SANDBOX_AGENTS):
        guidance = path.read_text(encoding="utf-8")
        normalized = " ".join(guidance.split())
        for fragment in required_fragments:
            assert fragment in normalized, f"{path.relative_to(PROJECT_ROOT)} lacks {fragment!r}"

    changelog = CHANGELOG.read_text(encoding="utf-8")
    assert "behavior-free install-sandbox quality foundation" in changelog
    assert "(#48)" in changelog


def test_temporary_ci_and_local_command_owner_drift_is_detected(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    for source in (FAST_WORKFLOW, COMPLETE_WORKFLOW, SANDBOX_README, SANDBOX_AGENTS):
        destination = repository / source.relative_to(PROJECT_ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

    assert not _command_owner_alignment_problems(repository)

    complete_workflow = repository / COMPLETE_WORKFLOW.relative_to(PROJECT_ROOT)
    complete_workflow.write_text(
        complete_workflow.read_text(encoding="utf-8").replace(
            f"{QUALITY_COMMAND} complete",
            "uv run --frozen --python 3.12 pip-audit",
        ),
        encoding="utf-8",
    )
    readme = repository / SANDBOX_README.relative_to(PROJECT_ROOT)
    readme.write_text(
        readme.read_text(encoding="utf-8").replace(
            f"{QUALITY_COMMAND} prove",
            "uv run --frozen --python 3.12 pytest tests/quality_gate",
        ),
        encoding="utf-8",
    )

    problems = _command_owner_alignment_problems(repository)
    assert any("install-sandbox.yml does not invoke" in problem for problem in problems)
    assert any("README.md does not document" in problem for problem in problems)
