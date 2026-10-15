"""Complete installation cases transported as JSON, without product contents."""

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import TypedDict, cast

from tools.install_sandbox.contracts.results import FileAlterationPlan
from tools.install_sandbox.contracts.spec import InstallTestSpec, fields, relative_path, text


class InitialFile(TypedDict):
    root: str
    path: str
    content: str


_PROJECT_INSTRUCTIONS = (
    "# My project\n\n## Language\nRespond in English.\n\n## Changes\nExplain proposed changes.\n"
)
_PERSONAL_INSTRUCTIONS = "# My instructions\nDo not modify my personal documents.\n"
_PERSONAL_NOTES = "Personal document to preserve.\n"


def first_install_files(
    spec: InstallTestSpec, case_name: str = "first-install"
) -> list[InitialFile]:
    """Place the common witnesses using target paths and the JSON list fact."""
    if case_name in {
        "repair-missing-json-hook",
        "repair-altered-json-hook",
        "repair-duplicate-json-hook",
    } and (spec.json_hook_management != "none" or not spec.json_hooks):
        raise ValueError("Missing JSON hook repair requires unmanaged JSON and a declared hook")
    if spec.json_hook_management == "none":
        if case_name not in {
            "first-install",
            "reinstall",
            "repair-missing-reference",
            "repair-altered-reference",
            "repair-skill",
            "preserve-skill-backup",
            "repair-markdown-section",
            "repair-missing-markdown-section",
            "repair-missing-json-hook",
            "repair-altered-json-hook",
            "repair-duplicate-json-hook",
        }:
            raise ValueError(
                "Unmanaged JSON supports first-install, reinstall, skill backup preservation, "
                "skill repair, Markdown repair and single-reference repair only"
            )
        return _unmanaged_files(spec, case_name)
    directory = PurePosixPath(spec.directory)
    markdown = _PROJECT_INSTRUCTIONS
    if case_name in {"repair-markdown-section", "repair-missing-markdown-section"}:
        markdown = markdown.replace("## Changes", spec.markdown_marker + "\n\n## Changes")
    config_file = directory / spec.json_file
    settings = (
        '{\n  "theme": "dark",\n  ' + json.dumps(spec.json_list) + ': ["my-instructions.md"]\n}\n'
    )
    if case_name in {
        "first-install",
        "reinstall",
        "repair-missing-reference",
        "repair-altered-reference",
    }:
        settings = (
            json.dumps(
                {
                    "theme": "dark",
                    spec.json_list: ["my-instructions.md"],
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Bash|Grep",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "python personal_graphify_audit.py",
                                        "timeout": 17,
                                    }
                                ],
                            }
                        ]
                    },
                },
                indent=2,
            )
            + "\n"
        )
    files: list[InitialFile] = [
        {
            "root": "project",
            "path": str(directory / spec.markdown_file),
            "content": markdown,
        },
        {"root": "project", "path": str(config_file), "content": settings},
        {
            "root": "project",
            "path": str(config_file.parent / "my-instructions.md"),
            "content": _PERSONAL_INSTRUCTIONS,
        },
        {"root": "home", "path": "personal-notes.txt", "content": _PERSONAL_NOTES},
    ]
    if case_name == "repair-json-entry":
        files[1]["content"] = (
            json.dumps(
                {"theme": "dark", spec.json_list: ["my-instructions.md", "team-guidelines.md"]},
                indent=2,
            )
            + "\n"
        )
        files.append(
            {
                "root": "project",
                "path": str(config_file.parent / "team-guidelines.md"),
                "content": "# Team guidelines\nExplain changes before applying them.\n",
            }
        )
    return files


def _initial_files(value: object) -> list[InitialFile]:
    if not isinstance(value, list) or not value:
        raise ValueError("Expected a non-empty initial_files list")
    result: list[InitialFile] = []
    seen: set[tuple[str, str]] = set()
    for item in cast(list[object], value):
        data = fields(item, "root path content")
        root, path = text(data["root"]), relative_path(data["path"])
        if root not in ("project", "home") or (root, path) in seen:
            raise ValueError("Invalid or duplicate initial file destination")
        if not isinstance(data["content"], str):
            raise ValueError("Initial file content must be a string")
        seen.add((root, path))
        result.append({"root": root, "path": path, "content": data["content"]})
    return result


CASE_NAMES = (
    "first-install",
    "reinstall",
    "repair-references",
    "repair-missing-reference",
    "repair-altered-reference",
    "repair-skill",
    "preserve-skill-backup",
    "repair-markdown-section",
    "repair-missing-markdown-section",
    "repair-json-entry",
    "repair-missing-json-hook",
    "repair-altered-json-hook",
    "repair-duplicate-json-hook",
)


def case_operations(name: str) -> list[str]:
    if name not in CASE_NAMES:
        raise ValueError(f"Unsupported project case: {name}")
    return ["install"] if name == "first-install" else ["install", "install"]


