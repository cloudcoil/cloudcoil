"""Type definitions for the informers module."""

import logging
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional, Type, TypeVar

from pydantic import BaseModel, Field, PrivateAttr, model_validator

from cloudcoil.resources import Resource

if TYPE_CHECKING:
    from typing_extensions import Self
else:
    try:
        from typing import Self
    except ImportError:
        from typing_extensions import Self

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Resource)


class InformerState(Enum):
    """State of an informer."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


class InformerOptions(BaseModel):
    """Options for configuring an informer."""

    resync_period: float = Field(
        default=300.0,
        ge=30.0,
        le=86400.0,  # 1 day max
        description="Resync period in seconds (minimum 30s, maximum 24h)",
    )
    page_size: int = Field(
        default=500, ge=10, le=5000, description="Page size for list operations (10-5000)"
    )
    label_selector: Optional[str] = Field(default=None, description="Kubernetes label selector")
    field_selector: Optional[str] = Field(default=None, description="Kubernetes field selector")
    namespace: Optional[str] = Field(
        default=None, description="Namespace to scope informer to (None = use default namespace)"
    )
    all_namespaces: bool = Field(
        default=False, description="Watch all namespaces (overrides namespace field)"
    )
    timeout_seconds: int = Field(
        default=300, ge=30, le=3600, description="Watch timeout in seconds (30s-1h)"
    )


class ResourceCache(BaseModel):
    """Per-resource cache configuration."""

    enabled: bool = Field(
        default=True, description="Whether caching is enabled for this resource type"
    )
    resync_period: Optional[float] = Field(
        default=None,
        ge=30.0,
        le=86400.0,
        description="Override global resync period (30s-24h, None uses global)",
    )
    max_items: int = Field(
        default=10000,
        ge=1,
        le=1_000_000,
        description="Maximum items to cache for this resource type",
    )
    label_selector: Optional[str] = Field(
        default=None, description="Label selector for this resource type"
    )
    field_selector: Optional[str] = Field(
        default=None, description="Field selector for this resource type"
    )


class CacheStatus(BaseModel):
    """Status information about the cache."""

    enabled: bool
    started: bool = False
    ready: bool = False
    resource_count: int = 0
    informer_count: int = 0
    errors: List[str] = Field(default_factory=list)


class Cache(BaseModel):
    """Cache configuration and control."""

    # Configuration
    enabled: bool = Field(default=True, description="Whether caching is enabled")
    wait_for_sync: bool = Field(
        default=True, description="Auto-wait for initial sync on context enter"
    )
    sync_timeout: float = Field(
        default=30.0, ge=1.0, le=3600.0, description="Cache sync timeout in seconds (1s-1h)"
    )
    resync_period: float = Field(
        default=300.0, ge=30.0, le=86400.0, description="Global resync period in seconds (30s-24h)"
    )
    mode: Literal["strict", "fallback"] = Field(
        default="fallback",
        description="Cache mode: 'strict' (cache-only) or 'fallback' (API fallback)",
    )

    # Scope control
    resources: Optional[List[Type[Resource]]] = Field(
        default=None, description="Resource types to cache (None = cache all discovered types)"
    )
    namespaces: Optional[List[str]] = Field(
        default=None, description="Namespaces to cache (None = all namespaces)"
    )
    label_selector: Optional[str] = Field(
        default=None, description="Global label selector for all cached resources"
    )
    field_selector: Optional[str] = Field(
        default=None, description="Global field selector for all cached resources"
    )

    # Memory management
    max_items_per_resource: int = Field(
        default=10000, ge=100, le=1_000_000, description="Maximum items to cache per resource type"
    )

    # Advanced
    per_resource: Optional[Dict[Type[Resource], Optional[ResourceCache]]] = Field(
        default=None, description="Per-resource cache overrides (None value disables caching)"
    )

    # Runtime state (set internally)
    _factory: Optional[Any] = PrivateAttr(default=None)  # SharedInformerFactory
    _started: bool = PrivateAttr(default=False)

    @model_validator(mode="after")
    def validate_configuration(self) -> Self:
        """Validate cache configuration for consistency."""
        # Validate strict mode configuration
        if self.mode == "strict" and not self.resources:
            raise ValueError(
                "Strict mode requires explicit resource list. "
                "Either specify resources or use 'fallback' mode."
            )

        # Ensure sync_timeout is reasonable compared to resync_period
        if self.sync_timeout > self.resync_period / 2:
            logger.warning(
                "sync_timeout (%0.1fs) is more than half of resync_period (%0.1fs). "
                "Consider reducing sync_timeout for better performance.",
                self.sync_timeout,
                self.resync_period,
            )

        # Validate namespace format if provided
        if self.namespaces:
            for namespace in self.namespaces:
                if not namespace or not isinstance(namespace, str):
                    raise ValueError(f"Invalid namespace: {namespace!r}")
                # Basic DNS-1123 validation
                if not namespace.replace("-", "a").replace("_", "a").isalnum():
                    raise ValueError(
                        f"Namespace '{namespace}' contains invalid characters. "
                        "Must be a valid DNS-1123 label."
                    )

        return self

    def should_cache(self, resource_type: Type[Resource]) -> bool:
        """Check if a resource type should be cached."""
        # Check per-resource config first
        if self.per_resource:
            if resource_type in self.per_resource:
                config = self.per_resource[resource_type]
                return config is not None and config.enabled if config else False

        # Check resource list
        if self.resources is not None:
            return resource_type in self.resources

        # Cache all by default if enabled
        return self.enabled


EventHandler = Callable[[Any], None]
AsyncEventHandler = Callable[[Any], Any]  # Returns awaitable
UpdateHandler = Callable[[Optional[Any], Any], None]
AsyncUpdateHandler = Callable[[Optional[Any], Any], Any]  # Returns awaitable
