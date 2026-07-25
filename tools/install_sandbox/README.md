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

- the repository development environment installed (`uv sync --all-extras`);
- a running Docker daemon available to the current user.

The examples use the repository's locked environment. If the project
environment is already active, `python` can replace `uv run --frozen python`.

## Quick start

Start with one target and one scope while developing:

```bash
uv run --frozen python tools/install_sandbox/run.py \
  --repo . \
  --target codex \
  --scope project
```

Run the complete catalog before finalizing a catalog-wide installer change:

```bash
uv run --frozen python tools/install_sandbox/run.py \
  --repo . \
  --all \
  --scope both
```

Each invocation builds the harness image before starting the container, so a
full-catalog run takes longer than a single-target run.

## Choose what to run

Exactly one of `--target` and `--all` is required.

| Argument | Meaning |
| --- | --- |
| `--repo PATH` | Graphify source checkout to install and test. |
| `--target NAME` | Run one target. Use `--help` to list names from the current catalog. |
| `--all` | Run every target plus catalog-wide installer checks. |
| `--scope user\|project\|both` | Select install roots; defaults to `both`. |
| `--output DIR` | Write artifacts to a fresh directory. The default is the ignored path `tools/install_sandbox/out/<UTC timestamp>/`. |

For example, give an agent or CI job an explicit artifact directory:

```bash
sandbox_output_dir="$(mktemp -d /tmp/graphify-install-sandbox-codex.XXXXXX)"
uv run --frozen python tools/install_sandbox/run.py \
  --repo . \
  --target codex \
  --scope both \
  --output "$sandbox_output_dir"
```

Set `GRAPHIFY_SANDBOX_RUNTIME` only when a different Docker-compatible runtime
executable should replace the default `docker` command.

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
