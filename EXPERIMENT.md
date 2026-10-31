# Plan B experiment

Base: `a55b53dbb864c5a8a09b6738dbb459d521c78d79`; branch `codex/architecture-b-20261031`.

## Independent review checkpoint — 2026-10-31

This checkpoint preserves the reviewed prototype; it does not accept or integrate it.
The later independent review found one open P2 in
`tools/install_sandbox/host/intermediate_reader.py`, `_check_expectations`:
retained `expectations/reinstall.json` is not validated if repair never starts.
Malformed JSON or a forged restoration source remains `failed` after a wrong
mutation, or `incomplete` after interrupted persistence, instead of invalid evidence.
No false success was demonstrated. Preserve honest incomplete prefixes when fixing it.

The exact source/test content matched final source SHA-256
`7e945a546168df638813286547872209f52d4df1fac83bd0dd4e8386c1d5889b`.
A fresh complete component run passed 438 tests (two collection warnings),
the common checks passed 70/70 and 16/16, and configured Ruff and Pyright passed.
The regression above was independently reproduced despite those green checks.
The current baseline rejected both comparable interrupted-archive tamper cases.

Architecture gains are concentrated in mutation binding and immutable progress.
Expectation representation remains hybrid; durable artifact order and repair
baseline selection remain distributed between execution, progress and replay.
The independent documentation repository owns the review and continuation prompt:
`install-sandbox-replacement/architecture-b-independent-review-2026-10-31.md`
and `architecture-b-improvement-prompt-2026-10-31.md`.
The historical review disposition below predates this new finding.

Owner: this worktree only. No commit, push, network, Docker, product installer, or Graphify operation was performed.

The actual runner uses `MarkdownRepairScenario.from_case(...).bind(...)`. MissingSectionScenario and AlteredBodyScenario own their independent preparation oracle and mutation rule. Binding recalculates initial conformity, retained case identity and source/fragments before constructing a BoundMarkdownMutation. That immutable mutation owns document/case/observation binding, bounds and checked physical application. Its apply method requires the unchanged regular document and uses O_NOFOLLOW. PerformedMutation separately retains the operation identity and hash of the actual physical document after application, without deriving conformity from that result. Replay checks both the actual receipt and independent expectation, never executes the mutation.

ExactDocumentExpectation and ComposedMarkdownExpectation own verification. PhysicalPreservation owns entry/type/neighbor comparisons; preparation takes the validated first installation as baseline, repair takes the validated prepared observation. Expected restored Markdown independently uses source and personal exterior. Initial_prefix is retained provenance for the separate position experiment, not a base restriction. Other declared effects and simple reinstall continue through the public runner and full observation verifier.

RepairProgress is immutable. Its strict codec rejects foreign fields/references, skipped prefixes and contradictory completion. Named transitions require matching DurableArtifact acknowledgements emitted by the writer after successful retention. Verification is captured as frozen mismatch and obstacle tuples; neither mutation of the supplied verdict nor mutation of a serialized copy can change authorization. Replay validates physical metadata predecessor order while allowing orphan raw blobs in interrupted writes. Producer publication serializes progress; replay reconstructs and validates it. The artifact acknowledgement proves retention, not conformity. Failed initial installation or preparation closes the dependent repair boundary. Public reader exposes MalformedEvidence; only that exception is normalized to invalid by test glue.

Removed: container/intermediate_builder.py and its prepare_intermediate entrypoint; contracts/intermediate.py PreparedByteRange; intermediate_execution.apply_prepared_range; effect_verifier._preservation and composed semantic dispatch; host intermediate_reader duplicated bound-operation and canonical-reference rules. Replaced structural test imports/patch seams with scenario.bind and mutation.apply. The independent literal retained archive fixture was updated explicitly for the prepared physical baseline and new initial_prefix provenance. No compatibility alias or old builder execution path remains.

## Verification

All commands run in this worktree unless stated otherwise; installed system Python and existing tools only.

