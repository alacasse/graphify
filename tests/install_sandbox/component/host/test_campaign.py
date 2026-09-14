"""Campaign behavior through the controlled Docker CLI and actual case evidence."""

import json
import signal
import time
from pathlib import Path

import pytest

from tests.install_sandbox.component.container.preserve_skill_backup_support import arrange_backup
from tests.install_sandbox.component.host.campaign_support import (
    COMPONENT,
    SPECS,
    campaign,
    commands,
)
from tools.install_sandbox.host.coordinator import InstallTestCoordinator


def test_two_cases_share_image_but_not_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arrange_backup(tmp_path, monkeypatch)
    result = campaign(tmp_path)
    assert result.passed, result
    calls = commands(tmp_path)
    builds = [c for c in calls if c[0] == "build"]
    runs = [c for c in calls if c[0] == "run"]
    assert len(builds) == 1 and len(runs) == 3
    assert any(a.endswith("/verify_preparation.py") for a in runs[0]) and all(
        not any(a.endswith("/verify_preparation.py") for a in c) for c in runs[1:]
    )
    assert result.preparation is not None
    assert all(result.preparation.image_id in c for c in runs)
    assert len({c[c.index("--name") + 1] for c in runs}) == 3
    for entry in result.cases:
        assert entry.result is not None and entry.result.passed
        assert (entry.output_directory / "expected.json").is_file()
        assert not (
            entry.output_directory / "steps/0/before/project/.sandbox-reference/skills"
        ).exists()
        assert "pip" not in (entry.output_directory / "preparation.log").read_text()
    assert result.cases[0].result != result.cases[1].result
    assert not list((tmp_path / "runtime").glob("image-*"))
    assert not list((tmp_path / "runtime").glob("container-*"))
    saved = json.loads((tmp_path / "campaign/campaign.json").read_text())
    assert saved["passed"] and len(saved["cases"]) == 2
    assert (tmp_path / "campaign/preparation/build.log").read_text().count(
        "controlled package preparation"
    ) == 1


