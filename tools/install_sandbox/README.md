# Graphify Install Sandbox

Docker harness for validating Graphify installer file effects without touching the host home directory.

This directory is repository-owned developer tooling. Keep generated run artifacts under `out/`, which is ignored by this directory's `.gitignore`.

## Quick Start

```bash
uv run pytest tests/install_sandbox -q
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

## Verification Scope

The install sandbox is a Tier 1 verification harness. Its maintained responsibility is to validate Graphify-owned installer file effects in an isolated filesystem, not to prove that every target tool runtime loads or executes the installed integration.

Verification tiers:

1. Tier 1, file-effect validation: Graphify installs, repeats, uninstalls, and purges the expected files at the paths in Graphify's platform registry. This is the sandbox's scope.
2. Tier 2, runtime availability probe: a target CLI installs or responds to a version/discovery command. This can be slow, network-sensitive, and still does not prove that the tool discovered Graphify.
3. Tier 3, runtime discovery/execution: the target tool actually discovers, loads, or executes the Graphify integration. This is the strongest verification, but it is tool-specific and often impractical for GUI, hosted, authenticated, or Windows-only runtimes.

Decision: keep this sandbox focused on Tier 1 only. Runtime availability probes and runtime discovery/execution checks are known gaps and may be built later as separate, explicit tooling for selected platforms. Existing Tier 2 probe behavior is out of scope for the install sandbox and should be removed rather than retained as speculative "just in case" code.

The correct claim for a passing sandbox run is: Graphify wrote, updated, and removed its expected files in the isolated filesystem. A passing run does not claim that every target application was installed, launched, authenticated, or proven to load Graphify.

Windows-named platforms are a special case. In Linux Docker, `windows` and `antigravity-windows` checks may validate cheap payload consistency only: the Windows skill bundle is packaged, the Windows references sidecar is copied, explicit `--platform windows` and `--platform antigravity-windows` select the intended payloads, and the generated files are internally consistent. Linux Docker should not treat these as Windows install-location validation because it cannot exercise real Windows `Path.home()`, `sys.platform == "win32"`, PowerShell/cmd entrypoints, path separators, permissions, cleanup semantics, or target-app discovery.

macOS has no separate platform in Graphify today. Linux Docker can cover shared Unix-style dotfile layouts, but it should not claim macOS app/editor discovery or macOS-specific filesystem behavior. Real Windows or macOS validation, if needed later, belongs in separate OS-specific tooling.

Use precise terminology in reports and artifacts:

- `Graphify package install`: installing Graphify into the sandbox Python environment.
- `Graphify installer command`: commands such as `graphify install --platform X`, `graphify uninstall`, and `graphify purge`.
- `Graphify file effects`: files Graphify writes, updates, or removes in isolated home/project roots.
- `Payload consistency`: packaged skill/reference assets are selected and copied consistently.
- `Install-location confidence`: how strongly we know a destination path matches the target tool's current expectations.
- `Target runtime verification`: installing, launching, discovering, or executing the target tool itself; this is outside this sandbox.

Avoid ambiguous labels like `Install Command`, `Target Runtime`, or `Runtime Evidence` when they could imply target-tool validation. Prefer `Graphify Installer Command`, `Graphify File Effects`, `Payload Consistency`, and explicit `not verified by this sandbox` wording.

## Spec Contract

Install target specs live in `specs/`. They declare target-local Graphify install surfaces: the files and configuration entries the current Graphify installer should create, repair, preserve, or remove during sandbox scenarios.

The sandbox validates real Graphify installer behavior today. It installs Graphify in Docker, runs Graphify installer commands, and checks the observed file effects against the loaded target specs. The product installer does not consume these YAML specs yet.

Keep YAML focused on target-local facts. Python derives roots, default installer commands, schema validation, harness policy, runtime limitations, safety checks, and idempotency rules from those facts plus sandbox-owned policy. This keeps the specs shaped for a future shared Installer Core without making that future core part of the current installer.

Checked-in default runnable scopes declare `effects`. Legacy `expected` registry input has been removed for runnable scopes; use `effects` for the files and configuration entries the sandbox should validate. Normalized registry output also emits `effects` only; internal Python scenario models may still name their loaded install-surface tuple `expected`. This vocabulary migration does not make the product installer consume YAML.

## Execution Order

The harness should fail immediately when Graphify cannot be installed into the sandbox or the Graphify command infrastructure is broken. Once that precondition passes, Graphify file-effect scenarios should continue across selected platforms/scopes so the run reports all Tier 1 failures instead of hiding later platform regressions.

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
scenarios/<scenario-id>/before-install-files.json
scenarios/<scenario-id>/after-install-files.json
scenarios/<scenario-id>/after-repeat-install-files.json
scenarios/<scenario-id>/after-stale-sidecar-repair-files.json
scenarios/<scenario-id>/after-uninstall-files.json
scenarios/<scenario-id>/generated-files/
scenarios/<scenario-id>/assertions.json
scenarios/<scenario-id>/risk.json
```

`manifest.json` includes Python, OS, architecture, Graphify version, package direct URL provenance, source snapshot details, scenario counts, and risk status values.

Skill installs assert the installed `SKILL.md`, `.graphify_version`, `references/` sidecar, exact packaged reference fragment names, live `references/<file>.md` pointers, and absence of leftover `references.tmp`. Progressive scenarios also run a dedicated stale-sidecar repair reinstall after the clean repeat-install idempotency check.

## Statuses

- `graphify_install_verified`: Graphify-owned file effects passed for the scenario. This is the sandbox's intended success condition.
- `graphify_install_failed`: one or more Graphify-owned file-effect checks failed.

Target runtime statuses are intentionally not emitted by this harness. Reports state that target runtime verification was not performed rather than recording a probe-like status.

## Tests

```bash
uv run pytest tests/install_sandbox -q
python tools/install_sandbox/run.py --repo /home/alacasse/projects/graphify --platform codex --scope both --output tools/install_sandbox/out/codex-smoke
```

The normal install sandbox unit suite lives under `tests/install_sandbox/` and runs through pytest. Docker-backed validation runs through `tools/install_sandbox/run.py` so it exercises the same harness used by the required installer validation sequence.

For installer-related changes, use `.kilo/instructions/installer-sandbox.md` as the source of truth for the required final validation sequence and failure-handling policy.
