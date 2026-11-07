"""Load explicit compositions through the same campaign boundary as --spec."""

import json
from pathlib import Path
from typing import cast

import pytest
import yaml

from tests.install_sandbox.component.host.native_support import arrange
from tools.install_sandbox.host.campaign_definition import load_campaign_definition


def _composition(tmp_path: Path, count: int = 3) -> tuple[Path, Path, Path]:
    subject, spec, context = arrange(tmp_path)
    members: list[dict[str, object]] = []
    for index in range(count):
        member = spec.parent / f"member-{index}.yaml"
        member.write_text(
            yaml.safe_dump(
                {
                    "scope": "project" if index else "user",
                    "directory": ".",
                    "effects": [
                        {
                            "kind": "skill",
                            "source": f"payload-{index}.md",
                            "references": f"bundle-{index}",
                            "destination": {
                                "root": "project" if index else "home",
                                "path": f".arbitrary-{index}/skills/custom",
                            },
                        }
                    ],
                }
            )
        )
        members.append(
            {
                "spec": member.name,
                "invocation": ["install", "--platform", f"arbitrary-{index}"]
                + (["--project"] if index else []),
            }
        )
    spec.write_text(yaml.safe_dump({"scope": "project", "installations": members}))
    data = json.loads(context.read_text())
    data.pop("invocation")
    data["uninstall_invocation"] = ["uninstall", "--project"]
    context.write_text(json.dumps(data))
    return subject, spec, context


@pytest.mark.parametrize("count", [2, 3, 23])
def test_composition_has_no_target_registry_or_member_cap(tmp_path: Path, count: int) -> None:
    subject, spec, context = _composition(tmp_path, count)
    manifest = yaml.safe_load(spec.read_text())
    manifest["installations"].reverse()
    spec.write_text(yaml.safe_dump(manifest))
    definition = load_campaign_definition(
        spec_file=spec, subject_context_file=context, subject_checkout=subject
    )
    retained = definition.context.to_data()
    assert retained["invocation"] == [
        "install",
        "--platform",
        f"arbitrary-{count - 1}",
        "--project",
    ]
    installs = retained["group_installs"]
    assert isinstance(installs, list)
    installs = cast(list[object], installs)
    assert len(installs) == count
    assert installs[0] == {
        "invocation": retained["invocation"],
        "destination": {"root": "project", "path": f".arbitrary-{count - 1}/skills/custom"},
    }
    assert "group_install_invocations" not in retained
    assert [case.name for case in definition.built.cases] == ["group-uninstall-project"]
    assert all("group_installs" in transport for transport in definition.transports)


@pytest.mark.parametrize(
    "fault",
    [
        "traversal",
        "missing",
        "scope",
        "root",
        "non-skill",
        "nested",
        "command",
        "duplicate",
    ],
)
def test_invalid_composition_is_rejected_before_execution(tmp_path: Path, fault: str) -> None:
    subject, spec, context = _composition(tmp_path)
    manifest = yaml.safe_load(spec.read_text())
    first = manifest["installations"][0]
    member = spec.parent / first["spec"]
    target = yaml.safe_load(member.read_text())
    if fault in {"traversal", "missing"}:
        first["spec"] = "../outside.yaml" if fault == "traversal" else "missing.yaml"
    elif fault == "scope":
        target["scope"] = "project"
    elif fault == "root":
        target["effects"][0]["destination"]["root"] = "project"
    elif fault == "non-skill":
        target["effects"] = []
    elif fault == "nested":
        target = {"scope": "user", "installations": cast(list[object], [])}
    elif fault == "command":
        first["invocation"] = ["install", "--platform", "x", "--purge"]
    elif fault == "duplicate":
        manifest["installations"].append(first)
    member.write_text(yaml.safe_dump(target))
    spec.write_text(yaml.safe_dump(manifest))
    with pytest.raises((ValueError, FileNotFoundError)):
        load_campaign_definition(
            spec_file=spec, subject_context_file=context, subject_checkout=subject
        )


