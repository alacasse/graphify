# Install sandbox effect specifications

The following six tool specifications declare executable project effects. Each also records the status of its user scope.

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

Selecting one of the other 18 historical YAML files produces an explicit conversion diagnostic.

## Data and responsibilities

Each YAML declares one tool. Under `scopes`, a list gives the effects for
that participant. Each effect has a local `effect_id`, `family`, physical
`root` (HOME or PROJECT) and a relative `path`. The root is independent of
the scope. Skill and Markdown sources are package-relative. JSON effects
declare every hook's local ID, event, matcher and expected content. Changing
a destination preserves the effect's identity.

A scope whose effects await conversion carries `state: unconstructible` and a
reason. A scope the product explicitly does not support carries
`state: not_applicable` and a reason. The six catalog specs currently declare
unconverted user effects. An unfiltered run exercises project and reports the
outstanding user obligation. A project-only request can establish full project
coverage within a partial campaign.

The subject context is a separate JSON object with these required fields:

- `identity`: declared subject identity.
- `revision` and `package_root`: exact Git commit and package-relative source
  directory for a packaged subject; `package_root` is `graphify` for this product.
- `invocations`: a map from participant (such as `birch:user`) to the argument words following the prepared executable. A single `invocation` remains supported for project contexts.
- `version_source`: relative source path containing distribution metadata with
  one `Version` header, required by a skill effect.
- `rules`: explicit `skill_lock`, `json_backup`, `skill_backup`
  and `json_registry` values. The supported reinstall rules currently require
  the declared JSON hook facts, persistent skill lock, `.graphify-bak` JSON backup, `.bak` skill
  backup convention and no JSON registry. JSON fields remain required by the context,
  but produce no expectations when no JSON hook effect is declared. Each hook
  may declare its own integer `timeout` in `content`.

These rules describe the subject being tested. They must be established
independently of its installation output. The context has no scenario selection
or tool profile.

## Native host interface

The command accepts `--spec`, `--subject-context`, `--repo` and optional `--output`.
The first two select the effect YAML and subject context JSON. `--repo` selects
the subject checkout. `--output` selects a fresh result location; omitting it uses
the managed output directory and its retention policy.

Without a filter, the CLI enumerates every applicable operation across the
declared scopes. For development, supply `--request FILE` containing a scope
projection or a member selection. Both use the same executor and replay.

```json
{"scopes":["project"]}
```

```json
{"operation":"missing-json-hook","target":{"participant":"birch:project","effect_id":"assistant-hooks","member":"run"}}
```

Repeat `--case NAME` to execute every occurrence of the named operations, for example
`--case reinstall --case stale-version`. The complete catalogue is constructed
and classified first, then selected entries retain their canonical campaign order
regardless of argument order. Unknown or duplicate names and combining `--case`
with `--request` or `--prepare-only` are input errors before output allocation or Docker access.
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
`preserve-skill-backup`, `stale-version` and `stale-reference` available
in that order, independently of the Markdown count. Without a skill, the campaign
reports those cases as `not_applicable`.
Each declared JSON hook adds one `missing-json-hook` case keyed by effect and
member. Without a JSON hook effect this operation is `not_applicable`. Each
executable case has two dependent installer calls. CodeBuddy has 11 project
cases (22 calls), Amp has 9 (18 calls), and Agents, Copilot, Kimi and Pi each
have 7 (14 calls). This gives 48 executable project cases across the six specs.

The hook repair fixture seeds the selected member beside a personal command,
with an explicit group attribute. A second group with the same matcher holds
two ordered personal commands. A third group uses another matcher. The first
install must leave exactly one conforming occurrence of each declared hook
under its event and matcher. The selected member may move to another matching
group. Personal groups, their attributes, their relative order and their commands
must survive. Installation must back up the preexisting settings byte for byte.