- `PYTHONPATH=. python ../shared/run_common.py --adapter experiment_adapter.py --output ../artifacts/b-common-review-fixed` — 70/70 passed, includes all effects, cleanup, physical faults and tampering. Evidence is retained under that output. Earlier iterations are retained separately (`b-common-1` through `b-common-5` and `b-common-final`) and are not final results.
- `python -m pytest -q tests/install_sandbox/component/container/test_missing_section_run.py tests/install_sandbox/component/container/test_altered_section_run.py tests/install_sandbox/component/host/test_intermediate_replay.py tests/install_sandbox/component/container/test_explicit_engine.py tests/install_sandbox/component/container/test_native_integration.py tests/install_sandbox/component/container/test_repair_scenario.py tests/install_sandbox/component/contracts/test_effect_contracts.py tests/install_sandbox/component/container/test_repair_objects.py` — 176 passed, two harmless TestResultWriter collection warnings, 5.75s.
- After review corrections and final replay cleanup: `python -m pytest -q tests/install_sandbox/component/container/test_repair_objects.py tests/install_sandbox/component/host/test_intermediate_replay.py` — 53 passed.
- `test_repair_objects.py` separately exercises persistence after snapshot blobs/metadata but before publication/acknowledgement, for both before/after mutation: incomplete replay, one installer call, retained artifact. It also checks immutable prefixes, skipped/duplicate transitions, foreign codec fields and unretained acknowledgement rejection.
- `/home/alacasse/projects/graphify-branches/graphify/.venv/bin/ruff check --config ruff.install-sandbox.toml tools/install_sandbox --output-format concise` — all checks passed with the actual project configuration.
- `node /home/alacasse/projects/graphify-branches/graphify/.venv/lib/python3.12/site-packages/pyright/dist/index.js --project pyrightconfig.install-sandbox.json` — 85 files analyzed, 0 errors, 0 warnings. This worktree's ignored `.venv` symlink points at the preinstalled main-checkout runtime; no dependency installation or diagnostic configuration changes. The existing include path `tests/install_sandbox/docker` is absent and prints an informational path message. Earlier default-config checks were weaker and do not establish strict compliance; their claim is superseded by this exact configured check.
- `PYTHONPATH=. python ../shared/run_common.py --vectors ../shared/review-vectors.json --adapter experiment_adapter.py --output ../artifacts/b-review-regressions-final` — 16/16 passed. Partial capture omits only the actual personal Markdown neighbor bytes and retains a read_file obstacle; environment, command shape and event shape tampering is rejected explicitly.
- `git diff --check` — clean.
- After aligning first_wrong to preserve the literal BEFORE/AFTER fragments: two first-wrong failures and two forbidden-later tamper rejections passed through the public boundary.

Adapter fault seams: wrong-mutation and preparation-neighbor-change patch BoundMarkdownMutation.apply after its physical write; capture faults patch EffectEnvironment.observe_intermediate before capture; persistence before mutation patches write_metadata(operation), persistence after mutation patches write_intermediate_snapshot(after) before writing. Additional object tests cover the distinct post-write/pre-publication windows. Neighbor faults use an existing personal-effect fixture, never an undeclared initial file. Target symlink is captured as an observed nonregular entry and yields failed, not incomplete; it is never followed by mutation.

## Separate position challenge

Copy: `/tmp/graphify-architecture-b-challenge-20261031-target-fixed`. Evidence: `/tmp/graphify-b-challenge-target-fixed-results`. `challenge.diff` retains the rule change. Only ComposedMarkdownExpectation.verify changes: compare parsed prefix with retained initial_prefix before the existing independent content/exterior comparison. Neither runner nor replay caller changes. Earlier challenge copies and results remain retained.

The one-method challenge.diff is only the final policy delta, not the total adaptation cost. The base prototype was already instrumented specifically for this challenge: ComposedMarkdownExpectation gained initial_prefix, MarkdownRepairScenario._build_bound supplies preparation.before, the expectation codec serializes/decodes this field, and the independent retained-altered-proof fixture carries the literal prefix. These four base locations constitute additional challenge preparation work and extra base transport surface. Base verification does not otherwise require initial_prefix. This must be counted when comparing with variants whose rule context naturally retains the fragments; claiming total cost as only one verification method would be misleading.

