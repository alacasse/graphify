"""Replay a package gate from independent capture and portable observations."""

import base64
import json
import shutil
from pathlib import Path

import pytest

from tools.install_sandbox.contracts.effect_case import EffectRules, SubjectContext
from tools.install_sandbox.contracts.effects import Destination, EffectSpec, SkillEffect
from tools.install_sandbox.host.preparation import capture_preparation, evaluate_preparation
from tools.install_sandbox.host.preparation_reader import read_preparation

_IMAGE = "sha256:" + "a" * 64
_SCRIPT = (
    b"#!/opt/install-sandbox/venv/bin/python\n"
    b"import sys\nfrom graphify.cli import main\n"
    b"if __name__ == '__main__':\n"
    b'    if sys.argv[0].endswith("-script.pyw"):\n'
    b"        sys.argv[0] = sys.argv[0][:-11]\n"
    b'    elif sys.argv[0].endswith(".exe"):\n'
    b"        sys.argv[0] = sys.argv[0][:-4]\n"
    b"    sys.exit(main())\n"
)


def capture(tmp_path: Path) -> Path:
    subject = tmp_path / "source"
    references = subject / "graphify/skills/codebuddy/references"
    references.mkdir(parents=True)
    (references / "nested").mkdir()
    (references / "nested/read.md").write_text("reference")
    (subject / "graphify/skill.md").write_text("skill")
    (subject / "pyproject.toml").write_text(
        '[project]\nname="graphifyy"\nversion="1.2.3"\n'
        '[project.scripts]\ngraphify="graphify.cli:main"\n'
    )
    context = SubjectContext(
        "graphify",
        ("codebuddy", "install"),
        "package-metadata",
        EffectRules(10, "persistent", ".graphify-bak", ".bak", False),
        package_root="graphify",
        revision="b" * 40,
    )
    effects = EffectSpec(
        (
            SkillEffect(
                "skill.md",
                "skills/codebuddy/references",
                Destination("project", ".skills/graphify"),
            ),
        )
    )
    output = tmp_path / "proof"
    capture_preparation(subject, output, effects, context)
    return output


def observe(output: Path) -> None:
    resources = {
        "skill.md": base64.b64encode(b"skill").decode(),
        "skills/codebuddy/references/nested/read.md": base64.b64encode(b"reference").decode(),
    }
    payload = {
        "format": "preparation-observation-v1",
        "image_id": _IMAGE,
        "distribution": "graphifyy",
        "version": "1.2.3",
        "entry_point": "graphify.cli:main",
        "interpreter": "/opt/install-sandbox/venv/bin/python",
        "executable": "/opt/install-sandbox/venv/bin/graphify",
        "module": "/opt/install-sandbox/venv/lib/python3.12/site-packages/graphify/cli.py",
        "source_root": "/opt/install-sandbox/venv/lib/python3.12/site-packages/graphify",
        "resources": resources,
        "directories": ["skills/codebuddy/references", "skills/codebuddy/references/nested"],
        "module_owned": True,
        "executable_owned": True,
        "executable_entry_point": True,
        "executable_regular": True,
        "executable_script": base64.b64encode(_SCRIPT).decode(),
        "executable_shebang": "#!/opt/install-sandbox/venv/bin/python",
        "errors": [],
    }
    (output / "observation.json").write_text(json.dumps(payload))


def test_replay_survives_loss_of_original_subject(tmp_path: Path) -> None:
    output = capture(tmp_path)
    observe(output)
    result = evaluate_preparation(output, _IMAGE)
    assert result.status == "prepared"
    shutil.rmtree(tmp_path / "source")
    assert read_preparation(output) == result
    assert (output / "expected/package-metadata").read_bytes() == b"Version: 1.2.3\n"


@pytest.mark.parametrize("name", ["inputs.json", "observation.json", "result.json"])
def test_missing_proof_is_incomplete(tmp_path: Path, name: str) -> None:
    output = capture(tmp_path)
    observe(output)
    evaluate_preparation(output, _IMAGE)
    (output / name).unlink()
    assert read_preparation(output).status == "incomplete"


