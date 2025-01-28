> [!WARNING]  
> This repository is auto-generated from the [cloudcoil repository](https://github.com/cloudcoil/cloudcoil/tree/main/models/kubernetes). Please do not submit pull requests here. Instead, submit them to the main repository at https://github.com/cloudcoil/cloudcoil.


## 🔧 Installation

> [!NOTE]
> For versioning information and compatibility, see the [Versioning Guide](https://github.com/cloudcoil/cloudcoil/blob/main/VERSIONING.md).

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

# Create a Deployment using the fluent builder
# The fluent style is great for one-liners and simple configurations
nginx_deployment = (
    Deployment.builder()
    # Metadata can be configured in a single chain for simple objects
    .metadata(lambda metadata: metadata
        .name("nginx")
        .namespace("default")
    )
    # Complex nested structures can be built using nested lambda functions
    .spec(lambda deployment_spec: deployment_spec
        .replicas(3)
        # Each level of nesting gets its own lambda for clarity
        .selector(lambda label_selector: label_selector
            .match_labels({"app": "nginx"})
        )
        .template(lambda pod_template: pod_template
            .metadata(lambda pod_metadata: pod_metadata
                .labels({"app": "nginx"})
            )
            .spec(lambda pod_spec: pod_spec
                # Lists can be built using array literals with lambda items
                .containers([
                    lambda container: container
                    .name("nginx")
                    .image("nginx:latest")
                    # Nested collections can use the add() helper
                    .ports(lambda port_list: port_list.add(
                        lambda port: port.container_port(80)
                    ))
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

### Using the Context Manager Builder API

For complex nested resources, Cloudcoil also provides a context manager-based builder pattern that can make the structure more clear:

```python
from cloudcoil.models.kubernetes.apps.v1 import Deployment
from cloudcoil.models.kubernetes.core.v1 import Service

# Create a deployment using context managers
# Context managers are ideal for deeply nested structures
with Deployment.new() as nginx_deployment:
    # Each context creates a clear visual scope
    with nginx_deployment.metadata() as deployment_metadata:
        deployment_metadata.name("nginx")
        deployment_metadata.namespace("default")
    
    with nginx_deployment.spec() as deployment_spec:
        # Simple fields can be set directly
        deployment_spec.replicas(3)
        
        # Each nested object gets its own context
        with deployment_spec.selector() as label_selector:
            label_selector.match_labels({"app": "nginx"})
        
        with deployment_spec.template() as pod_template:
            with pod_template.metadata() as pod_metadata:
                pod_metadata.labels({"app": "nginx"})
            
            with pod_template.spec() as pod_spec:
                # Collections use a parent context for the list
                with pod_spec.containers() as container_list:
                    # And child contexts for each item
                    with container_list.add() as nginx_container:
                        nginx_container.name("nginx")
                        nginx_container.image("nginx:latest")
                        # Ports can be added one by one
                        with nginx_container.add_port() as container_port:
                            container_port.container_port(80)

final_deployment = nginx_deployment.build()

# Create a service using context managers
with Service.new() as nginx_service:
    # Context managers make the structure very clear
    with nginx_service.metadata() as service_metadata:
        service_metadata.name("nginx")
        service_metadata.namespace("default")
    
    with nginx_service.spec() as service_spec:
        # Simple fields can still be set directly
        service_spec.selector({"app": "nginx"})
        # Port configuration is more readable with contexts
        with service_spec.add_port() as service_port:
            service_port.port(80)
            service_port.target_port(80)

final_service = nginx_service.build()
```

The context manager builder provides:
- 🎭 Clear visual nesting of resource structure
- 🔒 Automatic resource cleanup
- 🎯 Familiar Python context manager pattern
- ✨ Same great IDE support as the fluent builder

### Mixing Builder Styles

CloudCoil's intelligent builder system automatically detects which style you're using and provides appropriate IDE support:

```python
from cloudcoil.models.kubernetes.apps.v1 import Deployment
from cloudcoil import apimachinery

# Mixing styles lets you choose the best approach for each part
# The IDE automatically adapts to your chosen style at each level
with Deployment.new() as nginx_deployment:
    # Direct object initialization with full type checking
    nginx_deployment.metadata(apimachinery.ObjectMeta(
        name="nginx",
        namespace="default",
        labels={"app": "nginx"}
    ))
    
    with nginx_deployment.spec() as deployment_spec:
        # IDE shows all available fields with types
        deployment_spec.replicas(3)
        # Fluent style with rich autocomplete
        deployment_spec.selector(lambda sel: sel.match_labels({"app": "nginx"}))
        
        # Context manager style with full type hints
        with deployment_spec.template() as pod_template:
            # Mix and match freely - IDE adjusts automatically
            pod_template.metadata(apimachinery.ObjectMeta(labels={"app": "nginx"}))
            with pod_template.spec() as pod_spec:
                with pod_spec.containers() as container_list:
                    with container_list.add() as nginx_container:
                        # Complete IDE support regardless of style
                        nginx_container.name("nginx")
                        nginx_container.image("nginx:latest")
                        # Switch styles any time
                        nginx_container.ports(lambda ports: ports
                            .add(lambda p: p.container_port(80))
                            .add(lambda p: p.container_port(443))
                        )

final_deployment = nginx_deployment.build()
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