@pytest.mark.parametrize(
    "mode",
    [
        "build_fail",
        "invalid_image_id",
        "missing_image_id",
        "verify_fail",
        "verify_cleanup_fail",
        "build_timeout",
        "verify_timeout",
        "verify_interrupt",
    ],
)
def test_common_failure_never_invents_case_verdicts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    arrange_backup(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_MODE", mode)
    result = campaign(tmp_path, timeout=0.3 if "timeout" in mode else 5)
    assert not result.passed and result.preparation is not None
    assert result.preparation.state != "completed"
    assert all(c.result is None and c.not_run_reason for c in result.cases)
    assert not list((tmp_path / "campaign").rglob("result.json"))
    assert not any(
        c[0] == "run" and not any(a.endswith("/verify_preparation.py") for a in c)
        for c in commands(tmp_path)
    )
    assert result.cleanup is not None
    assert (tmp_path / "campaign/preparation/build.log").is_file()


@pytest.mark.parametrize("mode", ["run_fail", "invalid_result", "run_timeout", "business_failure"])
def test_case_failure_continues_after_confirmed_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    arrange_backup(
        tmp_path, monkeypatch, "first_failure" if mode == "business_failure" else "passed"
    )
    if mode != "business_failure":
        monkeypatch.setenv("FAKE_DOCKER_MODE", mode)
    if mode in {"invalid_result", "run_timeout"}:
        monkeypatch.delenv("FAKE_DOCKER_CASE_PROGRAM")
    result = campaign(tmp_path, timeout=0.3 if mode == "run_timeout" else 5)
    assert not result.passed
    assert all(c.result is not None and c.result.container.cleanup_complete for c in result.cases)
    assert len([c for c in commands(tmp_path) if c[0] == "run"]) == 3
    assert all(c.not_run_reason is None for c in result.cases)


@pytest.mark.parametrize("mode", ["container_cleanup_fail", "run_interrupt"])
def test_stops_after_unsafe_cleanup_or_user_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    arrange_backup(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_MODE", mode)
    if mode == "run_interrupt":
        monkeypatch.delenv("FAKE_DOCKER_CASE_PROGRAM")
    result = campaign(tmp_path)
    assert not result.passed and result.cases[0].result is not None
    assert result.cases[1].result is None and result.cases[1].not_run_reason
    assert len([c for c in commands(tmp_path) if c[0] == "run"]) == 2
    assert result.cleanup is not None


def test_final_cleanup_failure_preserves_passed_cases_and_foreign_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arrange_backup(tmp_path, monkeypatch)
    state = tmp_path / "runtime"
    state.mkdir()
    foreign = state / "container-foreign"
    foreign.write_text("keep")
    monkeypatch.setenv("FAKE_DOCKER_MODE", "cleanup_fail")
    result = campaign(tmp_path)
    assert not result.passed and all(c.result is not None and c.result.passed for c in result.cases)
    assert result.cleanup is not None and not result.cleanup.cleanup_complete
    assert foreign.read_text() == "keep"
    calls = commands(tmp_path)
    assert not any("prune" in c for c in calls)
    removal = next(c for c in calls if c[:2] == ["image", "rm"])
    assert removal[-1].startswith("install-sandbox-campaign:")
    assert (tmp_path / "campaign/campaign.json").is_file()


@pytest.mark.parametrize(
    "names", [(), ("first-install", "unknown"), ("first-install", "first-install")]
)
def test_entire_selection_validated_before_writes_or_docker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    names: tuple[str, ...],
) -> None:
    arrange_backup(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        campaign(tmp_path, names)
    assert not (tmp_path / "campaign").exists() and not commands(tmp_path)


def test_interrupt_during_read_preserves_first_and_does_not_start_second(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arrange_backup(tmp_path, monkeypatch)
    read = Path.read_text

    def interrupted(path: Path, *args: object, **kwargs: object) -> str:
        if path == tmp_path / "campaign/cases/first-install/result.json":
            signal.raise_signal(signal.SIGINT)
        return read(path)

    monkeypatch.setattr(Path, "read_text", interrupted)
    result = campaign(tmp_path)
    assert result.cases[0].result is not None and result.cases[0].result.passed
    assert result.cases[1].result is None and "interrupted" in (
        result.cases[1].not_run_reason or ""
    )
    assert not result.passed and result.cleanup is not None and result.cleanup.cleanup_complete


def test_common_and_individual_times_are_counted_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arrange_backup(tmp_path, monkeypatch)
    ticks = [0]
    monkeypatch.setattr(time, "monotonic_ns", lambda: ticks[0])
    read = Path.read_text

    def timed_read(path: Path, *args: object, **kwargs: object) -> str:
        if path.name == "image-id":
            ticks[0] += 10_000_000_000
        if path.name == "result.json":
            ticks[0] += 2_000_000_000
        return read(path)

    monkeypatch.setattr(Path, "read_text", timed_read)
    result = campaign(tmp_path)
    assert result.passed and result.duration_seconds == 14
    assert sum(t.duration_seconds or 0 for t in result.timings) == 10
    assert [c.result.duration_seconds for c in result.cases if c.result] == [2, 2]


@pytest.mark.parametrize("kind", ["overlap", "nonempty", "symlink", "comma"])
def test_campaign_destinations_refused_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    arrange_backup(tmp_path, monkeypatch)
    output = tmp_path / "campaign"
    if kind == "overlap":
        output = tmp_path / "subject/new/output"
    elif kind == "nonempty":
        output.mkdir()
        (output / "keep").write_text("existing evidence")
    elif kind == "symlink":
        output.symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    else:
        output = tmp_path / "comma,output"
    with pytest.raises(ValueError):
        InstallTestCoordinator().run_campaign(
            specs_directory=SPECS,
            target="sandbox-reference",
            case_names=["first-install"],
            subject_checkout=tmp_path / "subject",
            output_directory=output,
            runtime_executable=COMPONENT.parent / "host/fake_docker.py",
        )
    assert not commands(tmp_path)
    assert not (tmp_path / "subject/new").exists()
    if kind == "nonempty":
        assert (output / "keep").read_text() == "existing evidence"


def test_case_progress_is_saved_before_execution_and_completed_results_survive_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arrange_backup(tmp_path, monkeypatch)
    adapter = COMPONENT.parent / "container/controlled_backup_case.py"
    wrapper = tmp_path / "observe-progress.py"
    wrapper.write_text(
        "import json, runpy, sys\nfrom pathlib import Path\n"
        "root = Path(sys.argv[3]).parents[1]\n"
        "states = [c['state'] for c in json.loads((root / 'campaign.json').read_text())['cases']]\n"
        "with (root / 'observed-progress.jsonl').open('a') as stream:\n"
        "    stream.write(json.dumps(states) + '\\n')\n"
        f"runpy.run_path({str(adapter)!r}, run_name='__main__')\n"
    )
    monkeypatch.setenv("FAKE_DOCKER_CASE_PROGRAM", str(wrapper))
    result = campaign(tmp_path)
    assert result.passed
    observations = [
        json.loads(line)
        for line in (tmp_path / "campaign/observed-progress.jsonl").read_text().splitlines()
    ]
    assert observations == [["running", "pending"], ["finished", "running"]]


def test_temporary_context_cannot_be_created_inside_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tempfile

    arrange_backup(tmp_path, monkeypatch)
    original = sorted(
        str(p.relative_to(tmp_path / "subject")) for p in (tmp_path / "subject").rglob("*")
    )
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "subject"))
    result = campaign(tmp_path)
    assert not result.passed and result.preparation is not None
    assert "Temporary build context" in result.preparation.detail
    assert (
        sorted(str(p.relative_to(tmp_path / "subject")) for p in (tmp_path / "subject").rglob("*"))
        == original
    )
    assert not commands(tmp_path)


def test_all_destinations_are_prepared_before_docker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arrange_backup(tmp_path, monkeypatch)
    mkdir = Path.mkdir

    def denied(
        path: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False
    ) -> None:
        if path == tmp_path / "campaign/cases/preserve-skill-backup":
            raise PermissionError("Controlled evidence destination refusal")
        mkdir(path, mode, parents, exist_ok)

    monkeypatch.setattr(Path, "mkdir", denied)
    with pytest.raises(PermissionError, match="Controlled evidence destination refusal"):
        campaign(tmp_path)
    assert not commands(tmp_path)


def test_expected_contents_come_from_captured_sources_after_checkout_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arrange_backup(tmp_path, monkeypatch)
    read = Path.read_text
    original = (tmp_path / "subject/graphify/skill.md").read_bytes()

    def mutate_checkout(path: Path, *args: object, **kwargs: object) -> str:
        if path.name == "image-id":
            (tmp_path / "subject/graphify/skill.md").write_text("Changed after capture")
        return read(path)

    monkeypatch.setattr(Path, "read_text", mutate_checkout)
    result = campaign(tmp_path)
    assert result.passed
    assert (tmp_path / "subject/graphify/skill.md").read_text() == "Changed after capture"
    assert all(
        (entry.output_directory / "expected/graphify/skill.md").read_bytes() == original
        for entry in result.cases
    )
