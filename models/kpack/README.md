> [!WARNING]  
> This repository is auto-generated from the [cloudcoil repository](https://github.com/cloudcoil/cloudcoil/tree/main/models/kpack). Please do not submit pull requests here. Instead, submit them to the main repository at https://github.com/cloudcoil/cloudcoil.

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

## 💡 Examples

### Using kpack Models

```python
from cloudcoil import apimachinery
import cloudcoil.models.kpack.v1alpha2 as kpack
import cloudcoil.models.kpack.core as core
import cloudcoil.models.kubernetes.core.v1 as k8score

# Create an Image resource
image = kpack.Image(
    metadata=apimachinery.ObjectMeta(name="my-app"),
    spec=kpack.ImageSpec(
        tag="registry.example.com/my-app",
        builder_=k8score.ObjectReference(
            name="my-builder",
            kind="ClusterBuilder"
        ),
        source=core.SourceConfig(
            git=core.Git(
                url="https://github.com/my-org/my-app.git",
                revision="main"
            )
        )
    )
).create()

# Create a Builder
builder = kpack.BuilderResource(
    metadata=apimachinery.ObjectMeta(name="my-builder"),
    spec=kpack.BuilderSpec(
        tag="registry.example.com/builder",
        stack=k8score.ObjectReference(
            name="base",
            kind="ClusterStack"
        ),
        store=k8score.ObjectReference(
            name="default",
            kind="ClusterStore"
        )
    )
).create()

# List Images
for img in kpack.Image.list():
    print(f"Found image: {img.metadata.name}")

# Update an Image
image.spec.source.git.revision = "v1.0.0"
image.save()

# Delete resources
kpack.Image.delete("my-app")
kpack.BuilderResource.delete("my-builder")
```

### Using the Fluent Builder API

```python
from cloudcoil.models.kpack.v1alpha2 import Image

# Create an Image using the fluent builder
image = (
    Image.builder()
    .metadata(lambda m: m
        .name("my-app")
        .namespace("default")
    )
    .spec(lambda s: s
        .tag("registry.example.com/my-app")
        .builder_(lambda b: b
            .name("my-builder")
            .kind("ClusterBuilder")
        )
        .source(lambda src: src
            .git(lambda g: g
                .url("https://github.com/my-org/my-app.git")
                .revision("main")
            )
        )
    )
    .build()
)
```

### Using the Context Manager Builder API

```python
from cloudcoil.models.kpack.v1alpha2 import Image, BuilderResource

# Create an image using context managers
with Image.new() as app_image:
    with app_image.metadata() as metadata:
        metadata.name("my-app")
        metadata.namespace("default")
    
    with app_image.spec() as spec:
        spec.tag("registry.example.com/my-app")
        
        with spec.builder_() as builder:
            builder.name("my-builder")
            builder.kind("ClusterBuilder")
        
        with spec.source() as source:
            with source.git() as git:
                git.url("https://github.com/my-org/my-app.git")
                git.revision("main")

final_image = app_image.build()

# Create a builder using context managers
with BuilderResource.new() as builder:
    with builder.metadata() as metadata:
        metadata.name("my-builder")
        metadata.namespace("default")
    
    with builder.spec() as spec:
        spec.tag("registry.example.com/builder")
        
        with spec.stack() as stack:
            stack.name("base")
            stack.kind("ClusterStack")
        
        with spec.store() as store:
            store.name("default")
            store.kind("ClusterStore")
        
        # Add buildpacks to the builder
        with spec.buildpacks() as buildpacks:
            with buildpacks.add() as pack:
                pack.id("paketo-buildpacks/java")
                pack.version("3.0.0")

final_builder = builder.build()
```

The context manager builder provides:
- 🎭 Clear visual nesting of resource structure
- 🔒 Automatic resource cleanup
- 🎯 Familiar Python context manager pattern
- ✨ Same great IDE support as the fluent builder

## 📚 Documentation

For complete documentation, visit [cloudcoil.github.io/cloudcoil](https://cloudcoil.github.io/cloudcoil)

## 📜 License

Apache License, Version 2.0 - see [LICENSE](LICENSE)
