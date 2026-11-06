"""The filesystem writer accepts only the replacement bound to the skill's version."""

import hashlib
import json
from pathlib import Path

import pytest

from tests.install_sandbox.component.host.native_support import arrange
from tools.install_sandbox.container.effect_environment import EffectEnvironment
from tools.install_sandbox.container.file_mutation import apply_mutation
from tools.install_sandbox.contracts.bound_mutation import BoundFileRemoval, BoundFileReplacement
from tools.install_sandbox.contracts.effect_case import SubjectContext, build_effect_cases
from tools.install_sandbox.contracts.effects import Destination
from tools.install_sandbox.host.effect_reader import EffectSpecReader


@pytest.mark.parametrize("fault", [None, "operation", "destination", "original", "witness"])
def test_version_replacement_checks_binding_and_handles_witness_collision(
    tmp_path: Path, fault: str | None
) -> None:
    subject, spec, context = arrange(tmp_path, markdown=False, hooks=False)
    (subject / "METADATA").write_bytes(b"Version: 0.0.0-stale\n")
    cases = build_effect_cases(
        EffectSpecReader().read(spec), SubjectContext.from_data(json.loads(context.read_text()))
    )
    case = next(case for case in cases.cases if case.name == "stale-version")
    environment = EffectEnvironment(case, tmp_path / "work")
    case_bytes = case.to_json().encode()
    directory = environment.home / ".synthetic/skills/package"
    directory.mkdir(parents=True)
    target = directory / ".graphify_version"
    original = b"untrusted" if fault == "original" else b"0.0.0-stale"
    target.write_bytes(original)
    decoy = directory / "personal"
    decoy.write_bytes(original)
    selected = decoy if fault == "destination" else target
    binding = (
        hashlib.sha256(case_bytes).hexdigest(),
        "steps/0/after.json",
        Destination("home", selected.relative_to(environment.home).as_posix()),
        hashlib.sha256(original).hexdigest(),
    )
    witness = b"0.0.0-stale" if fault == "witness" else b"0.0.1-stale"
    operation = (
        BoundFileRemoval(*binding)
        if fault == "operation"
        else BoundFileReplacement(*binding, witness)
    )
    observed = environment.observe_intermediate("before")
    sources = environment.capture_sources(subject)
    if fault is None:
        apply_mutation(operation, environment, case_bytes, observed, sources)
        assert target.read_bytes() == witness
    else:
        with pytest.raises(ValueError):
            apply_mutation(operation, environment, case_bytes, observed, sources)
        assert target.read_bytes() == original
    assert decoy.read_bytes() == original
