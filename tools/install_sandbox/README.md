# Graphify install sandbox

The install sandbox is a Tier 1 behavioral test harness for Graphify's
installer. It installs the current source checkout inside Docker, exercises
the installer lifecycle in isolated user and project roots, and verifies the
Graphify-owned files that lifecycle should create, repair, preserve, and
remove.

Use it when changing installer commands, packaged integration files, target
specifications, cleanup behavior, or universal uninstall. It catches problems
such as wrong paths or payloads, duplicate managed Markdown, stale sidecars,
removed user content, and undeclared filesystem changes.

> **Coverage boundary:** the sandbox verifies installer-owned filesystem
> effects. It does not prove that a target tool discovers, authenticates,
> loads, or executes the installed integration.

## Prerequisites

Run the commands from a Graphify source checkout with:

- the frozen Python 3.12 development environment installed
  (`uv sync --all-extras --frozen --python 3.12`);
- a running Docker daemon available to the current user.

The committed `uv.lock` is the version authority. Do not replace these commands
with hand-assembled tool invocations.

## Quick start

Run the inexpensive gate while developing:

```bash
uv run --frozen --python 3.12 python scripts/install_sandbox_quality.py fast
```

Use the command owner's Docker tier for proportional diagnostic evidence:

```bash
uv run --frozen --python 3.12 python scripts/install_sandbox_quality.py docker --target <target>
uv run --frozen --python 3.12 python scripts/install_sandbox_quality.py docker --all
```

Run the complete tier for a behavioral milestone, architecture completion,
cutover candidate, or merge:

```bash
uv run --frozen --python 3.12 python scripts/install_sandbox_quality.py complete
```

Prove the command owner's positive and negative paths after changing the gate
or when accepting the quality foundation:

```bash
uv run --frozen --python 3.12 python scripts/install_sandbox_quality.py prove
```

`fast` owns scoped formatting, lint and complexity, strict typing, security,
and applicable Unit and Component Evidence. `complete` owns those checks plus
applicable branch coverage and Behavioral Evidence, dependency audit, the
warning-clean Python 3.12 repository suite, and a full official Docker
diagnostic. Each Docker invocation builds the harness image, so full-catalog
evidence takes longer than a targeted run.

`prove` runs the declared warning-clean quality proof suite against temporary
repositories. That suite demonstrates formatting, lint, complexity, typing,
security, warnings, tests, coverage, evidence applicability, configuration and
CI drift, dependency-audit and Docker outcome propagation, timeouts, and
`uv.lock` immutability. It is an operational self-test of the gate, not a
replacement for `fast`, `complete`, or official Docker evidence at the exact
commit being accepted.

Evidence applicability comes from repository facts, not a flag or marker:

| Repository state | Required replacement evidence |
| --- | --- |
| Gate installation | Unit, Component, Behavioral, and replacement coverage report `NOT APPLICABLE`; no replacement behavior exists. |
| Replacement construction | Unit, Component, and replacement branch coverage are required; early Behavioral Evidence is prohibited. |
| Atomic cutover | Unit, Component, Behavioral, and full remaining-tree coverage are required. |

The command owner returns exit `0` for complete success or valid
non-applicability, exit `1` for failed or missing evidence, exit `2` for invalid
usage or configuration, and exit `124` for a Docker timeout. It reports every
independent child outcome before aggregating the result.

## Choose what to run

The quality owner exposes five contributor-facing modes. Exactly one of
`--target` and `--all` is required for `docker`.

| Mode | Meaning |
| --- | --- |
| `fast` | Run every inexpensive blocking check. |
| `complete` | Run every complete-tier check, including dependency and full Docker evidence. |
| `prove` | Exercise the quality owner's declared positive and negative proof suite. |
| `docker --target NAME` | Run one catalog-derived Install Target in both scopes. |
| `docker --all` | Run every target, both scopes, and catalog-wide checks. |

The quality owner prints the external diagnostic-bundle path it allocated. The
underlying host runner also supports managed runs beneath the ignored
`tools/install_sandbox/out/` root. For example:

