"""Filesystem publication, reservation, and evidence portability on this host."""

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tests.install_sandbox.component.host.output_support import START, refused
from tools.install_sandbox.host import output_lifecycle, output_storage
from tools.install_sandbox.host.docker_runtime import SignalCapture
from tools.install_sandbox.host.output_storage import move_exclusive


@pytest.mark.parametrize(
    "output", ["out", "out/in-progress", "out/in-progress/nested", "out/.lock"]
)
def test_management_paths_are_refused_before_work(tmp_path: Path, output: str) -> None:
    result = refused(tmp_path, output=tmp_path / output)
    assert result.exit_code == 2 and result.output_directory is None
    assert not list((tmp_path / "out").glob("in-progress/*/campaign.json"))


def test_collisions_consider_final_work_and_reserved_destinations(tmp_path: Path) -> None:
    first = refused(tmp_path)
    assert first.output_directory is not None
    (tmp_path / "out/in-progress/20260917T143012Z-02").mkdir()
    third = refused(tmp_path)
    assert third.output_directory == tmp_path / "out/20260917T143012Z-03"
    assert first.output_directory.exists()


def test_native_move_refuses_even_an_empty_existing_destination(tmp_path: Path) -> None:
    source, final = tmp_path / "source", tmp_path / "final"
    source.mkdir()
    (source / "keep").write_text("source evidence")
    final.mkdir()
    inode = final.stat().st_ino
    with pytest.raises(FileExistsError):
        move_exclusive(source, final)
    assert final.stat().st_ino == inode and list(final.iterdir()) == []
    assert (source / "keep").read_text() == "source evidence"
    final.rmdir()
    move_exclusive(source, final)
    assert not source.exists() and (final / "keep").is_file()


def test_unavailable_native_primitive_refuses_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unsupported(*args: object, **kwargs: object) -> None:
        raise OSError("controlled filesystem lacks exclusive rename")

    monkeypatch.setattr(output_storage, "move_exclusive", unsupported)
    result = refused(tmp_path)
    assert result.exit_code == 2 and result.output_directory is None
    assert "exclusive rename" in result.report.render()
    assert not list((tmp_path / "out").rglob("campaign.json"))


def test_binary_empty_hidden_entries_survive_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = output_lifecycle.archive_evidence

    def add_files(directory: Path, interrupts: SignalCapture) -> None:
        evidence = directory / "evidence"
        (evidence / ".hidden").write_bytes(bytes(range(256)))
        (evidence / "empty-file").touch()
        (evidence / "empty-directory").mkdir()
        archive(directory, interrupts)

    monkeypatch.setattr(output_lifecycle, "archive_evidence", add_files)
    result = refused(tmp_path)
    assert result.output_directory is not None
    with zipfile.ZipFile(result.output_directory / "evidence.zip") as saved:
        assert saved.read("evidence/.hidden") == bytes(range(256))
        assert saved.read("evidence/empty-file") == b""
        assert "evidence/empty-directory/" in saved.namelist()
        assert not any("evidence.zip" in name for name in saved.namelist())


def test_archive_rejects_external_symlink_without_removing_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    external = tmp_path / "foreign"
    external.write_text("keep")
    archive = output_lifecycle.archive_evidence

    def add_link(directory: Path, interrupts: SignalCapture) -> None:
        (directory / "evidence/link").symlink_to(external)
        archive(directory, interrupts)

    monkeypatch.setattr(output_lifecycle, "archive_evidence", add_link)
    result = refused(tmp_path)
    assert result.exit_code != 0 and result.output_directory is not None
    assert external.read_text() == "keep"
    assert (result.output_directory / "evidence/link").is_symlink()
    assert not (result.output_directory / "evidence.zip").exists()


def test_simultaneous_processes_reserve_different_names(tmp_path: Path) -> None:
    (tmp_path / "subject").mkdir()
    code = (
        "from datetime import datetime; from pathlib import Path; import sys; "
        "from tools.install_sandbox.host.output_lifecycle import CampaignOutput; "
        "root=Path(sys.argv[1]); "
        f"clock=lambda: datetime.fromisoformat({START.isoformat()!r}); "
        "result=CampaignOutput(managed_root=root/'out',now=clock).run("
        "spec_file=root/'missing-effects.yaml',subject_context_file=root/'context.json',"
        "subject_checkout=root/'subject'); "
        "print(result.output_directory)"
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(tmp_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(3)
    ]
    try:
        paths: list[Path] = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=15)
            assert process.returncode == 0, stderr
            paths.append(Path(stdout.strip()))
        assert len(set(paths)) == 3
        assert {p.name for p in paths} == {
            "20260917T143012Z",
            "20260917T143012Z-02",
            "20260917T143012Z-03",
        }
        assert all((p / "campaign.json").is_file() for p in paths)
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)


def test_foreign_and_symlinked_outputs_are_never_adopted(tmp_path: Path) -> None:
    foreign = tmp_path / "outside"
    foreign.mkdir()
    (foreign / "keep").write_text("foreign")
    (tmp_path / "out").mkdir()
    (tmp_path / "out/link").symlink_to(foreign, target_is_directory=True)
    (tmp_path / "out/legacy").mkdir()
    (tmp_path / "out/legacy/campaign.json").write_text(json.dumps({"passed": True}))
    result = refused(tmp_path)
    assert foreign.is_dir() and (foreign / "keep").read_text() == "foreign"
    assert (tmp_path / "out/legacy/campaign.json").is_file()
    assert len(result.report.diagnostics) >= 3


def test_automatic_name_skips_empty_final_and_in_progress_entries(tmp_path: Path) -> None:
    (tmp_path / "out/20260917T143012Z").mkdir(parents=True)
    (tmp_path / "out/in-progress/20260917T143012Z-02").mkdir(parents=True)
    result = refused(tmp_path)
    assert result.output_directory == tmp_path / "out/20260917T143012Z-03"
    assert list((tmp_path / "out/20260917T143012Z").iterdir()) == []


def test_explicit_nested_destination_remains_reserved_after_publication_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object) -> None:
        raise OSError("controlled publication failure")

    monkeypatch.setattr(output_lifecycle, "move_exclusive", fail)
    first = refused(tmp_path, output=tmp_path / "out/group/final")
    assert (
        first.output_directory is not None and first.output_directory.parent.name == "in-progress"
    )
    for output in [
        tmp_path / "out/group",
        tmp_path / "out/group/final",
        tmp_path / "out/group/final/nested",
    ]:
        result = refused(tmp_path, output=output)
        assert result.exit_code == 2 and result.output_directory is None
    assert (first.output_directory / "evidence.zip").is_file()
