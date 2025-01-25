## 🔧 Installation

Using [uv](https://github.com/astral-sh/uv) (recommended):

```bash
# Install with FluxCD support
uv add cloudcoil.models.fluxcd
```

Using pip:

```bash
pip install cloudcoil.models.fluxcd
```

## 💡 Examples

### Using FluxCD Models

```python
from cloudcoil import apimachinery
import cloudcoil.models.fluxcd.source.v1 as fluxsource
import cloudcoil.models.fluxcd.kustomize.v1 as fluxkustomize

# Create a GitRepository
repo = fluxsource.GitRepository(
    metadata=apimachinery.ObjectMeta(name="my-app"),
    spec=fluxsource.GitRepositorySpec(
        url="https://github.com/org/repo",
        ref=fluxsource.Ref(
            branch="main"
        ),
        interval="1m"
    )
).create()

# Create a Kustomization
kustomization = fluxkustomize.Kustomization(
    metadata=apimachinery.ObjectMeta(name="my-app"),
    spec=fluxkustomize.KustomizationSpec(
        interval="5m",
        path="./kustomize",
        source_ref=fluxkustomize.SourceRef(
            kind="GitRepository",
            name="my-app"
        ),
        prune=True
    )
).create()

# List GitRepositories
for repo in fluxsource.GitRepository.list():
    print(f"Found repository: {repo.metadata.name}")

# Update a GitRepository
repo.spec.interval = "5m"
repo.save()

# Delete resources
fluxkustomize.Kustomization.delete("my-app")
fluxsource.GitRepository.delete("my-app")
```

### Using the Fluent Builder API

Cloudcoil provides a powerful fluent builder API with full IDE support and rich autocomplete capabilities. The builder pattern ensures type safety and provides intelligent code suggestions as you type:

```python
from cloudcoil.models.fluxcd.source.v1 import GitRepository
from cloudcoil.models.fluxcd.kustomize.v1 import Kustomization

# Create a GitRepository using the builder
# Every step provides rich autocomplete and type hints
repo = (
    GitRepository.builder()  # IDE shows all available builder methods
    .metadata(lambda m: m   # IDE shows all ObjectMeta fields
        .name("my-app")
        .namespace("default")
    )
    .spec(
        lambda s: s         # IDE shows all GitRepositorySpec fields
        .url("https://github.com/org/repo")
        .interval("1m")
        .ref(lambda r: r    # IDE shows all Ref fields
            .branch("main")
        )
    )
    .build()
)

# The builder validates your configuration at compile time
kustomization = (
    Kustomization.builder()
    .metadata(lambda m: m.name("my-app").namespace("default"))
    .spec(
        lambda s: s.path("./kustomize")
        .interval("5m")
        .source_ref(lambda r: r.kind("GitRepository").name("my-app"))
        .prune(True)
    )
    .build()
)
```

The fluent builder provides:
- ✨ Full IDE support with detailed type information
- 🔍 Rich autocomplete for all fields and nested objects
- ⚡ Compile-time validation of your configuration
- 🎯 Clear and chainable API that guides you through resource creation

## 📚 Documentation

For complete documentation, visit [cloudcoil.github.io/cloudcoil](https://cloudcoil.github.io/cloudcoil)

## 📜 License

Apache License, Version 2.0 - see [LICENSE](LICENSE)