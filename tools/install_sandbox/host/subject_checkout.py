"""Materialize the declared Git revision independently of the evolving harness."""

import subprocess
import tarfile
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from tools.install_sandbox.contracts.effect_case import SubjectContext


@contextmanager
def captured_subject(repository: Path, subject: SubjectContext) -> Generator[Path]:
    """Keep controlled historical sources unchanged; package runs use an exact commit."""
    if subject.package_root is None:
        yield repository
        return
    assert subject.revision is not None
    resolved = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "--verify", subject.revision + "^{commit}"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout.strip()
    if resolved != subject.revision:
        raise ValueError("Subject revision did not resolve to the declared commit")
    with tempfile.TemporaryDirectory(prefix="install-sandbox-subject-") as temporary:
        root = Path(temporary)
        archive = root / "subject.tar"
        with archive.open("wb") as stream:
            subprocess.run(
                ["git", "-C", str(repository), "archive", "--format=tar", resolved],
                stdout=stream,
                stderr=subprocess.PIPE,
                check=True,
                timeout=30,
            )
        checkout = root / "subject"
        checkout.mkdir()
        with tarfile.open(archive) as source:
            source.extractall(checkout, filter="data")
        yield checkout
