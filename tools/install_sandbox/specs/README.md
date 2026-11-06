# Install sandbox effect specifications

The active project-scope specifications are:

| Spec | Skill | Markdown | Hooks |
| --- | --- | --- | --- |
| `codebuddy.yaml` | HOME `.codebuddy/skills/graphify` | PROJECT `CODEBUDDY.md` | PROJECT `.codebuddy/settings.json` |
| `amp.yaml` | PROJECT `.agents/skills/graphify` | PROJECT `AGENTS.md` | None |
| `agents.yaml` | PROJECT `.agents/skills/graphify` | None | None |
| `copilot.yaml` | PROJECT `.copilot/skills/graphify` | None | None |
| `kimi.yaml` | PROJECT `.kimi/skills/graphify` | None | None |
| `pi.yaml` | PROJECT `.pi/agent/skills/graphify` | None | None |

Amp uses package sources `skill-amp.md`, `skills/amp/references` and
`always_on/agents-md.md`, with the `## graphify` section marker.

The four skill-only project compositions use these package-relative sources:

| Spec | Skill source | Reference source | Subject invocation after the executable |
| --- | --- | --- | --- |
| `agents.yaml` | `skill-agents.md` | `skills/agents/references` | `install --platform agents --project` |
| `copilot.yaml` | `skill-copilot.md` | `skills/copilot/references` | `install --platform copilot --project` |
| `kimi.yaml` | `skill.md` | `skills/claude/references` | `install --platform kimi --project` |
| `pi.yaml` | `skill-pi.md` | `skills/pi/references` | `install --platform pi --project` |

