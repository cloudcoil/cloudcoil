> [!WARNING]  
> This repository is auto-generated from the [cloudcoil repository](https://github.com/cloudcoil/cloudcoil/tree/main/models/sealed-secrets). Please do not submit pull requests here. Instead, submit them to the main repository at https://github.com/cloudcoil/cloudcoil.

## 🔧 Installation

> [!NOTE]
> For versioning information and compatibility, see the [Versioning Guide](https://github.com/cloudcoil/cloudcoil/blob/main/VERSIONING.md).

Using [uv](https://github.com/astral-sh/uv) (recommended):

```bash
# Install with Sealed Secrets support
uv add cloudcoil.models.sealed-secrets
```

Using pip:

```bash
pip install cloudcoil.models.sealed-secrets
```

## 💡 Examples

### Using Sealed Secrets Models

```python
from cloudcoil import apimachinery
import cloudcoil.models.sealed_secrets.v1alpha1 as sealed_secrets

# Create a SealedSecret
sealed_secret = sealed_secrets.SealedSecret(
    metadata=apimachinery.ObjectMeta(name="mysecret"),
    spec=sealed_secrets.SealedSecretSpec(
        encrypted_data={
            "username": "AgBy8hCi8...",  # Your encrypted data here
            "password": "AgBy8hCi8..."   # Your encrypted data here
        }
    )
).create()

# List SealedSecrets
for secret in sealed_secrets.SealedSecret.list():
    print(f"Found SealedSecret: {secret.metadata.name}")
```

### Using the Fluent Builder API

Cloudcoil provides a powerful fluent builder API for Sealed Secrets resources:

```python
from cloudcoil.models.sealed_secrets.v1alpha1 import SealedSecret

# Create a SealedSecret using the fluent builder
sealed_secret = (
    SealedSecret.builder()
    .metadata(lambda metadata: metadata
        .name("mysecret")
        .namespace("default")
        .labels({"app": "myapp"})
    )
    .spec(lambda spec: spec
        .encrypted_data({
            "username": "AgBy8hCi8...",  # Your encrypted data here
            "password": "AgBy8hCi8..."   # Your encrypted data here
        })
        .template(lambda template: template
            .metadata(lambda t_metadata: t_metadata
                .labels({"app": "myapp"})
            )
            .type("Opaque")
        )
    )
    .build()
)
```

### Using the Context Manager Builder API

For complex sealed secret configurations, you can use the context manager-based builder:

```python
from cloudcoil.models.sealed_secrets.v1alpha1 import SealedSecret

# Create a SealedSecret using context managers
with SealedSecret.new() as secret:
    with secret.metadata() as metadata:
        metadata.name("mysecret")
        metadata.namespace("default")
    
    with secret.spec() as spec:
        spec.encrypted_data({
            "username": "AgBy8hCi8...",  # Your encrypted data here
            "password": "AgBy8hCi8..."   # Your encrypted data here
        })
        with spec.template() as template:
            template.type("Opaque")
            with template.metadata() as t_metadata:
                t_metadata.labels({"app": "myapp"})

final_secret = secret.build()
```

## 📚 Documentation

For complete documentation, visit [cloudcoil.github.io/cloudcoil](https://cloudcoil.github.io/cloudcoil)

## 📜 License

Apache License, Version 2.0 - see [LICENSE](LICENSE)
