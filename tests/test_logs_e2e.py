"""Real API-server/kubelet log protocol coverage across the existing CI matrix."""

import asyncio
import os
import time
from importlib.metadata import version

import pytest
from cloudcoil.models.kubernetes.core.v1 import Namespace, Pod, ServiceAccount

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
            # Namespace creation does not wait for the default ServiceAccount controller.
            await ServiceAccount(metadata={"name": "logger", "namespace": ns.name}).async_create()
            pod = await Pod.model_validate(
                {
                    "metadata": {
                        "name": "logger",
                        "namespace": ns.name,
                        "labels": {"app": "log-test"},
                    },
                    "spec": {
                        "serviceAccountName": "logger",
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


@pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-sync-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=os.environ.get("CLUSTER_PROVIDER", "kind"),
    remove=False,
)
@pytest.mark.parametrize("kind", ["Deployment", "ReplicaSet", "StatefulSet"])
async def test_live_workload_logs(test_config, kind):
    from cloudcoil.resources import get_model

    model = get_model(kind, api_version="apps/v1")

    async with test_config:
        ns = await Namespace(metadata={"generateName": "test-workload-logs-"}).async_create()
        try:
            data = {
                "metadata": {"name": "workers", "namespace": ns.name},
                "spec": {
                    "replicas": 2,
                    "selector": {
                        "matchExpressions": [
                            {"key": "app", "operator": "In", "values": ["log-test"]},
                        ]
                    },
                    "template": {
                        "metadata": {"labels": {"app": "log-test"}},
                        "spec": {
                            "containers": [
                                {
                                    "name": "app",
                                    "image": "busybox:1.36",
                                    "command": ["sh", "-c", "echo 'ERROR hello'; sleep 600"],
                                }
                            ]
                        },
                    },
                },
            }
            if kind == "StatefulSet":
                data["spec"]["serviceName"] = "workers"
            workload = await model.model_validate(data).async_create()
            deadline = time.monotonic() + 180
            while True:
                workload = await model.async_get("workers", ns.name)
                if workload.status and workload.status.ready_replicas == 2:
                    break
                assert time.monotonic() < deadline, workload.status
                await asyncio.sleep(0.2)

            sources = list(logs.discover(workload, page_size=1))
            assert len(sources) == 2
            assert len({source.pod for source in sources}) == 2
            assert all(source.container == "app" for source in sources)
            assert logs.read(workload) == "ERROR hello\n"
            assert (
                await logs.async_read(f"{kind.lower()}/workers", namespace=ns.name)
                == "ERROR hello\n"
            )
            with logs.stream(workload, follow=False) as records:
                record = next(records)
                assert record.message == "ERROR hello"
                assert record.source.pod_uid in {source.pod_uid for source in sources}
            # With two live containers, only concurrent following can receive both.
            async with asyncio.timeout(30):
                async with logs.async_stream(
                    f"{kind.lower()}/workers",
                    namespace=ns.name,
                    all_pods=True,
                    match=logs.LogFilter(contains="ERROR"),
                ) as records:
                    seen = set()
                    async for record in records:
                        assert record.timestamp is not None
                        seen.add(record.pod)
                        if len(seen) == 2:
                            break
            assert seen == {source.pod for source in sources}
            async with logs.async_stream(
                workload, all_pods=True, follow=False, max_streams=1
            ) as records:
                result = [record async for record in records]
            assert {record.pod for record in result} == seen
            assert all(record.message == "ERROR hello" for record in result)
        finally:
            await ns.async_remove()


@pytest.mark.configure_test_cluster(
    cluster_name=f"test-cloudcoil-sync-v{k8s_version}",
    version=f"v{k8s_version}",
    provider=os.environ.get("CLUSTER_PROVIDER", "kind"),
    remove=False,
)
async def test_live_cronjob_ownership_logs(test_config):
    from cloudcoil.models.kubernetes.batch.v1 import CronJob, Job

    async with test_config:
        ns = await Namespace(metadata={"generateName": "test-owned-logs-"}).async_create()
        try:
            spec = {
                "template": {
                    "spec": {
                        "restartPolicy": "Never",
                        "containers": [
                            {
                                "name": "app",
                                "image": "busybox:1.36",
                                "command": ["sh", "-c", "echo owned"],
                            }
                        ],
                    }
                }
            }
            cron = await CronJob.model_validate(
                {
                    "metadata": {"name": "nightly", "namespace": ns.name},
                    "spec": {
                        "schedule": "0 0 * * *",
                        "suspend": True,
                        "jobTemplate": {"spec": spec},
                    },
                }
            ).async_create()
            # Create a run with the same ownership relationship as the CronJob controller,
            # so the test exercises real persisted ownership without a scheduling delay.
            job = await Job.model_validate(
                {
                    "metadata": {
                        "name": "run",
                        "namespace": ns.name,
                        "ownerReferences": [
                            {
                                "apiVersion": "batch/v1",
                                "kind": "CronJob",
                                "name": cron.name,
                                "uid": cron.metadata.uid,
                                "controller": True,
                            }
                        ],
                    },
                    "spec": spec,
                }
            ).async_create()
            deadline = time.monotonic() + 180
            while True:
                job = await Job.async_get("run", ns.name)
                if job.status and job.status.succeeded == 1:
                    break
                assert time.monotonic() < deadline, job.status
                await asyncio.sleep(0.2)
            sources = list(logs.discover(cron))
            assert len(sources) == 1 and sources[0].container == "app"
            assert logs.read("cj/nightly", namespace=ns.name) == "owned\n"
            assert await logs.async_read(cron) == "owned\n"
            async with logs.async_stream(cron, all_pods=True, follow=False) as records:
                result = [record async for record in records]
            assert len(result) == 1 and result[0].message == "owned"
            assert result[0].pod == sources[0].pod
        finally:
            await ns.async_remove()
