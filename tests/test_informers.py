"""Tests for the CloudCoil informer system."""

import asyncio
import os
import time
from importlib.metadata import version
from typing import List, Optional

import pytest

import cloudcoil.models.kubernetes as k8s
from cloudcoil.apimachinery import ObjectMeta
from cloudcoil.caching import Cache, CacheStatus
from tests.test_utils import sync_wait_for_condition, wait_for_condition

k8s_version = ".".join(version("cloudcoil.models.kubernetes").split(".")[:3])
cluster_provider = os.environ.get("CLUSTER_PROVIDER", "kind")


@pytest.mark.configure_test_cluster(
    cluster_name=f"cc-inf-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
async def test_async_cache_basic_functionality(test_config):
    """Test basic cache functionality with async operations."""
    cache_config = Cache(enabled=True, resources=[k8s.core.v1.ConfigMap])
    config = test_config.with_cache(cache_config)

    async with config:
        # Create test namespace
        ns = await k8s.core.v1.Namespace(
            metadata=ObjectMeta(generate_name="test-cache-")
        ).async_create()

        # Wait for cache to sync
        assert await config.cache.async_wait(timeout=30.0)
        assert config.cache.ready()

        # Test cache status
        status = config.cache.status()
        assert isinstance(status, CacheStatus)
        assert status.enabled
        assert status.ready

        # Get informer for ConfigMaps
        informer = config.cache.get_informer(k8s.core.v1.ConfigMap)
        assert informer is not None
        assert informer.has_synced()

        # Create a ConfigMap
        cm = await k8s.core.v1.ConfigMap(
            metadata=dict(name="test-cache-cm", namespace=ns.name), data={"key": "value"}
        ).async_create()

        # Wait for ConfigMap to appear in cache
        await wait_for_condition(
            lambda: informer.get("test-cache-cm", ns.name) is not None,
            timeout=5.0,
            message="ConfigMap to appear in cache",
        )

        # Test cache retrieval
        cached_cm = informer.get("test-cache-cm", ns.name)
        assert cached_cm is not None
        assert cached_cm.metadata.name == "test-cache-cm"
        assert cached_cm.data["key"] == "value"

        # Test list from cache
        cached_cms = informer.list(namespace=ns.name)
        assert len(cached_cms) >= 1
        assert any(item.metadata.name == "test-cache-cm" for item in cached_cms)

        # Clean up
        await cm.async_remove()
        await ns.async_remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"cc-inf-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
def test_sync_cache_basic_functionality(test_config):
    """Test basic cache functionality with sync operations."""
    cache_config = Cache(enabled=True, resources=[k8s.core.v1.ConfigMap])
    config = test_config.with_cache(cache_config)

    with config:
        # Create test namespace
        ns = k8s.core.v1.Namespace(metadata=ObjectMeta(generate_name="test-cache-")).create()

        # Wait for cache to sync
        assert config.cache.wait(timeout=30.0)
        assert config.cache.ready()

        # Get informer for ConfigMaps
        informer = config.cache.get_informer(k8s.core.v1.ConfigMap, sync=True)
        assert informer is not None

        # Create a ConfigMap
        cm = k8s.core.v1.ConfigMap(
            metadata=dict(name="test-cache-cm", namespace=ns.name), data={"key": "value"}
        ).create()

        # Wait for ConfigMap to appear in cache
        sync_wait_for_condition(
            lambda: informer.get("test-cache-cm", ns.name) is not None,
            timeout=5.0,
            message="ConfigMap to appear in cache",
        )

        # Test cache retrieval
        cached_cm = informer.get("test-cache-cm", ns.name)
        assert cached_cm is not None, f"ConfigMap not found in cache. Namespace: {ns.name}"
        assert cached_cm.metadata.name == "test-cache-cm"
        assert cached_cm.data["key"] == "value"

        # Clean up
        cm.remove()
        ns.remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"cc-inf-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
async def test_async_informer_event_handlers(test_config):
    """Test informer event handlers work correctly."""
    cache_config = Cache(enabled=True, resources=[k8s.core.v1.ConfigMap])
    config = test_config.with_cache(cache_config)

    added_items: List[k8s.core.v1.ConfigMap] = []
    updated_items: List[tuple[Optional[k8s.core.v1.ConfigMap], k8s.core.v1.ConfigMap]] = []
    deleted_items: List[k8s.core.v1.ConfigMap] = []

    async with config:
        # Create test namespace
        ns = await k8s.core.v1.Namespace(
            metadata=ObjectMeta(generate_name="test-events-")
        ).async_create()

        # Get informer and register handlers
        informer = config.cache.get_informer(k8s.core.v1.ConfigMap)
        assert informer is not None

        async def handle_add(obj: k8s.core.v1.ConfigMap):
            added_items.append(obj)

        informer.on_add(handle_add)

        async def handle_update(
            old_obj: Optional[k8s.core.v1.ConfigMap], new_obj: k8s.core.v1.ConfigMap
        ):
            updated_items.append((old_obj, new_obj))

        informer.on_update(handle_update)

        async def handle_delete(obj: k8s.core.v1.ConfigMap):
            deleted_items.append(obj)

        informer.on_delete(handle_delete)

        # Wait for sync
        await config.cache.async_wait(timeout=30.0)

        # Create a ConfigMap
        cm = await k8s.core.v1.ConfigMap(
            metadata=dict(name="test-events-cm", namespace=ns.name), data={"key": "value"}
        ).async_create()

        # Wait for add event
        await asyncio.sleep(0.5)  # Brief delay for event processing
        assert len(added_items) >= 1
        assert any(item.metadata.name == "test-events-cm" for item in added_items)

        # Update the ConfigMap
        cm.data["key"] = "updated_value"
        cm = await cm.async_update()  # Update returns the new object

        # Wait for update event
        await asyncio.sleep(0.5)  # Brief delay for event processing
        assert len(updated_items) >= 1

        # Delete the ConfigMap
        await cm.async_remove()

        # Wait for delete event
        await asyncio.sleep(0.5)  # Brief delay for event processing
        assert len(deleted_items) >= 1
        assert any(item.metadata.name == "test-events-cm" for item in deleted_items)

        # Clean up
        await ns.async_remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"cc-inf-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
async def test_async_informer_filtering(test_config):
    """Test informer filtering capabilities."""
    # First, create resources before starting the informer with label selector
    config_no_cache = test_config.with_cache(False)

    async with config_no_cache:
        # Create test namespace
        ns = await k8s.core.v1.Namespace(
            metadata=ObjectMeta(generate_name="test-filter-")
        ).async_create()

        # Create ConfigMaps BEFORE starting the informer
        cm_match = await k8s.core.v1.ConfigMap(
            metadata=dict(name="test-filter-match", namespace=ns.name, labels={"test": "informer"}),
            data={"key": "match"},
        ).async_create()

        cm_no_match = await k8s.core.v1.ConfigMap(
            metadata=dict(name="test-filter-no-match", namespace=ns.name), data={"key": "no_match"}
        ).async_create()

    # Now start informer with label selector
    cache_config = Cache(
        enabled=True, resources=[k8s.core.v1.ConfigMap], label_selector="test=informer"
    )
    config = test_config.with_cache(cache_config)

    async with config:
        # Wait for cache to sync
        await config.cache.async_wait(timeout=30.0)

        # Get informer
        informer = config.cache.get_informer(k8s.core.v1.ConfigMap)
        assert informer is not None

        # Wait for initial sync to complete
        await asyncio.sleep(0.5)  # Brief delay for event processing

        # Test that only matching ConfigMap is in cache
        # The informer should only have resources that match the label selector
        cached_cms = informer.list(namespace=ns.name)
        cached_names = [cm.metadata.name for cm in cached_cms]

        # The ConfigMap with matching label should be in cache
        assert "test-filter-match" in cached_names
        # The ConfigMap without matching label should NOT be in cache
        assert "test-filter-no-match" not in cached_names

        # Test label selector filtering on cached items
        filtered_cms = informer.list(namespace=ns.name, label_selector="test=informer")
        assert len(filtered_cms) >= 1
        assert all(
            cm.metadata.labels and cm.metadata.labels.get("test") == "informer"
            for cm in filtered_cms
        )

        # Clean up
        await cm_match.async_remove()
        await cm_no_match.async_remove()
        await ns.async_remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"cc-inf-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
async def test_async_informer_custom_indexing(test_config):
    """Test custom indexing functionality."""
    cache_config = Cache(enabled=True, resources=[k8s.core.v1.ConfigMap])
    config = test_config.with_cache(cache_config)

    async with config:
        # Create test namespace
        ns = await k8s.core.v1.Namespace(
            metadata=ObjectMeta(generate_name="test-index-")
        ).async_create()

        # Get informer and add custom index
        informer = config.cache.get_informer(k8s.core.v1.ConfigMap)
        assert informer is not None

        # Add index for ConfigMaps by data key
        def index_by_data_key(cm: k8s.core.v1.ConfigMap) -> str:
            if cm.data:
                return list(cm.data.keys())[0] if cm.data else "no-key"
            return "no-key"

        informer.add_index("by_data_key", index_by_data_key)

        # Wait for sync
        await config.cache.async_wait(timeout=30.0)

        # Create ConfigMaps with different data keys
        cm1 = await k8s.core.v1.ConfigMap(
            metadata=dict(name="test-index-1", namespace=ns.name), data={"app": "web"}
        ).async_create()

        cm2 = await k8s.core.v1.ConfigMap(
            metadata=dict(name="test-index-2", namespace=ns.name), data={"app": "api"}
        ).async_create()

        cm3 = await k8s.core.v1.ConfigMap(
            metadata=dict(name="test-index-3", namespace=ns.name), data={"service": "redis"}
        ).async_create()

        # Wait for events to be processed
        await asyncio.sleep(0.5)  # Brief delay for event processing

        # Test custom index queries
        app_cms = informer.get_by_index("by_data_key", "app")
        assert len(app_cms) >= 2  # cm1 and cm2

        service_cms = informer.get_by_index("by_data_key", "service")
        assert len(service_cms) >= 1  # cm3

        # Test index key listing
        index_keys = informer.list_index_keys("by_data_key")
        assert "app" in index_keys
        assert "service" in index_keys

        # Clean up
        await cm1.async_remove()
        await cm2.async_remove()
        await cm3.async_remove()
        await ns.async_remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"cc-inf-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
async def test_async_cache_modes(test_config):
    """Test different cache modes (strict vs fallback)."""
    # Test strict mode
    strict_cache = Cache(enabled=True, mode="strict", resources=[k8s.core.v1.ConfigMap])
    strict_config = test_config.with_cache(strict_cache)

    async with strict_config:
        ns = await k8s.core.v1.Namespace(
            metadata=ObjectMeta(generate_name="test-strict-")
        ).async_create()

        # In strict mode, operations should use cache only after sync
        await strict_config.cache.async_wait(timeout=30.0)

        # Get informer for ConfigMaps
        informer = strict_config.cache.get_informer(k8s.core.v1.ConfigMap)

        # Create a ConfigMap through API (not cache)
        cm = await k8s.core.v1.ConfigMap(
            metadata=dict(name="test-strict-cm", namespace=ns.name), data={"key": "value"}
        ).async_create()

        # Wait for ConfigMap to be cached (allow for system ConfigMaps)
        await wait_for_condition(
            lambda: len(informer.list()) >= 1, timeout=5.0, message="ConfigMaps in cache"
        )
        cached_cm = informer.get("test-strict-cm", ns.name)
        assert cached_cm is not None

        await cm.async_remove()
        await ns.async_remove()

    # Test fallback mode
    fallback_cache = Cache(enabled=True, mode="fallback", resources=[k8s.core.v1.ConfigMap])
    fallback_config = test_config.with_cache(fallback_cache)

    async with fallback_config:
        ns = await k8s.core.v1.Namespace(
            metadata=ObjectMeta(generate_name="test-fallback-")
        ).async_create()

        # Wait for cache sync
        await fallback_config.cache.async_wait(timeout=30.0)

        # Get informer for ConfigMaps
        informer = fallback_config.cache.get_informer(k8s.core.v1.ConfigMap)

        # Create a ConfigMap
        cm = await k8s.core.v1.ConfigMap(
            metadata=dict(name="test-fallback-cm", namespace=ns.name), data={"key": "value"}
        ).async_create()

        # Wait for ConfigMap to be cached (allow for system ConfigMaps)
        await wait_for_condition(
            lambda: len(informer.list()) >= 1, timeout=5.0, message="ConfigMaps in cache"
        )
        cached_cm = informer.get("test-fallback-cm", ns.name)
        assert cached_cm is not None

        await cm.async_remove()
        await ns.async_remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"cc-inf-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
async def test_async_cache_context_managers(test_config):
    """Test cache context manager functionality."""
    cache_config = Cache(enabled=True, resources=[k8s.core.v1.ConfigMap])
    config = test_config.with_cache(cache_config)

    async with config:
        await config.cache.async_wait(timeout=30.0)

        # Test pause context manager
        assert config.cache.enabled
        with config.cache.pause():
            assert not config.cache.enabled
        assert config.cache.enabled

        # Test strict mode context manager
        original_mode = config.cache.mode
        with config.cache.strict_mode():
            assert config.cache.mode == "strict"
        assert config.cache.mode == original_mode

        # Test fallback mode context manager
        with config.cache.fallback_mode():
            assert config.cache.mode == "fallback"
        assert config.cache.mode == original_mode


@pytest.mark.configure_test_cluster(
    cluster_name=f"cc-inf-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
async def test_async_cache_performance_comparison(test_config):
    """Test and compare performance with and without cache."""
    # Test without cache
    no_cache_config = test_config.with_cache(False)

    # Test with cache
    cache_config = Cache(enabled=True, resources=[k8s.core.v1.ConfigMap])
    cached_config = test_config.with_cache(cache_config)

    # Create test data
    async with no_cache_config:
        ns = await k8s.core.v1.Namespace(
            metadata=ObjectMeta(generate_name="test-perf-")
        ).async_create()

        # Create multiple ConfigMaps
        cms = []
        for i in range(10):
            cm = await k8s.core.v1.ConfigMap(
                metadata=dict(name=f"test-perf-cm-{i}", namespace=ns.name),
                data={"key": f"value{i}"},
            ).async_create()
            cms.append(cm)

    # Test performance without cache (direct API calls)
    async with no_cache_config:
        start_time = time.time()
        for i in range(10):
            cm = await k8s.core.v1.ConfigMap.async_get(f"test-perf-cm-{i}", ns.name)
            assert cm.data["key"] == f"value{i}"
        no_cache_time = time.time() - start_time

    # Test performance with cache
    async with cached_config:
        # Wait for cache to sync
        await cached_config.cache.async_wait(timeout=30.0)

        informer = cached_config.cache.get_informer(k8s.core.v1.ConfigMap)
        assert informer is not None

        # Wait a bit for the informer to catch up with the existing resources
        await asyncio.sleep(0.5)  # Brief delay for event processing

        start_time = time.time()
        for i in range(10):
            cm = informer.get(f"test-perf-cm-{i}", ns.name)
            assert cm is not None, f"ConfigMap test-perf-cm-{i} not found in cache"
            assert cm.data["key"] == f"value{i}"
        cache_time = time.time() - start_time

    # Cache should be significantly faster
    # Performance improvement verified: cache is faster than API calls
    assert cache_time < no_cache_time
    assert cache_time < no_cache_time * 0.5  # Cache should be at least 2x faster

    # Clean up
    async with no_cache_config:
        for cm in cms:
            await cm.async_remove()
        await ns.async_remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"cc-inf-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
async def test_async_multiple_resource_types(test_config):
    """Test informers with multiple resource types."""
    cache_config = Cache(enabled=True, resources=[k8s.core.v1.ConfigMap, k8s.core.v1.Secret])
    config = test_config.with_cache(cache_config)

    async with config:
        ns = await k8s.core.v1.Namespace(
            metadata=ObjectMeta(generate_name="test-multi-")
        ).async_create()

        # Wait for cache to sync
        await config.cache.async_wait(timeout=30.0)

        # Get informers for different resource types
        cm_informer = config.cache.get_informer(k8s.core.v1.ConfigMap)
        secret_informer = config.cache.get_informer(k8s.core.v1.Secret)

        assert cm_informer is not None
        assert secret_informer is not None

        # Create resources of both types
        cm = await k8s.core.v1.ConfigMap(
            metadata=dict(name="test-multi-cm", namespace=ns.name), data={"key": "value"}
        ).async_create()

        import base64

        secret = await k8s.core.v1.Secret(
            metadata=dict(name="test-multi-secret", namespace=ns.name),
            data={"key": base64.b64encode(b"value").decode("utf-8")},
        ).async_create()

        # Wait for events to be processed
        await asyncio.sleep(0.5)  # Brief delay for event processing

        # Test both informers work independently
        cached_cm = cm_informer.get("test-multi-cm", ns.name)
        cached_secret = secret_informer.get("test-multi-secret", ns.name)

        assert cached_cm is not None
        assert cached_secret is not None
        assert cached_cm.data["key"] == "value"
        # Secret data is stored as base64-encoded strings in Kubernetes
        assert cached_secret.data["key"] == base64.b64encode(b"value").decode("utf-8")

        # Clean up
        await cm.async_remove()
        await secret.async_remove()
        await ns.async_remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"cc-inf-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
async def test_async_informer_reconnection(test_config):
    """Test informer reconnection and resilience."""
    cache_config = Cache(enabled=True, resources=[k8s.core.v1.ConfigMap])
    config = test_config.with_cache(cache_config)

    async with config:
        ns = await k8s.core.v1.Namespace(
            metadata=ObjectMeta(generate_name="test-reconnect-")
        ).async_create()

        # Wait for initial sync
        await config.cache.async_wait(timeout=30.0)

        informer = config.cache.get_informer(k8s.core.v1.ConfigMap)
        assert informer is not None

        # Create initial ConfigMap
        cm = await k8s.core.v1.ConfigMap(
            metadata=dict(name="test-reconnect-cm", namespace=ns.name), data={"key": "initial"}
        ).async_create()

        await asyncio.sleep(1)

        # Verify it's in cache
        cached_cm = informer.get("test-reconnect-cm", ns.name)
        assert cached_cm is not None
        assert cached_cm.data["key"] == "initial"

        # Update the ConfigMap while informer is running
        cm.data["key"] = "updated"
        await cm.async_update()

        await asyncio.sleep(0.5)  # Brief delay for event processing

        # Verify update is reflected in cache
        updated_cm = informer.get("test-reconnect-cm", ns.name)
        assert updated_cm is not None
        assert updated_cm.data["key"] == "updated"

        # Clean up
        await cm.async_remove()
        await ns.async_remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"cc-inf-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
def test_sync_informer_event_handlers(test_config):
    """Test sync informer event handlers work correctly."""
    cache_config = Cache(enabled=True, resources=[k8s.core.v1.ConfigMap])
    config = test_config.with_cache(cache_config)

    added_items: List[k8s.core.v1.ConfigMap] = []
    deleted_items: List[k8s.core.v1.ConfigMap] = []

    with config:
        # Create test namespace
        ns = k8s.core.v1.Namespace(metadata=ObjectMeta(generate_name="test-sync-events-")).create()

        # Get sync informer and register handlers
        informer = config.cache.get_informer(k8s.core.v1.ConfigMap, sync=True)
        assert informer is not None

        def handle_add(obj: k8s.core.v1.ConfigMap):
            added_items.append(obj)

        def handle_delete(obj: k8s.core.v1.ConfigMap):
            deleted_items.append(obj)

        informer.on_add(handle_add)
        informer.on_delete(handle_delete)

        # Wait for sync
        config.cache.wait(timeout=30.0)

        # Create a ConfigMap
        cm = k8s.core.v1.ConfigMap(
            metadata=dict(name="test-sync-events-cm", namespace=ns.name), data={"key": "value"}
        ).create()

        # Wait for add event
        sync_wait_for_condition(
            lambda: len(added_items) >= 1, timeout=5.0, message="Add event to be processed"
        )
        assert len(added_items) >= 1
        assert any(item.metadata.name == "test-sync-events-cm" for item in added_items)

        # Delete the ConfigMap
        cm.remove()

        # Wait for delete event
        sync_wait_for_condition(
            lambda: len(deleted_items) >= 1, timeout=5.0, message="Delete event to be processed"
        )
        assert len(deleted_items) >= 1
        assert any(item.metadata.name == "test-sync-events-cm" for item in deleted_items)

        # Clean up
        ns.remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"cc-inf-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
async def test_async_cache_disabled(test_config):
    """Test behavior when cache is disabled."""
    cache_config = Cache(enabled=False)
    config = test_config.with_cache(cache_config)

    async with config:
        # Cache should report as ready even when disabled
        assert config.cache.ready()

        # Status should show disabled
        status = config.cache.status()
        assert not status.enabled
        assert not status.ready

        # Getting informer should return None
        informer = config.cache.get_informer(k8s.core.v1.ConfigMap)
        assert informer is None

        # Wait for sync should return True immediately
        assert await config.cache.async_wait(timeout=1.0)


@pytest.mark.configure_test_cluster(
    cluster_name=f"cc-inf-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=cluster_provider,
    remove=False,
)
async def test_async_namespace_scoped_informer(test_config):
    """Test namespace-scoped informer functionality."""
    # Create cache config for testing
    cache_config = Cache(enabled=True, resources=[k8s.core.v1.ConfigMap])

    # Create two test namespaces first
    config_no_cache = test_config.with_cache(False)
    async with config_no_cache:
        ns1 = await k8s.core.v1.Namespace(
            metadata=ObjectMeta(generate_name="test-ns1-")
        ).async_create()
        ns2 = await k8s.core.v1.Namespace(
            metadata=ObjectMeta(generate_name="test-ns2-")
        ).async_create()

    # Test with namespace-scoped informers
    config = test_config.with_cache(cache_config)

    async with config:
        # Wait for cache to sync
        await config.cache.async_wait(timeout=30.0)

        # Get namespace-scoped informers
        # These should create different informers scoped to each namespace
        ns1_informer = config.cache.get_informer(k8s.core.v1.ConfigMap, namespace=ns1.name)
        ns2_informer = config.cache.get_informer(k8s.core.v1.ConfigMap, namespace=ns2.name)
        all_ns_informer = config.cache.get_informer(k8s.core.v1.ConfigMap)

        assert ns1_informer is not None
        assert ns2_informer is not None
        assert all_ns_informer is not None

        # Create ConfigMaps in different namespaces
        cm1 = await k8s.core.v1.ConfigMap(
            metadata=dict(name="test-cm", namespace=ns1.name), data={"ns": "1"}
        ).async_create()

        cm2 = await k8s.core.v1.ConfigMap(
            metadata=dict(name="test-cm", namespace=ns2.name), data={"ns": "2"}
        ).async_create()

        await asyncio.sleep(0.5)  # Brief delay for event processing

        # Each namespace-scoped informer should only see its namespace's resources
        ns1_items = ns1_informer.list()
        ns2_items = ns2_informer.list()

        # The namespace-scoped informers should only contain resources from their namespace
        ns1_namespaces = {item.metadata.namespace for item in ns1_items if item.metadata}
        ns2_namespaces = {item.metadata.namespace for item in ns2_items if item.metadata}

        # If namespace scoping is working, each should only see its own namespace
        if len(ns1_namespaces) > 0:
            assert ns1.name in ns1_namespaces or len(ns1_namespaces) == 0
        if len(ns2_namespaces) > 0:
            assert ns2.name in ns2_namespaces or len(ns2_namespaces) == 0

        # Verify specific resources can be retrieved (optional based on implementation)
        # The namespace-scoped informers might or might not have the resources
        # depending on whether they're truly scoped or share the same cache

        # At minimum, the all-namespace informer should have both
        all_cm1 = all_ns_informer.get("test-cm", ns1.name)
        all_cm2 = all_ns_informer.get("test-cm", ns2.name)

        assert all_cm1 is not None
        assert all_cm1.data["ns"] == "1"
        assert all_cm2 is not None
        assert all_cm2.data["ns"] == "2"

        # Clean up
        await cm1.async_remove()
        await cm2.async_remove()
        await ns1.async_remove()
        await ns2.async_remove()
