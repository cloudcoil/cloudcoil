"""Bounded, best-effort events.k8s.io/v1 recording without model-package imports."""

import asyncio
import logging
import math
import re
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import quote
from uuid import uuid4

from cloudcoil._context import context
from cloudcoil.client import Config
from cloudcoil.client._response import raise_for_status
from cloudcoil.resources import Resource

logger = logging.getLogger(__name__)


class EventRecorder:
    """Emit diagnostics, suppressing repeated reasons per resource UID for interval.

    Memory is bounded by max_keys and traffic by a 20-event burst / 5 events per
    second token bucket per recorder. Changing messages do not defeat suppression.
    Delivery has a timeout and never raises an API/transport error to a reconciler.
    No background tasks or durable/exactly-once delivery guarantees.
    """

    def __init__(
        self,
        reporting_controller: str = "cloudcoil",
        *,
        interval: float = 60,
        max_keys: int = 1024,
        timeout: float = 2,
        namespace: str | None = None,
    ) -> None:
        if not reporting_controller or len(reporting_controller) > 128:
            raise ValueError("reporting_controller must contain 1-128 characters")
        if not all(math.isfinite(v) and v > 0 for v in (interval, timeout)):
            raise ValueError("Event interval and timeout must be finite and positive")
        if isinstance(max_keys, bool) or not isinstance(max_keys, int) or max_keys < 1:
            raise ValueError("max_keys must be a positive integer")
        self.reporting_controller = reporting_controller
        self.namespace = namespace
        self.interval = interval
        self.max_keys = max_keys
        self.timeout = timeout
        self._instance = str(uuid4())
        self._recent: OrderedDict[tuple[str, ...], float] = OrderedDict()
        self._clock = time.monotonic
        self._tokens = 20.0
        self._last_token = self._clock()

    async def emit(
        self,
        resource: Resource,
        reason: str,
        message: str,
        *,
        type: Literal["Normal", "Warning"] = "Normal",
        action: str | None = None,
        config: Config | None = None,
    ) -> bool:
        """Return whether delivered; False means suppressed, disabled identity, or failed.

        Programmer errors (invalid reason/type/action) raise. Cancellation propagates.
        Cluster-scoped objects use the recorder namespace or the Config namespace.
        """
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", reason) or len(reason) > 128:
            raise ValueError("Event reason must be a nonempty identifier of at most 128 characters")
        if type not in ("Normal", "Warning"):
            raise ValueError("Event type must be Normal or Warning")
        action = reason if action is None else action
        if not action or len(action) > 128:
            raise ValueError("Event action must contain 1-128 characters")
        if not resource.name or not resource.metadata or not resource.metadata.uid:
            return False
        config = config or context.active_config
        namespace = resource.namespace or self.namespace or config.namespace
        key = (config.server or "", namespace, resource.metadata.uid, type, reason, action)
        now = self._clock()
        previous = self._recent.get(key)
        if previous is not None and now - previous < self.interval:
            return False
        self._tokens = min(20.0, self._tokens + (now - self._last_token) * 5)
        self._last_token = now
        if self._tokens < 1:
            return False
        self._tokens -= 1
        # Reserve before awaiting: concurrent calls for the same key coalesce too.
        self._recent[key] = now
        self._recent.move_to_end(key)
        while len(self._recent) > self.max_keys:
            self._recent.popitem(last=False)
        regarding = {
            "apiVersion": resource.api_version,
            "kind": resource.kind,
            "name": resource.name,
            "uid": resource.metadata.uid,
        }
        if resource.namespace:
            regarding["namespace"] = resource.namespace
        body = {
            "apiVersion": "events.k8s.io/v1",
            "kind": "Event",
            "metadata": {"name": f"cloudcoil-{uuid4().hex}", "namespace": namespace},
            "eventTime": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            "reportingController": self.reporting_controller,
            "reportingInstance": self._instance,
            "regarding": regarding,
            "reason": reason,
            "action": action,
            "note": message[:1024],
            "type": type,
        }
        try:
            async with asyncio.timeout(self.timeout):
                response = await config.async_client.post(
                    f"/apis/events.k8s.io/v1/namespaces/{quote(namespace, safe='')}/events",
                    json=body,
                )
                raise_for_status(response)
            return True
        except Exception:
            # Keep the reservation on failure to bound repeated denied/API requests.
            logger.warning(
                "Could not record Kubernetes Event %s for %s", reason, resource.name, exc_info=True
            )
            return False
