## Crossplane models

Models are generated from pinned upstream schemas. Configuration, schema inputs
and README sources are maintained in
[cloudcoil/cloudcoil](https://github.com/cloudcoil/cloudcoil/tree/main/models/crossplane);
the generated package is in
[cloudcoil/models-crossplane](https://github.com/cloudcoil/models-crossplane). Edit the
source integration in Cloudcoil because generated repository edits are replaced
on template refresh.

### Use a typed resource

After installing `cloudcoil.models.crossplane`, use the package's typed lookup to
select an exact Kubernetes kind and API version:

```python
from cloudcoil.models.crossplane import get_model

Provider = get_model("Provider", api_version="pkg.crossplane.io/v1")

for resource in Provider.list():
    print(resource.name)
```

The lookup is local; `list` reads the configured cluster. Async code uses
`await Provider.async_list()`. Direct class imports are also supported; the
lookup avoids depending on schema-derived module names.

Install the upstream Crossplane CRDs and operator separately before making API calls.
The model package supplies Python types and client methods, not the operator.

Use the shared [resource guide](https://cloudcoil.github.io/cloudcoil/resources/)
for constructors, builders, writes and watches, and the
[controller guide](https://cloudcoil.github.io/cloudcoil/controllers/) for
reconciliation. Pydantic validates constructed models at runtime; generated
annotations provide field completion and static type checking.

### Maintain this integration

From the Cloudcoil repository root:

```sh
make gen-repo-crossplane
make -C output/models-crossplane lint test check-artifacts
```

Rendering generates the models before validation. The
[model release guide](https://cloudcoil.github.io/cloudcoil/model-releases/)
covers source updates, artifact checks and publishing.
