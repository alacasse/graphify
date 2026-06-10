from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, cast

try:
    from .platform_specs import ExpectedPath, Scenario
except ImportError:
    from platform_specs import ExpectedPath, Scenario


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


def object_dict(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def object_list(value: object) -> list[object]:
    return cast(list[object], value) if isinstance(value, list) else []


def object_dicts(value: object) -> list[dict[str, object]]:
    return [object_dict(item) for item in object_list(value) if isinstance(item, dict)]


def check_record(path: Path | str, ok: bool, detail: str, *, root: str | None = None, relative: str | Path | None = None, **extra: object) -> dict[str, object]:
    record: dict[str, object] = {"path": str(path), "ok": ok, "detail": detail}
    if root is not None:
        record["root"] = root
    if relative is not None:
        record["relative"] = relative.as_posix() if isinstance(relative, Path) else relative
    record.update(extra)
    return record


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


def graphify_command_hook_present(entry: object, *, matcher: str | None = None, required_fragments: tuple[str, ...] = ("graphify",)) -> bool:
    entry_data = object_dict(entry)
    if matcher is not None and entry_data.get("matcher") != matcher:
        return False
    for hook in object_dicts(entry_data.get("hooks")):
        if hook.get("type") != "command":
            continue
        command = hook.get("command")
        if isinstance(command, str) and all(fragment in command for fragment in required_fragments):
            return True
    return False


def hooks_by_event(data: object, event_name: str) -> list[object]:
    hooks = object_dict(object_dict(data).get("hooks"))
    return object_list(hooks.get(event_name))


def claude_like_settings_status(data: object, schema_name: str) -> tuple[bool, str]:
    pre_tool = hooks_by_event(data, "PreToolUse")
    bash_hook_present = any(graphify_command_hook_present(entry, matcher="Bash") for entry in pre_tool)
    read_glob_hook_present = any(graphify_command_hook_present(entry, matcher="Read|Glob") for entry in pre_tool)
    ok = bash_hook_present and read_glob_hook_present
    return ok, f"valid_json=true; schema={schema_name}; bash_hook_present={bash_hook_present}; read_glob_hook_present={read_glob_hook_present}"


def codex_hooks_status(data: object) -> tuple[bool, str]:
    pre_tool = hooks_by_event(data, "PreToolUse")
    graphify_hook_present = any(graphify_command_hook_present(entry, matcher="Bash", required_fragments=("graphify", "hook-check")) for entry in pre_tool)
    return graphify_hook_present, f"valid_json=true; schema=codex_hooks; graphify_hook_present={graphify_hook_present}"


def gemini_settings_status(data: object) -> tuple[bool, str]:
    before_tool = hooks_by_event(data, "BeforeTool")
    graphify_hook_present = any(graphify_command_hook_present(entry, matcher="read_file|list_directory") for entry in before_tool)
    return graphify_hook_present, f"valid_json=true; schema=gemini_settings; graphify_hook_present={graphify_hook_present}"


def plugin_config_status(data: object, *, schema_name: str, expected_entry: str, allow_file_uri: bool = False) -> tuple[bool, str]:
    plugins = object_list(object_dict(data).get("plugin"))
    plugin_present = False
    for plugin in plugins:
        if not isinstance(plugin, str):
            continue
        if plugin == expected_entry:
            plugin_present = True
            break
        if allow_file_uri and plugin.startswith("file://") and plugin.endswith(expected_entry):
            plugin_present = True
            break
    return plugin_present, f"valid_json=true; schema={schema_name}; plugin_present={plugin_present}"


def platform_json_status(entry: ExpectedPath, data: object) -> tuple[bool, str] | None:
    if entry.relative in (".claude/settings.json", ".codebuddy/settings.json"):
        schema_name = "claude_settings" if entry.relative == ".claude/settings.json" else "codebuddy_settings"
        return claude_like_settings_status(data, schema_name)
    if entry.relative == ".codex/hooks.json":
        return codex_hooks_status(data)
    if entry.relative == ".gemini/settings.json":
        return gemini_settings_status(data)
    if entry.relative == ".kilo/kilo.json":
        return plugin_config_status(data, schema_name="kilo_config", expected_entry=".kilo/plugins/graphify.js", allow_file_uri=True)
    if entry.relative == ".opencode/opencode.json":
        return plugin_config_status(data, schema_name="opencode_config", expected_entry=".opencode/plugins/graphify.js")
    return None


@dataclass(frozen=True)
class FileEffectOracle:
    roots: dict[str, Path]
    packaged_reference_names: Callable[[str], list[str] | None]
    expected_graphify_version: Callable[[], str]
    manifest_prune_dirs: set[str]

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

    def installed_reference_names(self, refs_dir: Path) -> list[str]:
        if not refs_dir.is_dir():
            return []
        return sorted(path.name for path in refs_dir.glob("*.md") if path.is_file())

    def skill_reference_pointers(self, skill_text: str) -> list[str]:
        return sorted(set(re.findall(r"references/([A-Za-z0-9_.-]+\.md)\b", skill_text)))

    def check_skill_version(self, entry: ExpectedPath) -> dict[str, object]:
        skill_dir = self.skill_dir_for_entry(entry)
        relative_dir = self.skill_relative_dir(entry)
        version_path = skill_dir / ".graphify_version"
        version_relative = relative_dir / ".graphify_version"
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
        relative_dir = self.skill_relative_dir(entry)
        refs_tmp = skill_dir / "references.tmp"
        return self.skill_assertion_record(
            entry,
            relative_dir / "references.tmp",
            not refs_tmp.exists(),
            "absent" if not refs_tmp.exists() else "present",
        )

    def check_packaged_references(self, scenario: Scenario, entry: ExpectedPath) -> dict[str, object]:
        skill_dir = self.skill_dir_for_entry(entry)
        relative_dir = self.skill_relative_dir(entry)
        refs_dir = skill_dir / "references"
        refs_relative = relative_dir / "references"
        expected_names = self.packaged_reference_names(scenario.platform)

        if expected_names is None:
            refs_ok = not refs_dir.exists()
            refs_detail = "no_packaged_references; references_absent" if refs_ok else "no_packaged_references; references_present"
        elif not refs_dir.exists():
            refs_ok = False
            refs_detail = f"references_missing; expected_names={expected_names}"
        elif not refs_dir.is_dir():
            refs_ok = False
            refs_detail = f"references_not_directory; expected_names={expected_names}"
        else:
            actual_names = self.installed_reference_names(refs_dir)
            missing = sorted(set(expected_names) - set(actual_names))
            extra = sorted(set(actual_names) - set(expected_names))
            refs_ok = not missing and not extra
            refs_detail = f"actual_names={actual_names}; expected_names={expected_names}; missing={missing}; extra={extra}"
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
        for entry in scenario.expected:
            if self.is_skill_expected(entry) and self.packaged_reference_names(scenario.platform) is not None:
                entries.append(entry)
        return entries

    def seed_stale_skill_sidecars(self, scenario: Scenario) -> list[dict[str, object]]:
        seeded: list[dict[str, object]] = []
        for entry in self.progressive_skill_entries(scenario):
            skill_dir = self.skill_dir_for_entry(entry)
            relative_dir = self.skill_relative_dir(entry)
            refs_dir = skill_dir / "references"
            refs_dir.mkdir(parents=True, exist_ok=True)
            stale_ref = refs_dir / "stale-sandbox-fragment.md"
            stale_ref.write_text("stale sandbox reference fragment\n", encoding="utf-8")
            seeded.append(self.skill_assertion_record(entry, relative_dir / "references" / stale_ref.name, True, "seeded_stale_reference_fragment"))

            refs_tmp = skill_dir / "references.tmp"
            refs_tmp.mkdir(parents=True, exist_ok=True)
            partial = refs_tmp / "partial.md"
            partial.write_text("partial staged reference fragment\n", encoding="utf-8")
            seeded.append(self.skill_assertion_record(entry, relative_dir / "references.tmp" / partial.name, True, "seeded_staged_reference_fragment"))
        return seeded

    def expected_manifest_relatives(self, scenario: Scenario, root_name: str) -> set[Path]:
        relatives: set[Path] = set()
        for entry in scenario.expected:
            if entry.root != root_name:
                continue
            relative = Path(entry.relative)
            relatives.add(relative)
            if self.is_skill_expected(entry):
                skill_dir = relative.parent
                relatives.add(skill_dir / ".graphify_version")
                relatives.add(skill_dir / "references.tmp")
                expected_names = self.packaged_reference_names(scenario.platform) or []
                for name in expected_names:
                    relatives.add(skill_dir / "references" / name)
        return relatives

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

    def json_marker_status(self, path: Path, entry: ExpectedPath) -> tuple[bool, str]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return False, f"invalid_json={exc.msg}"
        except OSError as exc:
            return False, f"json_read_failed={exc}"
        platform_status = platform_json_status(entry, data)
        if platform_status is not None:
            return platform_status
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
        skill_dir = self.skill_dir_for_entry(entry)
        relative_dir = self.skill_relative_dir(entry)
        checks: list[dict[str, object]] = []
        for sidecar in (".graphify_version", "references", "references.tmp"):
            sidecar_path = skill_dir / sidecar
            sidecar_ok = not sidecar_path.exists()
            checks.append(
                check_record(
                    sidecar_path,
                    sidecar_ok,
                    "removed" if sidecar_ok else "sidecar_still_exists",
                    root=entry.root,
                    relative=relative_dir / sidecar,
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
                relative_dir = self.skill_relative_dir(entry)
                keys.add((entry.root, (relative_dir / ".graphify_version").as_posix()))
                keys.add((entry.root, (relative_dir / "references").as_posix()))
                keys.add((entry.root, (relative_dir / "references.tmp").as_posix()))
                for name in self.packaged_reference_names(scenario.platform) or []:
                    keys.add((entry.root, (relative_dir / "references" / name).as_posix()))
        return keys

    def pruned_file_walk(self, base: Path) -> Iterable[Path]:
        if not base.exists():
            return
        for root, dirs, files in os.walk(base):
            root_path_obj = Path(root)
            dirs[:] = sorted(d for d in dirs if d not in self.manifest_prune_dirs)
            for name in sorted(files):
                yield root_path_obj / name

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

    def scenario_file_state(self, scenario: Scenario) -> dict[str, dict[str, object]]:
        state: dict[str, dict[str, object]] = {}
        for entry in scenario.expected:
            key = f"{entry.root}/{entry.relative}"
            state[key] = self.file_fingerprint(self.expected_path(entry), entry.marker)
            if not self.is_skill_expected(entry):
                continue
            skill_dir = self.skill_dir_for_entry(entry)
            relative_dir = self.skill_relative_dir(entry)
            sidecar_relatives: set[Path] = {
                relative_dir / ".graphify_version",
                relative_dir / "references",
                relative_dir / "references.tmp",
            }
            refs_dir = skill_dir / "references"
            if refs_dir.is_dir():
                sidecar_relatives.update(relative_dir / "references" / path.name for path in refs_dir.glob("*.md") if path.is_file())
            expected_names = self.packaged_reference_names(scenario.platform)
            if expected_names:
                sidecar_relatives.update(relative_dir / "references" / name for name in expected_names)
            for relative in sorted(sidecar_relatives, key=lambda item: item.as_posix()):
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
            skill_rel_dir = self.skill_relative_dir(entry)
            if relative == skill_rel_dir / ".graphify_version":
                return True
            for sidecar_dir in ("references", "references.tmp"):
                try:
                    relative.relative_to(skill_rel_dir / sidecar_dir)
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
