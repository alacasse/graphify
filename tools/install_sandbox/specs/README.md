# Install Sandbox Specs

Each `*.yaml` file in this directory, except `shared.yaml` if present, describes one install target known to the install sandbox.

The current top-level registry container is `targets`. Legacy `platforms` input remains accepted only as public schema compatibility during migration. Do not read either YAML input name as generated artifact vocabulary: manifests and reports describe run coverage with target-named fields such as `target_coverage` and `target_coverage_summary`.

Runnable scopes declare `effects`: target-local Graphify install surfaces such as skill files, instruction-file sections, hook settings, plugin entries, and other files the current Graphify installer should create, repair, preserve, or remove. Legacy `expected` registry input has been removed for runnable scopes; use `effects` only.

The sandbox validates real Graphify installer behavior by running Graphify installer commands in Docker and checking observed file effects against these specs. These YAML files are not consumed by the product installer today.

Keep the YAML as target-local facts. Python derives root selection, defaults, schema validation, harness policy, runtime limitations, generated-file handling, safety checks, and idempotency rules. The shape is intended to be consumable by a future Installer Core, but current PRs should not claim that installer consumption exists until product code uses it.

Target-local facts include install surfaces, target skill paths, packaged
reference bundles, unsupported scopes, and target runtime limitation notes.
Conventional skill paths of `.<target>/skills/graphify/SKILL.md` may be omitted
when they are equivalent to the loader default; nonconventional paths, disabled
skill paths, and paths that differ between user/project scopes remain explicit
because they are target-local facts rather than derivable boilerplate.
Command fields such as `install_command`, `uninstall_command`,
`equivalent_install_command`, root execution hints such as `cwd_root` and
`allowed_roots`, and planning fields such as `universal_uninstall_scopes` are
transitional sandbox inputs. Harness Policy inputs such as
`universal_uninstall_specs` and `disposable_artifact_specs` remain outside the
Install Target Catalog. The current Harness Policy eligibility input is
`eligible_target_scope`; legacy `eligible_platform_scope` remains reader-only
public schema compatibility.

Normalized registry output emits `effects` only. The default registry migration
is complete; checked-in default runnable scopes and normalized output must use
`effects` rather than preserving a normalized-output `expected` alias.
