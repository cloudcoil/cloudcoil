> [!WARNING]  
> This repository is auto-generated from the [cloudcoil repository](https://github.com/cloudcoil/cloudcoil/tree/main/models/keda). Please do not submit pull requests here. Instead, submit them to the main repository at https://github.com/cloudcoil/cloudcoil.

## 🔧 Installation

> [!NOTE]
> For versioning information and compatibility, see the [Versioning Guide](https://github.com/cloudcoil/cloudcoil/blob/main/VERSIONING.md).

Using [uv](https://github.com/astral-sh/uv) (recommended):

```bash
# Install with KEDA support
uv add cloudcoil.models.keda
```

Using pip:

```bash
pip install cloudcoil.models.keda
```

## 💡 Examples

### Using KEDA Models

```python
from cloudcoil import apimachinery
import cloudcoil.models.keda.v1alpha1 as keda

# Create a ScaledObject
scaled_object = keda.ScaledObject(
    metadata=apimachinery.ObjectMeta(name="rabbitmq-scaler"),
    spec=keda.ScaledObjectSpec(
        scale_target_ref=keda.ScaleTargetRef(
            name="my-deployment",
            kind="Deployment",
            api_version="apps/v1"
        ),
        triggers=[
            keda.TriggerModel(
                type="rabbitmq",
                metadata={
                    "queue_name": "hello",
                    "host": "amqp://guest:guest@rabbitmq:5672"
                }
            )
        ],
        min_replica_count=1,
        max_replica_count=10
    )
).create()

# List ScaledObjects
for scaler in keda.ScaledObject.list():
    print(f"Found scaler: {scaler.metadata.name}")

# Update a ScaledObject
scaled_object.spec.max_replica_count = 20
scaled_object.save()

# Delete resources
keda.ScaledObject.delete("rabbitmq-scaler")
```

### Using the Fluent Builder API

```python
from cloudcoil.models.keda.v1alpha1 import ScaledObject

# Create a ScaledObject using the fluent builder
scaled_object = (
    ScaledObject.builder()
    .metadata(lambda metadata: metadata
        .name("prometheus-scaler")
        .namespace("default")
    )
    .spec(lambda spec: spec
        .scale_target_ref(lambda target: target
            .name("my-deployment")
            .kind("Deployment")
            .api_version("apps/v1")
        )
        .min_replica_count(1)
        .max_replica_count(10)
        .triggers(lambda triggers: triggers.add(
            lambda trigger: trigger.type("prometheus").metadata({
                "server_address": "http://prometheus.monitoring.svc",
                "metric_name": "http_requests_total",
                "threshold": "100"
            })
        ))
    )
    .build()
)
```

### Using the Context Manager Builder API

```python
from cloudcoil.models.keda.v1alpha1 import ScaledObject

# Create a ScaledObject using context managers
with ScaledObject.new() as cpu_scaler:
    with cpu_scaler.metadata() as metadata:
        metadata.name("cpu-scaler")
        metadata.namespace("default")
    
    with cpu_scaler.spec() as spec:
        with spec.scale_target_ref() as target:
            target.name("my-deployment")
            target.kind("Deployment")
            target.api_version("apps/v1")
        
        spec.min_replica_count(1)
        spec.max_replica_count(10)
        
        with spec.triggers() as trigger_list:
            with trigger_list.add() as trigger:
                trigger.type("cpu")
                trigger.metadata({
                    "type": "Utilization",
                    "value": "50"
                })

final_scaler = cpu_scaler.build()
```

## 📚 Documentation

For complete documentation, visit [cloudcoil.github.io/cloudcoil](https://cloudcoil.github.io/cloudcoil)

## 📜 License

Apache License, Version 2.0 - see [LICENSE](LICENSE)
