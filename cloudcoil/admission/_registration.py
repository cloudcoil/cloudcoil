"""Shared scoped admission decorators for applications and controllers."""

import hashlib
import inspect
import re
from collections.abc import Callable
from typing import Any

from cloudcoil.resources import Resource

from ._webhook import AdmissionWebhook, Mutator, Validator


class AdmissionRegistry:
    def __init__(self, webhook: AdmissionWebhook, check: Callable[[], None]) -> None:
        self.webhook = webhook
        self.check = check

    def _register[F: Callable[..., Any]](
        self, model: type[Resource], mutation: bool, options: dict[str, Any]
    ) -> Callable[[F], F]:
        def register(handler: F) -> F:
            self.check()
            parameters = list(inspect.signature(handler).parameters.values())
            if (
                not inspect.iscoroutinefunction(handler)
                or len(parameters) != 1
                or parameters[0].kind
                not in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ):
                raise TypeError("Admission handlers must be async and take one AdmissionRequest")
            settings = dict(options)
            path = settings.pop("path", None)
            if path is None:
                target = settings.get("target") or model
                identity = f"{handler.__module__}.{handler.__qualname__}:{target.gvk()}:{settings.get('subresource', '')}"
                digest = hashlib.sha256(identity.encode()).hexdigest()[:12]
                name = (
                    re.sub(r"[^a-z0-9-]", "-", handler.__name__.lower()).strip("-")[:40]
                    or "handler"
                )
                path = f"/{'mutate' if mutation else 'validate'}/{name}-{digest}"
            decorator = self.webhook.mutating if mutation else self.webhook.validating
            decorator(model, path=path, **settings)(handler)
            return handler

        return register

    def validate[T: Resource](
        self, model: type[T], **options: Any
    ) -> Callable[[Validator[T]], Validator[T]]:
        return self._register(model, False, options)

    def mutate[T: Resource](
        self, model: type[T], **options: Any
    ) -> Callable[[Mutator[T]], Mutator[T]]:
        return self._register(model, True, options)
