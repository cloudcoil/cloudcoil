## kpack models

Models are generated from pinned upstream schemas. Configuration, schema inputs
and README sources are maintained in
[cloudcoil/cloudcoil](https://github.com/cloudcoil/cloudcoil/tree/main/models/kpack);
the generated package is in
[cloudcoil/models-kpack](https://github.com/cloudcoil/models-kpack). Edit the
source integration in Cloudcoil because generated repository edits are replaced
on template refresh.

### Use a typed resource

After installing `cloudcoil.models.kpack`, use the package's typed lookup to
select an exact Kubernetes kind and API version:

```python
from cloudcoil.models.kpack import get_model

Image = get_model("Image", api_version="kpack.io/v1alpha2")

for resource in Image.list(namespace="default"):
    print(resource.name)
```

The lookup is local; `list` reads the configured cluster. Async code uses
`await Image.async_list(namespace="default")`. Direct class imports are also supported; the
lookup avoids depending on schema-derived module names.

Install the upstream kpack CRDs and operator separately before making API calls.
The model package supplies Python types and client methods, not the operator.

Use the shared [resource guide](https://cloudcoil.github.io/cloudcoil/resources/)
for constructors, builders, writes and watches, and the
[controller guide](https://cloudcoil.github.io/cloudcoil/controllers/) for
reconciliation. Pydantic validates constructed models at runtime; generated
annotations provide field completion and static type checking.

### Maintain this integration

From the Cloudcoil repository root:

```sh
make gen-repo-kpack
make -C output/models-kpack lint test check-artifacts
```

Rendering generates the models before validation. The
[model release guide](https://cloudcoil.github.io/cloudcoil/model-releases/)
covers source updates, artifact checks and publishing.

`schemas/lifecycle.json` supplies lifecycle definitions omitted from the pinned
upstream OpenAPI document. Keep that supplement aligned with the upstream Go types
when updating the integration.
