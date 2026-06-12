from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Literal

try:
    from .file_walk import pruned_file_walk
    from .json_helpers import object_dict, object_dicts, object_list
    from .platform_specs import ExpectedPath, JsonExpectation, JsonHookExpectation, JsonPluginExpectation, Scenario
    from .reference_resolution import PackagedReferenceResolution, ReferenceResolutionStatus
except ImportError:
    from file_walk import pruned_file_walk
    from json_helpers import object_dict, object_dicts, object_list
    from platform_specs import ExpectedPath, JsonExpectation, JsonHookExpectation, JsonPluginExpectation, Scenario
    from reference_resolution import PackagedReferenceResolution, ReferenceResolutionStatus


USER_SENTINEL = "USER_OWNED_CONTENT_DO_NOT_REMOVE"
STALE_GRAPHIFY_SENTINEL = "STALE_GRAPHIFY_OWNED_CONTENT_SHOULD_BE_REPLACED"
GRAPHIFY_MARKER = "## graphify"
USER_CONTENT_PRESERVING_RELATIVES = {
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".claude/CLAUDE.md",
    ".github/copilot-instructions.md",
}
GENERATED_COPY_EXCLUDES = (
    ".local",
    ".cache",
    "__pycache__",
    ".pytest_cache",
)

def check_record(path: Path | str, ok: bool, detail: str, *, root: str | None = None, relative: str | Path | None = None, **extra: object) -> dict[str, object]:
    record: dict[str, object] = {"path": str(path), "ok": ok, "detail": detail}
    if root is not None:
        record["root"] = root
    if relative is not None:
        record["relative"] = relative.as_posix() if isinstance(relative, Path) else relative
    record.update(extra)
    return record


ReferenceSidecarMode = Literal["absent", "source_error", "installed_directory"]


@dataclass(frozen=True)
class ReferenceSidecarExpectation:
    status: ReferenceResolutionStatus
    mode: ReferenceSidecarMode
    expected_names: tuple[str, ...]
    detail: str

    @classmethod
    def from_resolution(cls, resolution: PackagedReferenceResolution) -> ReferenceSidecarExpectation:
        if resolution.status in {"intentionally_absent", "no_eligible_bundle"}:
            mode: ReferenceSidecarMode = "absent"
        elif resolution.status in {"missing", "not_directory"}:
            mode = "source_error"
        else:
            mode = "installed_directory"
        return cls(
            status=resolution.status,
            mode=mode,
            expected_names=resolution.expected_names,
            detail=resolution.detail,
        )

    @property
    def includes_reference_dir(self) -> bool:
        return self.mode in {"source_error", "installed_directory"}

    def expected_relatives(self, skill_relative_dir: Path) -> set[Path]:
        if not self.includes_reference_dir:
            return set()
        references = skill_relative_dir / "references"
        relatives = {references}
        relatives.update(references / name for name in self.expected_names)
        return relatives

    def check_installed(self, refs_dir: Path, installed_reference_names: Callable[[Path], list[str]]) -> tuple[bool, str]:
        expected_names = list(self.expected_names)
        if self.mode == "absent":
            refs_ok = not refs_dir.exists()
            refs_state = "references_absent" if refs_ok else "references_present"
            return refs_ok, f"{self.status}; {refs_state}; {self.detail}"
        if self.mode == "source_error":
            return False, f"{self.status}; {self.detail}"
        if not refs_dir.exists():
            return False, f"references_missing; status={self.status}; expected_names={expected_names}; {self.detail}"
        if not refs_dir.is_dir():
            return False, f"references_not_directory; status={self.status}; expected_names={expected_names}; {self.detail}"

        actual_names = installed_reference_names(refs_dir)
        missing = sorted(set(expected_names) - set(actual_names))
        extra = sorted(set(actual_names) - set(expected_names))
        refs_ok = not missing and not extra
        refs_detail = f"status={self.status}; actual_names={actual_names}; expected_names={expected_names}; missing={missing}; extra={extra}"
        return refs_ok, refs_detail


def expected_kind_status(path: Path, kind: str) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    if kind == "file":
        return path.is_file(), "file" if path.is_file() else "expected_file_but_not_file"
    if kind == "dir":
        return path.is_dir(), "directory" if path.is_dir() else "expected_directory_but_not_directory"
    return True, "exists"


