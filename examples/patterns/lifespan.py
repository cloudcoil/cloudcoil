"""Observe process startup and elected-leader acquisition/loss/shutdown.

Run two replicas against the same namespace to observe standby versus leader hooks.
"""

import logging
from collections.abc import AsyncIterator

from cloudcoil.models.kubernetes.core.v1 import ConfigMap

from cloudcoil.application import Application, LifecycleEvent, LifecycleType
from cloudcoil.controller import Context

logger = logging.getLogger(__name__)


def build_app() -> Application:
    app = Application("lifecycle", leader_election=True)
    configs = app.controller(ConfigMap, label_selector="patterns.cloudcoil.dev/observe=true")

    @app.lifespan()
    async def process(event: LifecycleEvent) -> AsyncIterator[None]:
        logger.info("Process event: %s", event.type)
        try:
            # Open shared connections here, or compose them with async with.
            yield
        finally:
            # Webhooks/controllers have stopped before process resources close.
            logger.info("Process exit: %s", event.type)

    @app.lifespan(scope="leader")
    async def leadership(event: LifecycleEvent) -> AsyncIterator[None]:
        logger.info("Leader acquired: %s", event.identity)
        try:
            # Start leader-only local services here. Lease renewal is active.
            yield
        finally:
            # Workers have stopped. Do not assume ownership during loss cleanup.
            if event.type == LifecycleType.LEADERSHIP_LOST:
                logger.warning("Leadership lost: %s", event.error)
            logger.info("Leader exit: %s", event.type)

    @configs.reconcile()
    async def observe(config: ConfigMap, ctx: Context[ConfigMap]) -> None:
        ctx.event("Observed", f"Observed configuration {config.name}")

    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    build_app().main()
