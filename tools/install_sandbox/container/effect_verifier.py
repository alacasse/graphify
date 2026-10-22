"""Compare explicit expectations with independent observations, without target inference."""

from tools.install_sandbox.container import comparison as checks
from tools.install_sandbox.container.environment import FilesystemSnapshot
from tools.install_sandbox.contracts.expectations import Expectation, ExpectationSet
from tools.install_sandbox.contracts.results import ObservationObstacle, VerificationResult


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
        else:
            _obstacle(result, root, path, "Unsupported observed entry")
    _roots_complete(snapshot, result)


def _roots_complete(snapshot: FilesystemSnapshot, result: VerificationResult) -> None:
    for root in ("home", "project"):
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
        for hook in item.hooks:
            count = len(
                checks.hook_positions(after, hook.event, hook.matcher, hook.content, exact=False)
            )
            if count != 1:
                checks.mismatch(
                    result, "hook_count", item.root, item.path, "one conforming hook", str(count)
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
    elif item.kind == "json-hooks":
        _json(item, current, result)


def _preservation(
    expected: ExpectationSet, observed: FilesystemSnapshot, result: VerificationResult
) -> None:
    if not expected.baseline:
        return
    before = {(e.root, e.path): e for e in expected.baseline}
    after = {(e["root"], e["path"]): e for e in observed.entries}
    allowed = set(expected.allowed_changes)
    for key in sorted(before.keys() | after.keys()):
        prior, current = before.get(key), after.get(key)
        if key in allowed and (
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
            result,
            "unexpected_change",
            key[0],
            key[1],
            "entry preserved",
            "entry added, removed or changed",
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
        _preservation(expected, observed, result)
        result.complete = not result.obstacles
        return result
