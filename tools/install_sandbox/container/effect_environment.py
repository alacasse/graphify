"""Observe native effects without imposing the legacy three-field spec."""

from pathlib import Path

from tools.install_sandbox.container.environment import ObservedEnvironment
from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.effects import MarkdownSectionEffect, SkillEffect
from tools.install_sandbox.contracts.observation import FilesystemSnapshot


def source_paths(case: EffectInstallCase) -> list[str]:
    sources: list[str] = []
    for effect in case.effects.effects:
        if isinstance(effect, SkillEffect):
            sources.extend((effect.source, effect.references, case.subject.version_source))
        elif isinstance(effect, MarkdownSectionEffect):
            sources.append(effect.source)
    # Shared sources are captured only once, including children of a source directory.
    return [
        path
        for path in dict.fromkeys(sources)
        if not any(path.startswith(other + "/") for other in sources if other != path)
    ]


class EffectEnvironment(ObservedEnvironment):
    def __init__(self, case: EffectInstallCase, directory: Path):
        self.case = EffectInstallCase.from_json(case.to_json())
        self.project = directory / "project"
        self.home = directory / "home"
        self.project.mkdir(parents=True, exist_ok=False)
        self.home.mkdir(parents=True, exist_ok=False)

    def prepare(self) -> None:
        for initial in self.case.initial_files:
            root = self.project if initial["root"] == "project" else self.home
            path = root / initial["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(initial["content"].encode("utf-8"))

    def capture_sources(self, subject: Path) -> FilesystemSnapshot:
        snapshot = FilesystemSnapshot()
        for path in source_paths(self.case):
            self._capture(snapshot, "subject", subject, path)
        return snapshot

    def capture_initial(self) -> FilesystemSnapshot:
        return self.observe_intermediate("initial")

    def observe_intermediate(self, phase: str) -> FilesystemSnapshot:
        snapshot = FilesystemSnapshot()
        for root, directory in (("project", self.project), ("home", self.home)):
            self._capture(snapshot, root, directory, ".")
        return snapshot
