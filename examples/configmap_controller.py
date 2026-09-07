"""Mirror selected ConfigMaps into owned children and repair changes to either side.

Run: CLOUDCOIL_NAMESPACE=default uv run --no-sync python examples/configmap_controller.py run
Select a source ConfigMap with the label example.com/mirror=true.
"""

from cloudcoil.models.kubernetes.core.v1 import ConfigMap

from cloudcoil.apimachinery import ObjectMeta
from cloudcoil.controller import (
    Controller,
    HealthServer,
    Request,
    TerminalError,
    mutate,
)
from cloudcoil.errors import ResourceNotFound
from cloudcoil.operator import Operator


async def reconcile(request: Request[ConfigMap]) -> None:
    source = request.resource
    if source is None or source.metadata is None or source.metadata.deletion_timestamp:
        return
    source_uid = source.metadata.uid
    name = f"{request.name}-mirror"
    client = await request.client(ConfigMap)
    try:
        child = await client.get(name)
    except ResourceNotFound:
        await request.ensure(ConfigMap(metadata=ObjectMeta(name=name), data=source.data))
        return

    def change(current: ConfigMap) -> None:
        refs = current.metadata.owner_references if current.metadata else None
        if not any(ref.uid == source_uid and ref.controller for ref in refs or []):
            raise TerminalError(f"Refusing to adopt unrelated ConfigMap {name}")
        current.data = dict(source.data) if source.data is not None else None

    # Fetches live child state, guards its UID/version, and avoids a write loop
    # when the child already has the desired data. Other child fields survive.
    await mutate(child, change, config=request.config)


def build_operator() -> Operator:
    return Operator(
        "configmap-mirror",
        Controller(
            ConfigMap,
            reconcile,
            label_selector="example.com/mirror=true",
            workers=2,
        ).owns(ConfigMap),
        leader_election=True,
        health=HealthServer(host="0.0.0.0", port=8080),
    )


if __name__ == "__main__":
    build_operator().main()
