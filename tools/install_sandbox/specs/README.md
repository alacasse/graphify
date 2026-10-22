# Install sandbox effect specifications

`codebuddy.yaml` is the active specification for the dedicated CodeBuddy project
installation. It describes a skill in HOME, a Markdown section and JSON hooks in
PROJECT. Other YAML files are retained historical target facts and are not part
of the current execution interface. The reference target and its consumer have
been removed.

## Data and responsibilities

The YAML declares effects, source paths, destinations and host hook names. It
contains no scenarios, execution defaults or test expectations. Shared conventions
remain in code; no target-name dispatch or parallel catalog selects behavior.

`EffectSpecReader` reads one explicit YAML file and validates structured effects.
The default destination root is PROJECT and the common `directory` applies unless
an effect overrides it with a different directory (including `.`). The skill
source and reference tree, and the Markdown section source, are relative to the
retained subject source directory supplied to the engine. A section defaults to
`## graphify`. The supported hook family is `pretooluse-context`.

The subject context is a separate JSON object with these required fields:

- `identity`: declared subject identity.
- `invocation`: argument words following the prepared executable.
- `version_source`: relative source path containing distribution metadata with
  one `Version` header, required by a skill effect.
- `rules`: explicit `hook_timeout`, `skill_lock`, `json_backup`, `skill_backup`
  and `json_registry` values. The supported reinstall rules currently require
  timeout `10`, persistent skill lock, `.graphify-bak` JSON backup, `.bak` skill
  backup convention and no JSON registry.

These rules describe the subject being tested. They must be established
independently of its installation output. The context has no scenario selection
or tool profile.

## Native host interface

The command accepts `--spec`, `--subject-context`, `--repo` and optional `--output`.
The first two select the effect YAML and subject context JSON. `--repo` selects
the subject checkout. `--output` selects a fresh result location; omitting it uses
the managed output directory and its retention policy.

The coordinator constructs one reinstall case with two dependent installation
steps. It uses the existing Docker harness for isolation, package preparation,
timeouts and resource cleanup. Local Component tests substitute a controlled
transport at the harness boundary; there is no public local-execution backend.
Only the controlled simulator path has been validated for the new model.

The active CodeBuddy YAML uses package-relative sources such as `skill.md`.
The current Docker harness captures a raw checkout, where this repository's
source is `graphify/skill.md`. Binding that package layout and its version
metadata to a real subject remains separate work. Reading the active YAML does
not demonstrate a working installation against this raw checkout.

## Explicit expectations and autonomous evidence

Before installation, source bytes and inventories are captured. Construction
produces typed expectations for content, directories, semantic Markdown and JSON,
absences, personal content and permitted changes. Actual HOME and PROJECT roots
are retained when known and bind the persistent skill-lock path. Each constraint
records its phase and provenance. Expectations are persisted before the
corresponding command.

The verifier compares explicit expectations with observations. It does not
reconstruct installation destinations or versions and does not infer the phase.
The second step runs only after the first command and verification succeed.
Reinstall preservation uses that independently validated first observation;
managed content still comes from the original retained sources.

After extracting `evidence.zip`, call
`tools.install_sandbox.host.result_reader.read_evidence(case_directory)` on the
retained `evidence/cases/reinstall` directory. It needs no original YAML, subject
context, subject checkout, executable or work directory. It reconstructs the
expectations from retained inputs, checks their equality with stored expectations,
validates phase continuity and recalculates verdicts. Partial failures retain the
stage reached. Old transport formats are rejected; historical evidence requires
its identified historical reader revision.

## Independent test data

`tests/install_sandbox/fixtures/generic-effects.yaml` uses the same supported
composition with synthetic source and destination names. It is independent of
the active YAML. Ingestion tests use this fixture; construction tests directly
supply structured effects and sources; verifier tests directly supply expectations
and observations; replay tests use dedicated evidence directories. Helpers do
not invoke preceding transformations to manufacture isolated test inputs.

A small integration set joins the layers, including the real CLI, host and engine
with an independent simulator for all three effects and Markdown alone. Active
CodeBuddy YAML reading has a separate integration check. These proofs do not
qualify a real installer or CodeBuddy application discovery.