def json_value_contains_marker(value: object, marker: str) -> bool:
    if isinstance(value, dict):
        return any(marker in str(key) or json_value_contains_marker(item, marker) for key, item in value.items())
    if isinstance(value, list):
        return any(json_value_contains_marker(item, marker) for item in value)
    if isinstance(value, str):
        return marker in value
    return False


def command_hook_present(entry: object, expectation: JsonHookExpectation) -> bool:
    entry_data = object_dict(entry)
    if entry_data.get("matcher") != expectation.matcher:
        return False
    for hook in object_dicts(entry_data.get("hooks")):
        if hook.get("type") != "command":
            continue
        command = hook.get("command")
        if isinstance(command, str) and all(fragment in command for fragment in expectation.required_fragments):
            return True
    return False


def hooks_by_event(data: object, event_name: str) -> list[object]:
    hooks = object_dict(object_dict(data).get("hooks"))
    return object_list(hooks.get(event_name))


def plugin_config_present(data: object, expectation: JsonPluginExpectation) -> bool:
    plugins = object_list(object_dict(data).get("plugin"))
    for plugin in plugins:
        if not isinstance(plugin, str):
            continue
        if plugin == expectation.expected_entry:
            return True
        if expectation.allow_file_uri and plugin.startswith("file://") and plugin.endswith(expectation.expected_entry):
            return True
    return False


def json_expectation_status(data: object, expectation: JsonExpectation) -> tuple[bool, str]:
    states: list[tuple[str, bool]] = []
    for hook in expectation.hooks:
        entries = hooks_by_event(data, hook.event)
        states.append((hook.detail_name, any(command_hook_present(entry, hook) for entry in entries)))
    if expectation.plugin is not None:
        states.append((expectation.plugin.detail_name, plugin_config_present(data, expectation.plugin)))
    ok = all(present for _, present in states)
    detail = f"valid_json=true; schema={expectation.schema_name}"
    for name, present in states:
        detail += f"; {name}={present}"
    return ok, detail


