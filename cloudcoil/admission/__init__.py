"""Typed, side-effect-free Kubernetes admission webhooks."""

from ._types import AdmissionDenied, AdmissionRequest, Operation, UserInfo
from ._webhook import AdmissionWebhook

__all__ = ["AdmissionDenied", "AdmissionRequest", "AdmissionWebhook", "Operation", "UserInfo"]
