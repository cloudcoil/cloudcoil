> [!WARNING]  
> This repository is auto-generated from the [cloudcoil repository](https://github.com/cloudcoil/cloudcoil/tree/main/models/velero). Please do not submit pull requests here. Instead, submit them to the main repository at https://github.com/cloudcoil/cloudcoil.

## 🔧 Installation

> [!NOTE]
> For versioning information and compatibility, see the [Versioning Guide](https://github.com/cloudcoil/cloudcoil/blob/main/VERSIONING.md).

Using [uv](https://github.com/astral-sh/uv) (recommended):

```bash
# Install with Velero support
uv add cloudcoil.models.velero
```

Using pip:

```bash
pip install cloudcoil.models.velero
```

## 💡 Examples

### Using Velero Models

```python
from cloudcoil import apimachinery
import cloudcoil.models.velero.v1 as velero

# Create a Backup
backup = velero.Backup(
    metadata=apimachinery.ObjectMeta(name="mybackup"),
    spec=velero.BackupSpec(
        included_namespaces=["default"],
        storage_location="default"
    )
).create()

# List Backups
for b in velero.Backup.list():
    print(f"Found Backup: {b.metadata.name}")
```

### Using the Fluent Builder API

Cloudcoil provides a powerful fluent builder API for Velero resources:

```python
from cloudcoil.models.velero.v1 import Backup

# Create a Backup using the fluent builder
backup = (
    Backup.builder()
    .metadata(lambda metadata: metadata
        .name("mybackup")
        .namespace("velero")
        .labels({"app": "myapp"})
    )
    .spec(lambda spec: spec
        .included_namespaces(["default", "kube-system"])
        .storage_location("default")
        .ttl("72h")
        .hooks(lambda hooks: hooks
            .resources(lambda resources: resources.add({
                "name": "my-hook",
                "included_namespaces": ["default"]
            }))
        )
    )
    .build()
)
```

### Using the Context Manager Builder API

For complex backup configurations, you can use the context manager-based builder:

```python
from cloudcoil.models.velero.v1 import Backup

# Create a Backup using context managers
with Backup.new() as backup:
    with backup.metadata() as metadata:
        metadata.name("mybackup")
        metadata.namespace("velero")

    with backup.spec() as spec:
        spec.included_namespaces(["default", "kube-system"])
        spec.storage_location("default")
        spec.ttl("72h")
        with spec.hooks() as hooks:
            with hooks.resources() as resources:
                with resources.add() as resource:
                    resource.name("my-hook").included_namespaces(["default"])
                with resources.add() as resource:
                    resource.name("another-hook").included_namespaces(["default"])
final_backup = backup.build()
```

## 📚 Documentation

For complete documentation, visit [cloudcoil.github.io/cloudcoil](https://cloudcoil.github.io/cloudcoil)

## 📜 License

Apache License, Version 2.0 - see [LICENSE](LICENSE)