@pytest.mark.parametrize("name", ["subject/graphify/skill.md", "expected/skill.md", "result.json"])
def test_altered_retained_proof_is_incomplete(tmp_path: Path, name: str) -> None:
    output = capture(tmp_path)
    observe(output)
    evaluate_preparation(output, _IMAGE)
    (output / name).write_text("altered")
    assert read_preparation(output).status == "incomplete"


def test_coherent_installed_resource_mismatch_is_nonconformant(tmp_path: Path) -> None:
    output = capture(tmp_path)
    observe(output)
    path = output / "observation.json"
    data = json.loads(path.read_text())
    data["resources"]["skill.md"] = base64.b64encode(b"wrong wheel content").decode()
    path.write_text(json.dumps(data))
    result = evaluate_preparation(output, _IMAGE)
    assert result.status == "nonconformant"
    assert read_preparation(output) == result


def test_missing_observation_is_retained_incomplete(tmp_path: Path) -> None:
    output = capture(tmp_path)
    result = evaluate_preparation(output, "")
    assert result.status == "incomplete"
    assert read_preparation(output) == result


def test_dynamic_metadata_is_rejected_before_build(tmp_path: Path) -> None:
    output = capture(tmp_path)
    subject = output / "subject"
    project = subject / "pyproject.toml"
    project.write_text(project.read_text().replace('version="1.2.3"', 'dynamic=["version"]'))
    from tools.install_sandbox.host.preparation_reader import retained_inputs

    with pytest.raises(ValueError, match="Dynamic"):
        retained_inputs(output)


@pytest.mark.parametrize("field", ["image_id", "source_root", "executable_shebang", "module_owned"])
def test_identity_or_provenance_mismatch_never_prepares(tmp_path: Path, field: str) -> None:
    output = capture(tmp_path)
    observe(output)
    path = output / "observation.json"
    data = json.loads(path.read_text())
    data[field] = False if field == "module_owned" else "/unexpected"
    path.write_text(json.dumps(data))
    result = evaluate_preparation(output, _IMAGE)
    assert result.status in {"nonconformant", "incomplete"}
    assert result.binding is None
    assert read_preparation(output) == result


def test_altered_saved_image_identity_is_incomplete(tmp_path: Path) -> None:
    output = capture(tmp_path)
    observe(output)
    evaluate_preparation(output, _IMAGE)
    path = output / "result.json"
    data = json.loads(path.read_text())
    data["binding"]["image_id"] = "sha256:" + "c" * 64
    path.write_text(json.dumps(data))
    assert read_preparation(output).status == "incomplete"


def test_empty_reference_resource_is_valid(tmp_path: Path) -> None:
    output = capture(tmp_path)
    source = tmp_path / "source"
    (source / "graphify/skills/codebuddy/references/nested/read.md").write_bytes(b"")
    shutil.rmtree(output)
    # Recreate the capture from the now-empty original reference using retained declarations.
    # A second minimal capture helper would hide the essential empty-byte comparison.
    from tools.install_sandbox.host.preparation_reader import retained_inputs

    other = capture(tmp_path / "other")
    _inputs, effects, context = retained_inputs(other)
    capture_preparation(source, output, effects, context)
    observe(output)
    observation = output / "observation.json"
    data = json.loads(observation.read_text())
    data["resources"]["skills/codebuddy/references/nested/read.md"] = ""
    observation.write_text(json.dumps(data))
    assert evaluate_preparation(output, _IMAGE).status == "prepared"


def test_interrupted_runtime_cannot_publish_a_valid_binding(tmp_path: Path) -> None:
    output = capture(tmp_path)
    observe(output)
    (output / "runtime.json").write_text(
        json.dumps(
            {"state": "interrupted", "phase": "verification", "detail": "container interrupted"}
        )
    )
    result = evaluate_preparation(output, _IMAGE)
    assert result.status == "incomplete"
    assert result.binding is None
    assert "interrupted" in result.diagnostics[0]
    assert read_preparation(output) == result


