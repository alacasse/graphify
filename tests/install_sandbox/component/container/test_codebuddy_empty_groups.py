"""Repair may retain one known vacated managed group without losing personal groups."""

import json
from pathlib import Path
from typing import Any, cast

import pytest

from tests.install_sandbox.component.container.codebuddy_support import CodeBuddyHookRepairPairCase
from tools.install_sandbox.container.installer import InstallerCommandResult
from tools.install_sandbox.contracts import case as case_contract
from tools.install_sandbox.contracts.case import InitialFile
from tools.install_sandbox.contracts.spec import InstallTestSpec
from tools.install_sandbox.host import coordinator
from tools.install_sandbox.host.result_reader import read_result

_SETTINGS = ".codebuddy/settings.json"
_SEARCH = {"type": "command", "command": "graphify hook-guard search", "timeout": 10}
_CASES = ["repair-duplicate-json-hook", "repair-altered-json-hook"]


class EmptyGroupRepairCase(CodeBuddyHookRepairPairCase):
    """Match the real installer's dedicated search group and keep-second repair."""

    def __init__(self, root: Path, case_name: str, variant: str = "keep-second") -> None:
        super().__init__(root, case_name, "keep-second")
        self.variant = variant

    def execute(
        self, args: list[str], project: Path, environment: dict[str, str], timeout: float
    ) -> InstallerCommandResult:
        first = not self.calls
        result = super().execute(args, project, environment, timeout)
        settings = project / _SETTINGS
        data = cast(dict[str, Any], json.loads(settings.read_bytes()))
        groups = data["hooks"]["PreToolUse"]
        if first:
            groups[0]["hooks"].remove(_SEARCH)
            groups.append({"matcher": "Bash|Grep", "hooks": [dict(_SEARCH)]})
        else:
            _repair_variant(data, self.variant)
            if self.variant == "backup":
                Path(str(settings) + ".graphify-bak").write_bytes(b"Changed backup.\n")
        settings.write_text(json.dumps(data, indent=2) + "\n")
        if first:
            self.first_files["project/" + _SETTINGS] = settings.read_bytes()
        return result


def _repair_variant(data: dict[str, Any], variant: str) -> None:
    groups = data["hooks"]["PreToolUse"]
    if variant == "keep-original":
        groups[1]["hooks"].remove(_SEARCH)
        groups[-1]["hooks"].append(dict(_SEARCH))
    elif variant == "remove-vacated":
        groups.pop()
    elif variant in {"lose-bare-personal", "move-bare-personal"}:
        _change_empty(groups, {"matcher": "Bash|Grep", "hooks": []}, variant)
    elif variant in {"lose-attributed-personal", "move-attributed-personal"}:
        _change_empty(
            groups,
            {"matcher": "Bash|Grep", "personal_group": "empty", "hooks": []},
            variant,
        )
    else:
        _other_fault(data, variant)


def _change_empty(groups: list[dict[str, Any]], empty: dict[str, Any], variant: str) -> None:
    # list.remove selects the initially personal group preceding the vacated one.
    groups.remove(empty)
    if variant.startswith("move-"):
        groups.insert(0, empty)


def _other_fault(data: dict[str, Any], variant: str) -> None:
    groups = data["hooks"]["PreToolUse"]
    if variant == "inject-unrelated-empty":
        groups.append({"matcher": "Write", "hooks": []})
    elif variant == "extra-empty-search":
        groups.append({"matcher": "Bash|Grep", "hooks": []})
    elif variant == "personal-hook-order":
        data["hooks"]["PostToolUse"][0]["hooks"].reverse()
    elif variant == "personal-group-order":
        groups[0], groups[1] = groups[1], groups[0]
    elif variant == "read-hook":
        _change_read_hook(groups)


def _change_read_hook(groups: list[dict[str, Any]]) -> None:
    for group in groups:
        for hook in group["hooks"]:
            if hook.get("command") == "graphify hook-guard read":
                hook["timeout"] = 99


@pytest.fixture
def personal_empty_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    original = case_contract.first_install_files

    def seed(spec: InstallTestSpec, case_name: str = "first-install") -> list[InitialFile]:
        files = original(spec, case_name)
        for entry in files:
            if entry["root"] == "project" and entry["path"] == _SETTINGS:
                data = json.loads(entry["content"])
                data["hooks"]["PreToolUse"].extend(
                    [
                        {"matcher": "Bash|Grep", "hooks": []},
                        {"matcher": "Bash|Grep", "personal_group": "empty", "hooks": []},
                    ]
                )
                entry["content"] = json.dumps(data, indent=2) + "\n"
        return files

    monkeypatch.setattr(case_contract, "first_install_files", seed)
    monkeypatch.setattr(coordinator, "first_install_files", seed)


@pytest.mark.parametrize("case_name", _CASES)
@pytest.mark.parametrize("variant", ["keep-second", "keep-original", "remove-vacated"])
def test_repair_accepts_only_the_known_vacated_managed_group(
    tmp_path: Path, case_name: str, variant: str
) -> None:
    local = EmptyGroupRepairCase(tmp_path, case_name, variant)
    result = local.run()
    assert result.status == "passed", result
    first = json.loads(local.first_files["project/" + _SETTINGS])
    assert first["hooks"]["PreToolUse"][-1] == {"matcher": "Bash|Grep", "hooks": [_SEARCH]}
    after = json.loads((local.output / "steps/1/after/project" / _SETTINGS).read_bytes())
    bare = [
        group
        for group in after["hooks"]["PreToolUse"]
        if group == {"matcher": "Bash|Grep", "hooks": []}
    ]
    assert len(bare) == (1 if variant == "keep-second" else 0)
    assert len(local.calls) == 2
    assert read_result(local.output, local.retained_case()) == result


@pytest.mark.usefixtures("personal_empty_groups")
@pytest.mark.parametrize("case_name", _CASES)
@pytest.mark.parametrize(
    ("variant", "status"),
    [
        ("keep-second", "passed"),
        ("lose-bare-personal", "failed"),
        ("move-bare-personal", "failed"),
        ("lose-attributed-personal", "failed"),
        ("move-attributed-personal", "failed"),
        ("inject-unrelated-empty", "failed"),
        ("extra-empty-search", "failed"),
        ("personal-hook-order", "failed"),
        ("personal-group-order", "failed"),
        ("read-hook", "failed"),
        ("backup", "failed"),
    ],
)
def test_vacated_group_exception_preserves_personal_empty_groups_and_other_contracts(
    tmp_path: Path, case_name: str, variant: str, status: str
) -> None:
    local = EmptyGroupRepairCase(tmp_path, case_name, variant)
    result = local.run()
    assert result.status == status, result
    assert len(local.calls) == 2
    assert read_result(local.output, local.retained_case()) == result
