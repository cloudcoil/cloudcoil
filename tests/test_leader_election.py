import asyncio
import json
from copy import deepcopy

import httpx
import pytest
from cloudcoil.models.kubernetes.core.v1 import ConfigMap

from cloudcoil.client import Config
from cloudcoil.controller import Controller, LeaderElection, LeadershipLost, Manager
from cloudcoil.errors import APIError


class LeaseServer:
    def __init__(self):
        self.lease = None
        self.version = 0
        self.error = None
        self.hang = False
        self.conflict = False
        self.requests = []

    async def handle(self, request):
        self.requests.append(request)
        if self.hang:
            await asyncio.Event().wait()
        if self.error:
            return httpx.Response(self.error, json={"message": "lease unavailable"})
        if request.method == "GET":
            if self.lease is None:
                return httpx.Response(404)
            return httpx.Response(200, json=self.lease)
        body = json.loads(request.content)
        if request.method == "POST":
            if self.lease is not None:
                return httpx.Response(409)
            body["metadata"]["uid"] = "lease-uid"
        elif request.method == "PUT":
            if self.lease is None:
                return httpx.Response(404)
            if (
                self.conflict
                or body["metadata"]["resourceVersion"] != self.lease["metadata"]["resourceVersion"]
            ):
                self.conflict = False
                return httpx.Response(409)
            assert body["metadata"]["uid"] == self.lease["metadata"]["uid"]
        else:
            pytest.fail(f"Unexpected {request.method}")
        self.version += 1
        body["metadata"]["resourceVersion"] = str(self.version)
        self.lease = deepcopy(body)
        return httpx.Response(201 if request.method == "POST" else 200, json=body)


@pytest.fixture
async def leases():
    server = LeaseServer()
    config = Config(server="https://cluster", namespace="ns")
    config.async_client._mounts.clear()
    config.async_client._transport = httpx.MockTransport(server.handle)
    yield server, config
    config.client.close()
    await config.async_client.aclose()


def election(identity="one", **kwargs):
    return LeaderElection(
        "controller",
        identity=identity,
        lease_duration=1,
        renew_deadline=0.15,
        retry_period=0.02,
        **kwargs,
    )


async def wait(awaitable):
    return await asyncio.wait_for(awaitable, 2)


async def test_lease_create_renew_and_release(leases):
    server, config = leases
    leader = election()
    entered, stop = asyncio.Event(), asyncio.Event()

    async def work():
        entered.set()
        await stop.wait()

    task = asyncio.create_task(leader._run(work, config=config, stop=stop))
    try:
        await wait(entered.wait())
        assert leader.is_leader
        assert server.lease["spec"]["holderIdentity"] == "one"
        await leader._attempt(config)
        assert server.lease["spec"]["leaseTransitions"] == 0
    finally:
        stop.set()
        await wait(task)
    assert not leader.is_leader
    assert server.lease["spec"]["holderIdentity"] == ""
    assert all(
        request.url.path.startswith("/apis/coordination.k8s.io/v1/namespaces/ns/leases")
        for request in server.requests
    )


async def test_two_contenders_handoff_only_after_old_work_finishes(leases):
    server, config = leases
    first, second = election("first"), election("second")
    stops = [asyncio.Event(), asyncio.Event()]
    entered = [asyncio.Event(), asyncio.Event()]
    active = set()

    async def work(index):
        assert not active
        active.add(index)
        entered[index].set()
        try:
            await stops[index].wait()
            await asyncio.sleep(0.05)  # Simulate draining old workers while renewal continues.
        finally:
            active.remove(index)

    a = asyncio.create_task(first._run(lambda: work(0), config=config, stop=stops[0]))
    await wait(entered[0].wait())
    b = asyncio.create_task(second._run(lambda: work(1), config=config, stop=stops[1]))
    try:
        await asyncio.sleep(0.04)
        assert not entered[1].is_set()
        stops[0].set()
        await wait(a)
        await wait(entered[1].wait())
        assert active == {1}
        assert server.lease["spec"]["holderIdentity"] == "second"
        assert server.lease["spec"]["leaseTransitions"] == 1
    finally:
        for stop in stops:
            stop.set()
        await asyncio.gather(a, b)