These mappings and commands are established at product revision
`7b9e3e80d25137d12e198cd1f6b87865821af491`. Kimi shares the Claude reference
bundle without declaring Claude registration. A reference named `hooks.md`
does not declare a hook. `agents install` is a different composition, and
`pi guard install` is not the Pi skill command. Each target needs a separate
subject context and campaign. Historical user-scope facts and uninstall metadata
remain available in the immutable
[original YAML](https://github.com/alacasse/graphify/tree/e181166ae11bda165e23bbd83d6357fe4872db49/tools/install_sandbox/specs);
conversion does not qualify or retire those capabilities.

Other YAML files
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

Repeat `--case NAME` to execute only named cases, for example
`--case reinstall --case stale-version`. The complete catalogue is constructed
and classified first, then selected entries retain their canonical campaign order
regardless of argument order. Unknown or duplicate names and combining `--case`
with `--prepare-only` are input errors before output allocation or Docker access.
Only selected executable cases are materialized and run; a selected
`not_applicable` or `unconstructible` entry retains its classification and reason.
A selection with no executable case fails without preparing an image.

Every explicit selection is a **partial campaign**, even when it names the whole
catalogue. Text, JSON and archived campaign reports retain `requested_cases`
(argument order), `omitted_cases` (catalogue order), and `executed_cases` (catalogue
order). Omission means not selected, never not applicable. `executed_cases` lists
only cases with validated retained evidence of at least one started installer
command, including interrupted commands; it does not claim all case steps passed.
A pending case, failed container launch, or unavailable/invalid result supplies no
such execution evidence. Their individual execution states and errors remain in
`cases`.

A successful selection exits zero with `scope: partial`, `successful: true`,
`status: partial_passed` and `passed: false`; it cannot establish full campaign
coverage. The selection declaration is retained even if execution stops before
its first progress report; its status remains `partial_incomplete` with no
executed cases. An interruption before raw evidence exists does not create an
empty evidence archive. Other selections report `partial_incomplete` and exit nonzero, including
selected unconstructible entries or no executable case. Preparation-only reports
`scope: preparation_only`. Omitting `--case` preserves full campaign execution.

The coordinator constructs the cases before allocating campaign output.
`reinstall` is always constructed. Exactly one Markdown section also makes
`missing-section` and `altered-section` available; zero sections makes those cases
not applicable, while multiple sections remains an explicit construction limit.
A skill makes `missing-reference`, `altered-reference`, `altered-skill`,
`preserve-skill-backup`, `stale-version`, `stale-reference` and `stale-references-tmp` available
in that order, independently of the Markdown count. Without a skill, the campaign
reports those cases as `not_applicable`.
The hook cases, `missing-json-hook`, `altered-json-hook` and
`duplicate-json-hook`, select the first hook of the first `json-hooks` effect.
A spec without that effect yields `not_applicable` for all three. Each case has two dependent
installation steps. A successful CodeBuddy project campaign runs 13 cases (26 installer
calls). Amp project runs 10 (20 installer calls). Each of Agents, Copilot, Kimi
and Pi project runs 8 cases (16 installer calls): reinstall and the seven skill
cases. Its two Markdown and three hook cases are `not_applicable`, with no
installer commands or case evidence. These classifications describe the declared
effects; a passed campaign qualifies only its represented paths.

Each hook repair case seeds the selected conforming hook beside the personal
`python personal_graphify_audit.py` command (timeout 17), with an explicit group
attribute and a neighboring personal group under the same event. Other declared
hooks are absent initially and must be installed by the first command. The first
installation must preserve the selected hook in its original mixed group.

`missing-json-hook` then removes only the selected hook. `altered-json-hook`
changes only its timeout from 10 to 11. `duplicate-json-hook` starts with a
second personal group under the same event and matcher. Preparation inserts
a copy of the entire observed hook between that group's two personal hooks.
The verifier requires exactly two conforming occurrences, checks every field
of the copy, and removes it from the observed settings for comparison with the
first installation. In all three cases, a mismatch in the settings or another
observed file, or an incomplete observation, blocks the second command.

Reinstallation must leave exactly one conforming occurrence under the declared
event and matcher, in either an existing or a new group. Leaving the altered
occurrence beside a conforming one fails verification even when the command
exits successfully. For a duplicated hook, either copy may survive. Both
personal groups must survive with their personal hooks in order.
All other hooks, group attributes, personal ordering and
settings must match the first installation. The backup must match the original
settings byte for byte, and all other observed files must retain their bytes.

`missing-reference` removes one representative reference: the first regular file
in lexical order of relative source paths, including subdirectories. A complete
source inventory with at least one reference is required before its first
installer call. An empty or incomplete bundle stops initial preparation with a
validation diagnostic: the case is `not_run` and the campaign is `incomplete`.
Multiple skills remain unsupported by the common engine.

`altered-reference` uses the same source inventory and lexical selection. After
a conforming first installation it appends exactly `b"\nSandbox repair witness.\n"`
to the selected installed file. Empty and binary source files are supported,
including files already containing that witness. Preparation must preserve every
other entry and permit no removals. The second installation must restore the
exact source bytes without adding a reference backup. Neither case creates a
personal witness inside `references/`; preservation of extra user files there
would be a distinct behavior.

`altered-skill` appends exactly `b"\nSandbox skill repair witness.\n"` once to
`SKILL.md` after a fully conforming first installation without a skill backup.
It supports empty and binary sources, including a source that already contains
the witness. Preparation may change only that file. Reinstallation must restore
its exact source bytes and create `SKILL.md.bak` containing the full altered
bytes, while preserving references, version, lock, personal files, other effects
and the initial JSON backup. The repair baseline is the verified preparation.
`preserve-skill-backup` covers a conforming skill with a preexisting backup.
After a fully conforming first installation with no backup, preparation creates
only `SKILL.md.bak`, containing the exact retained source bytes followed once by
`b"\nSandbox previous backup witness.\n"`. Empty, binary and already suffixed
sources retain their exact bytes. Creation binds the case digest, validated
observation and positively observed absence, recalculates the destination, and
uses exclusive creation without following symlinks. Existing files and incomplete
writes block dependent execution. Reinstallation preserves the explicit backup
expectation and uses the verified preparation baseline with no allowed changes
or removals. Skill, references, metadata, personal content and other effects must
also remain exact. An altered skill with a preexisting backup is a distinct case.
Other cases continue to require the skill backup to be absent.

`stale-version` replaces only the skill's `.graphify_version` after a conforming
install. The witness is `0.0.0-stale` without a newline, or `0.0.1-stale` when
the package version already equals the first witness. The second install runs
after the sandbox verifies this single change. It must restore the exact UTF-8
bytes derived from the retained `Version` header and preserve every other
observed entry in HOME and PROJECT.

`stale-reference` requires a complete package reference inventory with no entry
named `stale.md` at its root. An empty reference directory is valid. After a
conforming first install, preparation creates only `references/stale.md` in the
installed skill, with the exact bytes `b"Stale reference.\n"`. The second install
runs only after this addition is verified. It must remove that file, preserve
the package references byte for byte, and preserve every other observed entry
in HOME and PROJECT.

`stale-references-tmp` exercises the legacy staging directory beside the installed
`references/`. After verifying a conforming first install and the absence of
`references.tmp/`, preparation exclusively creates that directory and its sole
file, `stale.md`, containing exactly `b"Stale reference.\n"`. Reinstallation
must remove both entries. Leaving the directory empty fails even on exit 0.
Every other entry in HOME and PROJECT must be preserved, including empty
directories and any packaged `references/stale.md`. A completely observed
empty reference bundle is valid.

For `missing-reference`, the engine binds removal to the case, observed
file bytes and exact destination selected from retained sources. Only that file
may disappear during preparation; its directory and every other entry in HOME
and PROJECT must remain unchanged. Reinstallation requires exact source bytes
and preserves all other references, the skill, version, lock, personal content,
other effects and their initial backups. Markdown repair cases retain their
existing preservation checks.

The Docker harness isolates execution, prepares the package once, enforces
timeouts and cleans resources. It captures the subject's declared Git revision,
installs its package and binds source files and `METADATA` to the executable.
Local Component tests substitute a controlled transport at the harness boundary;
there is no public local-execution backend. Real qualification belongs to the exact sandbox and product revisions recorded
with each campaign. Component simulations and retained literal proofs do not
qualify the product; use the campaign evidence to establish which cases ran.

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
retained `evidence/cases/<case-name>` directory for each constructed case. It needs no original YAML, subject
context, subject checkout, executable or work directory. It reconstructs the
expectations from retained inputs, checks their equality with stored expectations,
validates phase continuity and recalculates verdicts. Partial failures retain the
stage reached. Old transport formats are rejected; historical evidence requires
its identified historical reader revision.

The current formats are case `explicit-expectations-v9`, expectations
`explicit-expectations-v4`, prepared operation `prepared-mutation-v3`, performed
result `performed-mutation-v3`, and case evidence `explicit-expectations-v11`.
The `kind` field identifies the operation as `markdown`, `file-removal`,
`file-append`, `file-creation`, `stale-references-tmp-creation`, or `file-replacement`. The
`preserve-skill-backup` and `stale-reference` cases use `file-creation` to
create their respective witnesses. The `stale-references-tmp-creation` operation
records creation of the directory and its witness as a single preparation.
All three JSON hook repair cases use `file-replacement` for the settings.
`stale-version` uses the same operation for the version file.
Campaign format v3, snapshots, timings and lifecycle checkpoints are unchanged. Replay
independently reconstructs the target selection, operation and expectations,
including both repaired skill bytes and altered backup bytes from retained sources.

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
CodeBuddy, Amp and the four skill-only project YAML readings have compact checks
separate from synthetic engine data. Simulated proofs do not qualify a real installer or host discovery.
