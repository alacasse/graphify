from __future__ import annotations


RISK_GRAPHIFY_VERIFIED = "graphify_install_verified"
RISK_GRAPHIFY_FAILED = "graphify_install_failed"


def known_status_values() -> list[str]:
    return [RISK_GRAPHIFY_VERIFIED, RISK_GRAPHIFY_FAILED]


def combined_status(graphify_passed: bool) -> str:
    return RISK_GRAPHIFY_VERIFIED if graphify_passed else RISK_GRAPHIFY_FAILED
