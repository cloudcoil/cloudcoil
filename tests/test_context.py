import pytest

from cloudcoil.client._config import Config
from cloudcoil.client._context import context


@pytest.fixture
def clean_context():
    # Reset context before each test
    original = context.configs
    context.configs = None
    yield context
    context.configs = original


def test_context_initial_state(clean_context):
    assert clean_context.configs is None


def test_context_enter_first_config(clean_context):
    config = Config()
    clean_context._enter(config)
    assert clean_context.configs == [config]


def test_context_enter_multiple_configs(clean_context):
    config1, config2 = Config(), Config()
    clean_context._enter(config1)
    clean_context._enter(config2)
    assert clean_context.configs == [config1, config2]


def test_context_exit(clean_context):
    config1, config2 = Config(), Config()
    clean_context._enter(config1)
    clean_context._enter(config2)
    clean_context._exit()
    assert clean_context.configs == [config1]
    clean_context._exit()
    assert clean_context.configs == []


def test_active_config_with_empty_stack(clean_context):
    config = clean_context.active_config
    assert isinstance(config, Config)
    assert len(clean_context.configs) == 1


def test_active_config_returns_top_config(clean_context):
    config1, config2 = Config(), Config()
    clean_context._enter(config1)
    clean_context._enter(config2)
    assert clean_context.active_config is config2


def test_configs_property_setter(clean_context):
    configs = [Config(), Config()]
    clean_context.configs = configs
    assert clean_context.configs == configs
