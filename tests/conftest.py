"""Shared readiness checks for the end-to-end tests."""

import time

import pytest

from cloudcoil.errors import WaitTimeout


@pytest.fixture
def wait_for_crd_discovery(test_config):
    def wait(resource, timeout=30):
        # Established does not guarantee that aggregated discovery has caught up.
        # Poll the same discovery mapping that create/status/scale will use.
        deadline = time.monotonic() + timeout
        while True:
            test_config.refresh_api_resources()
            try:
                client = test_config.client_for(resource, cached=False)
            except ValueError as error:
                if "is not registered with the server" not in str(error):
                    raise
            else:
                if {"status", "scale"} <= set(client.subresources):
                    return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WaitTimeout(
                    f"Discovery did not expose {resource.gvk()} with status and scale within {timeout}s"
                )
            time.sleep(min(0.1, remaining))

    return wait