@dataclass(frozen=True)
class FileEffectOracle:
    roots: dict[str, Path]
    packaged_reference_resolution: Callable[[str], PackagedReferenceResolution]
    expected_graphify_version: Callable[[], str]
    manifest_prune_dirs: set[str]

    # Path helpers
    def root_path(self, root: str) -> Path:
        try:
            return self.roots[root]
        except KeyError as exc:
            raise AssertionError(f"unknown root: {root}") from exc

    def expected_path(self, entry: ExpectedPath) -> Path:
        return self.root_path(entry.root) / entry.relative

    def is_skill_expected(self, entry: ExpectedPath) -> bool:
        return Path(entry.relative).name == "SKILL.md"

    def skill_dir_for_entry(self, entry: ExpectedPath) -> Path:
        return self.expected_path(entry).parent

    def skill_relative_dir(self, entry: ExpectedPath) -> Path:
        return Path(entry.relative).parent

    def skill_assertion_record(self, entry: ExpectedPath, relative: Path, ok: bool, detail: str) -> dict[str, object]:
        return check_record(self.root_path(entry.root) / relative, ok, detail, root=entry.root, relative=relative)

    def skill_version_relative(self, entry: ExpectedPath) -> Path:
        return self.skill_relative_dir(entry) / ".graphify_version"

    def skill_references_relative(self, entry: ExpectedPath) -> Path:
        return self.skill_relative_dir(entry) / "references"

    def skill_references_tmp_relative(self, entry: ExpectedPath) -> Path:
        return self.skill_relative_dir(entry) / "references.tmp"

    def expected_skill_sidecar_relatives(self, scenario: Scenario, entry: ExpectedPath) -> set[Path]:
        relatives = {
            self.skill_version_relative(entry),
            self.skill_references_tmp_relative(entry),
        }
        relatives.update(self.reference_sidecar_expectation(scenario).expected_relatives(self.skill_relative_dir(entry)))
        return relatives

    def installed_skill_reference_relatives(self, entry: ExpectedPath) -> set[Path]:
        refs_dir = self.skill_dir_for_entry(entry) / "references"
        refs_relative = self.skill_references_relative(entry)
        if not refs_dir.is_dir():
            return set()
        return {refs_relative / path.name for path in refs_dir.glob("*.md") if path.is_file()}

    def tracked_skill_sidecar_relatives(self, scenario: Scenario, entry: ExpectedPath) -> set[Path]:
        return self.expected_skill_sidecar_relatives(scenario, entry) | self.installed_skill_reference_relatives(entry)

    def reference_sidecar_expectation(self, scenario: Scenario) -> ReferenceSidecarExpectation:
        return ReferenceSidecarExpectation.from_resolution(self.packaged_reference_resolution(scenario.platform))

    def installed_reference_names(self, refs_dir: Path) -> list[str]:
        if not refs_dir.is_dir():
            return []
        return sorted(path.name for path in refs_dir.glob("*.md") if path.is_file())

    def skill_reference_pointers(self, skill_text: str) -> list[str]:
        return sorted(set(re.findall(r"references/([A-Za-z0-9_.-]+\.md)\b", skill_text)))

    # Skill sidecar checks
    def check_skill_version(self, entry: ExpectedPath) -> dict[str, object]:
        skill_dir = self.skill_dir_for_entry(entry)
        version_path = skill_dir / ".graphify_version"
        version_relative = self.skill_version_relative(entry)
        expected_version = self.expected_graphify_version()
        if version_path.exists():
            actual_version = version_path.read_text(encoding="utf-8", errors="replace").strip()
            version_ok = actual_version == expected_version
            version_detail = f"actual={actual_version}; expected={expected_version}"
        else:
            version_ok = False
            version_detail = f"missing; expected={expected_version}"
        return self.skill_assertion_record(entry, version_relative, version_ok, version_detail)

    def check_references_tmp_absent(self, entry: ExpectedPath) -> dict[str, object]:
        skill_dir = self.skill_dir_for_entry(entry)
        refs_tmp = skill_dir / "references.tmp"
        return self.skill_assertion_record(
            entry,
            self.skill_references_tmp_relative(entry),
            not refs_tmp.exists(),
            "absent" if not refs_tmp.exists() else "present",
        )

    def check_packaged_references(self, scenario: Scenario, entry: ExpectedPath) -> dict[str, object]:
        skill_dir = self.skill_dir_for_entry(entry)
        refs_dir = skill_dir / "references"
        refs_relative = self.skill_references_relative(entry)
        expectation = self.reference_sidecar_expectation(scenario)
        refs_ok, refs_detail = expectation.check_installed(refs_dir, self.installed_reference_names)
        return self.skill_assertion_record(entry, refs_relative, refs_ok, refs_detail)

    def check_skill_reference_pointers(self, entry: ExpectedPath, skill_text: str) -> dict[str, object]:
        mentions_references = "references/" in skill_text
        pointers = self.skill_reference_pointers(skill_text)
        refs_dir = self.skill_dir_for_entry(entry) / "references"
        if mentions_references and not refs_dir.is_dir():
            pointer_ok = False
            pointer_detail = f"references_missing; skill_mentions_references=true; pointers={pointers}"
        elif pointers:
            missing_pointers = [name for name in pointers if not (refs_dir / name).is_file()]
            pointer_ok = not missing_pointers
            pointer_detail = f"pointers={pointers}; missing={missing_pointers}"
        else:
            pointer_ok = True
            pointer_detail = "no_reference_pointers"
        return self.skill_assertion_record(entry, Path(entry.relative), pointer_ok, pointer_detail)

    def assert_installed_skill_sidecar(self, scenario: Scenario, entry: ExpectedPath) -> list[dict[str, object]]:
        if not self.is_skill_expected(entry):
            return []

        skill_path = self.expected_path(entry)
        skill_text = skill_path.read_text(encoding="utf-8", errors="replace") if skill_path.is_file() else ""
        return [
            self.check_skill_version(entry),
            self.check_references_tmp_absent(entry),
            self.check_packaged_references(scenario, entry),
            self.check_skill_reference_pointers(entry, skill_text),
        ]

    def assert_installed_skill_sidecars(self, scenario: Scenario) -> list[dict[str, object]]:
        checks: list[dict[str, object]] = []
        for entry in scenario.expected:
            checks.extend(self.assert_installed_skill_sidecar(scenario, entry))
        return checks

    def progressive_skill_entries(self, scenario: Scenario) -> list[ExpectedPath]:
        entries: list[ExpectedPath] = []
        expectation = self.reference_sidecar_expectation(scenario)
        for entry in scenario.expected:
            if self.is_skill_expected(entry) and expectation.includes_reference_dir:
                entries.append(entry)
        return entries

    def seed_stale_skill_sidecars(self, scenario: Scenario) -> list[dict[str, object]]:
        seeded: list[dict[str, object]] = []
        for entry in self.progressive_skill_entries(scenario):
            skill_dir = self.skill_dir_for_entry(entry)
            refs_dir = skill_dir / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            stale_ref = refs_dir / "stale-sandbox-fragment.md"
            stale_ref.write_text("stale sandbox reference fragment\n", encoding="utf-8")
            seeded.append(self.skill_assertion_record(entry, self.skill_references_relative(entry) / stale_ref.name, True, "seeded_stale_reference_fragment"))

            refs_tmp = skill_dir / "references.tmp"
            refs_tmp.mkdir(parents=True, exist_ok=True)
            partial = refs_tmp / "partial.md"
            partial.write_text("partial staged reference fragment\n", encoding="utf-8")
            seeded.append(self.skill_assertion_record(entry, self.skill_references_tmp_relative(entry) / partial.name, True, "seeded_staged_reference_fragment"))
        return seeded

    def expected_manifest_relatives(self, scenario: Scenario, root_name: str) -> set[Path]:
        relatives: set[Path] = set()
        for entry in scenario.expected:
            if entry.root != root_name:
                continue
            relative = Path(entry.relative)
            relatives.add(relative)
            if self.is_skill_expected(entry):
                relatives.update(self.expected_skill_sidecar_relatives(scenario, entry))
        return relatives

    # User content seeding
    def should_seed_user_content(self, entry: ExpectedPath) -> bool:
        return bool(entry.marker and entry.relative in USER_CONTENT_PRESERVING_RELATIVES)

    def should_seed_stale_graphify_section(self, entry: ExpectedPath) -> bool:
        return bool(entry.marker == GRAPHIFY_MARKER and entry.relative.endswith((".md", ".mdc")))

    def seeded_text(self, entry: ExpectedPath) -> str:
        if self.should_seed_stale_graphify_section(entry):
            return (
                f"# User Notes\n\n{USER_SENTINEL}\n\n"
                f"{entry.marker}\n{STALE_GRAPHIFY_SENTINEL}\n\n"
                "## User Section\nThis section should survive Graphify install and uninstall.\n"
            )
        return f"# User Notes\n\n{USER_SENTINEL}\n"

    def seed_user_owned_content(self, scenario: Scenario) -> None:
        for entry in scenario.expected:
            if self.should_seed_user_content(entry):
                path = self.expected_path(entry)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(self.seeded_text(entry), encoding="utf-8")

    # JSON/text marker validation
    def json_marker_status(self, path: Path, entry: ExpectedPath) -> tuple[bool, str]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return False, f"invalid_json={exc.msg}"
        except OSError as exc:
            return False, f"json_read_failed={exc}"
        if entry.json_expectation is not None:
            return json_expectation_status(data, entry.json_expectation)
        marker = entry.marker or ""
        marker_present = bool(marker) and json_value_contains_marker(data, marker)
        return marker_present, f"valid_json=true; schema=generic_marker; marker_present={marker_present}"

    def text_marker_status(self, path: Path, entry: ExpectedPath) -> tuple[bool, str]:
        text = path.read_text(encoding="utf-8", errors="replace")
        marker_count = text.count(entry.marker or "")
        ok = marker_count == 1
        detail = f"marker_count={marker_count}"
        if USER_SENTINEL in text:
            detail += "; user_content_preserved"
        elif self.should_seed_user_content(entry):
            ok = False
            detail += "; user_content_missing"
        if self.should_seed_stale_graphify_section(entry):
            stale_replaced = STALE_GRAPHIFY_SENTINEL not in text
            ok = ok and stale_replaced
            detail += f"; stale_replaced={stale_replaced}"
        return ok, detail

    def expected_entry_status(self, entry: ExpectedPath) -> tuple[bool, str]:
        path = self.expected_path(entry)
        ok, detail = expected_kind_status(path, entry.kind)
        if not ok or not entry.marker:
            return ok, detail
        if path.suffix == ".json":
            return self.json_marker_status(path, entry)
        return self.text_marker_status(path, entry)

    # Install/uninstall assertions
    def assert_expected_files(self, scenario: Scenario) -> list[dict[str, object]]:
        checks: list[dict[str, object]] = []
        for entry in scenario.expected:
            path = self.expected_path(entry)
            ok, detail = self.expected_entry_status(entry)
            checks.append(check_record(path, ok, detail, root=entry.root, relative=entry.relative))
            checks.extend(self.assert_installed_skill_sidecar(scenario, entry))
        return checks

    def uninstalled_entry_status(self, entry: ExpectedPath) -> tuple[bool, str]:
        path = self.expected_path(entry)
        if entry.marker and self.should_seed_user_content(entry):
            if path.exists() and path.is_file():
                text = path.read_text(encoding="utf-8", errors="replace")
                graphify_removed = entry.marker not in text and STALE_GRAPHIFY_SENTINEL not in text
                user_preserved = USER_SENTINEL in text
                return graphify_removed and user_preserved, f"graphify_removed={graphify_removed}; user_content_preserved={user_preserved}"
            return False, "user_content_file_missing"
        if entry.marker and path.exists():
            text = path.read_text(encoding="utf-8", errors="replace")
            ok = entry.marker not in text and STALE_GRAPHIFY_SENTINEL not in text
            detail = "graphify_removed; user_content_preserved" if USER_SENTINEL in text else "graphify_removed"
            return ok, detail
        ok = not path.exists()
        return ok, "removed" if ok else "still_exists"

    def uninstalled_skill_sidecar_checks(self, entry: ExpectedPath) -> list[dict[str, object]]:
        if not self.is_skill_expected(entry):
            return []
        checks: list[dict[str, object]] = []
        for relative in (self.skill_version_relative(entry), self.skill_references_relative(entry), self.skill_references_tmp_relative(entry)):
            sidecar_path = self.root_path(entry.root) / relative
            sidecar_ok = not sidecar_path.exists()
            checks.append(
                check_record(
                    sidecar_path,
                    sidecar_ok,
                    "removed" if sidecar_ok else "sidecar_still_exists",
                    root=entry.root,
                    relative=relative,
                )
            )
        return checks

    def assert_uninstalled(self, scenario: Scenario) -> list[dict[str, object]]:
        checks: list[dict[str, object]] = []
        for entry in scenario.expected:
            path = self.expected_path(entry)
            if not entry.remove_on_uninstall:
                continue
            ok, detail = self.uninstalled_entry_status(entry)
            checks.append(check_record(path, ok, detail, root=entry.root, relative=entry.relative))
            checks.extend(self.uninstalled_skill_sidecar_checks(entry))
        return checks

    def expected_generated_relative_keys(self, scenario: Scenario) -> set[tuple[str, str]]:
        keys: set[tuple[str, str]] = set()
        for entry in scenario.expected:
            keys.add((entry.root, entry.relative))
            if self.is_skill_expected(entry):
                for relative in self.expected_skill_sidecar_relatives(scenario, entry):
                    keys.add((entry.root, relative.as_posix()))
        return keys

    # Generated-file discovery/copying
    def pruned_file_walk(self, base: Path) -> Iterable[Path]:
        yield from pruned_file_walk(base, self.manifest_prune_dirs)

    def assert_no_unexpected_graphify_files(
        self,
        scenario: Scenario,
        *,
        phase: str,
        expected_keys: set[tuple[str, str]] | None = None,
    ) -> list[dict[str, object]]:
        expected = self.expected_generated_relative_keys(scenario) if expected_keys is None else expected_keys
        checks: list[dict[str, object]] = []
        for root_name, root in self.roots.items():
            if not root.exists():
                continue
            for path in self.pruned_file_walk(root):
                relative = path.relative_to(root)
                rel = relative.as_posix()
                if self.should_exclude_generated_path(relative):
                    continue
                if (root_name, rel) in expected:
                    continue
                if not self.is_relevant_generated_file(scenario, root_name, relative, path):
                    continue
                checks.append(
                    check_record(
                        path,
                        False,
                        f"unexpected_graphify_related_file_after_{phase}",
                        root=root_name,
                        relative=rel,
                    )
                )
        if not checks:
            checks.append(check_record("unexpected-graphify-files", True, f"none_after_{phase}"))
        return checks

    def assert_scope_boundaries(self, scenario: Scenario) -> list[dict[str, object]]:
        checks: list[dict[str, object]] = []
        for entry in scenario.expected:
            allowed = True
            if scenario.scope == "user" and entry.root not in ("home",):
                allowed = "mixed_scope_project_wiring" in scenario.risk_notes
            if scenario.scope == "project" and entry.root not in ("project",):
                allowed = "mixed_scope_global_skill_plus_project_wiring" in scenario.risk_notes
            checks.append(check_record(self.expected_path(entry), allowed, "allowed_root" if allowed else "unexpected_root"))
        return checks

    def file_fingerprint(self, path: Path, marker: str | None = None) -> dict[str, object]:
        if not path.exists():
            return {"exists": False}
        if path.is_dir():
            return {"exists": True, "kind": "dir"}
        data = path.read_bytes()
        item: dict[str, object] = {"exists": True, "kind": "file", "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
        if marker:
            text = data.decode("utf-8", errors="replace")
            item["marker_count"] = text.count(marker)
            item["user_content_preserved"] = USER_SENTINEL in text
            item["stale_graphify_present"] = STALE_GRAPHIFY_SENTINEL in text
        return item

    # Idempotency state
    def scenario_file_state(self, scenario: Scenario) -> dict[str, dict[str, object]]:
        state: dict[str, dict[str, object]] = {}
        for entry in scenario.expected:
            key = f"{entry.root}/{entry.relative}"
            state[key] = self.file_fingerprint(self.expected_path(entry), entry.marker)
            if not self.is_skill_expected(entry):
                continue
            for relative in sorted(self.tracked_skill_sidecar_relatives(scenario, entry), key=lambda item: item.as_posix()):
                state[f"{entry.root}/{relative.as_posix()}"] = self.file_fingerprint(self.root_path(entry.root) / relative)
        return state

    def should_exclude_generated_path(self, relative: Path) -> bool:
        return any(part in GENERATED_COPY_EXCLUDES for part in relative.parts)

    def is_expected_generated_key(self, scenario: Scenario, root_name: str, relative: Path) -> bool:
        expected = {(entry.root, entry.relative) for entry in scenario.expected}
        return (root_name, relative.as_posix()) in expected

    def is_skill_sidecar_relative(self, scenario: Scenario, root_name: str, relative: Path) -> bool:
        for entry in scenario.expected:
            if root_name != entry.root or not self.is_skill_expected(entry):
                continue
            if relative == self.skill_version_relative(entry):
                return True
            for sidecar_dir in (self.skill_references_relative(entry), self.skill_references_tmp_relative(entry)):
                try:
                    relative.relative_to(sidecar_dir)
                    return True
                except ValueError:
                    pass
        return False

    def is_adjacent_graphify_version(self, scenario: Scenario, root_name: str, relative: Path) -> bool:
        return relative.name == ".graphify_version" and any(
            root_name == entry.root and relative.parent.as_posix() == Path(entry.relative).parent.as_posix()
            for entry in scenario.expected
        )

    def is_small_text_candidate(self, path: Path) -> bool:
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if size > 1024 * 1024:
            return False
        text_suffixes = {".json", ".js", ".md", ".mdc", ".txt", ""}
        return path.suffix in text_suffixes

    def file_mentions_graphify_or_sentinel(self, path: Path) -> bool:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        return "graphify" in text.lower() or USER_SENTINEL in text

    def is_relevant_generated_file(self, scenario: Scenario, root_name: str, relative: Path, path: Path) -> bool:
        rel = relative.as_posix()
        if self.is_expected_generated_key(scenario, root_name, relative):
            return True
        if self.is_skill_sidecar_relative(scenario, root_name, relative):
            return True
        if self.is_adjacent_graphify_version(scenario, root_name, relative):
            return True
        if "graphify" in rel.lower():
            return True
        if not self.is_small_text_candidate(path):
            return False
        return self.file_mentions_graphify_or_sentinel(path)

    def copy_generated_files(self, scenario: Scenario, artifact_dir: Path) -> None:
        out = artifact_dir / "generated-files"
        if out.exists():
            shutil.rmtree(out)
        for root_name, root in self.roots.items():
            if not root.exists():
                continue
            target = out / root_name
            for path in self.pruned_file_walk(root):
                rel = path.relative_to(root)
                if self.should_exclude_generated_path(rel) or not self.is_relevant_generated_file(scenario, root_name, rel, path):
                    continue
                dest = target / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)


