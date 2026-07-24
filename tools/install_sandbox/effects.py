"""Filesystem observations and behavioral effect validation."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from .models import Effect, EffectKind, Observation, Root, ValidationResult


REFERENCE_NAMES = frozenset(
    {
        "add-watch.md",
        "exports.md",
        "extraction-spec.md",
        "github-and-merge.md",
        "hooks.md",
        "query.md",
        "transcribe.md",
        "update.md",
    }
)
_POINTER_RE = re.compile(r"references/([A-Za-z0-9_.-]+\.md)")
_REMINDER_RE = re.compile(r"""['"]echo "([^"\n]*)"\s*;\s*['"]\s*\+""")
_SNAPSHOT_EXCLUDES = frozenset({".cache", ".local", "__pycache__"})


def resolve_effect(effect: Effect, roots: Mapping[Root, Path]) -> Path:
    return roots[effect.root] / effect.path


def observe(effect: Effect, roots: Mapping[Root, Path]) -> Observation:
    path = resolve_effect(effect, roots)
    text = None
    json_value = None
    is_file = path.is_file()
    if is_file:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = None
        if effect.kind is EffectKind.JSON and text is not None:
            try:
                json_value = json.loads(text)
            except json.JSONDecodeError:
                json_value = None
    return Observation(
        root=effect.root,
        path=effect.path,
        exists=path.exists(),
        is_file=is_file,
        text=text,
        json_value=json_value,
    )


def _result(check: str, passed: bool, detail: str) -> ValidationResult:
    return ValidationResult(check=check, passed=passed, detail=detail)


def _expanded(value: Any, roots: Mapping[Root, Path]) -> Any:
    if isinstance(value, str):
        replacements = {
            "{home}": str(roots[Root.HOME]),
            "{xdg}": str(roots[Root.XDG]),
            "{project}": str(roots[Root.PROJECT]),
            "{user_cwd}": str(roots[Root.USER_CWD]),
        }
        for token, replacement in replacements.items():
            value = value.replace(token, replacement)
        return value
    if isinstance(value, list):
        return [_expanded(item, roots) for item in value]
    if isinstance(value, dict):
        return {key: _expanded(item, roots) for key, item in value.items()}
    return value


