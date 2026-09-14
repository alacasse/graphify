"""Complete installation cases transported as JSON, without product contents."""

import json
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
    directory = PurePosixPath(spec.directory)
    markdown = _PROJECT_INSTRUCTIONS
    if case_name == "repair-markdown-section":
        markdown = markdown.replace("## Changes", spec.markdown_marker + "\n\n## Changes")
    config_file = directory / spec.json_file
    settings = (
        '{\n  "theme": "dark",\n  ' + json.dumps(spec.json_list) + ': ["my-instructions.md"]\n}\n'
    )
    if case_name in {"first-install", "reinstall"}:
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
    "repair-skill",
    "preserve-skill-backup",
    "repair-markdown-section",
    "repair-json-entry",
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
        data = fields(json.loads(payload), "name target scope spec initial_files operations")
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
        return cls(
            name,
            text(data["target"]),
            "project",
            spec,
            initial_files,
            operations,
        )

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
    return {
        "skill": str(skill),
        "references": str(skill.parent / "references"),
        "version": str(skill.parent / ".graphify_version"),
        "markdown": str(directory / spec.markdown_file),
        "json": str(directory / spec.json_file),
    }


def markdown_repair_plan(case: InstallTestCase) -> tuple[FileAlterationPlan, bytes]:
    """Build the altered shared document from case witnesses, not installed output."""
    path = destinations(case)["markdown"]
    initial = next(f["content"] for f in case.initial_files if f["path"] == path)
    content = initial.replace(
        case.spec.markdown_marker + "\n",
        case.spec.markdown_marker + "\nSandbox altered Markdown section.\n",
        1,
    )
    return {
        "altered_path": path,
        "altered_content_file": "steps/1/preparation/altered-content.bin",
    }, content.encode("utf-8")


def json_repair_plan(case: InstallTestCase) -> tuple[FileAlterationPlan, bytes]:
    """Retain expected personal settings independently of the installed document."""
    path = destinations(case)["json"]
    content = next(
        f["content"] for f in case.initial_files if f["root"] == "project" and f["path"] == path
    )
    return {
        "altered_path": path,
        "altered_content_file": "steps/1/preparation/altered-content.bin",
    }, content.encode("utf-8")
