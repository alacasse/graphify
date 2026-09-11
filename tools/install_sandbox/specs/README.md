# Install sandbox spec authority

This directory is the source-controlled target-fact catalog for the install
sandbox. The YAML files are retained product-test inputs; they are not an
implementation template and do not make their current schema permanent.

## Current successor state

The upstream-refounded successor deliberately retains this catalog without
restoring the former loader, typed models, lifecycle runner, quality gates, or
workflows. The 24 retained YAML files are not consumed by the new reader.

A later catalog slice must review the facts against the then-current Graphify
installer, define the validation and loading boundary with the owner, and add
targeted evidence before the harness may act on them. File presence alone does
not authorize recreation of any historical module or private test surface.

The YAML is the independent oracle for expected Graphify-owned file effects.
It must not be generated from the installer output or behavior it is meant to
test.

## Reference development format

`reference/sandbox-reference.yaml` contains the new target facts. Supply
`reference/` alone to `InstallSpecReader`; it discovers direct `*.yaml` files
and derives target identities from their filename stems. This does not migrate
the retained catalog or make its older format readable.

`spec.py` validates the new facts. The common initial witnesses and the
first-install, reinstall, repair-references, repair-skill, preserve-skill-backup,
or repair-markdown-section operations belong
to the case, and `InstallTestCoordinator` assembles and writes
the complete project case JSON. Product source paths are transported without
reading or embedding their contents. No installation is executed by this entry.
The local Python environment needs PyYAML for YAML reading.

The repair-references case prepares a deletion and an alteration between two
verified project installations. Selection comes from the retained source
inventory, and preparation diagnostics remain separate from product commands.
The YAML needs no additional facts for this case.

The repair-skill case alters only the installed skill after a verified first
installation, then requires restoration and an exact backup of the altered
content. The intermediate plan and observations are retained and validated
before the second installation. Backup creation is permitted only for that
repair step; the initial state and first installation have no backup. Sources,
version stability and user preservation remain independently verified.

The preserve-skill-backup case prepares an exact backup witness after a fully
verified first installation, leaving the installed skill intact. The witness
is the retained skill source followed by `\nSandbox previous backup witness.\n`
with LF line endings. A complete preparation check permits only this new file;
a partial, incorrect or unobservable preparation prevents the second command.
The second installation must preserve the backup bytes while satisfying all
existing installation and user-preservation criteria. The plan, expected
witness and both observed backup contents are retained separately. The host
checks evidence bindings and continuation conditions without repeating the
installation verdict. No additional YAML facts are needed.

The repair-markdown-section case starts with a Graphify heading between two
personal sections. After a verified installation it replaces only the managed
section body with a known incorrect witness, retaining the heading and personal
text. Preparation must be fully observed, match that witness and preserve all
other entries before the second command. Reinstallation must restore the retained
Markdown source and preserve both personal sections and all existing criteria.
The host requires retained shared-document bytes and checks the plan and evidence
bindings. No additional YAML facts are needed.

## Current ownership

| Concern | Current owner |
| --- | --- |
| Catalog membership and target identity | `*.yaml` filename stems |
| Supported and unsupported scopes, expected effects, command exceptions, limitations, and aggregate-uninstall eligibility | Each target YAML |
| Schema vocabulary, validation, defaults, and typed conversion | `spec.py` for the reference format; retained catalog not migrated |
| Scenario construction, command derivation, lifecycle execution, filesystem validation, and reporting | Outside this catalog; first-install, reinstall, repair-references, repair-skill, preserve-skill-backup, and repair-markdown-section project cases are implemented |

## Classify data before changing it

Use one of these categories:

1. **Irreducible target fact.** A fact that differs by target and cannot be
   inferred safely, such as an expected path, payload source, marker, or
   documented target limitation. Keep it in that target's YAML.
2. **Deterministic derivation.** A value that follows from filename, scope,
   existing facts, or a target-independent convention. A future consumer
   should derive it instead of storing it here.
3. **Cross-target harness policy.** A generic rule such as lifecycle ordering
   or unexpected-change validation. It belongs in a future harness policy,
   not in a list of real target names.
4. **Product observation.** Something the current installer happens to do.
   Record it as evidence or a product defect; do not let a product bug redefine
   its own expected result.

`universal_uninstall_scopes` remains an explicit retained target fact because
its value is not currently safe to infer from scope support, effects, or
command mode. Retention does not commit the future loader or runner to the old
shape. A later slice may replace it only after proving a target-independent
derivation.

## No parallel catalog

Production target names must not be copied into a Python tuple, set, dispatch
table, or test parameter list that becomes a second source of membership or
policy. A future consumer must discover targets from this directory and apply
generic mechanics to reviewed facts.

## Change checklist

Before adding or changing target data:

- classify it as a target fact, derivation, harness policy, or observation;
- show why a new field cannot be derived safely;
- confirm expected results remain independent of the product being tested;
- confirm no second catalog of production target names was introduced;
- treat a failing product observation as a defect instead of weakening the
  oracle; and
- update this guide when the ownership boundary changes.
