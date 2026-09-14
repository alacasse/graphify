"""Discover and read target YAML files from a supplied directory."""

from pathlib import Path

import yaml

from tools.install_sandbox.contracts.spec import InstallTestSpec


class InstallSpecReader:
    def read(self, directory: Path) -> dict[str, InstallTestSpec]:
        """Read direct *.yaml children, keyed by their filename stems."""
        if not directory.is_dir():
            raise ValueError(f"Spec directory does not exist: {directory}")
        specs: dict[str, InstallTestSpec] = {}
        for path in sorted(directory.glob("*.yaml")):
            if not path.is_file():
                continue
            try:
                specs[path.stem] = InstallTestSpec.from_data(
                    yaml.safe_load(path.read_text(encoding="utf-8"))
                )
            except (ValueError, yaml.YAMLError) as error:
                raise ValueError(f"Invalid spec {path}: {error}") from error
        return specs
