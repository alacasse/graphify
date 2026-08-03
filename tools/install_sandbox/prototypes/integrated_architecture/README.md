# Integrated install-sandbox architecture prototype

Status: throwaway architecture evidence; `PREPARED — NOT RESOLVED`

This Python 3.12 prototype tests whether the domain/application, resource
custody, and diagnostic-authority candidates can compose through small,
lossless, acyclic interfaces without publishing false terminal success. It is
not imported by the production install sandbox and is not cutover authority.

Run the interactive terminal:

```bash
python3.12 -B -m tools.install_sandbox.prototypes.integrated_architecture
```

Run all deterministic demonstrations:

```bash
python3.12 -B -m tools.install_sandbox.prototypes.integrated_architecture --demo all --no-ansi
```

The terminal is a derived view. The domain-owned Validation Plan and results,
resource-owned evidence, and diagnostic Run Record and Manifest remain the
only modeled machine authorities.

## Demonstrated composition

- The public execution edge is `RunController.run(RunRequest)`. Resource and
  bundle fault controls exist only on the private deterministic harness
  constructor; callers cannot replace observed exits, publication facts, or
  evidence during `run`.
- The coordinator acquires an immutable image and the catalog bound to that
  image before compiling the one domain-owned Validation Plan. Subject
  preparation and origin/version/interface probes must produce `SubjectReady`
  evidence before product lifecycle actions can begin.
- Every planned action has a stable identity, family, scenario, phase, and
  purpose. Diagnostics proves that captured facts are an ordered subset of the
  plan and that phase/purge references are an exact one-to-one projection of
  captured product evidence. Command streams are bound to exact inventory
  entries.
- Resources own descriptors, stable reads, process and Docker-daemon custody,
  persistence, quiescence, recovery claims, and terminal mutation. Diagnostics
  owns strict document decoding, evidence meaning, final outcome/exit policy,
  report derivation, commit permits, retention authorization, and CI
  classification.
- Terminal publication consumes an opaque diagnostics-issued permit bound to
  the exact assessed revision and evidence digest. The report is persisted
  first, the terminal Run Record last, then a separate descriptor-bound reopen
  and reassessment authorize resource-owned keep-five retention. Publication
  and CI occur only after those steps.
- `RunController.recover(RecoveryRequest)` accepts only a path nomination plus
  expected diagnostic identity and an abandonment reason. Resource descriptors
  remain internal; recovery derives an incomplete report/Run Record, commits
  them through a revision-bound permit, freshly reopens, and reassesses.

The deterministic cases cover strict catalog and document codecs, witness-safe
cleanup, command-free not-applicable uninstall, independent aggregate coverage,
shared Docker namespace exclusion, stream and observation evidence, mutation
during stable reads and between assessment and commit, impossible exits,
Running-preserving persistence failures, recovery identity, and
reopen/retention/publication ordering.

## Deliberate limitations

This is Component Evidence using a local process/filesystem stand-in; it is not
Docker Behavioral Evidence. Image building, catalog acquisition, publication,
and keep-five retention are deterministic adapters rather than production
implementations. Recovery abandonment is explicitly modeled, and no production
cutover, compatibility decision, or architecture acceptance is implied.
