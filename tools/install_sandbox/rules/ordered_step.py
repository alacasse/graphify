"""Bind the authorized command and assess its observed effects at a plan index."""

from tools.install_sandbox.contracts.effect_case import EffectInstallCase
from tools.install_sandbox.contracts.expectations import ExpectationSet
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import VerificationResult
from tools.install_sandbox.rules.effect_verifier import EffectVerifier
from tools.install_sandbox.rules.group_assessment import assess_group_step


def command_intent(case: EffectInstallCase, index: int) -> dict[str, object]:
    return {"index": index, **case.steps[index].to_data()}


def expectation_path(case: EffectInstallCase, index: int) -> str:
    if index == 0:
        return "expectations/install.json"
    if case.group is not None:
        return f"steps/{index}/expectations.json"
    return "expectations/reinstall.json"


def verify_step(
    case: EffectInstallCase,
    index: int,
    expectations: ExpectationSet,
    initial: FilesystemSnapshot,
    before: FilesystemSnapshot,
    after: FilesystemSnapshot,
) -> tuple[dict[str, object] | None, VerificationResult]:
    group = case.group
    if group is None:
        return None, EffectVerifier().verify(expectations, after)
    step = case.steps[index]
    return assess_group_step(
        group.participants,
        group.prepare[:index],
        step.participants,
        step.action == "uninstall",
        initial,
        before,
        after,
    )
