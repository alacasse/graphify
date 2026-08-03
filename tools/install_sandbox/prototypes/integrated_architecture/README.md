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
