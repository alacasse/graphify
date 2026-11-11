"""Compare explicit expectations with independent observations, without target inference."""

from tools.install_sandbox.contracts.expectations import (
    Expectation,
    ExpectationSet,
)
from tools.install_sandbox.contracts.observation import FilesystemSnapshot
from tools.install_sandbox.contracts.results import ObservationObstacle, VerificationResult
from tools.install_sandbox.rules import comparison as checks
from tools.install_sandbox.rules.json_hook_repair import (
    altered_target_preserved,
    duplicated_target_preserved,
    removed_target_preserved,
    repaired_json_preserved,
    target_group_preserved,
    without_target,
)

PRESERVATION_CHECK_ROOTS = ("home", "project")


def _obstacle(result: VerificationResult, root: str, path: str, reason: str) -> None:
    result.obstacles.append(
        ObservationObstacle(operation="verify_expectation", root=root, path=path, reason=reason)
    )


def _complete(snapshot: FilesystemSnapshot, result: VerificationResult) -> None:
    result.obstacles.extend(snapshot.obstacles)
    keys = [(entry["root"], entry["path"]) for entry in snapshot.entries]
    if len(keys) != len(set(keys)):
        _obstacle(result, "project", ".", "Duplicate observed destination")
    for entry in snapshot.entries:
        root, path = entry["root"], entry["path"]
        if entry["kind"] == "directory":
            if not entry.get("listing_complete"):
                _obstacle(result, root, path, "Complete directory inventory unavailable")
        elif entry["kind"] == "file":
            if (root, path) not in snapshot.contents:
                _obstacle(result, root, path, "Retained file bytes unavailable")
        elif entry["kind"] != "other":
            _obstacle(result, root, path, "Unsupported observed entry")
    _roots_complete(snapshot, result)


def _roots_complete(snapshot: FilesystemSnapshot, result: VerificationResult) -> None:
    for root in PRESERVATION_CHECK_ROOTS:
        entry = snapshot.entry(root, ".")
        if entry is None or entry["kind"] != "directory":
            _obstacle(result, root, ".", "Complete observed root unavailable")


def _directory(item: Expectation, observed: FilesystemSnapshot, result: VerificationResult) -> None:
    entry = observed.entry(item.root, item.path)
    if entry is not None and entry["kind"] != "directory":
        checks.mismatch(result, "entry_kind", item.root, item.path, "directory", entry["kind"])
    elif entry is None and observed.absent(item.root, item.path):
        checks.mismatch(result, "missing_directory", item.root, item.path, "directory", "absent")
    elif entry is None:
        _obstacle(result, item.root, item.path, "Directory presence unavailable")


def _json(item: Expectation, current: bytes, result: VerificationResult) -> None:
    assert item.baseline is not None
    try:
        before, after = checks.read_json(item.baseline), checks.read_json(current)
        counts: list[int] = []
        for hook in item.hooks:
            count = len(
                checks.hook_positions(after, hook.event, hook.matcher, hook.content, exact=False)
            )
            counts.append(count)
            if count != 1:
                checks.mismatch(
                    result, "hook_count", item.root, item.path, "one conforming hook", str(count)
                )
        if (
            item.kind == "json-hooks-seeded"
            and counts[0] == 1
            and not target_group_preserved(before, after, item.hooks[0], item.hooks)
        ):
            checks.mismatch(
                result,
                "target_group_changed",
                item.root,
                item.path,
                "target retained in seeded personal group",
                "target group changed",
            )
        if not checks.json_equal(
            checks.personal_json(item.hooks, before), checks.personal_json(item.hooks, after)
        ):
            checks.mismatch(
                result,
                "user_content_lost",
                item.root,
                item.path,
                "personal JSON preserved",
                "personal JSON changed",
            )
    except (ValueError, UnicodeError):
        checks.mismatch(
            result, "invalid_json", item.root, item.path, "valid JSON hooks", "invalid JSON"
        )


