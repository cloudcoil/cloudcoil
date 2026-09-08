## Kubernetes models

Models are generated from pinned upstream schemas. Configuration, schema inputs
and README sources are maintained in
[cloudcoil/cloudcoil](https://github.com/cloudcoil/cloudcoil/tree/main/models/kubernetes);
the generated package is in
[cloudcoil/models-kubernetes](https://github.com/cloudcoil/models-kubernetes). Edit the
source integration in Cloudcoil because generated repository edits are replaced
on template refresh.

### Use a typed resource

After installing `cloudcoil.models.kubernetes`, use the package's typed lookup to
select an exact Kubernetes kind and API version:

```python
from cloudcoil.models.kubernetes import get_model

Pod = get_model("Pod", api_version="v1")

for resource in Pod.list(namespace="default"):
    print(resource.name)
```

The lookup is local; `list` reads the configured cluster. Async code uses
`await Pod.async_list(namespace="default")`. Direct class imports are also supported; the
lookup avoids depending on schema-derived module names.

Pin a Kubernetes model minor matching your target cluster. See the
[support and versioning policy](https://github.com/cloudcoil/cloudcoil/blob/main/VERSIONING.md)
for maintained versions and upgrade instructions.

Use the shared [resource guide](https://cloudcoil.github.io/cloudcoil/resources/)
for constructors, builders, writes and watches, and the
[controller guide](https://cloudcoil.github.io/cloudcoil/controllers/) for
reconciliation. Pydantic validates constructed models at runtime; generated
annotations provide field completion and static type checking.

### Maintain this integration

From the Cloudcoil repository root:

```sh
make gen-repo-kubernetes
make -C output/models-kubernetes lint test check-artifacts
```

Rendering generates the models before validation. The
[model release guide](https://cloudcoil.github.io/cloudcoil/model-releases/)
covers source updates, artifact checks and publishing.
