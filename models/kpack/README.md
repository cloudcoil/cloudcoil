> [!WARNING]  
> Models are generated from upstream 0.18.0 schemas with Cloudcoil 0.7. Run `make gen-models` to regenerate them.

## 🔧 Installation

> [!NOTE]
> For versioning information and compatibility, see the [Versioning Guide](https://github.com/cloudcoil/cloudcoil/blob/main/VERSIONING.md).

Using [uv](https://github.com/astral-sh/uv) (recommended):

```bash
# Install with kpack support
uv add cloudcoil.models.kpack
```

Using pip:

```bash
pip install cloudcoil.models.kpack
```

## Usage

Cloudcoil 0.7 generates a typed lookup function so callers do not need to depend on schema-derived module names:

```python
from cloudcoil.models.kpack import get_model

Image = get_model("Image", api_version="kpack.io/v1alpha2")
resource = Image.model_validate({
    "metadata": {"name": "example"},
    "spec": {'tag': 'example.com/app:latest', 'builder': {'name': 'builder', 'kind': 'ClusterBuilder'}, 'source': {'git': {'url': 'https://example.com/repo', 'revision': 'main'}}},
})
resource.create()
```

Generated resources support validation, fluent builders, and the Cloudcoil client API.

## Development

```sh
uv sync --dev
make gen-models
make lint test
uv build
```

Generation uses the `namespace` and `input` configuration in `pyproject.toml`, with automatic resource identity and field alias inference. Generated modules are built on release branches; pull requests regenerate and test them before publishing.

`schemas/lifecycle.json` supplies the lifecycle API definitions omitted from the upstream v0.18.0 OpenAPI document, matching [the upstream Go types](https://github.com/buildpacks-community/kpack/blob/v0.18.0/pkg/apis/build/v1alpha2/cluster_lifecycle_types.go). Other Kubernetes types are generated with this package, so a separate Kubernetes model dependency is unnecessary.
