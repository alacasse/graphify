"""Installed observations are independent of product command execution."""

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.install_sandbox.container import package_observation


def _locate(value: Path) -> Path:
    return value


def test_observe_records_installed_resources_and_owned_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "candidate"
    package.mkdir()
    module = package / "__init__.py"
    module.write_text("def main(): pass\n")
    (package / "skill.md").write_bytes(b"installed bytes")
    executable = tmp_path / "candidate-cli"
    executable.write_text(
        "#!/venv/python\nimport re\nimport sys\nfrom candidate import main\n"
        "if __name__ == '__main__':\n"
        "    sys.argv[0] = re.sub(r'(-script\\.pyw|\\.exe)?$', '', sys.argv[0])\n"
        "    sys.exit(main())\n"
    )
    executable.chmod(0o755)
    declaration = tmp_path / "inputs.json"
    declaration.write_text(
        json.dumps(
            {
                "distribution": "candidate",
                "console": "candidate-cli",
                "entry_point": "candidate:main",
                "package_root": "candidate",
            }
        )
    )
    distribution = SimpleNamespace(
        version="1.2.3",
        metadata={"Name": "candidate"},
        files=[module, executable],
        locate_file=_locate,
        entry_points=[
            SimpleNamespace(group="console_scripts", name="candidate-cli", value="candidate:main")
        ],
    )

    def installed(_name: str) -> SimpleNamespace:
        return distribution

    monkeypatch.setattr(package_observation.importlib.metadata, "distribution", installed)

    def imported(_name: str) -> SimpleNamespace:
        return SimpleNamespace(__file__=str(module))

    monkeypatch.setattr(package_observation.importlib, "import_module", imported)
    package_observation.observe(declaration, tmp_path, str(executable))
    observed = json.loads((tmp_path / "observation.json").read_text())
    assert observed["errors"] == []
    assert observed["module_owned"] is True
    assert observed["executable_entry_point"] is True
    assert base64.b64decode(observed["executable_script"]) == executable.read_bytes()
    assert base64.b64decode(observed["resources"]["skill.md"]) == b"installed bytes"
    assert observed["version"] == "1.2.3"


def test_observe_retains_missing_distribution_as_evidence(tmp_path: Path) -> None:
    declaration = tmp_path / "inputs.json"
    declaration.write_text(
        json.dumps(
            {
                "distribution": "sandbox-intentionally-missing-package",
                "console": "missing",
                "entry_point": "missing:main",
                "package_root": "missing",
            }
        )
    )
    package_observation.observe(declaration, tmp_path, str(tmp_path / "missing"))
    observed = json.loads((tmp_path / "observation.json").read_text())
    assert len(observed["errors"]) == 2
    assert observed["module_owned"] is False
    assert observed["resources"] == {}