```text
tools/install_sandbox/out/20260726T143012Z-codex-project/
tools/install_sandbox/out/20260726T143012Z-codex-project-02/
tools/install_sandbox/out/20260726T143012Z-all-both/
```

The numeric suffix resolves same-second collisions. The quality command owner
uses an absent external temporary leaf so it can publish the bundle path for a
person, agent, or CI artifact step without entering managed retention.

Set `GRAPHIFY_SANDBOX_RUNTIME` only when a different Docker-compatible runtime
executable should replace the default `docker` command.

## Output ownership and lifecycle

Managed and external output have deliberately separate ownership:

- A default run is managed by the host runner. Its run ID, metadata, and
  keep-five retention policy belong to the sandbox.
- `--output DIR` is an external leaf owned by the caller. The path must either
  be absent or be an empty real directory. Symlinks, non-empty directories, and
  explicit paths beneath `tools/install_sandbox/out/` are rejected.
- The runner never prunes external output. CI, an agent, or the person who
  supplied `--output` decides how long to keep it.

Every accepted destination is fresh: the runner allocates managed directories
atomically and never reuses files from an earlier run. It allocates the
diagnostic bundle after validating the repository but before catalog preflight,
so catalog, Docker build, and runtime failures can still leave host diagnostics.

The host writes two top-level lifecycle artifacts:

| Artifact | Use |
| --- | --- |
| `run.json` | Schema version, run ID, managed flag, timestamps, repository and output paths, selection, current phase, state, and exit code. |
| `runner.log` | Phase-labelled host preflight, Docker build, and container output, mirrored to the console. |

The runner replaces `run.json` atomically as the phase or state changes, so a
reader never observes a partially written metadata file. `run.json` moves
through these states:

| State | Meaning |
| --- | --- |
| `running` | The run has been allocated and has not reached a terminal state. An uncatchable termination can leave this state behind. |
| `passed` | Exit `0`, with a complete container `manifest.json` and `report.md`. |
| `failed` | Exit `1`, with complete behavioral results that contain a product-contract failure. |
| `incomplete` | Catalog, image-build, container-runtime, or missing-output failure prevented complete behavioral results. |
| `interrupted` | The host caught `SIGINT` or `SIGTERM` and returned the conventional signal exit code. |

Before allocating a managed run, the runner removes only surplus, valid,
terminal managed runs. After finalization it keeps the newest five, counting
`passed`, `failed`, `incomplete`, and `interrupted` equally. It does not delete
`running`, malformed, unreadable, unmarked, external, or symlinked entries.
Leftover `running` entries are preserved with a warning because the runner
cannot prove that another process is not using them.

### Optional VS Code exclusions

Repository-local managed output can still add editor file-watching and search
work. If that becomes noticeable, merge these keys into your existing
workspace settings:

```json
{
  "files.watcherExclude": {
    "**/tools/install_sandbox/out/**": true
  },
  "search.exclude": {
    "**/tools/install_sandbox/out/**": true
  }
}
```

Do not overwrite an existing `.vscode/settings.json`; merge with settings
already there and keep editor configuration local and untracked. Do not use
`files.exclude` for this purpose, because it would hide recent diagnostic
artifacts from the file explorer.

## What a run checks

For each supported target/scope pair, the harness exercises install,
reinstall, progressive-sidecar repair, and uninstall as applicable. It checks
exact packaged content and version stamps, preserves unrelated user content,
and rejects filesystem changes outside the effects declared for that target.

Every run also compares the spec catalog with the public installer target list
and checks that `graphify uninstall --purge` removes `graphify-out/` without
removing unrelated content. A full `--all` run additionally:

- runs grouped user and project universal-uninstall scenarios;
- proves user-scope installations survive `graphify uninstall --project`;
- proves uninstall without `--purge` preserves `graphify-out/`.

## Read the result

Start with `<output>/report.md`. It gives the overall scenario counts, purge
status, runtime limitations, and links to failed scenarios.

