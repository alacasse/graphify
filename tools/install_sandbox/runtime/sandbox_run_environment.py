from __future__ import annotations

import functools
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from .. import reference_resolution
    from .. import validation_plan
    from ..effects import file_effect_generated_artifacts
    from ..effects import file_effect_oracle as file_effect_oracle_module
    from ..effects import file_effect_state
    from ..effects import scenario_file_effects_adapter
    from ..harness_specs import DEFAULT_SANDBOX_ROOT_REGISTRY
    from ..lifecycle import scenario_lifecycle_support
    from ..reporting import reports
    from ..reporting.status import RISK_GRAPHIFY_FAILED, RISK_GRAPHIFY_VERIFIED, combined_status, known_status_values
    from ..targets.install_target_defaults import default_install_target_catalog
    from ..targets.install_target_models import Scenario
    from . import command_runner
    from . import source_snapshot
except ImportError:  # pragma: no cover - direct script import fallback
    from tools.install_sandbox import reference_resolution  # type: ignore[no-redef]
    from tools.install_sandbox import validation_plan  # type: ignore[no-redef]
    from tools.install_sandbox.effects import file_effect_generated_artifacts  # type: ignore[no-redef]
    from tools.install_sandbox.effects import file_effect_oracle as file_effect_oracle_module  # type: ignore[no-redef]
    from tools.install_sandbox.effects import file_effect_state  # type: ignore[no-redef]
    from tools.install_sandbox.effects import scenario_file_effects_adapter  # type: ignore[no-redef]
    from tools.install_sandbox.harness_specs import DEFAULT_SANDBOX_ROOT_REGISTRY  # type: ignore[no-redef]
    from tools.install_sandbox.lifecycle import scenario_lifecycle_support  # type: ignore[no-redef]
    from tools.install_sandbox.reporting import reports  # type: ignore[no-redef]
    from tools.install_sandbox.reporting.status import RISK_GRAPHIFY_FAILED, RISK_GRAPHIFY_VERIFIED, combined_status, known_status_values  # type: ignore[no-redef]
    from tools.install_sandbox.targets.install_target_defaults import default_install_target_catalog  # type: ignore[no-redef]
    from tools.install_sandbox.targets.install_target_models import Scenario  # type: ignore[no-redef]
    from tools.install_sandbox.runtime import command_runner  # type: ignore[no-redef]
    from tools.install_sandbox.runtime import source_snapshot  # type: ignore[no-redef]


HARNESS_VERSION = "2026-06-01.1"
PACKAGE_NAME = "graphifyy"
INSTALL_MODE = "normal"
COPY_EXCLUDES = (
    *source_snapshot.COPY_EXCLUDES,
)
GENERATED_COPY_EXCLUDES = file_effect_generated_artifacts.GENERATED_COPY_EXCLUDES
MANIFEST_PRUNE_DIRS = set(GENERATED_COPY_EXCLUDES) | {".mypy_cache", ".ruff_cache", "node_modules"}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def command_probe_summary(result: subprocess.CompletedProcess[str], command: tuple[str, ...]) -> dict[str, object]:
    return {
        "command": list(command),
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "timed_out": bool(getattr(result, "timed_out", False)),
    }


def version_from_probe(probe: dict[str, object]) -> str | None:
    stdout = probe.get("stdout")
    if not isinstance(stdout, str):
        return None
    match = re.search(r"\bgraphify\s+([^\s]+)", stdout)
    return match.group(1) if match else None


def probe_read_only(path: Path) -> bool:
    probe = path / ".graphify-sandbox-write-probe"
    try:
        probe.write_text("probe", encoding="utf-8")
    except OSError:
        return True
    else:
        try:
            probe.unlink()
        except OSError:
            pass
        return False


