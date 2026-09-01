# Install sandbox spec authority

This directory is the source-controlled target-fact catalog for the install
sandbox. The YAML files are retained product-test inputs; they are not an
implementation template and do not make their current schema permanent.

## Current successor state

The upstream-refounded successor deliberately retains this catalog without
restoring the former loader, typed models, lifecycle runner, quality gates, or
workflows. No current production module consumes these files yet.

A later catalog slice must review the facts against the then-current Graphify
installer, define the validation and loading boundary with the owner, and add
targeted evidence before the harness may act on them. File presence alone does
not authorize recreation of any historical module or private test surface.

The YAML is the independent oracle for expected Graphify-owned file effects.
It must not be generated from the installer output or behavior it is meant to
test.

## Current ownership

| Concern | Current owner |
| --- | --- |
| Catalog membership and target identity | `*.yaml` filename stems |
| Supported and unsupported scopes, expected effects, command exceptions, limitations, and aggregate-uninstall eligibility | Each target YAML |
| Schema vocabulary, validation, defaults, and typed conversion | Not implemented on the successor line |
| Scenario construction, command derivation, lifecycle execution, filesystem validation, and reporting | Outside this catalog; not implemented on the successor line |

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
