"""Small native integration subject for entrypoint and process behavior checks."""

import json
import sys
from pathlib import Path

from tools.install_sandbox.container.runner import InstallTestRunner
from tools.install_sandbox.contracts.effect_case import (
    EffectRules,
    SubjectContext,
    build_reinstall_case,
)
from tools.install_sandbox.contracts.effects import Destination, EffectSpec, MarkdownSectionEffect
from tools.install_sandbox.contracts.results import InstallTestResult


class NativeCase:
    def __init__(self, root: Path, mode: str = "passed") -> None:
        self.root, self.mode = root, mode
        subject = root / "subject"
        subject.mkdir(parents=True)
        (subject / "instructions.md").write_text("## graphify\nConsult the synthetic map.\n")
        self.case = build_reinstall_case(
            EffectSpec(
                (MarkdownSectionEffect("instructions.md", Destination("project", "GUIDE.md")),)
            ),
            SubjectContext(
                "entry-test",
                ("install",),
                "METADATA",
                EffectRules(10, "persistent", ".graphify-bak", ".bak", False),
            ),
        )
        self.case.write(root / "case.json")

    def prepare_executable(self) -> None:
        if self.mode == "not_started":
            return
        executable = self.root / "prepared/bin/graphify"
        executable.parent.mkdir(parents=True)
        action = (
            "pass\n"
            if self.mode == "missing"
            else (
                "from pathlib import Path\n"
                "p = Path('GUIDE.md')\ns = p.read_text()\n"
                "if '## graphify' not in s:\n"
                "    p.write_text(s + '\\n## graphify\\nConsult the synthetic map.\\n')\n"
            )
        )
        executable.write_text(f"#!{sys.executable}\n" + action)
        executable.chmod(0o755)

    def run(self) -> InstallTestResult:
        self.prepare_executable()
        return InstallTestRunner().run_case(
            reference_sources=self.root / "subject",
            prepared_executable=self.root / "prepared/bin/graphify",
            case_file=self.root / "case.json",
            work_directory=self.root / "work",
            output_directory=self.root / "results",
        )

    def saved(self) -> dict[str, object]:
        return json.loads((self.root / "results/result.json").read_text())