class SandboxRunEnvironment:
    def __init__(
        self,
        *,
        root_registry=DEFAULT_SANDBOX_ROOT_REGISTRY,
        scenario_registry=None,
        harness_version: str = HARNESS_VERSION,
        package_name: str = PACKAGE_NAME,
        install_mode: str = INSTALL_MODE,
    ) -> None:
        self.root_registry = root_registry
        self.runtime_roots = root_registry.runtime_paths()
        self.scenario_registry = scenario_registry or default_install_target_catalog()
        self.harness_version = harness_version
        self.package_name = package_name
        self.install_mode = install_mode
        self.copy_excludes = COPY_EXCLUDES
        self.manifest_prune_dirs = MANIFEST_PRUNE_DIRS
        self.roots = root_registry.scenario_roots(self.runtime_roots)

    @property
    def home(self) -> Path:
        return self.runtime_roots["home"]

    @property
    def xdg_config_home(self) -> Path:
        return self.runtime_roots["xdg_config_home"]

    @property
    def project(self) -> Path:
        return self.runtime_roots["project"]

    @property
    def user_cwd(self) -> Path:
        return self.runtime_roots["user_cwd"]

    @property
    def repo_mount(self) -> Path:
        return self.runtime_roots["repo_mount"]

    @property
    def src(self) -> Path:
        return self.runtime_roots["src"]

    @property
    def output(self) -> Path:
        return self.runtime_roots["output"]

    @functools.lru_cache(maxsize=None)
    def graphify_main_module(self):
        try:
            from graphify import __main__ as graphify_main
        except ModuleNotFoundError:
            for path in self.package_search_paths():
                path_text = str(path)
                if path_text not in sys.path:
                    sys.path.insert(0, path_text)
            from graphify import __main__ as graphify_main

        return graphify_main

    @functools.lru_cache(maxsize=None)
    def expected_graphify_version(self) -> str:
        return str(self.graphify_main_module().__version__)

    @functools.lru_cache(maxsize=None)
    def packaged_reference_resolution(self, platform_name: str) -> reference_resolution.PackagedReferenceResolution:
        spec = self.scenario_registry.platform_spec(platform_name)
        return reference_resolution.resolve_target_packaged_references(
            platform_name,
            graphify_main=self.graphify_main_module(),
            target_reference_facts=spec,
        )

    def package_search_paths(self) -> list[Path]:
        return source_snapshot.package_search_paths(self.home)

    def source_snapshot_config(self) -> source_snapshot.SourceSnapshotConfig:
        return source_snapshot.SourceSnapshotConfig(
            repo_mount=self.repo_mount,
            src=self.src,
            copy_excludes=self.copy_excludes,
            manifest_prune_dirs=frozenset(self.manifest_prune_dirs),
            package_name=self.package_name,
            home=self.home,
        )

    def copy_source_tree(self, copy_source: str) -> dict[str, object]:
        return source_snapshot.copy_source_tree(copy_source, config=self.source_snapshot_config())

    def sandbox_env(self) -> dict[str, str]:
        env = os.environ.copy()
        current_roots = {
            "home": self.home,
            "xdg_config_home": self.xdg_config_home,
            "project": self.project,
            "repo_mount": self.repo_mount,
            "src": self.src,
            "output": self.output,
        }
        for root in self.root_registry.roots:
            if root.env_var is not None:
                env[root.env_var] = str(current_roots[root.name])
        env["PATH"] = f"{self.home / '.local' / 'bin'}:{env.get('PATH', '')}"
        return env

    def reset_sandbox_dirs(self) -> None:
        for root in self.root_registry.reset_roots():
            path = self.runtime_roots[root.name]
            path.mkdir(parents=True, exist_ok=True)
            for child in path.iterdir():
                if child.name in root.preserve_children:
                    continue
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        self.xdg_config_home.mkdir(parents=True, exist_ok=True)

    def file_effect_oracle(self) -> file_effect_oracle_module.FileEffectOracle:
        return file_effect_oracle_module.FileEffectOracle(
            roots=self.roots,
            packaged_reference_resolution=self.packaged_reference_resolution,
            expected_graphify_version=self.expected_graphify_version,
            manifest_prune_dirs=self.manifest_prune_dirs,
        )

    def list_files(self, base: Path, *, scenario: Scenario | None = None, root_name: str | None = None) -> list[dict[str, object]]:
        if not base.exists():
            return []
        files: list[dict[str, object]] = []
        relevant_scenario = scenario if scenario is not None and root_name is not None else None
        relevant_root = root_name if relevant_scenario is not None else None
        oracle = self.file_effect_oracle()
        expected_relatives = oracle.expected_manifest_relatives(relevant_scenario, relevant_root) if relevant_scenario is not None and relevant_root is not None else None
        for path in oracle.pruned_file_walk(base):
            try:
                rel = path.relative_to(base).as_posix()
                stat = path.stat()
            except OSError:
                continue
            relative = Path(rel)
            if (
                expected_relatives is not None
                and relevant_scenario is not None
                and relevant_root is not None
                and relative not in expected_relatives
                and not oracle.is_relevant_generated_file(relevant_scenario, relevant_root, relative, path)
            ):
                continue
            files.append({"path": rel, "size": stat.st_size})
        return files

    def write_file_manifest(self, path: Path, roots: dict[str, Path], *, scenario: Scenario | None = None, debug_full: bool = False) -> None:
        data = {name: self.list_files(root, scenario=None if debug_full else scenario, root_name=name) for name, root in roots.items()}
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def install_graphify(self, env: dict[str, str]) -> dict[str, object]:
        artifact_dir = self.output / "package-install"
        install_command = (sys.executable, "-m", "pip", "install", "--user", str(self.src))
        result = command_runner.run_capture(install_command, cwd=Path("/tmp"), env=env, artifact_dir=artifact_dir, command_class="package_install")
        if result.returncode != 0:
            raise RuntimeError("pip install failed; see package-install artifacts")

        metadata = source_snapshot.read_installed_package_metadata(self.package_name, self.src, home=self.home)
        version_command = ("graphify", "--version")
        probe_result = command_runner.run_capture(version_command, cwd=Path("/tmp"), env=env, artifact_dir=artifact_dir / "graphify-version", command_class="graphify_version")
        if probe_result.returncode != 0:
            raise RuntimeError("graphify version probe failed; see package-install/graphify-version artifacts")
        probe = command_probe_summary(probe_result, version_command)
        metadata["version"] = metadata.get("version") or version_from_probe(probe)
        metadata["install_mode"] = self.install_mode
        metadata["install_command"] = list(install_command)
        metadata["command_probe"] = probe
        if metadata.get("installed_from_copied_source") is not True:
            raise RuntimeError(
                "installed package provenance check failed; "
                f"package_name={metadata.get('package_name')}; "
                f"location={metadata.get('location')}; "
                f"direct_url={metadata.get('direct_url')}; "
                f"expected_source={self.src.resolve()}"
            )
        return metadata

    def install_variant_artifact_label(self, label: str, used: set[str]) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", label).strip(".-_").lower() or "variant"
        candidate = safe
        index = 2
        while candidate in used:
            candidate = f"{safe}-{index}"
            index += 1
        used.add(candidate)
        return candidate

    def run_install_variant(self, scenario: Scenario, command: tuple[str, ...], env: dict[str, str], artifact_dir: Path) -> dict[str, object]:
        oracle = self.file_effect_oracle()
        self.reset_sandbox_dirs()
        artifact_dir.mkdir(parents=True, exist_ok=True)
        oracle.seed_user_owned_content(scenario)
        self.write_file_manifest(artifact_dir / "before-install-files.json", self.roots, scenario=scenario)
        cwd = oracle.root_path(scenario.cwd_root)
        result = command_runner.run_capture(command, cwd=cwd, env=env, artifact_dir=artifact_dir, command_class="installer")
        checks = oracle.assert_expected_files(scenario) + oracle.assert_scope_boundaries(scenario) + oracle.assert_no_unexpected_graphify_files(scenario, phase="install")
        state = oracle.scenario_file_state(scenario)
        self.write_file_manifest(artifact_dir / "after-install-files.json", self.roots, scenario=scenario)
        return {
            "command": list(command),
            "exit_code": result.returncode,
            "checks": checks,
            "state": state,
            "passed": result.returncode == 0 and all(check["ok"] for check in checks),
        }

    def run_equivalence_check(self, scenario: Scenario, env: dict[str, str], artifact_dir: Path) -> list[dict[str, object]]:
        variants = self.scenario_registry.equivalent_install_variants(scenario)
        equivalence_dir = artifact_dir / "generic-direct-equivalence"
        if variants is None:
            (equivalence_dir / "status.json").parent.mkdir(parents=True, exist_ok=True)
            (equivalence_dir / "status.json").write_text(json.dumps(self.scenario_registry.equivalence_status(scenario), indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return []

        primary_variant, alternate_variant = variants
        used_labels: set[str] = set()
        primary_label = self.install_variant_artifact_label(primary_variant.label, used_labels)
        alternate_label = self.install_variant_artifact_label(alternate_variant.label, used_labels)
        primary = self.run_install_variant(scenario, primary_variant.command, env, equivalence_dir / primary_label)
        alternate_result = self.run_install_variant(scenario, alternate_variant.command, env, equivalence_dir / alternate_label)
        same_effects = primary["state"] == alternate_result["state"]
        passed = bool(primary["passed"] and alternate_result["passed"] and same_effects)
        report = {
            "status": "runnable",
            "passed": passed,
            "primary_label": primary_variant.label,
            "alternate_label": alternate_variant.label,
            "primary": primary,
            "alternate": alternate_result,
            "same_file_effects": same_effects,
        }
        (equivalence_dir / "equivalence.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return [
            {
                "path": f"{scenario.platform}/{scenario.scope}",
                "ok": passed,
                "detail": f"generic_direct_equivalent={same_effects}; primary_exit={primary['exit_code']}; alternate_exit={alternate_result['exit_code']}",
            }
        ]

    def risk_report(self, scenario: Scenario, passed: bool) -> dict[str, object]:
        return {
            "statuses": [RISK_GRAPHIFY_VERIFIED if passed else RISK_GRAPHIFY_FAILED],
            "notes": list(scenario.risk_notes),
            "known_status_values": known_status_values(),
        }

    def scenario_lifecycle_hooks(
        self,
        *,
        run_scenario_func=None,
        run_universal_uninstall_scenario_func=None,
        run_purge_scenario_func=None,
    ) -> scenario_lifecycle_support.ScenarioLifecycleHooks:
        oracle = self.file_effect_oracle()
        return scenario_lifecycle_support.ScenarioLifecycleHooks(
            paths=scenario_lifecycle_support.SandboxPaths(
                output=self.output,
                roots=self.roots,
                project=self.project,
                user_cwd=self.user_cwd,
                utc_timestamp=utc_timestamp,
                root_path=oracle.root_path,
                reset_sandbox_dirs=self.reset_sandbox_dirs,
            ),
            file_effects=scenario_file_effects_adapter.ScenarioFileEffectsAdapter(
                oracle=oracle,
                write_file_manifest=self.write_file_manifest,
                run_equivalence_check=self.run_equivalence_check,
            ),
            commands=scenario_lifecycle_support.CommandExecutor(command_runner.run_capture),
            artifacts=scenario_lifecycle_support.ScenarioArtifacts(
                risk_report=self.risk_report,
                command_artifact_summary=lambda artifact_dir: reports.command_artifact_summary(artifact_dir, output_root=self.output),
                combined_status=combined_status,
                known_status_values=known_status_values,
            ),
            scenario_registry=self.scenario_registry,
            matrix_overrides=scenario_lifecycle_support.MatrixRunnerOverrides(
                run_scenario=run_scenario_func,
                run_universal_uninstall_scenario=run_universal_uninstall_scenario_func,
                run_purge_scenario=run_purge_scenario_func,
            ),
        )

    def preflight(self) -> dict[str, object]:
        self.scenario_registry.validate_roots(self.root_registry.install_surface_root_names())
        validation_plan.DEFAULT_HARNESS_POLICY.validate_roots(self.root_registry.install_surface_root_names())
        for root in self.root_registry.roots:
            path = self.runtime_roots[root.name]
            if root.reset or root.mount_mode == "rw" or root.name == "xdg_config_home":
                path.mkdir(parents=True, exist_ok=True)
        checks: dict[str, object] = {root.name: str(self.runtime_roots[root.name]) for root in self.root_registry.roots}
        required_keys: list[str] = []
        for root in self.root_registry.preflight_roots():
            path = self.runtime_roots[root.name]
            if root.sandbox_path_required is not None:
                key = "xdg_is_sandbox" if root.name == "xdg_config_home" else f"{root.name}_is_sandbox"
                checks[key] = str(path) == root.sandbox_path_required
                required_keys.append(key)
            if root.mount_mode == "ro":
                exists_key = f"{root.name}_exists"
                read_only_key = f"{root.name}_read_only"
                checks[exists_key] = path.is_dir()
                checks[read_only_key] = probe_read_only(path) if path.exists() else False
                required_keys.extend([exists_key, read_only_key])
        (self.output / "preflight.json").write_text(json.dumps(checks, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if not all(bool(checks[key]) for key in required_keys):
            raise RuntimeError(f"sandbox invariant failed: {checks}")
        return checks

