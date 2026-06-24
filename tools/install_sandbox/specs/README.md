# Install Sandbox Specs

Each `*.yaml` file in this directory, except `shared.yaml` if present, describes one install target known to the install sandbox.

Runnable scopes declare `effects`: target-local Graphify install surfaces such as skill files, instruction-file sections, hook settings, plugin entries, and other files the current Graphify installer should create, repair, preserve, or remove. Checked-in default runnable scopes use `effects`. `expected` is still accepted for legacy compatibility in older or external registry data.

The sandbox validates real Graphify installer behavior by running Graphify installer commands in Docker and checking observed file effects against these specs. These YAML files are not consumed by the product installer today.

Keep the YAML as target-local facts. Python derives root selection, defaults, schema validation, harness policy, runtime limitations, generated-file handling, safety checks, and idempotency rules. The shape is intended to be consumable by a future Installer Core, but current PRs should not claim that installer consumption exists until product code uses it.

Normalized registry output still emits both `expected` and `effects` aliases for
compatibility. The default registry migration is complete; legacy `expected`
fixtures remain coverage for accepted input, not a separate checked-in default
spec contract.