def assert_idempotent_state(before: dict[str, dict[str, object]], after: dict[str, dict[str, object]]) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    for key in sorted(set(before) | set(after)):
        stable = before.get(key) == after.get(key)
        checks.append(check_record(key, stable, "unchanged_after_repeat_install" if stable else "changed_after_repeat_install"))
    return checks


@dataclass(frozen=True)
class ScenarioFileEffectsAdapter:
    oracle: FileEffectOracle
    write_file_manifest: Callable[..., None]
    run_equivalence_check: Callable[[Scenario, dict[str, str], Path], list[dict[str, object]]]

    def seed_scenario_inputs(self, scenario: Scenario) -> None:
        self.oracle.seed_user_owned_content(scenario)

    def write_manifest(self, path: Path, roots: dict[str, Path], **kwargs: object) -> None:
        self.write_file_manifest(path, roots, **kwargs)

    def capture_state(self, scenario: Scenario) -> dict[str, dict[str, object]]:
        return self.oracle.scenario_file_state(scenario)

    def install_checks(self, scenario: Scenario) -> list[dict[str, object]]:
        return self.oracle.assert_expected_files(scenario) + self.oracle.assert_scope_boundaries(scenario)

    def unexpected_checks(self, scenario: Scenario, *, phase: str) -> list[dict[str, object]]:
        return self.oracle.assert_no_unexpected_graphify_files(scenario, phase=phase)

    def archive_generated_files(self, scenario: Scenario, artifact_dir: Path) -> None:
        self.oracle.copy_generated_files(scenario, artifact_dir)

    def repeat_install_checks(
        self,
        scenario: Scenario,
        before: dict[str, dict[str, object]],
        after: dict[str, dict[str, object]],
        *,
        phase: str,
    ) -> list[dict[str, object]]:
        return assert_idempotent_state(before, after) + self.oracle.assert_no_unexpected_graphify_files(scenario, phase=phase)

    def seed_stale_sidecar_repair(self, scenario: Scenario) -> list[dict[str, object]]:
        return self.oracle.seed_stale_skill_sidecars(scenario)

    def stale_sidecar_repair_checks(self, scenario: Scenario, *, phase: str) -> list[dict[str, object]]:
        return self.oracle.assert_installed_skill_sidecars(scenario) + self.oracle.assert_no_unexpected_graphify_files(scenario, phase=phase)

    def uninstall_checks(self, scenario: Scenario, *, phase: str) -> list[dict[str, object]]:
        return self.oracle.assert_uninstalled(scenario) + self.oracle.assert_no_unexpected_graphify_files(scenario, phase=phase)

    def equivalence_checks(self, scenario: Scenario, env: dict[str, str], artifact_dir: Path) -> list[dict[str, object]]:
        return self.run_equivalence_check(scenario, env, artifact_dir)

    def universal_uninstall_checks(
        self,
        runner_scenario: Scenario,
        installed_scenarios: Iterable[Scenario],
        install_checks: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        scenarios = list(installed_scenarios)
        expected_keys = set().union(*(self.oracle.expected_generated_relative_keys(scenario) for scenario in scenarios))
        return (
            install_checks
            + [check for scenario in scenarios for check in self.oracle.assert_uninstalled(scenario)]
            + self.oracle.assert_no_unexpected_graphify_files(runner_scenario, phase="universal_uninstall", expected_keys=expected_keys)
        )

    def purge_checks(self, graphify_out: Path, purged: bool) -> list[dict[str, object]]:
        return [check_record(graphify_out, purged, "purged" if purged else "still_exists")]
