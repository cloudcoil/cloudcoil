"""Kubernetes clients; Config is loaded lazily to avoid the informer import cycle."""

from typing import TYPE_CHECKING, Any

from ._api_client import APIClient, AsyncAPIClient

if TYPE_CHECKING:
    from ._config import Config

__all__ = ["Config", "APIClient", "AsyncAPIClient"]


def __getattr__(name: str) -> Any:
    if name == "Config":
        from ._config import Config

        globals()[name] = Config
        return Config
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
