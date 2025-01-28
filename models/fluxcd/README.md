> [!WARNING]  
> This repository is auto-generated from the [cloudcoil repository](https://github.com/cloudcoil/cloudcoil/tree/main/models/fluxcd). Please do not submit pull requests here. Instead, submit them to the main repository at https://github.com/cloudcoil/cloudcoil.

## 🔧 Installation

> [!NOTE]
> For versioning information and compatibility, see the [Versioning Guide](https://github.com/cloudcoil/cloudcoil/blob/main/VERSIONING.md).

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

### Using the Context Manager Builder API

For complex nested resources, Cloudcoil also provides a context manager-based builder pattern that can make the structure more clear:

```python
from cloudcoil.models.fluxcd.source.v1 import GitRepository
from cloudcoil.models.fluxcd.kustomize.v1 import Kustomization

# Create a GitRepository using context managers
with GitRepository.new() as repo:
    with repo.metadata() as metadata:
        metadata.name("my-app")
        metadata.namespace("default")
        metadata.labels({"env": "prod"})
    
    with repo.spec() as spec:
        spec.url("https://github.com/org/repo")
        spec.interval("1m")
        
        with spec.ref() as ref:
            ref.branch("main")

final_repo = repo.build()

# Create a Kustomization using context managers
with Kustomization.new() as kustomization:
    with kustomization.metadata() as metadata:
        metadata.name("my-app")
        metadata.namespace("default")
    
    with kustomization.spec() as spec:
        spec.path("./kustomize")
        spec.interval("5m")
        spec.prune(True)
        
        with spec.source_ref() as ref:
            ref.kind("GitRepository")
            ref.name("my-app")

final_kustomization = kustomization.build()
```

The context manager builder provides:
- 🎭 Clear visual nesting of resource structure
- 🔒 Automatic resource cleanup
- 🎯 Familiar Python context manager pattern
- ✨ Same great IDE support as the fluent builder

### Mixing Builder Styles

CloudCoil's intelligent builder system automatically detects which style you're using and provides appropriate IDE support:

```python
from cloudcoil.models.fluxcd.source.v1 import GitRepository
from cloudcoil import apimachinery

# Mixing styles lets you choose the best approach for each part
with GitRepository.new() as repo:
    # Direct object initialization with full type checking
    repo.metadata(apimachinery.ObjectMeta(
        name="my-app",
        namespace="default",
        labels={"env": "prod"}
    ))
    
    with repo.spec() as spec:
        # Simple fields directly
        spec.url("https://github.com/org/repo")
        spec.interval("1m")
        # Fluent style
        spec.ref(lambda r: r
            .branch("main")
            .tag("v1.0.0")
        )
        # Direct assignment
        spec.timeout = "1m"

final_repo = repo.build()
```

This flexibility allows you to:
- 🔀 Choose the most appropriate style for each part of your configuration
- 📖 Maximize readability for both simple and complex structures
- 🎨 Format your code according to your team's preferences
- 🧠 Get full IDE support with automatic style detection
- ✨ Enjoy rich autocomplete in all styles
- ⚡ Benefit from type checking across mixed styles
- 🎯 Receive immediate feedback on type errors
- 🔍 See documentation for all fields regardless of style

## 📚 Documentation

For complete documentation, visit [cloudcoil.github.io/cloudcoil](https://cloudcoil.github.io/cloudcoil)

## 📜 License

Apache License, Version 2.0 - see [LICENSE](LICENSE)