"""Load native effects or retained legacy cases at the shared execution boundary."""

import json

from tools.install_sandbox.contracts.case import InstallTestCase
from tools.install_sandbox.contracts.effect_case import EffectInstallCase

ExecutionCase = InstallTestCase | EffectInstallCase


def load_case(payload: str) -> ExecutionCase:
    data: object = json.loads(payload)
    if isinstance(data, dict) and "format" in data:
        return EffectInstallCase.from_json(payload)
    return InstallTestCase.from_json(payload)
