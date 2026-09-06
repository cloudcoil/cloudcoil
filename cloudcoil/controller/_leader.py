"""Lease-based leader election with monotonic expiry and optimistic writes."""

import asyncio
import json
import logging
import math
import random
import re
import socket
import time
from collections.abc import Awaitable, Callable
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx

from cloudcoil.client import Config
from cloudcoil.client._response import raise_for_status
from cloudcoil.errors import APIError

logger = logging.getLogger(__name__)


class LeadershipLost(Exception):
    """The leader can no longer prove ownership; its workers must stop."""


def _dns_name(value: str, *, namespace: bool = False) -> str:
    limit = 63 if namespace else 253
    if (
        not value
        or len(value) > limit
        or (namespace and "." in value)
        or any(
            len(label) > 63 or not re.fullmatch(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?", label)
            for label in value.split(".")
        )
    ):
        raise ValueError("Lease name and namespace must be valid Kubernetes DNS names")
    return value


class LeaderElection:
    """Elect one active manager using a coordination.k8s.io/v1 Lease.

    Identity defaults to a process-unique hostname/UUID. Explicit identities must
    also be unique per participant. Takeover waits for the observed record to stop
    changing for its lease duration, measured locally; remote wall clocks are not
    used for expiry. Like client-go, this is coordination, not distributed fencing.
    Reconciliation and external operations must remain idempotent and cancellable.
    """

    def __init__(
        self,
        name: str,
        *,
        namespace: str | None = None,
        identity: str | None = None,
        lease_duration: int = 15,
        renew_deadline: float = 10,
        retry_period: float = 2,
        config: Config | None = None,
    ) -> None:
        self.name = _dns_name(name)
        self.namespace = _dns_name(namespace, namespace=True) if namespace is not None else None
        self.identity = identity if identity is not None else f"{socket.gethostname()}_{uuid4()}"
        if not self.identity or len(self.identity) > 128:
            raise ValueError("Lease identity must have 1-128 characters")
        if (
            isinstance(lease_duration, bool)
            or not isinstance(lease_duration, int)
            or not 1 <= lease_duration <= 2**31 - 1
        ):
            raise ValueError("lease_duration must be a positive int32 number of seconds")
        if (
            not all(math.isfinite(value) for value in (renew_deadline, retry_period))
            or not 0 < retry_period < renew_deadline < lease_duration
        ):
            raise ValueError("Require 0 < retry_period < renew_deadline < lease_duration")
        self.lease_duration = lease_duration
        self.renew_deadline = renew_deadline
        self.retry_period = retry_period
        self.config = config
        self._clock = time.monotonic
        self._active = False
        self._used = False
        self._last_renewed = 0.0
        self._observed_at = 0.0
        self._record: str | None = None
        self._lease: dict[str, Any] | None = None
        self._acquisitions = 0
        self._renewal_failures = 0

    @property
    def is_leader(self) -> bool:
        return self._active and self._clock() < self._last_renewed + self.renew_deadline

    def _urls(self, config: Config) -> tuple[str, str]:
        namespace = _dns_name(self.namespace or config.namespace, namespace=True)
        collection = f"/apis/coordination.k8s.io/v1/namespaces/{namespace}/leases"
        return collection, f"{collection}/{self.name}"

    def _observe(self, lease: dict[str, Any]) -> None:
        metadata = lease.get("metadata") or {}
        if not metadata.get("uid") or not metadata.get("resourceVersion"):
            raise ValueError("Lease response is missing UID or resourceVersion")
        spec = lease.get("spec") or {}
        record = json.dumps(
            {
                "uid": metadata["uid"],
                **{
                    key: spec.get(key)
                    for key in (
                        "holderIdentity",
                        "leaseDurationSeconds",
                        "acquireTime",
                        "renewTime",
                        "leaseTransitions",
                    )
                },
            },
            sort_keys=True,
        )
        if record != self._record:
            self._record = record
            self._observed_at = self._clock()
        self._lease = lease

    async def _attempt(self, config: Config) -> bool:
        """Acquire/renew with one bounded GET + conditional create/update attempt."""
        started = self._clock()
        timeout = self.retry_period
        if self._active:
            timeout = min(timeout, self._last_renewed + self.renew_deadline - started)
            if timeout <= 0:
                raise LeadershipLost("Lease renewal deadline exceeded")
        try:
            async with asyncio.timeout(timeout):
                collection, url = self._urls(config)
                response = await config.async_client.get(url)
                now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
                if response.status_code == 404:
                    if self._active:
                        raise LeadershipLost("Leader Lease was deleted")
                    body: dict[str, Any] = {
                        "apiVersion": "coordination.k8s.io/v1",
                        "kind": "Lease",
                        "metadata": {
                            "name": self.name,
                            "namespace": self.namespace or config.namespace,
                        },
                        "spec": {
                            "holderIdentity": self.identity,
                            "leaseDurationSeconds": self.lease_duration,
                            "acquireTime": now,
                            "renewTime": now,
                            "leaseTransitions": 0,
                        },
                    }
                    response = await config.async_client.post(collection, json=body)
                else:
                    raise_for_status(response)
                    current = response.json()
                    previous_uid = self._lease["metadata"]["uid"] if self._lease else None
                    spec = current.get("spec") or {}
                    holder = spec.get("holderIdentity")
                    if self._active and (
                        holder != self.identity or current["metadata"]["uid"] != previous_uid
                    ):
                        raise LeadershipLost("Leader Lease ownership changed")
                    self._observe(current)
                    if holder and holder != self.identity:
                        duration = spec.get("leaseDurationSeconds")
                        if (
                            isinstance(duration, bool)
                            or not isinstance(duration, int)
                            or duration <= 0
                        ):
                            raise ValueError("Held Lease has an invalid leaseDurationSeconds")
                        if self._clock() - self._observed_at < duration:
                            return False
                    body = deepcopy(current)
                    body["spec"] = {
                        **spec,
                        "holderIdentity": self.identity,
                        "leaseDurationSeconds": self.lease_duration,
                        "renewTime": now,
                    }
                    if holder != self.identity:
                        body["spec"]["acquireTime"] = now
                        body["spec"]["leaseTransitions"] = (spec.get("leaseTransitions") or 0) + 1
                    # resourceVersion from the GET prevents two contenders winning.
                    response = await config.async_client.put(url, json=body)
                raise_for_status(response)
                self._observe(response.json())
                # Use request start, not response arrival, as the conservative local deadline.
                self._last_renewed = started
                return True
        except APIError as exc:
            if (
                exc.status_code is not None
                and 400 <= exc.status_code < 500
                and exc.status_code not in {404, 408, 409, 429}
            ):
                raise
            logger.warning("Lease %s request failed: %s", self.name, exc)
        except (httpx.RequestError, TimeoutError) as exc:
            logger.warning("Lease %s request failed: %s", self.name, exc)
        return False

    async def _renew(self, config: Config) -> None:
        while True:
            remaining = self._last_renewed + self.renew_deadline - self._clock()
            if remaining <= 0:
                raise LeadershipLost("Lease renewal deadline exceeded")
            await asyncio.sleep(min(self.retry_period, remaining))
            if not await self._attempt(config):
                self._renewal_failures += 1

    async def _release(self, config: Config) -> None:
        if self._lease is None:
            return
        try:
            async with asyncio.timeout(self.retry_period):
                _, url = self._urls(config)
                response = await config.async_client.get(url)
                if response.status_code == 404:
                    return
                raise_for_status(response)
                current = response.json()
                if (current.get("spec") or {}).get("holderIdentity") != self.identity or current[
                    "metadata"
                ]["uid"] != self._lease["metadata"]["uid"]:
                    return
                body = deepcopy(current)
                body["spec"]["holderIdentity"] = ""
                body["spec"]["leaseDurationSeconds"] = 1
                body["spec"]["renewTime"] = datetime.now(timezone.utc).isoformat(
                    timespec="microseconds"
                )
                # Never clear a successor's ownership, even if it changes after this GET.
                response = await config.async_client.put(url, json=body)
                raise_for_status(response)
        except (APIError, httpx.RequestError, TimeoutError) as exc:
            logger.warning("Could not release Lease %s; it will expire: %s", self.name, exc)

    async def _run(
        self,
        callback: Callable[[], Awaitable[None]],
        *,
        config: Config,
        stop: asyncio.Event,
    ) -> None:
        if self._used:
            raise RuntimeError("LeaderElection instances can only run once")
        self._used = True
        work: asyncio.Task[None] | None = None
        renew: asyncio.Task[None] | None = None
        acquired = False
        try:
            while not stop.is_set():
                if await self._attempt(config):
                    acquired = True
                    break
                try:
                    await asyncio.wait_for(
                        stop.wait(), self.retry_period * random.uniform(0.9, 1.1)
                    )
                except TimeoutError:
                    pass
            if not acquired or stop.is_set():
                return
            self._active = True
            self._acquisitions += 1
            logger.info("Acquired Lease %s as %s", self.name, self.identity)

            async def invoke() -> None:
                await callback()

            work = asyncio.create_task(invoke())
            renew = asyncio.create_task(self._renew(config))
            done, _ = await asyncio.wait((work, renew), return_when=asyncio.FIRST_COMPLETED)
            if renew in done:
                await renew
                raise LeadershipLost("Lease renewal stopped unexpectedly")
            await work
        finally:
            self._active = False
            # Cancelling/joining the callback also joins its controller workers. Release
            # only afterwards, so a healthy successor cannot race draining workers.
            tasks = [task for task in (work, renew) if task is not None]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if acquired:
                await self._release(config)
