## Knative Eventing models

Models are generated from pinned upstream schemas. Configuration, schema inputs
and README sources are maintained in
[cloudcoil/cloudcoil](https://github.com/cloudcoil/cloudcoil/tree/main/models/knative-eventing);
the generated package is in
[cloudcoil/models-knative-eventing](https://github.com/cloudcoil/models-knative-eventing). Edit the
source integration in Cloudcoil because generated repository edits are replaced
on template refresh.

### Use a typed resource

After installing `cloudcoil.models.knative_eventing`, use the package's typed lookup to
select an exact Kubernetes kind and API version:

```python
from cloudcoil.models.knative_eventing import get_model

Broker = get_model("Broker", api_version="eventing.knative.dev/v1")

for resource in Broker.list(namespace="default"):
    print(resource.name)
```

The lookup is local; `list` reads the configured cluster. Async code uses
`await Broker.async_list(namespace="default")`. Direct class imports are also supported; the
lookup avoids depending on schema-derived module names.

Install the upstream Knative Eventing CRDs and operator separately before making API calls.
The model package supplies Python types and client methods, not the operator.

Use the shared [resource guide](https://cloudcoil.github.io/cloudcoil/resources/)
for constructors, builders, writes and watches, and the
[controller guide](https://cloudcoil.github.io/cloudcoil/controllers/) for
reconciliation. Pydantic validates constructed models at runtime; generated
annotations provide field completion and static type checking.

### Maintain this integration

From the Cloudcoil repository root:

```sh
make gen-repo-knative-eventing
make -C output/models-knative-eventing lint test check-artifacts
```

Rendering generates the models before validation. The
[model release guide](https://cloudcoil.github.io/cloudcoil/model-releases/)
covers source updates, artifact checks and publishing.