@dataclass(frozen=True)
class InstallTestCase:
    name: str
    target: str
    scope: str
    spec: InstallTestSpec
    initial_files: list[InitialFile]
    operations: list[str]

    @classmethod
    def from_json(cls, payload: str) -> "InstallTestCase":
        data = fields(
            json.loads(payload, object_pairs_hook=_unique_object),
            "name target scope spec initial_files operations",
        )
        spec = InstallTestSpec.from_data(data["spec"])
        name = text(data["name"])
        operations = case_operations(name)
        if data["operations"] != operations:
            raise ValueError("Operations do not match the case definition")
        if data["scope"] != "project" or "project" not in spec.scopes:
            raise ValueError("Installation case requires a supported project scope")
        initial_files = _initial_files(data["initial_files"])
        if initial_files != first_install_files(spec, name):
            raise ValueError("Initial files do not match the case definition")
        result = cls(
            name,
            text(data["target"]),
            "project",
            spec,
            initial_files,
            operations,
        )
        install_arguments(result)
        return result

    def to_json(self) -> str:
        data = asdict(self)
        data["spec"] = self.spec.to_data()
        payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        self.from_json(payload)
        return payload

    def write(self, path: Path) -> None:
        """Validate before touching the destination file."""
        path.write_text(self.to_json(), encoding="utf-8", newline="\n")


def destinations(case: InstallTestCase) -> dict[str, str]:
    spec = case.spec
    directory = Path(spec.directory)
    skill = directory / spec.skill_file
    result = {
        "skill": str(skill),
        "references": str(skill.parent / "references"),
        "version": str(skill.parent / ".graphify_version"),
        "markdown": str(directory / spec.markdown_file),
        "json": str(directory / spec.json_file),
    }
    if spec.destinations is not None:
        result.update({name: entry["path"] for name, entry in spec.destinations.items()})
        parent = PurePosixPath(result["skill"]).parent
        result.update(
            references=str(parent / "references"), version=str(parent / ".graphify_version")
        )
    return result


def destination_roots(case: InstallTestCase) -> dict[str, str]:
    roots = dict.fromkeys(destinations(case), "project")
    if case.spec.destinations is not None:
        roots.update({name: entry["root"] for name, entry in case.spec.destinations.items()})
        roots.update(references=roots["skill"], version=roots["skill"])
    return roots


def install_arguments(case: InstallTestCase) -> list[str]:
    if case.spec.command is not None:
        return list(case.spec.command)
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", case.target):
        raise ValueError("Invalid installation target")
    return ["install", "--platform", case.target, "--project"]


def _unmanaged_files(spec: InstallTestSpec, case_name: str) -> list[InitialFile]:
    case = InstallTestCase("first-install", "fixture", "project", spec, [], ["install"])
    paths, roots = destinations(case), destination_roots(case)
    markdown = _PROJECT_INSTRUCTIONS
    if case_name in {"repair-markdown-section", "repair-missing-markdown-section"}:
        markdown = markdown.replace("## Changes", spec.markdown_marker + "\n\n## Changes")
    personal: dict[str, object] = {
        "theme": "dark",
        "metadata": {"owner": "personal", "order": ["second", "first"]},
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash|Grep",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python personal_graphify_audit.py",
                            "timeout": 17,
                        }
                    ],
                }
            ],
            "PostToolUse": [
                {
                    "matcher": "Read",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python personal_after_read.py",
                            "timeout": 9,
                        },
                        {"type": "command", "command": "python personal_record.py", "timeout": 8},
                    ],
                }
            ],
        },
    }
    if case_name == "repair-missing-json-hook":
        _seed_json_hook(spec, personal)
    if case_name in {"repair-altered-json-hook", "repair-duplicate-json-hook"}:
        _seed_hook_pair_groups(spec, personal)
    settings = json.dumps(personal, indent=2) + "\n"
    files: list[InitialFile] = [
        {"root": roots["markdown"], "path": paths["markdown"], "content": markdown},
        {"root": roots["json"], "path": paths["json"], "content": settings},
        {"root": "home", "path": "personal-notes.txt", "content": _PERSONAL_NOTES},
        {"root": "home", "path": ".cache/personal-cache.txt", "content": _PERSONAL_NOTES},
    ]
    for name in ("markdown", "json"):
        opposite = "home" if roots[name] == "project" else "project"
        counterpart = (
            str(PurePosixPath(spec.directory) / spec.markdown_file)
            if name == "markdown"
            else str(PurePosixPath(spec.directory) / spec.json_file)
        )
        files.append(
            {
                "root": opposite,
                "path": counterpart,
                "content": _PERSONAL_INSTRUCTIONS if name == "markdown" else settings,
            }
        )
        files.append(
            {
                "root": roots[name],
                "path": str(PurePosixPath(paths[name]).parent / ("personal-" + name + ".txt")),
                "content": _PERSONAL_NOTES,
            }
        )
    return _initial_files(files)