@pytest.mark.parametrize("field", ["group_installs", "group_install_invocations", "invocation"])
def test_composition_rejects_context_override(tmp_path: Path, field: str) -> None:
    subject, spec, context = _composition(tmp_path)
    data = json.loads(context.read_text())
    data[field] = ["different"]
    context.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_campaign_definition(
            spec_file=spec, subject_context_file=context, subject_checkout=subject
        )


def test_member_symlink_cannot_escape_manifest_directory(tmp_path: Path) -> None:
    subject, spec, context = _composition(tmp_path)
    member = spec.parent / "member-0.yaml"
    outside = tmp_path.parent / (tmp_path.name + "-outside.yaml")
    outside.write_bytes(member.read_bytes())
    member.unlink()
    member.symlink_to(outside)
    with pytest.raises(ValueError, match="escapes"):
        load_campaign_definition(
            spec_file=spec, subject_context_file=context, subject_checkout=subject
        )


@pytest.mark.parametrize("field", ["group_installs", "group_install_invocations"])
def test_ordinary_spec_cannot_inject_group_transport(tmp_path: Path, field: str) -> None:
    subject, spec, context = arrange(tmp_path)
    data = json.loads(context.read_text())
    data[field] = [
        {
            "invocation": ["install", "--platform", "bypass"],
            "destination": {"root": "home", "path": "bypass"},
        }
    ]
    context.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="only by the composition manifest"):
        load_campaign_definition(
            spec_file=spec, subject_context_file=context, subject_checkout=subject
        )


@pytest.mark.parametrize(
    "name,count,cases",
    [
        ("group-uninstall-project", 3, ["group-uninstall-project"]),
        ("global-uninstall", 4, ["global-uninstall", "global-uninstall-purge"]),
    ],
)
def test_shipped_manifests_use_existing_target_specs(
    tmp_path: Path, name: str, count: int, cases: list[str]
) -> None:
    subject, _, context = arrange(tmp_path)
    data = json.loads(context.read_text())
    data["invocation"] = ["install", "--platform", "agents"]
    data["uninstall_invocation"] = ["uninstall"]
    if name == "global-uninstall":
        data["purge_invocation"] = ["uninstall", "--purge"]
    else:
        data["uninstall_invocation"].append("--project")
    context.write_text(json.dumps(data))
    spec = Path(__file__).resolve().parents[4] / "tools/install_sandbox/specs" / f"{name}.yaml"
    definition = load_campaign_definition(
        spec_file=spec, subject_context_file=context, subject_checkout=subject
    )
    assert len(definition.effects.effects) == count
    assert [case.name for case in definition.built.cases] == cases
    if name == "global-uninstall":
        installs = definition.context.group_installs
        assert installs is not None
        assert [item.invocation[2] for item in installs] == ["agents", "copilot", "kimi", "pi"]


@pytest.mark.parametrize("fault", ["no-home", "repeated-command", "removal", "locks"])
def test_prepare_only_validates_group_behavior(tmp_path: Path, fault: str) -> None:
    subject, spec, context = _composition(tmp_path)
    manifest = yaml.safe_load(spec.read_text())
    data = json.loads(context.read_text())
    data.update(package_root="graphify", revision="a" * 40)
    if fault == "no-home":
        manifest["installations"].pop(0)
    elif fault == "repeated-command":
        manifest["installations"][2]["invocation"] = manifest["installations"][1]["invocation"]
    elif fault == "removal":
        data["uninstall_invocation"] = ["uninstall", "--purge"]
    else:
        data["home_lock_destinations"] = ["unexpected/lock"]
    spec.write_text(yaml.safe_dump(manifest))
    context.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_campaign_definition(
            spec_file=spec,
            subject_context_file=context,
            subject_checkout=subject,
            prepare_only=True,
        )


def test_prepare_only_valid_group_skips_execution_cases(tmp_path: Path) -> None:
    subject, spec, context = _composition(tmp_path)
    data = json.loads(context.read_text())
    data.update(package_root="graphify", revision="a" * 40)
    context.write_text(json.dumps(data))
    definition = load_campaign_definition(
        spec_file=spec, subject_context_file=context, subject_checkout=subject, prepare_only=True
    )
    assert definition.built.cases == () and definition.transports == ()
