import asyncio
from functools import wraps
from typing import Any, Callable, Coroutine, ParamSpec, TypeVar

P = ParamSpec("P")
A = TypeVar("A")
B = TypeVar("B")
T = TypeVar("T")


def async_to_sync[T, A, B, **P](
    f: Callable[P, Coroutine[A, B, T]],
) -> Callable[[Callable[..., Any]], Callable[P, T]]:
    def decorator(_: Callable) -> Callable[P, T]:
        @wraps(f)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            event_loop = asyncio.get_event_loop()
            return event_loop.run_until_complete(f(*args, **kwargs))

        return wrapper

    return decorator