def _frontmatter_body(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    closing = text.find("\n---\n", 4)
    if closing == -1:
        return text
    return text[closing + len("\n---\n") :].lstrip("\n")


def contains_json(actual: Any, expected: Any) -> bool:
    """Return whether *actual* contains the expected JSON subset."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and contains_json(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        return all(
            any(contains_json(candidate, item) for candidate in actual)
            for item in expected
        )
    return actual == expected


def _validate_payload(
    effect: Effect,
    actual: str | None,
    source_root: Path,
) -> list[ValidationResult]:
    if effect.source is None or actual is None:
        return []
    source = source_root / effect.source
    try:
        expected = source.read_text(encoding="utf-8")
    except OSError as exc:
        return [_result("payload source", False, f"cannot read {source}: {exc}")]
    if effect.kind is EffectKind.SECTION:
        expected = expected.strip()
        actual = actual.strip()
    comparisons = {
        "exact": actual == expected,
        "prefix": actual.startswith(expected),
        "suffix": actual.endswith(expected),
        "contains": expected in actual,
        "frontmatter-body": _frontmatter_body(actual)
        == _frontmatter_body(expected),
    }
    passed = comparisons[effect.payload_mode]
    return [
        _result(
            "payload equality",
            passed,
            f"{effect.path} {effect.payload_mode}-matches {effect.source}"
            if passed
            else f"{effect.path} does not {effect.payload_mode}-match {effect.source}",
        )
    ]


def _owned_section(text: str, marker: str) -> str | None:
    """Return the last exact owned heading section, mirroring the installer."""
    lines = text.splitlines()
    starts = [index for index, line in enumerate(lines) if line.strip() == marker]
    if not starts:
        return None
    start = starts[-1]
    heading_level = len(marker) - len(marker.lstrip("#"))
    boundary = "#" * heading_level + " "
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith(boundary):
            end = index
            break
    return "\n".join(lines[start:end]).strip()


def _validate_sidecars(
    effect: Effect,
    path: Path,
    source_root: Path,
) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    version = path.parent / ".graphify_version"
    results.append(
        _result(
            "version sidecar",
            version.is_file() and bool(version.read_text(encoding="utf-8").strip()),
            f"{version} is present and non-empty",
        )
    )
    refs = path.parent / "references"
    staged = path.parent / "references.tmp"
    if effect.reference_bundle is None:
        results.append(
            _result(
                "monolith sidecars",
                not refs.exists() and not staged.exists(),
                f"{path.parent} has no progressive reference sidecars",
            )
        )
        return results

    actual_names = (
        frozenset(item.name for item in refs.iterdir() if item.is_file())
        if refs.is_dir()
        else frozenset()
    )
    results.append(
        _result(
            "reference set",
            actual_names == REFERENCE_NAMES,
            f"{effect.path} has the exact 8-reference set: {sorted(actual_names)}",
        )
    )
    results.append(
        _result(
            "staged sidecar absent",
            not staged.exists(),
            f"{staged} does not exist",
        )
    )
    source_refs = (
        source_root / "graphify" / "skills" / effect.reference_bundle / "references"
    )
    equal = actual_names == REFERENCE_NAMES
    for name in REFERENCE_NAMES:
        actual_file = refs / name
        source_file = source_refs / name
        if not actual_file.is_file() or not source_file.is_file():
            equal = False
            continue
        if actual_file.read_bytes() != source_file.read_bytes():
            equal = False
    results.append(
        _result(
            "reference payloads",
            equal,
            f"{refs} matches packaged {effect.reference_bundle} references",
        )
    )
    skill_text = path.read_text(encoding="utf-8") if path.is_file() else ""
    pointers = frozenset(_POINTER_RE.findall(skill_text))
    resolved = bool(pointers) and all((refs / pointer).is_file() for pointer in pointers)
    results.append(
        _result(
            "reference pointers",
            resolved,
            f"{len(pointers)} SKILL.md reference pointers resolve",
        )
    )
    return results


def _validate_reminder(
    effect: Effect, observation: Observation
) -> list[ValidationResult]:
    text = observation.text or ""
    matches = _REMINDER_RE.findall(text)
    if len(matches) != 1:
        return [
            _result(
                "captured reminder",
                False,
                f"expected one semicolon-joined reminder string, found {len(matches)}",
            )
        ]
    reminder = matches[0]
    required = all(fragment in reminder for fragment in effect.required_text)
    forbidden = all(fragment not in reminder for fragment in effect.forbidden_text)
    return [
        _result(
            "captured reminder required text",
            required,
            f"captured reminder contains {list(effect.required_text)}",
        ),
        _result(
            "captured reminder forbidden text",
            forbidden,
            f"captured reminder excludes {list(effect.forbidden_text)}",
        ),
        _result(
            "captured reminder semicolon join",
            '" ; \' +' in text and '" && \' +' not in text,
            "reminder uses the cross-shell semicolon join, not the old && join",
        ),
    ]


def validate_installed(
    effects: Iterable[Effect],
    roots: Mapping[Root, Path],
    source_root: Path,
) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    for effect in effects:
        path = resolve_effect(effect, roots)
        observation = observe(effect, roots)
        label = f"{effect.root.value}:{effect.path}"
        results.append(
            _result(
                f"{label} exists",
                observation.is_file,
                f"{path} is a regular file",
            )
        )
        if not observation.is_file:
            continue
        text = observation.text or ""
        fragment_text = text
        if effect.kind is EffectKind.SECTION:
            section = _owned_section(text, effect.marker or "")
            marker_present = section is not None
            results.append(
                _result(
                    f"{label} owned section",
                    marker_present,
                    f"exact marker line {effect.marker!r} is present",
                )
            )
            fragment_text = section or ""
            results.extend(_validate_payload(effect, section, source_root))
        else:
            results.extend(_validate_payload(effect, observation.text, source_root))
        if effect.kind is EffectKind.JSON:
            expected = _expanded(dict(effect.entries), roots)
            results.append(
                _result(
                    f"{label} JSON entries",
                    contains_json(observation.json_value, expected),
                    f"JSON contains {expected!r}",
                )
            )
        elif effect.kind is EffectKind.REMINDER_PLUGIN:
            results.extend(_validate_reminder(effect, observation))
        if effect.kind is not EffectKind.REMINDER_PLUGIN:
            for fragment in effect.required_text:
                results.append(
                    _result(
                        f"{label} requires text",
                        fragment in fragment_text,
                        f"{fragment!r} is present in the owned content",
                    )
                )
            for fragment in effect.forbidden_text:
                results.append(
                    _result(
                        f"{label} forbids text",
                        fragment not in fragment_text,
                        f"{fragment!r} is absent from the owned content",
                    )
                )
        if effect.kind is EffectKind.SKILL:
            results.extend(_validate_sidecars(effect, path, source_root))
    return results


def json_owned_entries_absent(actual: Any, expected: Any) -> bool:
    """Return whether every independently owned expected JSON entry is absent."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return True
        return all(
            key not in actual or json_owned_entries_absent(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return True
        return all(
            not any(contains_json(candidate, item) for candidate in actual)
            for item in expected
        )
    return actual != expected


def validate_removed(
    effects: Iterable[Effect],
    roots: Mapping[Root, Path],
    source_root: Path | None = None,
) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    for effect in effects:
        path = resolve_effect(effect, roots)
        observation = observe(effect, roots)
        label = f"{effect.root.value}:{effect.path}"
        if effect.kind is EffectKind.SECTION:
            text = observation.text or ""
            absent = effect.marker not in {line.strip() for line in text.splitlines()}
            residual_body = False
            if effect.source and source_root is not None:
                try:
                    expected = (source_root / effect.source).read_text(
                        encoding="utf-8"
                    )
                except OSError:
                    residual_body = True
                else:
                    expected_lines = expected.strip().splitlines()
                    body = "\n".join(expected_lines[1:]).strip()
                    residual_body = bool(body) and body in text
            elif effect.required_text:
                residual_body = all(
                    fragment in text for fragment in effect.required_text
                )
            absent = absent and not residual_body
            detail = (
                f"owned marker {effect.marker!r} and owned section body are absent"
            )
        elif effect.kind is EffectKind.JSON:
            expected = _expanded(dict(effect.entries), roots)
            absent = json_owned_entries_absent(observation.json_value, expected)
            detail = f"owned JSON entries are absent: {expected!r}"
        else:
            absent = not path.exists()
            detail = f"owned file {path} is absent"
        results.append(_result(f"{label} removed", absent, detail))
        if effect.kind is EffectKind.SKILL:
            refs = path.parent / "references"
            staged = path.parent / "references.tmp"
            version = path.parent / ".graphify_version"
            results.append(
                _result(
                    f"{label} sidecars removed",
                    not refs.exists()
                    and not staged.exists()
                    and not version.exists(),
                    "references, references.tmp, and version stamp are absent",
                )
            )
    return results


def snapshot(
    roots: Mapping[Root, Path],
) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {}
    for root_name, base in roots.items():
        files: list[dict[str, object]] = []
        if base.exists():
            for path in sorted(base.rglob("*")):
                try:
                    relative = path.relative_to(base)
                except ValueError:
                    continue
                if any(part in _SNAPSHOT_EXCLUDES for part in relative.parts):
                    continue
                if path.is_symlink():
                    files.append(
                        {
                            "path": relative.as_posix(),
                            "type": "symlink",
                            "target": str(path.readlink()),
                        }
                    )
                elif path.is_file():
                    content = path.read_bytes()
                    files.append(
                        {
                            "path": relative.as_posix(),
                            "type": "file",
                            "size": len(content),
                            "sha256": hashlib.sha256(content).hexdigest(),
                        }
                    )
        result[root_name.value] = files
    return result


def snapshot_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
