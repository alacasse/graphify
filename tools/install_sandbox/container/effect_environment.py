"""Observe native effects without imposing the legacy three-field spec."""

from pathlib import Path

from tools.install_sandbox.container.environment import FilesystemSnapshot, ObservedEnvironment
from tools.install_sandbox.container.evidence_writer import TestResultWriter
from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.effects import MarkdownSectionEffect, SkillEffect


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

    def preserve_expected(self, subject: Path, writer: TestResultWriter) -> FilesystemSnapshot:
        snapshot = FilesystemSnapshot()
        for path in source_paths(self.case):
            self._capture(snapshot, "subject", subject, path)
        writer.write_snapshot(snapshot, "expected")
        return snapshot
