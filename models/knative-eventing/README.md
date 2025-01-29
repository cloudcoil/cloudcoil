> [!WARNING]  
> This repository is auto-generated from the [cloudcoil repository](https://github.com/cloudcoil/cloudcoil/tree/main/models/knative-eventing). Please do not submit pull requests here. Instead, submit them to the main repository at https://github.com/cloudcoil/cloudcoil.

## 🔧 Installation

> [!NOTE]
> For versioning information and compatibility, see the [Versioning Guide](https://github.com/cloudcoil/cloudcoil/blob/main/VERSIONING.md).

Using [uv](https://github.com/astral-sh/uv) (recommended):

```bash
# Install with Knative Eventing support
uv add cloudcoil.models.knative-eventing
```

Using pip:

```bash
pip install cloudcoil.models.knative-eventing
```

## 💡 Examples

### Using Knative Eventing Models

```python
from cloudcoil import apimachinery
import cloudcoil.models.knative_eventing.eventing.v1 as eventing

# Create a Broker
broker = eventing.Broker(
    metadata=apimachinery.ObjectMeta(name="default"),
    spec=eventing.BrokerSpec(
        config=eventing.Config(
            kind="ConfigMap",
            name="kafka-broker-config"
        )
    )
).create()

# Create a Trigger
trigger = eventing.Trigger(
    metadata=apimachinery.ObjectMeta(name="my-service-trigger"),
    spec=eventing.TriggerSpec(
        broker="default",
        filter=eventing.Filter(
            attributes={
                "type": "dev.knative.samples.helloworld"
            }
        ),
        subscriber=eventing.Subscriber(
            ref=eventing.Ref(
                api_version="serving.knative.dev/v1",
                kind="Service",
                name="event-display"
            )
        )
    )
).create()

# List Brokers
for b in eventing.Broker.list():
    print(f"Found Broker: {b.metadata.name}")
```

### Using the Fluent Builder API

Cloudcoil provides a powerful fluent builder API for Knative Eventing resources:

```python
from cloudcoil.models.knative_eventing.eventing.v1 import Broker, Trigger

# Create a Broker using the builder
broker = (
    Broker.builder()
    .metadata(lambda m: m
        .name("default")
    )
    .spec(lambda s: s
        .config(lambda c: c
            .kind("ConfigMap")
            .name("kafka-broker-config")
        )
    )
    .build()
)

# Create a Trigger using the builder
trigger = (
    Trigger.builder()
    .metadata(lambda m: m
        .name("my-service-trigger")
    )
    .spec(lambda s: s
        .broker("default")
        .filter(lambda f: f
            .attributes({
                "type": "dev.knative.samples.helloworld"
            })
        )
        .subscriber(lambda sub: sub
            .ref(lambda r: r
                .api_version("serving.knative.dev/v1")
                .kind("Service")
                .name("event-display")
            )
        )
    )
    .build()
)
```

### Using the Context Manager Builder API

For complex eventing configurations, you can use the context manager-based builder:

```python
from cloudcoil.models.knative_eventing.eventing.v1 import Trigger

# Create a Trigger using context managers
with Trigger.new() as trigger:
    with trigger.metadata() as metadata:
        metadata.name("my-service-trigger")
    
    with trigger.spec() as spec:
        spec.broker("default")
        with spec.filter() as filter_:
            filter_.attributes({
                "type": "dev.knative.samples.helloworld"
            })
        with spec.subscriber() as subscriber:
            with subscriber.ref() as ref:
                ref.api_version("serving.knative.dev/v1")
                ref.kind("Service")
                ref.name("event-display")

final_trigger = trigger.build()
```

### Mixing Builder Styles

You can mix different builder styles based on your needs:

```python
from cloudcoil.models.knative_eventing.eventing.v1 import Trigger
from cloudcoil import apimachinery

# Create a Trigger using mixed styles
with Trigger.new() as trigger:
    # Direct object initialization
    trigger.metadata(apimachinery.ObjectMeta(
        name="my-service-trigger"
    ))
    
    with trigger.spec() as spec:    
        # Fluent style for spec
        spec.broken("default")
        spec.filter(lambda f: f
            .attributes({
                "type": "dev.knative.samples.helloworld"
            })
        )
        spec.subscriber(lambda sub: sub
            .ref(lambda r: r
                .api_version("serving.knative.dev/v1")
                .kind("Service")
                .name("event-display")
            )
        )

final_trigger = trigger.build()
```

## 📚 Documentation

For complete documentation, visit [cloudcoil.github.io/cloudcoil](https://cloudcoil.github.io/cloudcoil)

## 📜 License

Apache License, Version 2.0 - see [LICENSE](LICENSE)
