from pathlib import Path

from tools.install_sandbox.models import PhaseResult, ScenarioResult
from tools.install_sandbox.reporting import (
    build_manifest,
    render_report,
    write_run_outputs,
)
from tools.install_sandbox.run import main, parser


def test_public_cli_has_exact_selection_and_scope_defaults(tmp_path):
    args = parser().parse_args(
        ["--repo", str(tmp_path), "--target", "codex"]
    )

    assert args.target == "codex"
    assert args.all_targets is False
    assert args.scope == "both"
    assert args.output is None


def test_cli_rejects_non_graphify_repo_before_docker(tmp_path, capsys):
    assert main(["--repo", str(tmp_path), "--all"]) == 2
    assert "not a Graphify source checkout" in capsys.readouterr().err


def test_reporting_is_concise_and_writes_only_top_level_contract_files(tmp_path):
    result = ScenarioResult(
        scenario="codex-project",
        target="codex",
        scope="project",
        status="PASS",
        phases=[
            PhaseResult(name="install", status="PASS"),
            PhaseResult(name="uninstall", status="PASS"),
        ],
        artifact_dir="scenarios/codex-project",
    )
    manifest = build_manifest(
        repo=Path("/repo"),
        selection={"target": "codex", "all": False, "scope": "project"},
        package={"version": "graphify 1.0"},
        results=[result],
        purge={"status": "PASS"},
    )

    report = render_report(manifest)
    write_run_outputs(tmp_path, manifest)

    assert "codex-project" in report
    assert "PASS=1" in report
    assert len(report.splitlines()) < 20
    assert {item.name for item in tmp_path.iterdir()} == {
        "manifest.json",
        "report.md",
    }

