# Contributor guidance

Cloudcoil is a typed Kubernetes client, model generator, controller runtime and
admission framework for Python 3.14+. Read the guide for the area you change;
`docs/index.md` is the documentation entry point.

## Development commands

```sh
make lint           # Ruff checks/formatting and mypy
make fix-lint       # Apply formatting and lint fixes
make test           # Pytest with four workers; integration tests need Docker
make docs-build     # Strict MkDocs build
make docs-serve     # Serve documentation locally
make prepare-for-pr # Formatting, lint and tests
```

The Makefile uses the frozen uv environment by default. Follow
`docs/getting-started.md#run-the-checkout` to generate matching Kubernetes models.
After replacing the development bootstrap models, use `UV_RUN_FLAGS=--no-sync`
for checks so uv does not restore the bootstrap package.

## Git and DCO

All commits must include Developer Certificate of Origin sign-off:

```sh
git commit -s -m "Describe the change"
```

Use `git commit --amend -s` to add a missing sign-off. Let git use the configured
author name and email; do not manually add additional Signed-off-by lines. The
repository uses Sambhav Kothari <sambhavs.email@gmail.com>.

## Source layout

| Area | Source |
| --- | --- |
| Resource operations and model lookup | `cloudcoil/resources.py` |
| Sync/async clients and Config lifetime | `cloudcoil/client/` |
| Model generation and templates | `cloudcoil/codegen/` |
| Handwritten CRD schemas | `cloudcoil/crd.py` |
| Controller decorators, queue, persistence and leadership | `cloudcoil/controller/` |
| Application assembly, manifests, TLS hosting and lifespans | `cloudcoil/application/` |
| Admission registration, requests and ASGI handling | `cloudcoil/admission/` |
| Caches and informer storage | `cloudcoil/caching/` |
| Pytest cluster fixtures | `cloudcoil/_testing/` |
| Integration source overlays and package template | `models/`, `cookiecutter/` |

`cloudcoil/apimachinery.py` is generated from the configured Kubernetes schema.
External model distributions use the `cloudcoil.models` namespace. Generation
configuration lives under `[[tool.cloudcoil.codegen.models]]` in pyproject.toml;
see `docs/models.md` and `docs/model-releases.md` before changing it.

## Implementation conventions

- Use explicit annotations, clear names and small functions. Public exports belong
  in package `__init__.py` files and their `__all__` lists.
- Keep imports grouped as standard library, third-party packages and local modules;
  follow the repository's Ruff configuration.
- Use Pydantic models for typed resources. Standard mypy and pyright handle the
  generated annotations; no Cloudcoil mypy plugin is required.
- Resource async methods use `async_` names; async client methods are awaited.
  Do not block the event loop with synchronous discovery or API calls.
- Preserve cancellation, UID/resourceVersion guards, no-op write suppression and
  explicit live-versus-cached read contracts when changing controller behavior.
- Keep handler registration free of I/O and validate completed definitions before
  execution. Examples use Application/Controller decorators; low-level APIs remain
  available for embedding.
- Include focused regression coverage for behavior changes. Test real API behavior
  with the supplied Kubernetes fixtures and deployment wiring with the Widget demo.
  Direct callback tests do not prove runtime scheduling, admission routing or RBAC.
- Keep executable examples and guides aligned with public imports and signatures.
  Explain workflow contracts in guides; keep implementation detail in references.
