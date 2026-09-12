"""Exercise configured Python campaigns and the real module command without Docker."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.install_sandbox.component.test_campaign import commands
from tests.install_sandbox.component.test_preserve_skill_backup import arrange_backup
from tools.install_sandbox.coordinator import InstallTestCoordinator

_ROOT = Path(__file__).resolve().parents[3]
_COMPONENT = Path(__file__).parent
_DEFAULTS = _ROOT / "tools/install_sandbox/campaign-defaults.yaml"


def run_cli(
    root: Path, arguments: list[str], cwd: Path = _ROOT
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.install_sandbox",
            "--repo",
            str(root / "subject"),
            "--specs",
            str(root / "specs"),
            "--target",
            "another-target",
            "--output",
            str(root / "campaign"),
            *arguments,
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def arrange(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    arrange_backup(root, monkeypatch)
    (root / "bin").mkdir()
    (root / "bin/docker").symlink_to(_COMPONENT / "fake_docker.py")
    monkeypatch.setenv("PATH", str(root / "bin") + os.pathsep + os.environ["PATH"])
    (root / "specs").mkdir()
    shutil.copyfile(
        _ROOT / "tools/install_sandbox/specs/reference/sandbox-reference.yaml",
        root / "specs/another-target.yaml",
    )


@pytest.mark.parametrize("names", [None, ["preserve-skill-backup"], ["reinstall", "first-install"]])
@pytest.mark.parametrize("interface", ["python", "cli"])
def test_selected_order_scope_and_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    names: list[str] | None,
    interface: str,
) -> None:
    arrange(tmp_path, monkeypatch)
    selected = names if names is not None else ["first-install", "reinstall"]
    if interface == "cli":
        completed = run_cli(tmp_path, [arg for n in names or [] for arg in ("--case", n)])
        assert completed.returncode == 0, completed.stderr + completed.stdout
        assert completed.stdout.endswith((tmp_path / "campaign/campaign.txt").read_text())
    else:
        result = InstallTestCoordinator().run_campaign(
            specs_directory=tmp_path / "specs",
            target="another-target",
            case_names=names,
            subject_checkout=tmp_path / "subject",
            output_directory=tmp_path / "campaign",
        )
        assert result.passed
    saved = json.loads((tmp_path / "campaign/campaign.json").read_text())
    assert saved["selected_cases"] == selected
    assert saved["selection_origin"] == ("default" if names is None else "explicit")
    assert [c["name"] for c in saved["cases"]] == selected
    assert len(saved["not_selected_cases"]) == 7 - len(selected)
    assert not set(saved["not_selected_cases"]) & set(selected)
    assert len([c for c in commands(tmp_path) if c[0] == "run"]) == len(selected) + 1


@pytest.mark.parametrize(
    "arguments",
    [
        ["--case"],
        ["--case", ""],
        ["--case", "unknown"],
        ["--case", "first-install", "--case", "first-install"],
        ["--target", "missing"],
    ],
)
def test_cli_refuses_whole_invalid_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
) -> None:
    arrange(tmp_path, monkeypatch)
    completed = run_cli(tmp_path, arguments)
    assert completed.returncode == 2 and completed.stderr
    assert not commands(tmp_path)


@pytest.mark.parametrize("interface", ["python", "cli"])
@pytest.mark.parametrize("spec", ["invalid", "user_only"])
def test_spec_applicability_before_docker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interface: str,
    spec: str,
) -> None:
    arrange(tmp_path, monkeypatch)
    path = tmp_path / "specs/another-target.yaml"
    path.write_text("invalid" if spec == "invalid" else path.read_text().replace("project", "user"))
    if interface == "cli":
        assert run_cli(tmp_path, []).returncode == 2
    else:
        with pytest.raises(ValueError):
            InstallTestCoordinator().run_campaign(
                specs_directory=tmp_path / "specs",
                target="another-target",
                subject_checkout=tmp_path / "subject",
                output_directory=tmp_path / "campaign",
            )
    assert not commands(tmp_path)


@pytest.mark.parametrize(
    "mode,code,runs",
    [
        ("build_fail", 1, 0),
        ("run_fail", 1, 3),
        ("invalid_result", 1, 3),
        ("container_cleanup_fail", 1, 2),
        ("run_interrupt", 130, 2),
        ("verify_interrupt", 130, 1),
        ("cleanup_fail", 1, 3),
    ],
)
def test_cli_failure_continuation_cleanup_and_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    code: int,
    runs: int,
) -> None:
    arrange(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_MODE", mode)
    if mode in {"run_interrupt", "invalid_result"}:
        monkeypatch.delenv("FAKE_DOCKER_CASE_PROGRAM")
    completed = run_cli(tmp_path, [])
    assert completed.returncode == code, completed.stderr + completed.stdout
    saved = json.loads((tmp_path / "campaign/campaign.json").read_text())
    assert not saved["passed"] and saved["cleanup"] is not None
    assert saved["interrupted"] == (code == 130)
    assert completed.stdout.endswith((tmp_path / "campaign/campaign.txt").read_text())
    assert len([c for c in commands(tmp_path) if c[0] == "run"]) == runs


def sandbox_copy(root: Path) -> Path:
    destination = root / "copy"
    shutil.copytree(
        _ROOT / "tools/install_sandbox",
        destination / "tools/install_sandbox",
        ignore=shutil.ignore_patterns("__pycache__", "out", "graphify-out"),
    )
    return destination


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "unreadable",
        "syntax",
        "key",
        "empty",
        "duplicate",
        "unknown",
        "scalar",
        "nonstring",
    ],
)
def test_copied_configuration_refusal_and_explicit_bypass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    defect: str,
) -> None:
    arrange(tmp_path, monkeypatch)
    original = _DEFAULTS.read_bytes()
    copy = sandbox_copy(tmp_path)
    path = copy / "tools/install_sandbox/campaign-defaults.yaml"
    contents = {
        "syntax": "[",
        "key": "wrong: []",
        "empty": "default_cases: []",
        "duplicate": "default_cases: [reinstall, reinstall]",
        "unknown": "default_cases: [unknown]",
        "scalar": "default_cases: reinstall",
        "nonstring": "default_cases: [42]",
    }
    if defect == "missing":
        path.unlink()
    elif defect == "unreadable":
        path.chmod(0)
    else:
        path.write_text(contents[defect])
    try:
        refused = run_cli(tmp_path, [], copy)
        assert refused.returncode == 2, refused.stdout + refused.stderr
        assert not commands(tmp_path)
        completed = run_cli(tmp_path, ["--case", "preserve-skill-backup"], copy)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        saved = json.loads((tmp_path / "campaign/campaign.json").read_text())
        assert saved["selected_cases"] == ["preserve-skill-backup"]
        assert saved["selection_origin"] == "explicit"
    finally:
        if path.exists():
            path.chmod(0o644)
    assert _DEFAULTS.read_bytes() == original


def test_yaml_alone_changes_default_cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    arrange(tmp_path, monkeypatch)
    original = _DEFAULTS.read_bytes()
    copy = sandbox_copy(tmp_path)
    (copy / "tools/install_sandbox/campaign-defaults.yaml").write_text(
        "default_cases: [preserve-skill-backup, first-install]\n"
    )
    completed = run_cli(tmp_path, [], copy)
    assert completed.returncode == 0, completed.stderr + completed.stdout
    saved = json.loads((tmp_path / "campaign/campaign.json").read_text())
    assert saved["selected_cases"] == ["preserve-skill-backup", "first-install"]
    assert saved["selection_origin"] == "default"
    assert _DEFAULTS.read_bytes() == original


def test_all_seven_cases_apply_to_renamed_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arrange(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DOCKER_MODE", "build_fail")
    names = [
        "first-install",
        "reinstall",
        "repair-references",
        "repair-skill",
        "preserve-skill-backup",
        "repair-markdown-section",
        "repair-json-entry",
    ]
    completed = run_cli(tmp_path, [arg for name in names for arg in ("--case", name)])
    assert completed.returncode == 1
    saved = json.loads((tmp_path / "campaign/campaign.json").read_text())
    assert saved["selected_cases"] == names and saved["not_selected_cases"] == []
    assert all(c["state"] == "not_run" and c["not_run_reason"] for c in saved["cases"])
    for name in names:
        case = json.loads((tmp_path / f"campaign/inputs/{name}.json").read_text())
        assert case["target"] == "another-target" and case["scope"] == "project"
        assert len(case["operations"]) == (1 if name == "first-install" else 2)


def test_failed_report_write_keeps_cleanup_and_returns_campaign_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arrange(tmp_path, monkeypatch)
    wrapper = tmp_path / "report-write-failure.py"
    adapter = _COMPONENT / "controlled_backup_case.py"
    wrapper.write_text(
        "import runpy, sys\nfrom pathlib import Path\n"
        "root = Path(sys.argv[3]).parents[1]\n"
        "(root / 'campaign.json.tmp').mkdir()\n"
        f"runpy.run_path({str(adapter)!r}, run_name='__main__')\n"
    )
    monkeypatch.setenv("FAKE_DOCKER_CASE_PROGRAM", str(wrapper))
    completed = run_cli(tmp_path, [])
    assert completed.returncode == 1, completed.stderr + completed.stdout
    assert "Cannot save campaign evidence" in completed.stdout
    assert "Final cleanup: True" in completed.stdout
    assert "reinstall" in completed.stdout and "not_run" in completed.stdout
    assert not list((tmp_path / "runtime").glob("image-*"))
    assert not list((tmp_path / "runtime").glob("container-*"))
    assert (tmp_path / "campaign/cases/first-install/result.json").is_file()
