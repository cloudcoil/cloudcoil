from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cloudcoil.client._client_set import ClientSet

_clientsets = ContextVar("_clientsets", default=None)


class _Context:
    def _enter(self, clientset: "ClientSet") -> None:
        if self.clientsets is None:
            self.clientsets = []
        self.clientsets.append(clientset)

    def _exit(self) -> None:
        if self.clientsets:
            self.clientsets.pop()

    @property
    def active_client_set(self) -> "ClientSet":
        if not self.clientsets:
            from cloudcoil.client._client_set import ClientSet

            self.clientsets = [ClientSet()]
        return self.clientsets[-1]

    @property
    def clientsets(self) -> list["ClientSet"] | None:
        return _clientsets.get()

    @clientsets.setter
    def clientsets(self, value) -> None:
        _clientsets.set(value)


context = _Context()