async def test_remote_clock_skew_does_not_trigger_premature_takeover(leases):
    server, config = leases
    original = election("old")
    assert await original._attempt(config)
    server.lease["spec"]["renewTime"] = "1900-01-01T00:00:00Z"
    contender = election("new")
    clock = [100.0]
    contender._clock = lambda: clock[0]
    assert not await contender._attempt(config)
    clock[0] = 100.9
    assert not await contender._attempt(config)
    # Metadata-only changes must not reset the lease observation clock.
    server.lease["metadata"]["resourceVersion"] = "metadata-change"
    clock[0] = 101.1
    assert await contender._attempt(config)
    assert server.lease["spec"]["holderIdentity"] == "new"


async def test_changed_renew_record_resets_observation_deadline(leases):
    server, config = leases
    assert await election("old")._attempt(config)
    contender = election("new")
    clock = [100.0]
    contender._clock = lambda: clock[0]
    assert not await contender._attempt(config)
    clock[0] = 100.9
    server.lease["spec"]["renewTime"] = "2200-01-01T00:00:00Z"
    assert not await contender._attempt(config)
    clock[0] = 101.1
    assert not await contender._attempt(config)
    clock[0] = 102.0
    assert await contender._attempt(config)


@pytest.mark.parametrize("failure", ["timeout", "server", "deleted", "stolen", "recreated"])
async def test_loss_cancels_work_and_does_not_release_successor(leases, failure):
    server, config = leases
    leader = election()
    entered, exited, stop = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def work():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            exited.set()

    task = asyncio.create_task(leader._run(work, config=config, stop=stop))
    await wait(entered.wait())
    if failure == "timeout":
        server.hang = True
    elif failure == "server":
        server.error = 503
    elif failure == "deleted":
        server.lease = None
    elif failure == "stolen":
        server.lease["spec"]["holderIdentity"] = "successor"
    else:
        server.lease["metadata"]["uid"] = "new-lease"
    with pytest.raises(LeadershipLost):
        await wait(task)
    assert exited.is_set() and not leader.is_leader
    if failure == "stolen":
        assert server.lease["spec"]["holderIdentity"] == "successor"
    if failure == "recreated":
        assert server.lease["spec"]["holderIdentity"] == "one"


async def test_conflicting_update_is_retried_and_forbidden_is_fatal(leases):
    server, config = leases
    leader = election()
    assert await leader._attempt(config)
    server.conflict = True
    assert not await leader._attempt(config)
    assert await leader._attempt(config)
    server.error = 403
    with pytest.raises(APIError) as caught:
        await leader._attempt(config)
    assert caught.value.status_code == 403


async def test_standby_stop_never_starts_work(leases):
    server, config = leases
    assert await election("other")._attempt(config)
    leader, stop = election(), asyncio.Event()

    async def work():
        pytest.fail("standby must not start work")

    task = asyncio.create_task(leader._run(work, config=config, stop=stop))
    await asyncio.sleep(0.03)
    stop.set()
    await wait(task)
    assert server.lease["spec"]["holderIdentity"] == "other"


async def test_cancellation_joins_work_before_releasing(leases):
    server, config = leases
    leader, entered = election(), asyncio.Event()

    async def work():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            assert server.lease["spec"]["holderIdentity"] == "one"

    task = asyncio.create_task(leader._run(work, config=config, stop=asyncio.Event()))
    await wait(entered.wait())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert server.lease["spec"]["holderIdentity"] == ""


async def test_manager_standby_has_no_informers_and_failure_reaches_readiness(leases):
    server, config = leases
    assert await election("other")._attempt(config)

    async def reconcile(request):
        pytest.fail("standby must not reconcile")

    manager = Manager(Controller(ConfigMap, reconcile), config=config, leader_election=election())
    task = asyncio.create_task(manager.run())
    await asyncio.sleep(0.03)
    assert not manager.ready and manager.informer_count == 0
    server.error = 403
    with pytest.raises(APIError):
        await manager.wait_ready(2)
    with pytest.raises(APIError):
        await wait(task)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "../bad"},
        {"namespace": "bad/ns"},
        {"identity": ""},
        {"lease_duration": 1.5},
        {"lease_duration": True},
        {"renew_deadline": 20},
        {"retry_period": 10},
        {"retry_period": float("nan")},
    ],
)
def test_invalid_election_settings(kwargs):
    with pytest.raises(ValueError):
        LeaderElection(**{"name": "controller", **kwargs})
