> [!WARNING]  
> This repository is auto-generated from the [cloudcoil repository](https://github.com/cloudcoil/cloudcoil/tree/main/models/knative-serving). Please do not submit pull requests here. Instead, submit them to the main repository at https://github.com/cloudcoil/cloudcoil.

## 🔧 Installation

> [!NOTE]
> For versioning information and compatibility, see the [Versioning Guide](https://github.com/cloudcoil/cloudcoil/blob/main/VERSIONING.md).

Using [uv](https://github.com/astral-sh/uv) (recommended):

```bash
# Install with Knative Serving support
uv add cloudcoil.models.knative-serving
```

Using pip:

```bash
pip install cloudcoil.models.knative-serving
```

## 💡 Examples

### Using Knative Serving Models

```python
from cloudcoil import apimachinery
import cloudcoil.models.knative_serving.serving.v1 as serving

# Create a Service
service = serving.Service(
    metadata=apimachinery.ObjectMeta(name="hello"),
    spec=serving.ServiceSpec(
        template=serving.Template(
            spec=serving.Spec(
                containers=[
                    serving.Container(
                        image="gcr.io/knative-samples/helloworld-go",
                        ports=[serving.Port(container_port=8080)],
                        env=[
                            serving.Env(name="TARGET", value="World")
                        ]
                    )
                ]
            )
        )
    )
).create()

# List Services
for svc in serving.Service.list():
    print(f"Found Service: {svc.metadata.name}")
```

### Using the Fluent Builder API

Cloudcoil provides a powerful fluent builder API for Knative Serving resources:

```python
from cloudcoil.models.knative_serving.serving.v1 import Service

# Create a Service using the fluent builder
service = (
    Service.builder()
    # Metadata configuration
    .metadata(lambda metadata: metadata
        .name("hello")
        .namespace("default")
        .labels({"app": "hello"})
    )
    # Complex nested structures with proper collection handling
    .spec(lambda spec: spec
        .template(lambda template: template
            .metadata(lambda t_metadata: t_metadata
                .labels({"app": "hello"})
            )
            .spec(lambda revision_spec: revision_spec
                # Container list with nested collection handling
                .containers(lambda containers: containers.add(
                    lambda container: container
                    .name("hello")
                    .image("gcr.io/knative-samples/helloworld-go")
                    # Collections use add() helper for better type support
                    .ports(lambda ports: ports
                        .add(lambda p: p.container_port(8080))
                    )
                    .env(lambda env: env
                        .add(lambda e: e.name("TARGET").value("World"))
                        .add(lambda e: e.name("PORT").value("8080"))
                    )
                    # Resource requirements can be chained
                    .resources(lambda r: r
                        .requests({"cpu": "100m", "memory": "128Mi"})
                        .limits({"cpu": "200m", "memory": "256Mi"})
                    )
                ))
            )
        )
    )
    .build()
)
```

### Using the Context Manager Builder API

For complex serving configurations, you can use the context manager-based builder:

```python
from cloudcoil.models.knative_serving.serving.v1 import Service

# Create a Service using context managers
with Service.new() as service:
    with service.metadata() as metadata:
        metadata.name("hello")
        metadata.namespace("default")
    
    with service.spec() as spec:
        with spec.template() as template:
            with template.spec() as revision_spec:
                with revision_spec.containers() as container_list:
                    with container_list.add() as container:
                        container.name("hello")
                        container.image("gcr.io/knative-samples/helloworld-go")
                        with container.ports() as port_list:
                            with port_list.add() as port:
                                port.container_port(8080)
                        with container.env() as env_list:
                            with env_list.add() as env:
                                env.name("TARGET")
                                env.value("World")

final_service = service.build()
```

### Mixing Builder Styles

You can mix different builder styles based on your needs:

```python
from cloudcoil.models.knative_serving.serving.v1 import Service
from cloudcoil import apimachinery

# Create a Service using mixed styles
with Service.new() as service:
    # Direct object initialization
    service.metadata(apimachinery.ObjectMeta(
        name="hello"
    ))
    
    # Fluent style for spec
    service.spec(lambda s: s
        .template(lambda t: t
            .spec(lambda rs: rs
                .containers(lambda containers: containers.add(
                    lambda container: container
                    .name("hello")
                    .image("gcr.io/knative-samples/helloworld-go")
                    # Collections use add() helper for better type support
                    .ports(lambda ports: ports
                        .add(lambda p: p.container_port(8080))
                    )
                ))
            )
        )
    )

final_service = service.build()
```

## 📚 Documentation

For complete documentation, visit [cloudcoil.github.io/cloudcoil](https://cloudcoil.github.io/cloudcoil)

## 📜 License

Apache License, Version 2.0 - see [LICENSE](LICENSE)
