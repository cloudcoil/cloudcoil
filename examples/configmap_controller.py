"""Mirror selected ConfigMaps into owned children and repair changes to either side.

Run: uv run python examples/configmap_controller.py --namespace default
Select a source ConfigMap with the label example.com/mirror=true.
"""

import argparse
import asyncio
import signal

from cloudcoil.models.kubernetes.core.v1 import ConfigMap

from cloudcoil.client import Config
from cloudcoil.controller import Controller, Request, TerminalError, mutate
from cloudcoil.errors import ResourceNotFound


async def reconcile(request: Request[ConfigMap]) -> None:
    source = request.resource
    if source is None or source.metadata is None or source.metadata.deletion_timestamp:
        return
    source_uid = source.metadata.uid
    name = f"{request.name}-mirror"
    try:
        child = await ConfigMap.async_get(name, request.namespace)
    except ResourceNotFound:
        await ConfigMap.model_validate(
            {
                "metadata": {
                    "name": name,
                    "namespace": request.namespace,
                    "ownerReferences": [
                        {
                            "apiVersion": source.api_version,
                            "kind": source.kind,
                            "name": source.name,
                            "uid": source_uid,
                            "controller": True,
                        }
                    ],
                },
                "data": source.data,
            }
        ).async_create()
        return

    def change(current: ConfigMap) -> None:
        refs = current.metadata.owner_references if current.metadata else None
        if not any(ref.uid == source_uid and ref.controller for ref in refs or []):
            raise TerminalError(f"Refusing to adopt unrelated ConfigMap {name}")
        current.data = dict(source.data) if source.data is not None else None

    # Fetches live child state, guards its UID/version, and avoids a write loop
    # when the child already has the desired data. Other child fields survive.
    await mutate(child, change)


async def main(namespace: str) -> None:
    config = Config(namespace=namespace)
    controller = Controller(
        ConfigMap,
        reconcile,
        config=config,
        namespace=namespace,
        label_selector="example.com/mirror=true",
        workers=2,
    ).owns(ConfigMap)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await controller.run(stop=stop)
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
        config.client.close()
        await config.async_client.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="default")
    asyncio.run(main(parser.parse_args().namespace))
