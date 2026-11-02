# Install sandbox effect specifications

The active project-scope specifications are:

| Spec | Skill | Markdown | Hooks |
| --- | --- | --- | --- |
| `codebuddy.yaml` | HOME `.codebuddy/skills/graphify` | PROJECT `CODEBUDDY.md` | PROJECT `.codebuddy/settings.json` |
| `amp.yaml` | PROJECT `.agents/skills/graphify` | PROJECT `AGENTS.md` | None |

Amp uses package sources `skill-amp.md`, `skills/amp/references` and
`always_on/agents-md.md`, with the `## graphify` section marker. Other YAML files
retain historical target facts and are outside the current execution interface.
User scope, uninstall, other platforms and other effects are outside this scope.

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
- `revision` and `package_root`: exact Git commit and package-relative source
  directory for a packaged subject; `package_root` is `graphify` for this product.
- `invocation`: argument words following the prepared executable.
- `version_source`: relative source path containing distribution metadata with
  one `Version` header, required by a skill effect.
- `rules`: explicit `hook_timeout`, `skill_lock`, `json_backup`, `skill_backup`
  and `json_registry` values. The supported reinstall rules currently require
  timeout `10`, persistent skill lock, `.graphify-bak` JSON backup, `.bak` skill
  backup convention and no JSON registry. JSON and hook fields remain required by the context,
  but produce no expectations when no JSON hook effect is declared.

These rules describe the subject being tested. They must be established
independently of its installation output. The context has no scenario selection
or tool profile.

## Native host interface

The command accepts `--spec`, `--subject-context`, `--repo` and optional `--output`.
The first two select the effect YAML and subject context JSON. `--repo` selects
the subject checkout. `--output` selects a fresh result location; omitting it uses
the managed output directory and its retention policy.

The coordinator constructs the cases before allocating campaign output.
Exactly one Markdown section makes `reinstall`, `missing-section` and
`altered-section` available, each with two dependent installation steps. Effects
select the behavior; filenames, subject identities and invocation words do not.
The skill is verified and preserved during the Markdown repair cases.

The Docker harness isolates execution, prepares the package once, enforces
timeouts and cleans resources. It captures the subject's declared Git revision,
installs its package and binds source files and `METADATA` to the executable.
Local Component tests substitute a controlled transport at the harness boundary;
there is no public local-execution backend. Real CodeBuddy campaigns have also
qualified all three cases with the corrected product.

For the Amp project campaign, use a separate subject context with:

```json
{
  "identity": "graphify-7b9e3e80",
  "revision": "7b9e3e80d25137d12e198cd1f6b87865821af491",
  "invocation": ["amp", "install", "--project"],
  "package_root": "graphify",
  "version_source": "METADATA",
  "rules": {
    "hook_timeout": 10,
    "skill_lock": "persistent",
    "json_backup": ".graphify-bak",
    "skill_backup": ".bak",
    "json_registry": false
  }
}
```

From the sandbox checkout, with the selected product commit available in
`/path/to/product-checkout` and a fresh output location:

```sh
python -m tools.install_sandbox \
  --spec tools/install_sandbox/specs/amp.yaml \
  --subject-context /path/to/subject-context.json \
  --repo /path/to/product-checkout \
  --output /path/to/fresh-campaign
```

Each real campaign needs its own explicit execution budget. Passing these cases
qualifies only the executed installation and repair paths, not complete host
support or application discovery.

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
retained `evidence/cases/<case-name>` directory for each of the three cases. It needs no original YAML, subject
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
with an independent literal simulator for all three effects, Markdown alone,
and a skill in PROJECT plus Markdown without hooks. A negative composition
returns command success while putting the skill in HOME: verification fails
after the first command and replay retains that verdict. Replay equality is
checked after deleting the source inputs and execution environment. Active
CodeBuddy and Amp YAML reading have compact checks separate from synthetic
engine data. Simulated proofs do not qualify a real installer or host discovery.
