# Graphify install sandbox

This Tier 1 Docker harness validates Graphify-owned installer file effects. It
does not claim that any target tool discovers or executes the installed files.

Run one target or the full 24-target catalog:

```bash
python tools/install_sandbox/run.py --repo . --target codex --scope project
python tools/install_sandbox/run.py --repo . --all --scope both
```

`--scope` defaults to `both`. Use `--output DIR` to choose the artifact
directory. A run writes `manifest.json`, `report.md`, and concise per-scenario
results, command logs, and filesystem snapshots.

Every target/scope scenario rejects filesystem changes outside its declared
effects, replaces stale managed Markdown without duplicate markers, and checks
the exact installed version stamp. A full `--all` run also checks the public
installer target list and adds grouped user/project universal-uninstall
scenarios. The project group proves user-scope installations survive
`graphify uninstall --project`; uninstall without `--purge` must preserve
`graphify-out/`.

The YAML specs are the authority for the target catalog, install effects, and
universal-uninstall eligibility. Python discovers the catalog from the spec
filenames and derives aggregate scenarios from those declarations; it does not
maintain a second list of target names.

The repository is mounted read-only, copied to a separate container source
directory, and installed from that copy. HOME, XDG configuration, project,
user working directory, copied source, and output are distinct isolated roots.
No real user home is mounted.

Windows and Antigravity-Windows scenarios only compare packaged payloads in the
Linux container. They do not validate Windows paths, shells, permissions,
cleanup, or runtime discovery. Hermes validates its normal Linux path only;
`%LOCALAPPDATA%` behavior is not exercised.
