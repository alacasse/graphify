"""Independently replay initial preparation from confined retained evidence."""

import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.evidence_layout import (
    ArtifactLocation,
    FilesystemEntry,
    StagedEvidence,
    classify_staging,
)
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.initial_preparation import REFERENCES, InitialPreparationState
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import VerificationResult
from tools.install_sandbox.contracts.spec import fields, text
from tools.install_sandbox.host.evidence_reader import (
    check_snapshot,
    read_json_evidence,
    safe_evidence_path,
)
from tools.install_sandbox.rules.effect_verifier import EffectVerifier
from tools.install_sandbox.rules.expectation_builder import (
    bind_roots,
    build_initial_expectations,
    build_install_expectations,
)
from tools.install_sandbox.rules.initial_preparation import InitialPreparationInventory, inspect

ARTIFACTS = {
    name: ArtifactLocation(reference, "snapshot" if name in {"sources", "before"} else "json")
    for name, reference in REFERENCES.items()
}


@dataclass(frozen=True)
class InitialInputs:
    roots: dict[str, str]
    sources: FilesystemSnapshot
    before: FilesystemSnapshot
    expectations: ExpectationSet


def replay_initial(
    state: InitialPreparationState,
    case: EffectInstallCase,
    output: Path,
    snapshot: Callable[[Path, str], FilesystemSnapshot],
) -> InitialInputs | None:
    loaded, staged = _inventory(output, snapshot)
    roots = _roots(loaded.get("environment"))
    sources, before = _observation(loaded.get("sources")), _observation(loaded.get("before"))
    initial, rejected = _initial_expectations(case, roots, sources)
    _check_expectations(loaded, "expectations", initial)
    verdict = _initial_verdict(loaded, initial, before)
    passed = (
        None
        if verdict is None
        else bool(verdict.complete and not verdict.mismatches and not verdict.obstacles)
    )
    installed, install_rejected = _install_expectations(case, roots, sources, before, passed)
    _check_expectations(loaded, "install_expectations", installed)
    stopped = _diagnostic(loaded, rejected | install_rejected)
    names = {descriptor.reference: name for name, descriptor in ARTIFACTS.items()}
    inspect(
        state,
        InitialPreparationInventory(
            present=frozenset(loaded),
            verification_passed=passed,
            stopped_state=stopped,
            staged=tuple(
                frozenset(names[owner] for owner in item.owners if owner in names)
                for item in staged
            ),
        ),
    )
    if state.checkpoint != "ready":
        return None
    if roots is None or sources is None or before is None or installed is None:
        raise ValueError("Ready preparation requires retained initial inputs")
    return InitialInputs(roots, sources, before, installed)


