"""Mirror selected ConfigMaps into owned children and repair changes to either side.

Run: CLOUDCOIL_NAMESPACE=default uv run --no-sync python examples/configmap_controller.py run
Select a source ConfigMap with the label example.com/mirror=true.
"""

from cloudcoil.models.kubernetes.core.v1 import ConfigMap

from cloudcoil.apimachinery import ObjectMeta
from cloudcoil.application import Application
from cloudcoil.controller import (
    Context,
    HealthServer,
    TerminalError,
    mutate,
)
from cloudcoil.errors import ResourceNotFound


def build_app() -> Application:
    app = Application(
        "configmap-mirror",
        leader_election=True,
        health=HealthServer(host="0.0.0.0", port=8080),
    )
    mirrors = app.controller(
        ConfigMap,
        owns=(ConfigMap,),
        label_selector="example.com/mirror=true",
        workers=2,
    )

    @mirrors.reconcile()
    async def reconcile(source: ConfigMap, ctx: Context[ConfigMap]) -> None:
        assert source.metadata and source.metadata.uid
        source_uid = source.metadata.uid
        name = f"{source.name}-mirror"
        client = await ctx.client(ConfigMap)
        try:
            child = await client.get(name)
        except ResourceNotFound:
            await ctx.ensure(ConfigMap(metadata=ObjectMeta(name=name), data=source.data))
            return

        def change(current: ConfigMap) -> None:
            refs = current.metadata.owner_references if current.metadata else None
            if not any(ref.uid == source_uid and ref.controller for ref in refs or []):
                raise TerminalError(f"Refusing to adopt unrelated ConfigMap {name}")
            current.data = dict(source.data) if source.data is not None else None

        # Fetches live child state, guards its UID/version, and avoids a write loop
        # when the child already has the desired data. Other child fields survive.
        await mutate(child, change)

    return app


if __name__ == "__main__":
    build_app().main()
