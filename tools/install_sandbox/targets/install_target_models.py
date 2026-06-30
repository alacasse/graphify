from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..surfaces.install_surface_models import (
    ExpectedPath,
    FileEffect,
    InstallSurface,
    JsonExpectation,
    JsonHookExpectation,
    JsonHooksEffect,
    JsonPluginEffect,
    JsonPluginExpectation,
    SkillEffect,
    SkillSidecarExpectation,
    TextExpectation,
    TextSectionEffect,
)

GRAPHIFY_MARKER = "## graphify"
PUBLIC_CLI_LACKS_USER_SKILL_UNINSTALL_NOTE = "public_cli_lacks_user_skill_uninstall"
MIXED_SCOPE_PROJECT_WIRING_NOTE = "mixed_scope_project_wiring"
MIXED_SCOPE_GLOBAL_SKILL_PROJECT_WIRING_NOTE = "mixed_scope_global_skill_plus_project_wiring"
SIMULATED_LINUX_LAYOUT_NOTE = "simulated_linux_file_layout_only"


@dataclass(frozen=True)
class GeneratedFileExpectation:
    relative_substrings: tuple[str, ...] = ("graphify",)
    text_suffixes: tuple[str, ...] = (".json", ".js", ".md", ".mdc", ".txt", "")
    content_markers: tuple[str, ...] = ("graphify",)
    include_user_content_sentinel: bool = True
    max_text_bytes: int = 1024 * 1024


@dataclass(frozen=True)
class InstallCommandVariant:
    label: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class TargetRuntimeValidationSpec:
    section_title: str
    status: str
    strategy: str
    targets: tuple[str, ...]
    notes: tuple[str, ...]
    evidence_path: str | None = None

    def to_manifest(self) -> dict[str, object]:
        return {
            "section_title": self.section_title,
            "status": self.status,
            "evidence_path": self.evidence_path,
            "strategy": self.strategy,
            "targets": list(self.targets),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class UniversalUninstallScenarioSpec:
    scenario_id: str
    platform_label: str
    scope: str
    command: tuple[str, ...]
    cwd_root: str
    eligible_platform_scope: str
    minimum_installed_scenarios: int = 2
    artifact_subdir: str = "uninstall"
    risk_note: str = "universal uninstall covers Graphify-owned file effects after multiple installs"


@dataclass(frozen=True)
class SelectedUniversalUninstallScenario:
    spec: UniversalUninstallScenarioSpec
    installed_scenarios: tuple[Scenario, ...]


@dataclass(frozen=True)
class DisposableSeedFile:
    relative: str
    content: str


@dataclass(frozen=True)
class DisposableArtifactScenarioSpec:
    scenario_id: str
    platform_label: str
    scope: str
    command: tuple[str, ...]
    cwd_root: str
    artifact_subdir: str
    disposable_path_root: str
    disposable_path_relative: str
    seed_files: tuple[DisposableSeedFile, ...]
    scope_eligibility: tuple[str, ...]
    risk_note: str


@dataclass(frozen=True)
class Scenario:
    platform: str
    scope: str
    install_command: tuple[str, ...]
    uninstall_command: tuple[str, ...] | None
    cwd_root: str
    expected: tuple[InstallSurface, ...]
    risk_notes: tuple[str, ...] = field(default_factory=tuple)
    allowed_roots: tuple[str, ...] = ()
    generated_file_expectation: GeneratedFileExpectation = field(default_factory=GeneratedFileExpectation)


@dataclass(frozen=True)
class ScopeSpec:
    install_command: tuple[str, ...]
    uninstall_command: tuple[str, ...] | None
    cwd_root: str
    expected: tuple[InstallSurface, ...]
    risk_notes: tuple[str, ...] = field(default_factory=tuple)
    equivalent_install_command: tuple[str, ...] | None = None
    install_variants: tuple[InstallCommandVariant, ...] = ()
    allowed_roots: tuple[str, ...] = ()
    generated_file_expectation: GeneratedFileExpectation = field(default_factory=GeneratedFileExpectation)


@dataclass(frozen=True)
class ReferenceBundle:
    name: str
    required_package_relative: str | None = None

    def is_eligible(self, package_dir: Path) -> bool:
        return self.required_package_relative is None or (package_dir / self.required_package_relative).exists()


@dataclass(frozen=True)
class InstallTargetSpec:
    name: str
    display_name: str | None = None
    target_kind: str = "product"
    user_skill: str | None = None
    project_skill: str | None = None
    scopes: dict[str, ScopeSpec] = field(default_factory=dict)
    unsupported_scopes: dict[str, str] = field(default_factory=dict)
    uses_packaged_references: bool = True
    reference_bundles: tuple[ReferenceBundle, ...] = ()
    simulated_linux_layout: bool = False
    universal_uninstall_scopes: tuple[str, ...] = ()
    target_runtime_validation: tuple[TargetRuntimeValidationSpec, ...] = ()
