# Graphify Install Sandbox

Docker harness for validating Graphify installer file effects without touching the host home directory.

This directory is repository-owned developer tooling. Keep generated run artifacts under `out/`, which is ignored by this directory's `.gitignore`.

## Quick Start

```bash
python tools/install_sandbox/selftest.py
python tools/install_sandbox/run.py --repo /home/alacasse/projects/graphify --platform codex --scope both --output tools/install_sandbox/out/codex-smoke
```

Run all registered platforms:

```bash
python tools/install_sandbox/run.py --repo /home/alacasse/projects/graphify --all --scope both
```

## Isolation Model

- The host repo is mounted read-only at `/mnt/graphify-repo`.
- The mounted repo is copied to `/tmp/graphify-src` inside the container.
- Graphify is installed with `python -m pip install /tmp/graphify-src`.
- `HOME` is `/tmp/graphify-home`.
- `XDG_CONFIG_HOME` is `/tmp/graphify-home/.config`.
- Project-scope scenarios run in `/tmp/graphify-project`.
- User-scope scenarios run in `/tmp/graphify-user-cwd` to expose accidental project wiring separately from home writes.
- Artifacts are written to the output mount, defaulting to `sandbox-out/`.

## Execution Order

The harness is intentionally fail-fast across the two testing levels:

1. Install Graphify into the sandbox and validate Graphify-owned installer file effects.
2. Only if those Graphify checks pass, install/probe target tool runtimes.

If Graphify package installation or a Graphify install/file-effect scenario fails, the target runtime probes are skipped because their results would not be actionable.

## Artifacts

Each complete run writes:

```text
manifest.json
preflight.json
package-install/
scenarios/<scenario-id>/command.txt
scenarios/<scenario-id>/env.json
scenarios/<scenario-id>/stdout.txt
scenarios/<scenario-id>/stderr.txt
scenarios/<scenario-id>/transcript.txt
scenarios/<scenario-id>/exit-code.txt
scenarios/<scenario-id>/before-files.json
scenarios/<scenario-id>/after-files.json
scenarios/<scenario-id>/generated-files/
scenarios/<scenario-id>/assertions.json
scenarios/<scenario-id>/risk.json
```

`manifest.json` includes Python, OS, architecture, Graphify version, package direct URL provenance, source snapshot details, scenario counts, and risk status values.

Skill installs assert the installed `SKILL.md`, `.graphify_version`, `references/` sidecar, exact packaged reference fragment names, live `references/<file>.md` pointers, and absence of leftover `references.tmp`. Progressive scenarios also run a dedicated stale-sidecar repair reinstall after the clean repeat-install idempotency check.

## Risk Statuses

- `graphify_install_verified`: Graphify-owned file effects passed for the scenario.
- `target_tool_runtime_verified`: The target tool runtime installed or responded successfully in Docker.
- `risk_unverified_tool_runtime`: Runtime probing was not applicable, skipped, or did not produce a conclusive runtime result.
- `tool_unavailable_in_docker`: The target runtime is GUI/hosted/credentialed or otherwise unavailable in the Docker sandbox; Graphify file effects may still be verified.

## Self-Tests

```bash
python tools/install_sandbox/selftest.py
GRAPHIFY_RUN_DOCKER_TESTS=1 python tools/install_sandbox/selftest.py --docker
```

The default self-test does not require Docker. Docker execution is gated behind `--docker` and `GRAPHIFY_RUN_DOCKER_TESTS=1`.

For installer-related changes, use `.kilo/instructions/installer-sandbox.md` as the source of truth for the required final validation sequence and failure-handling policy.