@pytest.mark.parametrize(
    "change",
    [
        "nested-missing",
        "extra-reference",
        "directory-missing",
        "version",
        "module",
        "executable",
        "interpreter",
    ],
)
def test_independent_installed_observation_mismatches(tmp_path: Path, change: str) -> None:
    output = capture(tmp_path)
    observe(output)
    path = output / "observation.json"
    data = json.loads(path.read_text())
    if change == "nested-missing":
        del data["resources"]["skills/codebuddy/references/nested/read.md"]
    elif change == "extra-reference":
        data["resources"]["skills/codebuddy/references/unexpected.md"] = "ZXh0cmE="
    elif change == "directory-missing":
        data["directories"].remove("skills/codebuddy/references/nested")
    else:
        data[change] = "9.9.9" if change == "version" else "/unexpected/path"
    path.write_text(json.dumps(data))
    result = evaluate_preparation(output, _IMAGE)
    assert result.status == "nonconformant"
    assert result.binding is None
    assert read_preparation(output) == result


@pytest.mark.parametrize(
    "declaration",
    [
        '[project]\nname="graphifyy"\n[project.scripts]\ngraphify="graphify.cli:main"\n',
        '[project]\nname="graphifyy"\ndynamic=["version"]\n[project.scripts]\ngraphify="graphify.cli:main"\n',
        '[project]\nname="graphifyy"\nversion="1.2.3"\n[project.scripts]\ngraphify=["graphify.cli:main"]\n',
    ],
)
def test_unusable_static_declaration_is_rejected(tmp_path: Path, declaration: str) -> None:
    output = capture(tmp_path)
    from tools.install_sandbox.host.preparation_reader import retained_inputs

    _inputs, effects, context = retained_inputs(output)
    subject = tmp_path / "source"
    (subject / "pyproject.toml").write_text(declaration)
    with pytest.raises(ValueError):
        capture_preparation(subject, tmp_path / "invalid-proof", effects, context)


@pytest.mark.parametrize("change", ["partial", "invalid-base64", "missing-image"])
def test_malformed_observation_is_incomplete(tmp_path: Path, change: str) -> None:
    output = capture(tmp_path)
    observe(output)
    path = output / "observation.json"
    data = json.loads(path.read_text())
    if change == "partial":
        del data["resources"]
    elif change == "invalid-base64":
        data["resources"]["skill.md"] = "!!"
    else:
        del data["image_id"]
    path.write_text(json.dumps(data))
    result = evaluate_preparation(output, _IMAGE)
    assert result.status == "incomplete"
    assert result.binding is None
    assert read_preparation(output) == result


@pytest.mark.parametrize(
    "script",
    [
        _SCRIPT.replace(b"from graphify.cli import main", b"# from graphify.cli import main"),
        _SCRIPT.replace(b"sys.exit(main())", b"sys.exit(0)"),
    ],
)
def test_reader_checks_script_despite_forged_provenance_flag(tmp_path: Path, script: bytes) -> None:
    output = capture(tmp_path)
    observe(output)
    path = output / "observation.json"
    data = json.loads(path.read_text())
    data["executable_script"] = base64.b64encode(script).decode()
    data["executable_entry_point"] = True
    path.write_text(json.dumps(data))
    result = evaluate_preparation(output, _IMAGE)
    assert result.status == "nonconformant"
    assert result.binding is None
    assert any("does not dispatch" in message for message in result.diagnostics)
    assert read_preparation(output) == result


def test_other_named_consoles_do_not_make_graphify_ambiguous(tmp_path: Path) -> None:
    output = capture(tmp_path)
    from tools.install_sandbox.host.preparation_reader import retained_inputs

    _inputs, effects, context = retained_inputs(output)
    subject = tmp_path / "source"
    project = subject / "pyproject.toml"
    project.write_text(project.read_text() + 'graphify-mcp="graphify.serve:_main"\n')
    second = tmp_path / "second-proof"
    capture_preparation(subject, second, effects, context)
    observe(second)
    assert evaluate_preparation(second, _IMAGE).status == "prepared"
