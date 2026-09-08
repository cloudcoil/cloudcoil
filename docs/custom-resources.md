# Custom resources

Define a typed resource, generate its CRD, then use it in a [controller](controllers.md)
or attach [admission policies](admission.md). Application includes decorated primary
models in its manifests; its `install` command applies their CRDs. Importing a model
or starting `run` does not install a CRD.

## Define and generate

```python
from typing import Annotated, Literal
from pydantic import Field
from cloudcoil.controller import ReconcileStatus
from cloudcoil.crd import CRD, PrinterColumn, custom_resource
from cloudcoil.pydantic import BaseModel
from cloudcoil.resources import Resource

class WidgetSpec(BaseModel):
    message: str = Field(min_length=1, max_length=200)

class WidgetStatus(ReconcileStatus):
    ready_replicas: Annotated[int, PrinterColumn(name="Ready replicas")] = 0

@custom_resource(api_version="examples.cloudcoil.dev/v1alpha1", plural="widgets")
class Widget(Resource):
    spec: WidgetSpec
    status: WidgetStatus | None = None

print(CRD(Widget).to_yaml())  # Offline; does not install anything.
```

The decorator sets validated `apiVersion` and `kind` fields; kind defaults to the
class name. Explicit Literal fields are also supported when omitting `api_version`
from the decorator. Explicit plural names avoid guessing English plurals. Keep the `apiVersion` alias when overriding `api_version`, and use
aliases such as `observedGeneration` for fields whose Kubernetes names differ from
Python names. Generation checks that validation and serialization agree on names.
`PrinterColumn` on an `Annotated` field infers its serialized JSONPath and scalar
type, including nested models and aliases; a `date-time` field becomes a `date`
column. Inferred columns are followed by the default Age column. Explicit
`CRD(Widget, columns=[...])` replaces them; `columns=[]` disables all columns.
Collection-item columns need an explicit `json_path`.

The class decorator preserves the Pydantic model and supplies its wire identity and CRD metadata. It does
not create a controller, install the CRD, or register a global webhook. Each concrete
subclass declares its own plural. Existing models can still use
`CRD(Widget, plural="widgets", ...)`; constructor options override class metadata.

The generator emits one served/storage version in
`apiextensions.k8s.io/v1`. It enables the status subresource when the model has a
status field, with an explicit override available. Keep status optional with a
`None` default: the API server removes status during normal creates. A required
status field would prevent initial creation. Scope and CRD installation permissions
are independent of a controller's watch namespace.

`CRD` generation does not install anything. Review the emitted manifest and apply it
with your normal deployment workflow. Updating an existing CRD is an API change:
consider stored objects and compatibility before narrowing its schema. Multiple
served versions, conversion webhooks and storage-version migration are unsupported.

## Status for controllers

`ReconcileStatus` supplies standard conditions and `observedGeneration`. A controller
using this status model automatically reports Ready; stages add their named conditions.
Additional fields need defaults so an absent status can be initialized. Keep the
resource's `status` optional, as in the example above.

Use `ctx.set_status(ready_replicas=2)` inside a handler. The helper validates fields
and queues a guarded status write. Use an ordinary `BaseModel` status when another
component owns reporting, or disable automatic reporting with `report_status=False`.
See [status helpers](staged-controllers.md#status-helpers) for failure behavior and
condition ownership.

## Use a handwritten resource as a client

Every `Resource` subclass inherits the same get, list, watch, create, update,
patch, status, and delete methods as generated Kubernetes models. The return types
remain your concrete resource type. No decorator or code-generation step is needed
for these methods; the CRD must be installed and discoverable by the API server.

Use the resource's typed client when you have an explicit `Config`, such as in an
operator or admission handler:

```python
client = await Widget.async_client(config, namespace="team-a", cached=False)
widget = await client.get("example")  # Widget
widgets = await client.list()         # ResourceList[Widget]

widget.spec.message = "Updated"
widget = await client.update(widget)
```

`Widget.client(config)` is the synchronous equivalent. Omitting `config` uses the
active configuration, like `Widget.get(...)` and `widget.async_update_status()`.
The optional namespace override belongs to the returned client and does not alter
the shared configuration. `cached=` follows `Config.client_for` semantics. The
configuration owns the transports and their lifetime; creating a resource client
does not create or close a separate connection pool. Status and scale operations
still require the corresponding server-side subresources.

Handwritten `cloudcoil.pydantic.BaseModel` and `Resource` subclasses also have
runtime `.builder()`, `.new()`, and `.list_builder()` helpers. Nested model fields,
optional models, and lists of models support callbacks and context managers,
including generated `ObjectMeta` builders:

```python
widget = (
    Widget.builder()
    .metadata(lambda meta: meta.name("example"))
    .spec(lambda spec: spec.message("Hello"))
    .build()
)
```

These dynamic field setters validate at `build()` time. Their field signatures
are not available to static type checkers: use ordinary typed constructors for
handwritten models when you need field completion and static argument checking.
Generated models keep their existing fully typed builders. Builder chains are
immutable outside `with Model.new()` contexts; a failed nested context does not
commit a partial model. Ambiguous unions accept an explicit model value rather
than guessing which model to construct.

## Schema behavior

The generator translates Pydantic validation schemas into Kubernetes structural
OpenAPI schemas. Nested models are inlined, nullable fields use `nullable`, constants
become enums, and supported numeric/string/list bounds remain validations. Typed
maps and lists retain their item schemas. Explicit arbitrary JSON fields preserve
unknown values; ordinary object schemas are pruned by Kubernetes according to their
schema. See [Kubernetes structural schemas and pruning](https://kubernetes.io/docs/tasks/extend-kubernetes/custom-resources/custom-resource-definitions/#specifying-a-structural-schema).

Unsupported constructs raise `SchemaError` with the field path. Recursive models,
ambiguous unions, and constraints that Kubernetes cannot represent are not silently
converted into permissive schemas. Python validators are **not** exported: use a
validation webhook for Python business rules, or explicit Kubernetes CEL schema
extensions when appropriate. Pydantic may coerce input during local validation;
Kubernetes's schema validation does not promise the same coercions.

Use regular Pydantic `Field` annotations for bounds and aliases. `CEL` and
`ListType` express common Kubernetes-only extensions next to the type:

```python
from cloudcoil.crd import CEL, ListType


class Condition(BaseModel):
    type: str
    status: Literal["True", "False", "Unknown"]


class ExampleSpec(BaseModel):
    replicas: Annotated[int, Field(ge=0), CEL("self <= 10", "At most ten replicas")] = 1
    conditions: Annotated[list[Condition], ListType("map", keys=("type",))] = Field(
        default_factory=list
    )
```

`ListType("set")` and `ListType("atomic")` are also supported. Map keys use wire
names. CEL runs in Kubernetes, not in Pydantic; Python `field_validator` and
`model_validator` still apply when admission parses the typed resource.
`Field(json_schema_extra=...)` remains available for other Kubernetes extensions.
These must still be valid for the field's Kubernetes schema. Generation is not a CEL compiler; test your CRD
against the API-server versions you support. The repository's integration test
installs generated CRDs and checks schema validation and status operations.
