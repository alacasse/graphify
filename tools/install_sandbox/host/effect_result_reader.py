"""Recompute native effects verdicts using only retained evidence."""

from pathlib import Path, PurePosixPath

from tools.install_sandbox.container.effect_verifier import EffectVerifier
from tools.install_sandbox.container.environment import FilesystemSnapshot
from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.effects import MarkdownSectionEffect, SkillEffect
from tools.install_sandbox.contracts.results import (
    CommandEvidence,
    InstallTestResult,
    StepEvidence,
    VerificationResult,
)
from tools.install_sandbox.host.evidence_reader import (
    check_environment,
    check_snapshot,
    lock_expectation,
    read_json_evidence,
    retained_snapshot,
    safe_evidence_path,
    verification,
)


def _snapshot(output: Path, relative: str, *, complete: bool = True) -> FilesystemSnapshot:
    snapshot = retained_snapshot(output, relative)
    entries = check_snapshot(
        output,
        relative,
        complete=complete
        and not (relative == "expected.json" and not snapshot.entries and not snapshot.obstacles),
    )
    for entry in entries:
        key = (str(entry["root"]), str(entry["path"]))
        if (
            entry["kind"] == "file"
            and key not in snapshot.contents
            and not any((o["root"], o["path"]) == key for o in snapshot.obstacles)
        ):
            raise ValueError("Effects observation requires retained file bytes")
        if relative != "expected.json" and entry["path"] != ".":
            parent = str(PurePosixPath(str(entry["path"])).parent)
            parent_entry = snapshot.entry(key[0], parent)
            if parent_entry is None or parent_entry["kind"] != "directory":
                raise ValueError("Snapshot inventory requires each observed parent directory")
    return snapshot


def _expected_sources(
    case: EffectInstallCase, expected: FilesystemSnapshot, *, complete: bool = True
) -> None:
    required: dict[str, str] = {}
    for effect in case.effects.effects:
        if isinstance(effect, SkillEffect):
            required[effect.source] = "file"
            required[case.subject.version_source] = "file"
            required[effect.references] = "directory"
        elif isinstance(effect, MarkdownSectionEffect):
            required[effect.source] = "file"
    for path, kind in required.items():
        if not complete and (
            _source_obstructed(expected, path)
            or any(path.startswith(parent + "/") for parent in required)
        ):
            continue
        entry = expected.entry("subject", path)
        if entry is None or (complete and entry["kind"] != kind):
            raise ValueError(f"Missing retained effects source: {path}")


def _source_obstructed(expected: FilesystemSnapshot, path: str) -> bool:
    return any(
        obstacle["root"] == "subject"
        and (path == obstacle["path"] or path.startswith(obstacle["path"] + "/"))
        for obstacle in expected.obstacles
    )


def _same_observation(first: FilesystemSnapshot, second: FilesystemSnapshot) -> bool:
    def inventory(snapshot: FilesystemSnapshot) -> list[dict[str, object]]:
        return [
            {key: value for key, value in entry.items() if key != "content_file"}
            for entry in sorted(snapshot.entries, key=lambda entry: (entry["root"], entry["path"]))
        ]

    return (
        inventory(first) == inventory(second)
        and first.contents == second.contents
        and first.obstacles == second.obstacles
    )


def _lock_binding(case: EffectInstallCase, result: InstallTestResult, output: Path) -> None:
    skills = [effect for effect in case.effects.effects if isinstance(effect, SkillEffect)]
    if not skills:
        if (output / "skill-lock.json").exists():
            raise ValueError("Undeclared skill lock evidence")
        return
    home, skill_directory, _ = lock_expectation(output)
    effect = skills[0]
    for step in result.steps:
        command = step["command"]
        if command is None:
            continue
        project = PurePosixPath(command["cwd"])
        root = home if effect.destination.root == "home" else project
        if home != project.parent / "home" or skill_directory != root / effect.destination.path:
            raise ValueError("Skill lock contradicts effects destination or isolated roots")


def check_effect_result(result: InstallTestResult, case: EffectInstallCase, output: Path) -> None:
    """Bind case, sources, commands and verdicts after temporary inputs are removed."""
    retained_case = EffectInstallCase.from_json(
        safe_evidence_path(output, "case.json").read_text(encoding="utf-8")
    )
    if retained_case != case:
        raise ValueError("Retained effects case contradicts the requested case")
    safe_evidence_path(output, result.preparation["log"]).read_bytes()
    if not result.preparation["ready"]:
        _failed_initial_evidence(case, result, output)
        return
    if result.evidence != {"journal": "journal.log", "expected_contents": "expected/"}:
        raise ValueError("Prepared effects result requires source and journal references")
    safe_evidence_path(output, "journal.log").read_bytes()
    _lock_binding(case, result, output)
    expected, initial = _initial_evidence(case, output)
    _steps_evidence(case, result, output, expected, initial)


