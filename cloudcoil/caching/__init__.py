"""CloudCoil Caching - Efficient client-side caching for Kubernetes resources.

This module provides a caching system powered by informers that watch Kubernetes
resources and maintain a local cache, similar to client-go's informer pattern.

Key components:
- Cache: Configuration and control for the informer system
- AsyncInformer/SyncInformer: Watch and cache individual resource types
- ConcurrentStore: Thread-safe storage with custom indexing
- CachedClient/AsyncCachedClient: Client wrappers that use cache for reads

Example usage:

    from cloudcoil.caching import Cache
    from cloudcoil.client import Config
    import cloudcoil.models.kubernetes as k8s

    # Basic usage - just enable caching
    config = Config(cache=True)

    with config:
        deployment = k8s.apps.v1.Deployment.get("my-app")  # From cache

    # Advanced configuration
    cache_config = Cache(
        resync_period=600,  # 10 minutes
        mode="strict",      # Cache-only mode
        resources=[k8s.apps.v1.Deployment, k8s.core.v1.Pod]
    )
    config = Config(cache=cache_config)

    # Event handling
    async with config:
        informer = config.cache.get_informer(k8s.apps.v1.Deployment)

        @informer.on_add
        def handle_new_deployment(deployment):
            print(f"New deployment: {deployment.metadata.name}")
"""

from ._cache import Cache
from ._cached_client import AsyncCachedClient, CachedClient
from ._informer import AsyncInformer
from ._store import ConcurrentStore
from ._sync_informer import SyncInformer
from ._types import CacheStatus

__all__ = [
    # Core configuration
    "Cache",
    "CacheStatus",
    # Informer types (for type hints)
    "AsyncInformer",
    "SyncInformer",
    # Cached clients
    "CachedClient",
    "AsyncCachedClient",
    # Store for direct cache access
    "ConcurrentStore",
]