def markdown_repair_plan(case: InstallTestCase) -> tuple[FileAlterationPlan, bytes]:
    """Build the altered shared document from case witnesses, not installed output."""
    path = destinations(case)["markdown"]
    root = destination_roots(case)["markdown"]
    initial = next(
        f["content"] for f in case.initial_files if (f["root"], f["path"]) == (root, path)
    )
    content = initial.replace(
        case.spec.markdown_marker + "\n",
        case.spec.markdown_marker + "\nSandbox altered Markdown section.\n",
        1,
    )
    if case.name == "repair-missing-markdown-section":
        content = initial.replace(case.spec.markdown_marker + "\n\n", "", 1)
    return {
        "altered_path": path,
        "altered_content_file": "steps/1/preparation/altered-content.bin",
    }, content.encode("utf-8")


def json_repair_plan(case: InstallTestCase) -> tuple[FileAlterationPlan, bytes]:
    """Retain expected personal settings independently of the installed document."""
    path = destinations(case)["json"]
    content = next(
        f["content"]
        for f in case.initial_files
        if f["root"] == destination_roots(case)["json"] and f["path"] == path
    )
    return {
        "altered_path": path,
        "altered_content_file": "steps/1/preparation/altered-content.bin",
    }, content.encode("utf-8")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate case transport field")
        result[key] = value
    return result


def remove_json_hook(case: InstallTestCase, document: dict[str, object]) -> None:
    """Remove exactly one full matching first-declared hook, retaining its group."""
    hook = case.spec.json_hooks[0]
    hooks = cast(dict[str, object], document["hooks"])
    groups = cast(list[object], hooks[hook.event])
    matches: list[tuple[list[object], object]] = []
    for raw in groups:
        if not isinstance(raw, dict):
            raise ValueError("Hook group must be an object")
        group = cast(dict[str, object], raw)
        if group.get("matcher") != hook.matcher:
            continue
        entries = cast(list[object], group["hooks"])
        for entry in entries:
            if _hook_matches(entry, hook.content):
                matches.append((entries, entry))
    if len(matches) != 1:
        raise ValueError("Expected exactly one declared hook before deletion")
    entries, entry = matches[0]
    entries.remove(entry)


def _hook_matches(entry: object, expected: dict[str, object]) -> bool:
    if not isinstance(entry, dict):
        return False
    content = cast(dict[str, object], entry)
    return all(key in content and content[key] == value for key, value in expected.items())


def _seed_json_hook(spec: InstallTestSpec, document: dict[str, object]) -> None:
    hook = spec.json_hooks[0]
    events = cast(dict[str, list[dict[str, object]]], document["hooks"])
    groups = events.setdefault(hook.event, [])
    group = next((g for g in groups if g["matcher"] == hook.matcher), None)
    if group is None:
        new_group: dict[str, object] = {
            "matcher": hook.matcher,
            "hooks": [
                {"type": "command", "command": "python personal_graphify_audit.py", "timeout": 17}
            ],
        }
        groups.append(new_group)
        group = new_group
    cast(list[object], group["hooks"]).append(dict(hook.content))


def _seed_hook_pair_groups(spec: InstallTestSpec, document: dict[str, object]) -> None:
    hook = spec.json_hooks[0]
    events = cast(dict[str, list[dict[str, object]]], document["hooks"])
    groups = events.setdefault(hook.event, [])
    group = next((group for group in groups if group["matcher"] == hook.matcher), None)
    if group is None:
        new_group: dict[str, object] = {"matcher": hook.matcher, "hooks": []}
        groups.append(new_group)
        group = new_group
    group["personal_group"] = "first"
    groups.append(
        {
            "matcher": hook.matcher,
            "personal_group": "second",
            "hooks": [
                {"type": "command", "command": "python personal_second_search.py", "timeout": 13}
            ],
        }
    )


def _selected_json_hook(
    case: InstallTestCase, document: dict[str, object]
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object]]:
    hook = case.spec.json_hooks[0]
    events = cast(dict[str, object], document["hooks"])
    groups = cast(list[dict[str, object]], events[hook.event])
    matches = [
        (group, entry)
        for group in groups
        if group.get("matcher") == hook.matcher
        for entry in cast(list[dict[str, object]], group["hooks"])
        if _hook_matches(entry, hook.content)
    ]
    if len(matches) != 1:
        raise ValueError("Expected exactly one declared hook before transformation")
    group, entry = matches[0]
    return groups, group, entry


def transform_json_hook(case: InstallTestCase, document: dict[str, object]) -> None:
    """Apply only the case-declared transformation to one observed hook object."""
    if case.name == "repair-missing-json-hook":
        remove_json_hook(case, document)
        return
    groups, source, entry = _selected_json_hook(case, document)
    if case.name == "repair-altered-json-hook":
        if entry.get("timeout") != 10:
            raise ValueError("Altered hook repair requires declared timeout 10")
        entry["timeout"] = 11
        return
    targets = [
        group
        for group in groups
        if group is not source
        and group.get("matcher") == case.spec.json_hooks[0].matcher
        and group.get("personal_group") in {"first", "second"}
    ]
    if case.name != "repair-duplicate-json-hook" or not targets:
        raise ValueError("Duplicate hook repair requires the second personal group")
    cast(list[object], targets[-1]["hooks"]).append(dict(entry))
