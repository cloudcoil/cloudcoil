from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cloudcoil.client._config import Config

_configs: ContextVar[tuple["Config", ...] | None] = ContextVar("_configs", default=None)
_default_config = None


class _Context:
    def _enter(self, config: "Config") -> None:
        self.configs = [*(self.configs or []), config]

    def _exit(self, config: "Config | None" = None) -> None:
        configs = self.configs
        if config is not None and (not configs or configs[-1] is not config):
            raise RuntimeError("Configurations must be deactivated in reverse activation order")
        if configs:
            self.configs = configs[:-1]

    def set_default(self, config: "Config") -> None:
        global _default_config
        _default_config = config

    @property
    def active_config(self) -> "Config":
        if not self.configs:
            from cloudcoil.client._config import Config

            config = _default_config or Config()
            self.configs = [config]
        return self.configs[-1]

    @property
    def configs(self) -> list["Config"] | None:
        configs = _configs.get()
        return list(configs) if configs is not None else None

    @configs.setter
    def configs(self, value) -> None:
        _configs.set(tuple(value) if value is not None else None)


context = _Context()
