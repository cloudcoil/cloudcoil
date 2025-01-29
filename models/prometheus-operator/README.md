> [!WARNING]  
> This repository is auto-generated from the [cloudcoil repository](https://github.com/cloudcoil/cloudcoil/tree/main/models/prometheus-operator). Please do not submit pull requests here. Instead, submit them to the main repository at https://github.com/cloudcoil/cloudcoil.


## 🔧 Installation

> [!NOTE]
> For versioning information and compatibility, see the [Versioning Guide](https://github.com/cloudcoil/cloudcoil/blob/main/VERSIONING.md).

Using [uv](https://github.com/astral-sh/uv) (recommended):

```bash
# Install with Prometheus Operator support
uv add cloudcoil.models.prometheus_operator
```

Using pip:

```bash
pip install cloudcoil.models.prometheus_operator
```

## 💡 Examples

### Using Prometheus Operator Models

```python
from cloudcoil import apimachinery
import cloudcoil.models.prometheus_operator.v1 as prometheus_operator

# Create a Prometheus instance
prometheus = prometheus_operator.Prometheus(
    metadata=apimachinery.ObjectMeta(name="main"),
    spec=prometheus_operator.PrometheusSpec(
        external_url="http://monitoring.my.systems/prometheus",
        resources=apimachinery.ResourceRequirements(
            requests={
                "memory": "400Mi"
            }
        )
    )
).create()

# Create an Alertmanager instance
alert_manager = prometheus_operator.Alertmanager(
    metadata=apimachinery.ObjectMeta(name="main"),
    spec=prometheus_operator.AlertmanagerSpec(
        replicas=3,
        external_url="http://monitoring.my.systems/alertmanager",
        resources=apimachinery.ResourceRequirements(
            requests={
                "memory": "400Mi"
            }
        )
    )
).create()

# List Prometheus instances
for prom in prometheus_operator.Prometheus.list():
    print(f"Found Prometheus: {prom.metadata.name}")
```

### Using the Fluent Builder API

Cloudcoil provides a powerful fluent builder API for Prometheus Operator resources:

```python
from cloudcoil.models.prometheus_operator.v1 import Prometheus, Alertmanager

# Create a Prometheus using the builder
prometheus = (
    Prometheus.builder()
    .metadata(lambda m: m
        .name("main")
    )
    .spec(lambda s: s
        .external_url("http://monitoring.my.systems/prometheus")
        .resources(lambda r: r
            .requests({
                "memory": "400Mi"
            })
        )
    )
    .build()
)

# Create an Alertmanager using the builder
alert_manager = (
    Alertmanager.builder()
    .metadata(lambda m: m
        .name("main")
    )
    .spec(lambda s: s
        .replicas(3)
        .external_url("http://monitoring.my.systems/alertmanager")
        .resources(lambda r: r
            .requests({
                "memory": "400Mi"
            })
        )
    )
    .build()
)
```

### Using the Context Manager Builder API

For complex monitoring configurations, you can use the context manager-based builder:

```python
from cloudcoil.models.prometheus_operator.v1 import Prometheus

# Create a Prometheus instance using context managers
with Prometheus.new() as prometheus:
    with prometheus.metadata() as metadata:
        metadata.name("main")
    
    with prometheus.spec() as spec:
        spec.external_url("http://monitoring.my.systems/prometheus")
        with spec.resources() as resources:
            resources.requests({
                "memory": "400Mi"
            })

final_prometheus = prometheus.build()
```

### Mixing Builder Styles

You can mix different builder styles based on your needs:

```python
from cloudcoil.models.prometheus_operator.v1 import Alertmanager
from cloudcoil import apimachinery

# Create an Alertmanager using mixed styles
with Alertmanager.new() as alert_manager:
    # Direct object initialization
    alert_manager.metadata(apimachinery.ObjectMeta(
        name="main"
    ))
    
    # Fluent style for spec
    alert_manager.spec(lambda s: s
        .replicas(3)
        .external_url("http://monitoring.my.systems/alertmanager")
        .resources(lambda r: r
            .requests({
                "memory": "400Mi"
            })
        )
    )

final_alert_manager = alert_manager.build()
```

## 📚 Documentation

For complete documentation, visit [cloudcoil.github.io/cloudcoil](https://cloudcoil.github.io/cloudcoil)

## 📜 License

Apache License, Version 2.0 - see [LICENSE](LICENSE)
