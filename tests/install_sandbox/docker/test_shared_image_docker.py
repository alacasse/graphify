"""One explicitly authorized campaign, one build, two fresh case containers."""

from tests.install_sandbox.docker.test_first_install_docker import pytestmark, run_campaign_proof
from tests.install_sandbox.docker.test_preserve_skill_backup_docker import check_case
from tools.install_sandbox.coordinator import CoordinatedResult

__all__ = ["pytestmark"]


def _check(result: CoordinatedResult) -> None:
    assert result.test is not None
    if result.test.case["name"] == "preserve-skill-backup":
        check_case(result)


def test_shared_image_docker() -> None:
    run_campaign_proof(["first-install", "preserve-skill-backup"], _check)
