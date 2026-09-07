# Generating models

## Generate a package

Install Python 3.14 and the codegen extra:

```shell
pip install 'cloudcoil[codegen]'
cloudcoil-model-codegen --namespace hello --input crds.yaml --output .
```

That is enough for ordinary CRDs. Inputs can be local paths or URLs, YAML or JSON,
multi-document installation bundles, Kubernetes `List` objects, Swagger/OpenAPI
2 or 3 documents, or JSON Schema definitions. Format detection uses the content,
so download URLs do not need a `.yaml` or `.json` suffix. Multiple inputs work too:

```shell
cloudcoil-model-codegen --namespace hello --input first.yaml second.json --output .
```

For repeatable project generation, put only the package and sources in
`pyproject.toml`, then run `cloudcoil-model-codegen`:

```toml
[[tool.cloudcoil.codegen.models]]
namespace = "hello"
input = ["crds.yaml"]
```

The generator automatically:

- Uses CRD group/version/kind metadata, OpenAPI endpoint references, and unambiguous
  versioned schema families to recognize resources.
- Maps built-in Kubernetes APIs to packages such as `core.v1` and `apps.v1`, and
  reuses Cloudcoil's metadata and scalar types instead of duplicating them.
- Places a single CRD group under its version; separates multiple groups so their
  model names cannot silently collide.
- Gives nested objects names derived from their parent and field path.
- Handles Kubernetes integer-or-string, nullable, embedded-resource, and
  preserve-unknown-fields annotations, including schemas nested inside lists.
- Keeps wire names intact while escaping Python API collisions such as the
  `builder` field (`builder_`) and the `Builder` resource (`BuilderResource`).
- Produces fluent builders, context builders, and package-local typed lookups.

Generation stages and syntax-checks output before copying it to the destination.
Repeat generation replaces generated files and removes stale files recorded in its
manifest, while leaving unrelated files alone. Conflicting definitions and naming
collisions are errors rather than silent overwrites.

### When an override is useful

Hints remain useful for intentionally different public package layouts, genuine
schema errors, or missing/ambiguous resource identity that cannot be established
from the source. Prefer supplying the CRD or complete OpenAPI document over
manually describing its GVK. Generation cannot infer a missing API group from a
Python/Go type name alone, and does not implement Kubernetes admission or CEL
validation locally.

Explicit `transformations`, `updates`, and `aliases` remain available. Updates
accept JSON values, including booleans, numbers, lists, objects, and null; string
updates support regex substitutions. Explicit transformations take precedence
over inferred names. `crd-namespace` is an optional layout override, not a
requirement. Set `infer = false` (CLI: `--no-infer`) to retain manual control.
`exclude-unknown` discards unmatched definitions and their dependents.

The checked-in regression corpus covers complete HelmRelease, Certificate, and
Prometheus CRDs plus the complete kpack OpenAPI schema, without schema hints.
The cookiecutter template remains available for packaging and publishing models.

### Migrating from 0.4 / earlier 0.5 development builds

- Upgrade to Python 3.14 and regenerate your models with the current codegen extra.
- Remove `cloudcoil.mypy` from type-checker configuration. Use direct imports or a
  generated package's `get_model` for precise static types.
- Inferred module and nested-class names can change; retain explicit
  transformations when you need a particular layout.
- Iterate watches directly: `async for event in Pod.async_watch(): ...` (no `await`
  before the iterable). Async operations perform initial discovery off the event loop;
  explicit clients are available with `await config.async_client_for(Pod)`.
- A bare kind lookup now rejects ambiguous versions instead of selecting one by
  import order.
- Direct client deletion now defaults to performing the operation, matching
  resource methods. Pass `dry_run=True` explicitly to preview a deletion.
- List pagination follows the server's continuation token and stays with its
  originating client. Requesting a nonexistent next page raises `ValueError`.
- `save()` uses the fetched resource version for replacement without mutating the
  caller's model. A caller-supplied version remains authoritative.
- Nested and concurrent cached scopes share a cache until the last scope exits.
  Use separate cached configs for synchronous and asynchronous scopes.

## IDE typing

Cloudcoil targets Python 3.14 and uses standard Python annotations understood by
Pyright/Pylance and mypy. No Cloudcoil or Pydantic mypy plugin is required.
Direct imports provide the clearest completions:

```python
from hello.v1 import Widget

widget = Widget.builder().metadata(lambda meta: meta.name("example")).build()
```

Generated packages also include their own typed lookup. Literal names and API
versions resolve to the concrete class in both type checkers:

```python
from hello import get_model

Widget = get_model("Widget", api_version="widgets.example.com/v1")
widget = Widget.builder().metadata(lambda meta: meta.name("example")).build()
```

A kind name alone works when it is unique in that package. If several versions
exist, specify `api_version`. The global `cloudcoil.resources.get_model()` remains
available for runtime discovery and returns `type[Resource]`; use a direct import
or the generated package lookup when you need static completion of specific fields.
