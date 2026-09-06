"""Typed, side-effect-free Kubernetes admission webhooks."""

from ._decorators import mutating, validating
from ._types import AdmissionDenied, AdmissionRequest, Operation, UserInfo
from ._webhook import AdmissionWebhook

__all__ = [
    "AdmissionDenied",
    "AdmissionRequest",
    "AdmissionWebhook",
    "Operation",
    "UserInfo",
    "mutating",
    "validating",
]