Preparation removes the selected member at its observed position. The sandbox
checks this edit against the first installation, including the backup and every
other observed file. An incomplete observation or any additional change blocks
the second command. Repair must restore exactly one conforming occurrence and
preserve the surrounding document, including the other hooks. The repaired
settings' backup must be a readable regular file. Its generation after that
write is product-specific. All other observed files retain their bytes. In the
ordinary `reinstall` case, the sandbox checks each hook count and requires the
original settings backup to remain byte-identical.

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
in HOME and PROJECT, including empty personal directories.

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
    "skill_lock": "persistent",
    "json_backup": ".graphify-bak",
    "skill_backup": ".bak",
    "json_registry": false
  }
}
```

From the sandbox checkout, with the selected product commit available in
`/path/to/product-checkout` and a fresh output location, use a request file containing `{"scopes":["project"]}`:

```sh
python -m tools.install_sandbox \
  --spec tools/install_sandbox/specs/amp.yaml \
  --request /path/to/project-only.json \
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

Use `tools.install_sandbox.host.campaign_replay.replay_campaign(path_to_zip)` to
verify the complete or partial report. The ZIP reader limits temporary extraction
to 1 GiB and 100,000 entries by default. For larger archives, pass explicit
`max_bytes` and `max_entries` budgets. Replay re-enumerates the archived spec and
selection, checks the host receipts and replays every finished case. Each
selected key includes tool, scope, operation, effect ID and member. The
directory name is a SHA-256 digest of that key. To inspect one extracted case,
call `tools.install_sandbox.host.result_reader.read_evidence(case_directory)`
using the case's reported evidence path. It needs no original YAML, subject
context, subject checkout, executable or work directory. It reconstructs the
expectations from retained inputs, checks their equality with stored expectations,
validates phase continuity and recalculates verdicts. Partial failures retain the
stage reached. Old transport formats are rejected; historical evidence requires
its identified historical reader revision.
Replay also reconstructs the case inventory. Use reader `534af187` for archives
from that revision with v11 cases and a timeout in the subject rules. Use reader `4ba40355` for archives
from that revision, which included timeout and duplicate hook repair cases. Use
reader `7a956f79` for archives from that revision, which also included the legacy
reference staging scenario. Earlier archives retain their historical readers.

The current formats are case `explicit-expectations-v12`, expectations
`explicit-expectations-v4`, prepared operation `prepared-mutation-v4`, performed
result `performed-mutation-v3`, and case evidence `explicit-expectations-v13`.
The `kind` field identifies the operation as `markdown`, `file-removal`,
`file-append`, `file-creation`, or `file-replacement`. The
`preserve-skill-backup` and `stale-reference` cases use `file-creation` to
create their respective witnesses.
`missing-json-hook` uses `file-replacement` for the selected settings file.
`stale-version` uses the same operation for the version file.
Campaign format v4 includes the coverage and outcome of each declared scope. Replay
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

Run the dedicated synthetic Docker acceptance lane with
`python -m pytest tests/install_sandbox/docker/test_lot_one_cli.py`.

### Ordered group requests

A partial campaign can prepare explicit participants and remove an ordered subset:

```json
{"operation":"group-uninstall","prepare":["cedar:user","cedar:project","birch:project"],"remove":["birch:project","cedar:project"]}
```

The chosen `--spec` tool must participate. Other tools resolve by canonical filename
in that spec's directory; only requested tools are read, and declared identities
must match. Campaign definition v2 archives their source once for autonomous replay.
The subject context binds install argv in `invocations` by `tool:scope`, and binds
one exact ordered removal in `removals`, for example:

```json
{"removals":[{"action":"uninstall","participants":["birch:project","cedar:project"],"argv":["uninstall","birch","cedar"]}]}
```

Every argv includes its operation and is copied verbatim. No CLI syntax or scope
option is inferred. Duplicate participants and overlapping physical destinations,
including auxiliary paths and parent/child paths, are rejected before execution.
Case transport v12 includes immutable ordered command steps and participant specs.