def _constraint(
    item: Expectation, observed: FilesystemSnapshot, result: VerificationResult
) -> None:
    if item.kind == "absent":
        checks.require_absent(observed, item.path, result, item.root)
    elif item.kind == "directory":
        _directory(item, observed, result)
    elif item.kind == "file":
        assert item.content is not None
        checks.compare_bytes(observed, item.path, item.content, result, item.root)
    else:
        current = checks.file(observed, item.path, result, item.root)
        if current is not None:
            _semantic(item, current, result)


def _semantic(item: Expectation, current: bytes, result: VerificationResult) -> None:
    if item.kind == "markdown":
        assert item.content is not None and item.baseline is not None and item.marker is not None
        checks.verify_markdown_section(
            item.content,
            item.baseline,
            current,
            result,
            root=item.root,
            path=item.path,
            marker=item.marker,
        )
    elif item.kind == "markdown-composed":
        assert item.content is not None and item.baseline is not None and item.marker is not None
        checks.verify_markdown_composed(
            item.content,
            item.baseline,
            current,
            result,
            root=item.root,
            path=item.path,
            marker=item.marker,
        )
    elif item.kind in {"json-hooks", "json-hooks-seeded"}:
        _json(item, current, result)
    elif item.kind in {
        "json-hook-removed",
        "json-hook-altered",
        "json-hook-duplicated",
        "json-hook-repair",
    }:
        _json_transition(item, current, result)
    else:
        raise ValueError("Unsupported expectation kind")


def _json_transition(item: Expectation, current: bytes, result: VerificationResult) -> None:
    assert item.baseline is not None and len(item.hooks) == 1
    try:
        before, after = checks.read_json(item.baseline), checks.read_json(current)
        target = item.hooks[0]
        if item.kind == "json-hook-removed":
            valid = removed_target_preserved(before, after, target)
        elif item.kind == "json-hook-altered":
            valid = altered_target_preserved(before, after, target)
        else:
            expected_count = 2 if item.kind == "json-hook-duplicated" else 1
            count = len(
                checks.hook_positions(
                    after, target.event, target.matcher, target.content, exact=False
                )
            )
            if count != expected_count:
                checks.mismatch(
                    result,
                    "hook_count",
                    item.root,
                    item.path,
                    "two conforming hooks" if expected_count == 2 else "one conforming hook",
                    str(count),
                )
                return
            valid = (
                duplicated_target_preserved(before, after, target)
                if item.kind == "json-hook-duplicated"
                else repaired_json_preserved(without_target(before, target), after, target)
            )
        if not valid:
            checks.mismatch(
                result,
                "user_content_lost",
                item.root,
                item.path,
                "JSON structure preserved around target",
                "JSON outside conforming target changed; unexpected or altered hooks may remain"
                if item.kind == "json-hook-repair"
                else "JSON changed",
            )
    except (ValueError, UnicodeError):
        checks.mismatch(
            result,
            "invalid_json",
            item.root,
            item.path,
            "valid JSON with unique target",
            "invalid JSON",
        )


class EffectVerifier:
    """The only inputs are constraints and the observation being compared."""

    def verify(self, expected: ExpectationSet, observed: FilesystemSnapshot) -> VerificationResult:
        result = VerificationResult()
        _complete(observed, result)
        if expected.roots is None:
            _obstacle(result, "project", ".", "Expectations have no retained root binding")
        for item in expected.expectations:
            _constraint(item, observed, result)
        if expected.baseline:
            _preservation(expected, observed, result)
        result.complete = not result.obstacles
        return result


def _preservation(
    expected: ExpectationSet, observed: FilesystemSnapshot, result: VerificationResult
) -> None:
    before = {(e.root, e.path): e for e in expected.baseline}
    after = {(e["root"], e["path"]): e for e in observed.entries}
    for key in sorted(before.keys() | after.keys()):
        prior, current = before.get(key), after.get(key)
        if key in expected.allowed_removals and current is None and observed.absent(*key):
            continue
        if key in expected.allowed_changes and (
            prior is None or (current is not None and prior.kind == current["kind"])
        ):
            continue
        if (
            prior is not None
            and current is not None
            and prior.kind == current["kind"]
            and (prior.kind == "directory" or prior.content == observed.contents.get(key))
        ):
            continue
        checks.mismatch(
            result, "unexpected_change", *key, "entry preserved", "entry added, removed or changed"
        )
