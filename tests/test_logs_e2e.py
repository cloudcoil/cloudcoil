"""Real API-server/kubelet log protocol coverage across the existing CI matrix."""

import asyncio
import os
import time
from importlib.metadata import version

import pytest
from cloudcoil.models.kubernetes.core.v1 import Namespace, Pod

from cloudcoil import logs

k8s_version = ".".join(version("cloudcoil.models.kubernetes").split(".")[:3])


@pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-sync-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=os.environ.get("CLUSTER_PROVIDER", "kind"),
    remove=False,
)
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_live_logs_discovery_and_filtering(test_config, asynchronous):
    async with test_config:
        ns = await Namespace(metadata={"generateName": "test-logs-"}).async_create()
        try:
            pod = await Pod.model_validate(
                {
                    "metadata": {
                        "name": "logger",
                        "namespace": ns.name,
                        "labels": {"app": "log-test"},
                    },
                    "spec": {
                        "restartPolicy": "Never",
                        "initContainers": [
                            {
                                "name": "setup",
                                "image": "busybox:1.36",
                                "command": ["sh", "-c", "echo initialized"],
                            }
                        ],
                        "containers": [
                            {
                                "name": "app",
                                "image": "busybox:1.36",
                                "command": ["sh", "-c", "printf 'hello\\nERROR example\\n'"],
                            }
                        ],
                    },
                }
            ).async_create()
            deadline = time.monotonic() + 180
            while True:
                pod = await Pod.async_get("logger", ns.name)
                if pod.status and pod.status.phase == "Succeeded":
                    break
                assert not pod.status or pod.status.phase != "Failed", pod.status
                assert time.monotonic() < deadline, pod.status
                await asyncio.sleep(0.2)

            kwargs = dict(
                config=test_config, namespace=ns.name, label_selector="app=log-test", page_size=1
            )
            sources = (
                [s async for s in logs.async_discover(**kwargs)]
                if asynchronous
                else list(logs.discover(**kwargs))
            )
            assert {s.container for s in sources} == {"app", "setup"}
            app = next(s for s in sources if s.container == "app")
            assert app.pod_uid == pod.metadata.uid
            assert app.state == "terminated"
            assert app.labels == {"app": "log-test"}
            text = (
                await logs.async_read(app, tail_lines=1)
                if asynchronous
                else logs.read(app, tail_lines=1)
            )
            assert text == "ERROR example\n"
            # A completed container makes follow finite while still testing the kubelet's
            # follow protocol and timestamp framing; mock tests cover indefinite quiet streams.
            if asynchronous:
                async with logs.async_stream(
                    app, match=logs.LogFilter(contains="ERROR")
                ) as records:
                    result = [record async for record in records]
            else:
                with logs.stream(app, match=logs.LogFilter(contains="ERROR")) as records:
                    result = list(records)
            assert len(result) == 1
            assert result[0].message == "ERROR example"
            assert result[0].timestamp is not None
            assert result[0].source is app
            setup = next(s for s in sources if s.container_type == "init")
            text = await logs.async_read(setup) if asynchronous else logs.read(setup)
            assert text == "initialized\n"
        finally:
            await ns.async_remove()
