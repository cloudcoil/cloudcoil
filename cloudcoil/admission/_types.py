"""Typed admission inputs and explicit policy denials."""

from typing import Any, Literal

from pydantic import ConfigDict, Field

from cloudcoil.pydantic import BaseModel
from cloudcoil.resources import Resource

type Operation = Literal["CREATE", "UPDATE", "DELETE"]


class UserInfo(BaseModel):
    """Identity supplied by the Kubernetes API server, not independently authenticated here."""

    username: str = ""
    uid: str = ""
    groups: list[str] = Field(default_factory=list)
    extra: dict[str, list[str]] = Field(default_factory=dict)


class AdmissionRequest[T: Resource](BaseModel):
    """A typed snapshot of one admission request; DELETE has resource=None.

    Callbacks must have no external side effects, including during dry runs.
    Return an edited resource from a mutator; editing this snapshot and returning
    None has no effect. raw_object and raw_old_object are copies for inspection.
    """

    model_config = ConfigDict(frozen=True)

    uid: str
    operation: Operation
    resource: T | None
    old_resource: T | None
    name: str = ""
    namespace: str = ""
    subresource: str = ""
    dry_run: bool = False
    user_info: UserInfo = Field(default_factory=UserInfo)
    options: dict[str, Any] | None = None
    raw_object: dict[str, Any] | None = None
    raw_old_object: dict[str, Any] | None = None


class AdmissionDenied(Exception):
    """Reject admission with a message visible to the requesting Kubernetes user."""

    def __init__(self, message: str, *, code: int = 403, reason: str = "Forbidden") -> None:
        if not message:
            raise ValueError("An admission denial needs a message")
        if isinstance(code, bool) or not isinstance(code, int) or not 400 <= code <= 599:
            raise ValueError("A denial code must be an integer between 400 and 599")
        super().__init__(message)
        self.code = code
        self.reason = reason