def _steps_evidence(
    case: EffectInstallCase,
    result: InstallTestResult,
    output: Path,
    expected: FilesystemSnapshot,
    initial: FilesystemSnapshot,
) -> None:
    verifier = EffectVerifier()
    previous = initial
    first_command: tuple[list[str], str] | None = None
    for index, step in enumerate(result.steps):
        command = step["command"]
        if "preparation" in step:
            raise ValueError("Reinstall effects case cannot contain intermediate preparation")
        if command is None:
            continue
        first_command = _command_binding(command, case, output, index, first_command)
        saved = _step_evidence(step, command, output, index)
        before = _snapshot(output, f"steps/{index}/before.json")
        if not _same_observation(previous, before):
            raise ValueError("Reinstall before observation contradicts the previous stage")
        after = _snapshot(output, f"steps/{index}/after.json", complete=saved.complete)
        if verifier.verify(case, expected, before, after) != saved:
            raise ValueError("Effects verification contradicts retained observations")
        previous = after


def _initial_evidence(
    case: EffectInstallCase, output: Path
) -> tuple[FilesystemSnapshot, FilesystemSnapshot]:
    expected = _snapshot(output, "expected.json")
    _expected_sources(case, expected)
    initial = _snapshot(output, "steps/0/before.json")
    verdict = EffectVerifier().verify_initial(case, expected, initial)
    saved = verification(read_json_evidence(output, "initial-verification.json"))
    if verdict != saved:
        raise ValueError("Initial verification differs from retained observations")
    if not verdict.complete or verdict.mismatches:
        raise ValueError("Initial effects preparation contradicts retained observations")
    return expected, initial


def _step_evidence(
    step: StepEvidence, command: CommandEvidence, output: Path, index: int
) -> VerificationResult:
    observations = step["observations"]
    if observations != {
        "before": f"steps/{index}/before.json",
        "after": f"steps/{index}/after.json",
    }:
        raise ValueError("Effects command requires its own before and after observations")
    for key, filename in (("stdout_file", "stdout.txt"), ("stderr_file", "stderr.txt")):
        relative = f"steps/{index}/{filename}"
        if command[key] != relative:
            raise ValueError("Effects command requires retained output for its own step")
        safe_evidence_path(output, relative).read_bytes()
    saved = verification(read_json_evidence(output, f"steps/{index}/verification.json"))
    if saved != step["verification"]:
        raise ValueError("Effects verification differs from its saved evidence")
    return saved


def _command_binding(
    command: CommandEvidence,
    case: EffectInstallCase,
    output: Path,
    index: int,
    first_command: tuple[list[str], str] | None,
) -> tuple[list[str], str]:
    if command["args"][1:] != list(case.subject.invocation):
        raise ValueError("Command contradicts explicit subject invocation")
    identity = (command["args"], command["cwd"])
    if first_command is None:
        first_command = identity
    elif identity != first_command:
        raise ValueError("Reinstallation must repeat the same command and isolated project")
    check_environment(command, output, index)
    return identity


def _failed_initial_evidence(
    case: EffectInstallCase, result: InstallTestResult, output: Path
) -> None:
    stage = result.preparation.get("stage")
    if stage in ("started", "sources_retained"):
        if (output / "initial-verification.json").is_symlink() or (
            output / "initial-verification.json"
        ).exists():
            raise ValueError("Preparation stage contradicts retained initial verification")
        safe_evidence_path(output, "journal.log").read_bytes()
        if stage == "sources_retained":
            expected = _snapshot(output, "expected.json", complete=False)
            _expected_sources(case, expected, complete=False)
        return
    if result.evidence["expected_contents"] != "expected/":
        return
    saved = verification(read_json_evidence(output, "initial-verification.json"))
    expected = _snapshot(output, "expected.json", complete=False)
    before = _snapshot(output, "steps/0/before.json", complete=False)
    computed = EffectVerifier().verify_initial(case, expected, before)
    if computed != saved or (computed.complete and not computed.mismatches):
        raise ValueError("Failed initial preparation contradicts retained observations")
