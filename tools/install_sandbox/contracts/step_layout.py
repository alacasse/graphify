"""Shared expectation references for ordered case steps."""

from tools.install_sandbox.contracts.effect_case import EffectInstallCase


def step_expectation_reference(case: EffectInstallCase, index: int) -> str:
    if case.steps[index].action == "uninstall":
        return "expectations/uninstall.json"
    if index == 0:
        return "expectations/install.json"
    if index == case.repair_after_index + 1:
        return "expectations/reinstall.json"
    return f"expectations/step-{index}.json"


def case_expectation_references(case: EffectInstallCase) -> tuple[str, ...]:
    references = ["expectations/initial.json"]
    references.extend(step_expectation_reference(case, index) for index in range(len(case.steps)))
    if case.intermediate_preparation is not None:
        references.append("expectations/intermediate.json")
    return tuple(dict.fromkeys(references))
