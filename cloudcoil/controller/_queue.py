"""An event-loop-local, deduplicating workqueue with delayed retries."""

import asyncio
import math
import random
from collections import deque
from collections.abc import Hashable


class QueueClosed(Exception):
    """The queue has shut down and has no ready work."""


class WorkQueue[K: Hashable]:
    """Serialize each key while allowing different keys to run concurrently.

    Call add/done/retry from the same event loop as get. Repeated adds coalesce;
    an add during processing guarantees one more pass after done. Delayed work
    uses one timer per key, never a sleeping task per event. This is an in-memory
    queue: restart recovery comes from listing the desired Kubernetes state.
    """

    def __init__(
        self, *, base_delay: float = 1.0, max_delay: float = 60.0, jitter: float = 0.1
    ) -> None:
        if not all(math.isfinite(v) for v in (base_delay, max_delay, jitter)):
            raise ValueError("Retry settings must be finite")
        if base_delay <= 0 or max_delay < base_delay or not 0 <= jitter <= 1:
            raise ValueError("Require 0 < base_delay <= max_delay and 0 <= jitter <= 1")
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._jitter = jitter
        self._ready: deque[K] = deque()
        self._dirty: set[K] = set()
        self._processing: set[K] = set()
        self._delayed: dict[K, asyncio.TimerHandle] = {}
        self._retries: dict[K, int] = {}
        self._available = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._closed = False
        self._immediate = False

    def add(self, key: K) -> None:
        """Request reconciliation now; fresh events supersede a delayed retry."""
        if self._closed:
            return
        timer = self._delayed.pop(key, None)
        if timer is not None:
            timer.cancel()
        if key in self._dirty:
            return
        self._idle.clear()
        self._dirty.add(key)
        if key not in self._processing:
            self._ready.append(key)
            self._available.set()

    def add_after(self, key: K, delay: float) -> None:
        """Schedule a key, preserving the earliest pending deadline."""
        if not math.isfinite(delay) or delay < 0:
            raise ValueError("delay must be finite and nonnegative")
        if self._closed:
            return
        if delay == 0:
            self.add(key)
            return
        if key in self._dirty:
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + delay
        current = self._delayed.get(key)
        if current is not None:
            if current.when() <= deadline:
                return
            current.cancel()
        self._idle.clear()
        self._delayed[key] = loop.call_at(deadline, self._release, key)

    def _release(self, key: K) -> None:
        self._delayed.pop(key, None)
        self.add(key)

    def retry(self, key: K) -> float:
        """Schedule exponential backoff with jitter and return the chosen delay."""
        if self._closed:
            return 0.0
        attempt = self._retries.get(key, 0)
        self._retries[key] = attempt + 1
        # Clamp the exponent before computing it, even after prolonged failures.
        cap = math.ceil(math.log2(self._max_delay) - math.log2(self._base_delay))
        delay = self._max_delay if attempt >= cap else math.ldexp(self._base_delay, attempt)
        delay = min(self._max_delay, delay * random.uniform(1 - self._jitter, 1 + self._jitter))
        self.add_after(key, delay)
        return delay

    def forget(self, key: K) -> None:
        """Reset failure history after success or a terminal error."""
        self._retries.pop(key, None)

    def num_retries(self, key: K) -> int:
        """Return consecutive retry requests since the last forget."""
        return self._retries.get(key, 0)

    async def get(self) -> K:
        """Take the next key; always pair a successful get with done in finally."""
        while not self._ready:
            if self._closed:
                raise QueueClosed
            self._available.clear()
            await self._available.wait()
        key = self._ready.popleft()
        self._dirty.remove(key)
        self._processing.add(key)
        return key

    def done(self, key: K) -> None:
        """Release a processing key and queue any update that arrived meanwhile."""
        if key not in self._processing:
            raise ValueError("done called for a key that is not processing")
        self._processing.remove(key)
        if key in self._dirty and not self._immediate:
            self._ready.append(key)
            self._available.set()
        self._check_idle()

    async def join(self) -> None:
        """Wait until ready, processing, and delayed work are all finished."""
        await self._idle.wait()

    def shutdown(self, *, immediate: bool = False) -> None:
        """Reject new work and discard timers; optionally discard ready work too.

        With immediate=False, consumers can drain accepted ready/dirty work.
        In-flight work always requires done; shutdown never cancels callers.
        """
        self._closed = True
        self._immediate = self._immediate or immediate
        for timer in self._delayed.values():
            timer.cancel()
        self._delayed.clear()
        self._retries.clear()
        if self._immediate:
            self._ready.clear()
            self._dirty.clear()
        self._available.set()
        self._check_idle()

    def _check_idle(self) -> None:
        if not (self._dirty or self._processing or self._delayed):
            self._idle.set()
