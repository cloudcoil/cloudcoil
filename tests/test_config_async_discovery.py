"""Concurrent discovery and refresh must leave admission's event loop responsive."""

import asyncio
import threading

import pytest
from cloudcoil.models.kubernetes.core.v1 import ConfigMap, Namespace

from cloudcoil.client import Config


@pytest.mark.parametrize("refresh", [False, True])
async def test_concurrent_discovery_does_not_block_event_loop(monkeypatch, refresh):
    config = Config(server="https://example.invalid")
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def discover():
        nonlocal calls
        calls += 1
        config._rest_mapping[Namespace.gvk()] = {
            "resource": "namespaces",
            "namespaced": False,
            "subresources": {},
        }
        started.set()
        assert release.wait(5), "test did not release discovery"
        config._rest_mapping[ConfigMap.gvk()] = {
            "resource": "configmaps",
            "namespaced": True,
            "subresources": {},
        }

    monkeypatch.setattr(config, "_create_rest_mapper", discover)
    if refresh:
        config._rest_mapping[Namespace.gvk()] = {}
    first = asyncio.create_task(
        asyncio.to_thread(config.refresh_api_resources)
        if refresh
        else config.async_client_for(ConfigMap, cached=False)
    )
    second = None
    # Release from another thread even if the regression blocks the event loop.
    fallback = threading.Timer(2, release.set)
    try:
        assert await asyncio.to_thread(started.wait, 2)
        fallback.start()
        second = asyncio.create_task(config.async_client_for(ConfigMap, cached=False))
        loop = asyncio.get_running_loop()
        before = loop.time()
        await asyncio.sleep(0.05)
        assert loop.time() - before < 1, "client creation blocked the event loop"
        assert not second.done(), "partial discovery was treated as ready"
        release.set()
        await first
        client = await second
        assert client.resource == "configmaps"
        assert calls == 1
    finally:
        release.set()
        fallback.cancel()
        await asyncio.gather(first, *([second] if second else []), return_exceptions=True)
        config.client.close()
        await config.async_client.aclose()


async def test_failed_partial_discovery_can_retry(monkeypatch):
    config = Config(server="https://example.invalid")
    calls = 0

    def discover():
        nonlocal calls
        calls += 1
        config._rest_mapping[Namespace.gvk()] = {}
        if calls == 1:
            raise ValueError("temporary discovery failure")
        config._rest_mapping[ConfigMap.gvk()] = {
            "resource": "configmaps",
            "namespaced": True,
            "subresources": {},
        }

    monkeypatch.setattr(config, "_create_rest_mapper", discover)
    try:
        with pytest.raises(ValueError, match="temporary discovery failure"):
            await config.async_client_for(ConfigMap)
        assert not config._rest_mapping
        assert (await config.async_client_for(ConfigMap)).resource == "configmaps"
        assert calls == 2
    finally:
        config.client.close()
        await config.async_client.aclose()
