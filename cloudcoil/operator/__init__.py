"""Shared operator manifests, installation, and process entry point."""

from ._manifests import RBACRule
from ._operator import Operator
from ._server import WebhookServer

__all__ = ["Operator", "RBACRule", "WebhookServer"]
