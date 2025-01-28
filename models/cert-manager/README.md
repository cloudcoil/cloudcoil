> [!WARNING]  
> This repository is auto-generated from the [cloudcoil repository](https://github.com/cloudcoil/cloudcoil/tree/main/models/cert-manager). Please do not submit pull requests here. Instead, submit them to the main repository at https://github.com/cloudcoil/cloudcoil.

## 🔧 Installation

> [!NOTE]
> For versioning information and compatibility, see the [Versioning Guide](https://github.com/cloudcoil/cloudcoil/blob/main/VERSIONING.md).

Using [uv](https://github.com/astral-sh/uv) (recommended):

```bash
# Install with cert-manager support
uv add cloudcoil.models.cert_manager
```

Using pip:

```bash
pip install cloudcoil.models.cert_manager
```

## 💡 Examples

### Using cert-manager Models

```python
from cloudcoil import apimachinery
import cloudcoil.models.cert_manager.v1 as cm

# Create a Certificate
certificate = cm.Certificate(
    metadata=apimachinery.ObjectMeta(name="example-cert", namespace="default"),
    spec=cm.CertificateSpec(
        secret_name="example-cert-tls",
        issuer_ref=cm.IssuerRef(name="example-issuer"),
        dns_names=["example.com"]
    )
).create()

# List Certificates
for cert in cm.Certificate.list(namespace="default"):
    print(f"Found certificate: {cert.metadata.name}")

# Update a Certificate
certificate.spec.dns_names.append("www.example.com")
certificate.save()

# Delete a Certificate
cm.Certificate.delete("example-cert", namespace="default")
```

### Using the Fluent Builder API

Cloudcoil provides a powerful fluent builder API for cert-manager resources with full IDE support and rich autocomplete capabilities:

```python
from cloudcoil.models.cert_manager.v1 import Certificate, ClusterIssuer

# Create a Certificate using the fluent builder
# The fluent style is great for one-liners and simple configurations
certificate = (
    Certificate.builder()
    .metadata(lambda metadata: metadata
        .name("example-cert")
        .namespace("default")
        .labels({"env": "prod"})
    )
    .spec(lambda cert_spec: cert_spec
        .secret_name("example-cert-tls")
        .issuer_ref(lambda issuer: issuer
            .name("example-issuer")
            .kind("ClusterIssuer")
        )
        .dns_names(["example.com", "www.example.com"])
        .subject(lambda subject: subject
            .organizations(["Example Corp"])
        )
    )
    .build()
)

# Create a ClusterIssuer using the builder
cluster_issuer = (
    ClusterIssuer.builder()
    .metadata(lambda m: m.name("letsencrypt-prod"))
    .spec(
        lambda s: s.acme(
            lambda acme: acme.email("admin@example.com")
            .server("https://acme-v02.api.letsencrypt.org/directory")
            .private_key_secret_ref(lambda ref: ref.name("letsencrypt-account-key"))
            .solvers(
                lambda solvers: solvers.add(
                    lambda solver: solver.http01(
                        lambda http: http.ingress(lambda ing: ing.class_("nginx"))
                    )
                )
            )
        )
    )
    .build()
)
```

### Using the Context Manager Builder API

For complex nested resources, Cloudcoil also provides a context manager-based builder pattern that can make the structure more clear:

```python
from cloudcoil.models.cert_manager.v1 import Certificate, ClusterIssuer

# Create a certificate using context managers
with Certificate.new() as cert:
    with cert.metadata() as metadata:
        metadata.name("example-cert")
        metadata.namespace("default")
        metadata.labels({"env": "prod"})
    
    with cert.spec() as spec:
        spec.secret_name("example-cert-tls")
        
        with spec.issuer_ref() as issuer_ref:
            issuer_ref.name("example-issuer")
            issuer_ref.kind("ClusterIssuer")
        
        spec.dns_names(["example.com", "www.example.com"])
        
        with spec.subject() as subject:
            subject.organizations(["Example Corp"])

final_cert = cert.build()

# Create a ClusterIssuer using context managers
with ClusterIssuer.new() as issuer:
    with issuer.metadata() as metadata:
        metadata.name("letsencrypt-prod")
    
    with issuer.spec() as spec:
        with spec.acme() as acme:
            acme.email("admin@example.com")
            acme.server("https://acme-v02.api.letsencrypt.org/directory")
            
            with acme.private_key_secret_ref() as key_ref:
                key_ref.name("letsencrypt-account-key")
            
            with acme.solvers() as solvers:
                with solvers.add() as solver:
                    with solver.http01() as http:
                        with http.ingress() as ingress:
                            ingress.class_("nginx")

final_issuer = issuer.build()
```

The context manager builder provides:
- 🎭 Clear visual nesting of resource structure
- 🔒 Automatic resource cleanup
- 🎯 Familiar Python context manager pattern
- ✨ Same great IDE support as the fluent builder

### Mixing Builder Styles

CloudCoil's intelligent builder system automatically detects which style you're using and provides appropriate IDE support:

```python
from cloudcoil.models.cert_manager.v1 import Certificate
from cloudcoil import apimachinery

# Mixing styles lets you choose the best approach for each part
with Certificate.new() as cert:
    # Direct object initialization with full type checking
    cert.metadata(apimachinery.ObjectMeta(
        name="example-cert",
        namespace="default",
        labels={"env": "prod"}
    ))
    
    with cert.spec() as spec:
        # Simple fields directly
        spec.secret_name("example-cert-tls")
        # Fluent style
        spec.issuer_ref(lambda ref: ref
            .name("example-issuer")
            .kind("ClusterIssuer")
        )
        # Direct assignment
        spec.dns_names(["example.com", "www.example.com"])
        # Context manager style
        with spec.subject() as subject:
            subject.organizations(["Example Corp"])

final_cert = cert.build()
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
