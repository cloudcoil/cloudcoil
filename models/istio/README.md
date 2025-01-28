> [!WARNING]  
> This repository is auto-generated from the [cloudcoil repository](https://github.com/cloudcoil/cloudcoil/tree/main/models/istio). Please do not submit pull requests here. Instead, submit them to the main repository at https://github.com/cloudcoil/cloudcoil.

## 🔧 Installation

> [!NOTE]
> For versioning information and compatibility, see the [Versioning Guide](https://github.com/cloudcoil/cloudcoil/blob/main/VERSIONING.md).

Using [uv](https://github.com/astral-sh/uv) (recommended):

```bash
# Install with Istio support
uv add cloudcoil.models.istio
```

Using pip:

```bash
pip install cloudcoil.models.istio
```

## 💡 Examples

### Using Istio Models

```python

from cloudcoil import apimachinery
from cloudcoil.models.istio import networking

# Create a Gateway
gateway = networking.v1.Gateway(
    metadata=apimachinery.ObjectMeta(name="main-gateway"),
    spec=networking.v1.GatewaySpec(
        selector={"istio": "ingressgateway"},
        servers=[networking.v1.Server(
            port=networking.v1.PortModel(
                number=80,
                name="http",
                protocol="HTTP"
            ),
            hosts=["*.example.com"]
        )]
    )
).create()

# Create a VirtualService
virtual_service = networking.v1.VirtualService(
    metadata=apimachinery.ObjectMeta(name="website"),
    spec=networking.v1.VirtualServiceSpec(
        hosts=["website.example.com"],
        gateways=["main-gateway"],
        http=[networking.v1.HttpModel(
            route=[networking.v1.Route(
                destination=networking.v1.Destination(
                    host="website-svc",
                    port=networking.v1.Port(number=8080)
                )
            )]
        )]
    )
).create()

# List Virtual Services
for vs in networking.v1.VirtualService.list():
    print(f"Found VirtualService: {vs.metadata.name}")
```

### Using the Fluent Builder API

```python
from cloudcoil.models.istio import networking

# Create a Gateway using the fluent builder
gateway = (
    networking.v1.Gateway.builder()
    .metadata(lambda metadata: metadata
        .name("main-gateway")
        .namespace("default")
    )
    .spec(lambda gateway_spec: gateway_spec
        .selector({"istio": "ingressgateway"})
        .servers(lambda servers: servers.add(
            lambda server: server
            .port(lambda port: port
                .number(80)
                .name("http")
                .protocol("HTTP")
            )
            .hosts(["*.example.com"])
        ))
    )
    .build()
)
```

### Using the Context Manager Builder API

```python
from cloudcoil.models.istio import networking

# Create a Gateway using context managers
with networking.v1.Gateway.new() as gateway:
    with gateway.metadata() as metadata:
        metadata.name("main-gateway")
        metadata.namespace("default")
    
    with gateway.spec() as spec:
        spec.selector({"istio": "ingressgateway"})
        
        with spec.servers() as server_list:
            with server_list.add() as server:
                with server.port() as port:
                    port.number(80)
                    port.name("http")
                    port.protocol("HTTP")
                server.hosts(["*.example.com"])

# Create a VirtualService using context managers
with networking.v1.VirtualService.new() as vs:
    with vs.metadata() as metadata:
        metadata.name("website")
        metadata.namespace("default")
    
    with vs.spec() as vs_spec:
        vs_spec.hosts(["website.example.com"])
        vs_spec.gateways(["main-gateway"])
        
        with vs_spec.http() as http_list:
            with http_list.add() as route:
                with route.route() as route_list:
                    with route_list.add() as weight:
                        with weight.destination() as dest:
                            dest.host("website-svc")
                            with dest.port() as dest_port:
                                dest_port.number(8080)

final_vs = vs.build()
```

### Mixing Builder Styles

```python
from cloudcoil.models.istio import networking
from cloudcoil import apimachinery

# Create a Gateway mixing different builder styles
with networking.v1.Gateway.new() as gateway:
    # Direct object initialization
    gateway.metadata(apimachinery.ObjectMeta(
        name="main-gateway",
        namespace="default"
    ))
    
    with gateway.spec() as spec:
        # Simple field assignment
        spec.selector({"istio": "ingressgateway"})
        
        # Fluent style for complex structures
        spec.servers([
            networking.v1.Server(
                port=networking.v1.Port(
                    number=80,
                    name="http",
                    protocol="HTTP"
                ),
                hosts=["*.example.com"]
            )
        ])

final_gateway = gateway.build()

# Create a VirtualService mixing styles
with networking.v1.VirtualService.new() as vs:
    vs.metadata(lambda m: m
        .name("website")
        .namespace("default")
    )
    
    with vs.spec() as spec:
        # Simple assignments
        spec.hosts(["website.example.com"])
        spec.gateways(["main-gateway"])
        
        # Context managers for deep nesting
        with spec.http() as http_list:
            with http_list.add() as route:
                # Fluent style for route configuration
                route.route(lambda routes: routes
                    .add(lambda w: w
                        .destination(lambda d: d
                            .host("website-svc")
                            .port(lambda p: p.number(8080))
                        )
                    )
                )

final_vs = vs.build()
```

The builder system provides:
- ✨ Full IDE support with detailed type information
- 🔍 Rich autocomplete for all fields and nested objects
- ⚡ Compile-time validation of your configuration
- 🎯 Clear and chainable API that guides you through resource creation
- 🔀 Flexibility to mix different builder styles

## 📚 Documentation

For complete documentation, visit [cloudcoil.github.io/cloudcoil](https://cloudcoil.github.io/cloudcoil)

## 📜 License

Apache License, Version 2.0 - see [LICENSE](LICENSE)
