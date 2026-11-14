"""Select the executable reinstall obligation using its complete campaign key."""

from tools.install_sandbox.contracts.effect_case import (
    CaseKey,
    EffectInstallCase,
    SubjectContext,
    build_effect_cases,
)
from tools.install_sandbox.contracts.effects import EffectSpec


def reinstall_case(
    spec: EffectSpec, subject: SubjectContext, target: str = "controlled"
) -> EffectInstallCase:
    key = CaseKey(target, spec.scope, "reinstall")
    return next(case for case in build_effect_cases(spec, subject, target).cases if case.key == key)
