> [!WARNING]  
> Models are generated from upstream 1.23.0 schemas with Cloudcoil 0.7. Run `make gen-models` to regenerate them.

## 🔧 Installation

> [!NOTE]
> For versioning information and compatibility, see the [Versioning Guide](https://github.com/cloudcoil/cloudcoil/blob/main/VERSIONING.md).

Using [uv](https://github.com/astral-sh/uv) (recommended):

```bash
# Install with Knative Eventing support
uv add cloudcoil.models.knative-eventing
```

Using pip:

```bash
pip install cloudcoil.models.knative-eventing
```

## Usage

Cloudcoil 0.7 generates a typed lookup function so callers do not need to depend on schema-derived module names:

```python
from cloudcoil.models.knative_eventing import get_model

Broker = get_model("Broker", api_version="eventing.knative.dev/v1")
resource = Broker.model_validate({
    "metadata": {"name": "example"},
    "spec": {},
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

The generator collapses titled scalar root models to keep Knative Eventing field types inside the generated package.
