"""One user campaign: allocation, execution, evidence conservation and retention."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from tools.install_sandbox.host.build_context import validate_evidence_location
from tools.install_sandbox.host.coordinator import CampaignResult, InstallTestCoordinator
from tools.install_sandbox.host.docker_runtime import SignalCapture
from tools.install_sandbox.host.output_archive import archive_evidence, check_interrupt
from tools.install_sandbox.host.output_report import OutputReport, Writer
from tools.install_sandbox.host.output_retention import retain_finished
from tools.install_sandbox.host.output_storage import (
    FileLock,
    choose_paths,
    coordination,
    move_exclusive,
    safe_path,
    verify_publication,
)

_DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "out"


@dataclass(frozen=True)
class CampaignCommandResult:
    exit_code: int
    output_directory: Path | None
    report: OutputReport


class CampaignOutput:
    """Own the complete user path; direct coordinator calls keep their raw evidence."""

    def __init__(
        self,
        *,
        managed_root: Path = _DEFAULT_ROOT,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.root = managed_root
        self.now = now

    def run(
        self,
        *,
        specs_directory: Path,
        target: str,
        subject_checkout: Path,
        case_names: Sequence[str] | None = None,
        output_directory: Path | None = None,
        runtime_executable: str | Path = "docker",
    ) -> CampaignCommandResult:
        report = OutputReport(
            self.now().astimezone(UTC).isoformat(),
            str(output_directory or ""),
            None,
            str(subject_checkout),
            str(specs_directory),
            target,
            list(case_names) if case_names is not None else None,
        )
        session = _Session(self.root, report, self.now)
        with SignalCapture() as interrupts:
            return session.run(output_directory, str(runtime_executable), interrupts)


class _Session:
    def __init__(self, root: Path, report: OutputReport, now: Callable[[], datetime]) -> None:
        self.root, self.report, self.now = root, report, now
        self.directory: Path | None = None
        self.lock: FileLock | None = None

    def run(
        self, requested: Path | None, runtime: str, interrupts: SignalCapture
    ) -> CampaignCommandResult:
        try:
            self._allocate(requested)
            self._conduct(runtime, interrupts)
        except (Exception, KeyboardInterrupt) as error:
            self._record_error(error)
        finally:
            self._finish(runtime, interrupts)
        return CampaignCommandResult(self.report.exit_code, self.directory, self.report)

    def _conduct(self, runtime: str, interrupts: SignalCapture) -> None:
        try:
            check_interrupt(interrupts)
            self._execute(runtime, interrupts)
        except (Exception, KeyboardInterrupt) as error:
            self._record_error(error)
        self._finalize(interrupts)

    def _record_error(self, error: BaseException) -> None:
        if isinstance(error, KeyboardInterrupt):
            self.report.exit_code = 130
        elif self.report.phase == "allocated":
            self.report.exit_code = 2
        elif self.report.exit_code == 0:
            self.report.exit_code = 1
        self.report.diagnostics.append(f"{type(error).__name__}: {error}")
        self.report.phase = "incomplete"

    def _allocate(self, requested: Path | None) -> None:
        self.root = safe_path(self.root)
        destination = safe_path(requested) if requested is not None else None
        subject = Path(self.report.subject).expanduser().resolve()
        self.report.subject = str(subject)
        validate_evidence_location(subject, destination or self.root / "in-progress" / "pending")
        if destination is not None and not destination.is_relative_to(self.root):
            self._allocate_external(destination)
            return
        self.root.mkdir(parents=True, exist_ok=True)
        with coordination(self.root):
            work, final = choose_paths(
                self.root,
                datetime.fromisoformat(self.report.started_at).strftime("%Y%m%dT%H%M%SZ"),
                destination,
            )
            safe_path(work)
            safe_path(final)
            work.parent.mkdir(exist_ok=True)
            final.parent.mkdir(parents=True, exist_ok=True)
            verify_publication(work.parent, final.parent)
            self.report.destination, self.report.managed_root = str(final), str(self.root)
            work.mkdir()
            self.directory = work
            self._start_report()

    def _allocate_external(self, destination: Path) -> None:
        if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
            raise ValueError("External output must be fresh or empty")
        destination.mkdir(parents=True, exist_ok=True)
        self.report.destination = str(destination)
        self.directory = destination
        self._start_report()

    def _start_report(self) -> None:
        assert self.directory is not None
        lock = FileLock(self.directory / ".active.lock")
        if not lock.acquire(wait=False):
            lock.close()
            self.directory = None
            raise ValueError("Output is owned by an active campaign")
        self.lock = lock
        self._save()

    def _execute(self, runtime: str, interrupts: SignalCapture) -> None:
        assert self.directory is not None
        result = InstallTestCoordinator().run_campaign(
            specs_directory=Path(self.report.specs),
            target=self.report.target,
            subject_checkout=Path(self.report.subject),
            case_names=self.report.requested_cases,
            output_directory=self.directory / "evidence",
            runtime_executable=runtime,
            interrupts=interrupts,
            observer=self,
            progress=self._progress,
        )
        self.report.observe(result)
        self.report.exit_code = 0 if result.passed else 1
        self.report.phase = "executed"
        self.report.save(self.directory)

    def _progress(self, result: CampaignResult) -> None:
        assert self.directory is not None
        self.report.observe(result)
        self.report.phase = "running"
        self.report.raw_evidence = True
        self.report.save(self.directory)

    def before_launch(self, name: str, role: str, runtime: str, daemon_id: str) -> None:
        self.report.writers.append(Writer(name, role, runtime, daemon_id))
        self._save()

    def client_returned(self, name: str) -> None:
        self._writer(name).state = "returned"
        self._save()

    def stopped(self, name: str) -> None:
        self._writer(name).state = "stopped"
        self._save()

    def _writer(self, name: str) -> Writer:
        return next(writer for writer in self.report.writers if writer.name == name)

    def _save(self) -> None:
        assert self.directory is not None
        self.report.available_directory = str(self.directory)
        self.report.save(self.directory)

    def _finalize(self, interrupts: SignalCapture) -> None:
        assert self.directory is not None
        check_interrupt(interrupts)
        if any(writer.state != "stopped" for writer in self.report.writers):
            raise ValueError(
                "Writer termination uncertain; raw evidence retained for manual inspection"
            )
        (self.directory / "evidence").mkdir(exist_ok=True)
        self.report.raw_evidence = True
        self.report.phase, self.report.archive = "archiving", "pending"
        self._save()
        archive_evidence(self.directory, interrupts)
        self.report.archive = "verified"
        self._save()
        if self._remove_raw(interrupts):
            self._publish(interrupts)

    def _remove_raw(self, interrupts: SignalCapture) -> bool:
        assert self.directory is not None
        try:
            check_interrupt(interrupts)
            shutil.rmtree(self.directory / "evidence")
        except OSError as error:
            self.report.diagnostics.append(
                f"Verified archive retained; raw evidence removal failed: {error}"
            )
            self.report.phase = "raw-remains"
            return False
        self.report.raw_evidence = False
        self._save()
        return True

    def _publish(self, interrupts: SignalCapture) -> None:
        assert self.directory is not None
        check_interrupt(interrupts)
        if self.report.managed_root is not None:
            with coordination(self.root):
                destination = safe_path(Path(self.report.destination))
                move_exclusive(self.directory, destination)
                self.directory = destination
        self.report.phase = "finished"

    def _finish(self, runtime: str, interrupts: SignalCapture) -> None:
        if interrupts.signal_number is not None:
            self.report.exit_code = 128 + interrupts.signal_number
        if self.directory is None:
            return
        try:
            if all(writer.state == "stopped" for writer in self.report.writers):
                self.report.finished_at = self.now().isoformat()
            if self.report.managed_root is not None:
                self.report.diagnostics.extend(
                    retain_finished(self.root, self.directory, runtime, self.now)
                )
            if interrupts.signal_number is not None:
                self.report.exit_code = 128 + interrupts.signal_number
                self.report.diagnostics.append(f"Interrupted by signal {interrupts.signal_number}")
            self._save()
        except (Exception, KeyboardInterrupt) as error:
            self.report.exit_code = 1
            self.report.diagnostics.append(
                f"Final report or retention failed at {self.directory}: {error}"
            )
        finally:
            self._release()

    def _release(self) -> None:
        if self.lock is None or self.directory is None:
            return
        try:
            if self.report.managed_root is not None:
                with coordination(self.root):
                    self.lock.remove_file(self.directory / ".active.lock")
            else:
                self.lock.remove_file(self.directory / ".active.lock")
        except OSError as error:
            self.report.diagnostics.append(f"Activity lock retained at {self.directory}: {error}")
        finally:
            self.lock.close()