def _roots(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    roots = {key: text(item) for key, item in fields(value, "home project").items()}
    project, home = (PurePosixPath(roots[key]) for key in ("project", "home"))
    canonical = (
        project.is_absolute() and project.name == "project" and home == project.parent / "home"
    )
    canonical = (
        canonical
        and ".." not in project.parts
        and str(project) == roots["project"]
        and str(home) == roots["home"]
    )
    if not canonical:
        raise ValueError("Evidence requires canonical isolated roots")
    return roots


def _observation(value: object) -> FilesystemSnapshot | None:
    return value if isinstance(value, FilesystemSnapshot) else None


def _initial_expectations(
    case: EffectInstallCase, roots: dict[str, str] | None, sources: FilesystemSnapshot | None
) -> tuple[ExpectationSet | None, set[str]]:
    if roots is None or sources is None:
        return None, set()
    try:
        return bind_roots(build_initial_expectations(case, sources), roots), set()
    except ValueError:
        return None, {"expectations"}


def _install_expectations(
    case: EffectInstallCase,
    roots: dict[str, str] | None,
    sources: FilesystemSnapshot | None,
    before: FilesystemSnapshot | None,
    passed: bool | None,
) -> tuple[ExpectationSet | None, set[str]]:
    if not passed or roots is None or sources is None or before is None:
        return None, set()
    try:
        return build_install_expectations(case, sources, before, roots), set()
    except ValueError:
        return None, {"install_expectations"}


def _check_expectations(
    loaded: dict[str, object], name: str, expected: ExpectationSet | None
) -> None:
    if name in loaded and (expected is None or ExpectationSet.from_data(loaded[name]) != expected):
        raise ValueError(f"Stored {name} expectations contradict retained inputs")


def _initial_verdict(
    loaded: dict[str, object], initial: ExpectationSet | None, before: FilesystemSnapshot | None
) -> VerificationResult | None:
    if before is None:
        computed = None
    else:
        if initial is None:
            raise ValueError("Initial observation requires reconstructable expectations")
        computed = EffectVerifier().verify(initial, before)
    if "verification" in loaded and (
        computed is None or VerificationResult.from_data(loaded["verification"]) != computed
    ):
        raise ValueError("Initial verification contradicts retained observations")
    return computed


def _diagnostic(loaded: dict[str, object], rejected: set[str]) -> InitialPreparationState | None:
    if "failure" not in loaded:
        return None
    stopped = InitialPreparationState.from_data(loaded["failure"])
    stop = stopped.stop
    if stop is not None and stop.category == "validation" and stop.operation not in rejected:
        raise ValueError("Validation stop contradicts independently reconstructed inputs")
    return stopped


def _physical_entries(output: Path) -> tuple[FilesystemEntry, ...]:
    entries: list[FilesystemEntry] = []

    def visit(relative: str) -> None:
        path = safe_evidence_path(output, relative)
        mode = path.lstat().st_mode
        if stat.S_ISREG(mode):
            entries.append(FilesystemEntry(relative, "file"))
        elif stat.S_ISDIR(mode):
            entries.append(FilesystemEntry(relative, "directory"))
            for child in sorted(path.iterdir()):
                visit(child.relative_to(output).as_posix())
        else:
            raise ValueError("Initial evidence must be a regular file or directory")

    for child in sorted(output.iterdir()):
        relative = child.name
        if relative in {
            "initial",
            "expected",
            "expectations",
            "roots.json",
            "expected.json",
            "initial-verification.json",
        } or (
            relative.startswith(".")
            and any(
                relative.startswith("." + PurePosixPath(a.reference).name + ".")
                for a in ARTIFACTS.values()
                if "/" not in a.reference
            )
        ):
            visit(relative)
    return tuple(entries)


def _load_artifacts(
    output: Path, snapshot: Callable[[Path, str], FilesystemSnapshot]
) -> tuple[dict[str, object], set[str]]:
    loaded: dict[str, object] = {}
    referenced: set[str] = set()
    for name, descriptor in ARTIFACTS.items():
        if safe_evidence_path(output, descriptor.reference).exists():
            if descriptor.transport == "snapshot":
                _require_blob_digests(output, descriptor.reference)
                loaded[name] = snapshot(output, descriptor.reference)
                for entry in check_snapshot(output, descriptor.reference, complete=False):
                    content = entry.get("content_file")
                    if isinstance(content, str):
                        referenced.add(content)
            else:
                loaded[name] = read_json_evidence(output, descriptor.reference)
    return loaded, referenced


def _require_blob_digests(output: Path, reference: str) -> None:
    for entry in check_snapshot(output, reference, complete=False):
        if entry.get("content_file") is not None:
            digest = entry.get("sha256")
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ValueError("Initial retained blobs require a SHA-256 digest")


def _inventory(
    output: Path, snapshot: Callable[[Path, str], FilesystemSnapshot]
) -> tuple[dict[str, object], tuple[StagedEvidence, ...]]:
    entries = _physical_entries(output)
    loaded, referenced = _load_artifacts(output, snapshot)
    foreign = tuple(
        ArtifactLocation(f"expectations/{phase}.json", "json")
        for phase in ("intermediate", "reinstall")
    )
    staged = classify_staging(
        tuple(entries), tuple(ARTIFACTS.values()) + foreign, referenced, set()
    )
    own = {a.reference for a in ARTIFACTS.values()}
    retained_references = {
        descriptor.reference for name, descriptor in ARTIFACTS.items() if name in loaded
    }
    return loaded, tuple(
        item
        for item in staged
        if item.owners & own
        and not (item.form == "directory" and item.owners <= retained_references)
    )