- `PASS` means the supported scenario met every declared installer contract.
- `FAIL` means at least one command or filesystem assertion failed.
- `UNSUPPORTED` is a declared coverage limitation, not a failure.
- `NOT_APPLICABLE` means that lifecycle phase is not defined for the scenario.

Use the remaining artifacts only when more detail is needed:

| Artifact | Use |
| --- | --- |
| `run.json` | Host-owned lifecycle metadata and raw exit classification. |
| `runner.log` | Complete phase-labelled host and container console output. |
| `manifest.json` | Machine-readable run selection, package data, summary, scenarios, and purge result. |
| `scenarios/<name>/result.json` | Assertions and phase status for one scenario. |
| `scenarios/<name>/*.stdout.log` and `*.stderr.log` | Installer command output. |
| `scenarios/<name>/*.json` snapshots | Filesystem state before and after lifecycle phases. |
| `scenarios/<name>/commands.log` | Commands executed for the scenario. |

An exit status of `0` means all supported scenarios and the purge check
passed. Exit status `1` means a scenario or purge check failed. Other nonzero
statuses indicate invalid input, catalog validation, image build, runtime, or
container-execution problems; read the console error before interpreting
scenario artifacts.

For agent handoff, report the exact command, output directory, exit status,
summary from `report.md`, and any failed scenario names. Do not infer a product
failure from an image-build or container-runtime error.

## Continuous integration

`.github/workflows/install-sandbox-fast.yml` invokes the canonical `fast`
command as an unconditional check on every pull request, with no path filter.
An older in-progress fast run for the same pull request is cancelled.

`.github/workflows/install-sandbox.yml` invokes the canonical `complete`
command after a push to `v8` or `main`, nightly at `05:27 UTC`, and on manual
`workflow_dispatch`. Use that manual event for a behavioral milestone,
architecture completion, or cutover review. The complete run owns its
dependency audit and full Docker diagnostic; the workflow does not duplicate
their tool commands.

Complete, Docker, and acceptance evidence binds to the exact commit that ran.
A later source, test, lock, configuration, workflow, scope, or documentation
change requires fresh evidence. A scheduled result is informational unless it
covers the exact commit under acceptance. The workflow uploads the complete
diagnostic bundle after success or failure and writes `report.md` (or
`run.json`) to the job summary.

The general Python-version matrix remains separate. Python 3.10 continues to
exercise unrelated Graphify behavior while excluding `tests/install_sandbox`
and `tests/quality_gate`, which require the Python 3.12 gate runtime.

Two commented settings near the top of the workflow are the storage-cost
controls:

- `INSTALL_SANDBOX_ARTIFACT_RETENTION_DAYS` is `14`;
- `INSTALL_SANDBOX_ARTIFACT_COMPRESSION_LEVEL` is `9`.

Artifacts are compressed during upload. GitHub Actions artifacts are immutable
after upload, so the workflow does not attempt age-based recompression;
maintainers can reduce cost by changing those retention or compression values.
A representative current bundle measured about 3.1 MB locally and roughly
80 KB at maximum compression. See
[upload-artifact compression and immutability](https://github.com/actions/upload-artifact).

## Catalog authority

The YAML specs are the authority for target membership, install effects, and
universal-uninstall eligibility. Python discovers the catalog from spec
filenames and derives aggregate scenarios from those declarations; it does not
maintain a second list of target names.

The [spec authority guide](specs/README.md) explains how to place new target
facts, deterministic derivations, cross-target policy, and product
observations without freezing the current YAML schema.

## Isolation and platform limits

The repository is mounted read-only, copied to a separate container source
directory, and installed from that copy. HOME, XDG configuration, project,
user working directory, copied source, and output are distinct isolated roots.
No real user home is mounted.

Windows and Antigravity-Windows scenarios only compare packaged payloads in the
Linux container. They do not validate Windows paths, shells, permissions,
cleanup, or runtime discovery. Hermes validates its normal Linux path only;
`%LOCALAPPDATA%` behavior is not exercised.
