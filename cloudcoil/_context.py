from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cloudcoil.client._config import Config

_configs = ContextVar("_configs", default=None)


class _Context:
    def _enter(self, config: "Config") -> None:
        if self.configs is None:
            self.configs = []
        self.configs.append(config)

    def _exit(self) -> None:
        if self.configs:
            self.configs.pop()

    @property
    def active_config(self) -> "Config":
        if not self.configs:
            from cloudcoil.client._config import Config

            config = Config()
            self.configs = [config]
        return self.configs[-1]

    @property
    def configs(self) -> list["Config"] | None:
        return _configs.get()

    @configs.setter
    def configs(self, value) -> None:
        _configs.set(value)


context = _Context()
