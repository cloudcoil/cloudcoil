## 🔧 Installation

Using [uv](https://github.com/astral-sh/uv) (recommended):

```bash
# Install with Kubernetes support
uv add cloudcoil.models.kubernetes
```

Using pip:

```bash
pip install cloudcoil.models.kubernetes
```

## 💡 Examples

### Using Kubernetes Models

```python
from cloudcoil import apimachinery
import cloudcoil.models.kubernetes.core.v1 as k8score
import cloudcoil.models.kubernetes.apps.v1 as k8sapps

# Create a Deployment
deployment = k8sapps.Deployment(
    metadata=apimachinery.ObjectMeta(name="nginx"),
    spec=k8sapps.DeploymentSpec(
        replicas=3,
        selector=apimachinery.LabelSelector(
            match_labels={"app": "nginx"}
        ),
        template=k8score.PodTemplateSpec(
            metadata=apimachinery.ObjectMeta(
                labels={"app": "nginx"}
            ),
            spec=k8score.PodSpec(
                containers=[
                    k8score.Container(
                        name="nginx",
                        image="nginx:latest",
                        ports=[k8score.ContainerPort(container_port=80)]
                    )
                ]
            )
        )
    )
).create()

# Create a Service
service = k8score.Service(
    metadata=apimachinery.ObjectMeta(name="nginx"),
    spec=k8score.ServiceSpec(
        selector={"app": "nginx"},
        ports=[k8score.ServicePort(port=80, target_port=80)]
    )
).create()

# List Deployments
for deploy in k8sapps.Deployment.list():
    print(f"Found deployment: {deploy.metadata.name}")

# Update a Deployment
deployment.spec.replicas = 5
deployment.save()

# Delete resources
k8score.Service.delete("nginx")
k8sapps.Deployment.delete("nginx")
```

### Using the Fluent Builder API

Cloudcoil provides a powerful fluent builder API for Kubernetes resources with full IDE support and rich autocomplete capabilities:

```python
from cloudcoil.models.kubernetes.apps.v1 import Deployment
from cloudcoil.models.kubernetes.core.v1 import Service

# Create a Deployment using the builder
deployment = (
    Deployment.builder()
    .metadata(lambda m: m
        .name("nginx")
        .namespace("default")
    )
    .spec(lambda s: s
        .replicas(3)
        .selector(lambda sel: sel
            .match_labels({"app": "nginx"})
        )
        .template(lambda t: t
            .metadata(lambda m: m
                .labels({"app": "nginx"})
            )
            .spec(lambda ps: ps
                .containers([
                    lambda c: c
                    .name("nginx")
                    .image("nginx:latest")
                    .ports(lambda ports: ports.add(lambda p: p.container_port(80)))
                ])
            )
        )
    )
    .build()
)

# Create a Service using the builder
service = (
    Service.builder()
    .metadata(lambda m: m
        .name("nginx")
        .namespace("default")
    )
    .spec(lambda s: s
        .selector({"app": "nginx"})
        .ports(lambda ports: ports.add(lambda p: p.container_port(80)))
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
