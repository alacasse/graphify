# Install Sandbox Specs

Each `*.yaml` file in this directory, except `shared.yaml` if present, describes one install target known to the install sandbox.

The top-level YAML `platforms` container remains the checked-in registry schema for now. Do not read that name as generated artifact vocabulary: manifests and reports describe run coverage with target-named fields such as `target_coverage` and `target_coverage_summary`.

Runnable scopes declare `effects`: target-local Graphify install surfaces such as skill files, instruction-file sections, hook settings, plugin entries, and other files the current Graphify installer should create, repair, preserve, or remove. Legacy `expected` registry input has been removed for runnable scopes; use `effects` only.

The sandbox validates real Graphify installer behavior by running Graphify installer commands in Docker and checking observed file effects against these specs. These YAML files are not consumed by the product installer today.

Keep the YAML as target-local facts. Python derives root selection, defaults, schema validation, harness policy, runtime limitations, generated-file handling, safety checks, and idempotency rules. The shape is intended to be consumable by a future Installer Core, but current PRs should not claim that installer consumption exists until product code uses it.

Normalized registry output emits `effects` only. The default registry migration
is complete; checked-in default runnable scopes and normalized output must use
`effects` rather than preserving a normalized-output `expected` alias.