In the challenge copy: `PYTHONPATH=. python /home/alacasse/projects/graphify-branches/graphify/graphify-out/architecture-experiment-20261031/shared/run_common.py --adapter experiment_adapter.py --output /tmp/graphify-b-challenge-target-fixed-results --challenge` — 6/6 passed; middle succeeds, start/end fail in execution and autonomous replay for both scenarios.

## Limits

These are controlled simulations, not real-product qualification. Filesystem durability here means successful evidence writes/publication, not an fsync/power-loss guarantee. Generic non-Markdown expectations retain their established transport; exact/composed behavior objects currently subclass that record and reject irrelevant fields through their constructors. Their inherited constructor surface is wider than ideal, a real design tradeoff to include in the comparison. Progress controls the preparation/repair authorization boundary; generic command-step progress remains its established runner/reader representation. Independent reviewer and import-topology review are coordinated by the principal and remain required before any completion claim.

## Independent review corrections

1. Canonical future observation/verification metadata is now rejected whenever a required predecessor is missing, including operation persistence failure followed by forged after.json. Raw blob directories without metadata remain legitimate write-interruption leftovers.
2. Actual performed mutation identity and observed result are retained separately from the expected restoration oracle. An accurately observed bad mutation remains failed; changing its retained operation later is invalid. The literal archive-only bad-mutation counterexample also retains its independently supplied performed facts.
3. FrozenVerification captures complete, mismatch tuples and immutable obstacle tuples. Both input-verdict mutation and serialized-output mutation are covered by an authorization regression.

The three regression tests live in test_repair_objects.py and pass with the final replay suite. Independent re-review is still coordinated by the principal; these fixes do not claim its acceptance.

## Re-review: target capture obstacle

PerformedMutation.verify now distinguishes unavailable actual target bytes from contradictory bytes. An observed regular target file with a matching explicit read_file obstacle may remain incomplete; absence without that obstacle is invalid, and present bytes with a conflicting digest remain invalid even if an obstacle is also present. The receipt identity check still runs first.

Added targeted regressions for both missing/altered cases, injecting the obstacle at the actual fourth GUIDE.md physical capture, deleting workspace/source through the adapter, and replaying retained evidence. A direct receipt regression checks both unexcused missing bytes and conflicting present bytes. `python -m pytest -q tests/install_sandbox/component/container/test_repair_objects.py tests/install_sandbox/component/host/test_intermediate_replay.py` — 56 passed. The earlier combined 176-test result predates this narrow correction; it is retained as history.

Configured Ruff production check remains clean; exact project-config strict Pyright remains 0 errors/0 warnings. The independent 16-assertion supplement was repeated with `--output ../artifacts/b-review-regressions-target-fixed`: 16/16 passed. The latest separate target-fixed challenge copy was synchronized from corrected base and only the position verification rule reapplied; six execution/replay vectors passed. Previous challenge copies/evidence remain intact.

## Coordinator verification after worker handoff

The full controlled component run produced 434 passed/4 failed (artifacts/b-component-coordinator-final.log). The 4 failures were stale test assertions: symlink capture is an observed other entry without an I/O obstacle, and missing required proof now raises public MalformedEvidence. The coordinator updated these assertions, retaining no-follow and invalid-evidence requirements; both affected files then passed 19 tests (artifacts/b-final-assertions.log). Production code did not change in this correction. The same test edits are preserved in the separate challenge.

Authoritative final identity/diffs are artifacts/b-final-manifest.json and its tracked/untracked patches, produced by the coordinator after these edits. Earlier worker manifests are historical snapshots. Durable challenge copy: ../challenges/b (within the experiment directory), re-exercised 6/6 in artifacts/b-challenge-preserved-final. The comparison report in my-docs owns final review disposition and recommendation.

## Final coordinator check index

Final repeated common and review-vector checks are artifacts/b-verified-final-common and artifacts/b-verified-final-regressions. They exercise the final source content identified by artifacts/b-final-manifest.json. Configured strict Pyright and production Ruff pass. General review corrections and import review are closed; A host-summary follow-up is also independently cleared. These reviews do not clear remaining static limitations. No prototype integration or acceptance.
