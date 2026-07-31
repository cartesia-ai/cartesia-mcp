"""Run sync MCP tool bodies off the asyncio event loop.

Hosted streamable-http serves `/health` on the same uvicorn loop that executes
tools. Sync Cartesia SDK calls can block that loop long enough for Render's 5s
health timeout to fail and restart the instance.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import Callable
from typing import Any, TypeVar, cast

F = TypeVar("F", bound=Callable[..., Any])


def offload_sync_callable(fn: F) -> F:
    """Wrap a sync callable so MCPServer awaits it via ``asyncio.to_thread``.

    Contextvars are copied into the worker thread (Python 3.11+), so hosted
    request-scoped API credentials remain available inside the tool body.
    """
    if inspect.iscoroutinefunction(fn):
        return fn

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        return await asyncio.to_thread(fn, *args, **kwargs)

    return cast(F, wrapper)


def is_offloaded_sync_tool(fn: Callable[..., Any]) -> bool:
    """True when ``fn`` is an async wrapper produced by :func:`offload_sync_callable`."""
    if not inspect.iscoroutinefunction(fn):
        return False
    original = getattr(fn, "__wrapped__", None)
    return original is not None and not inspect.iscoroutinefunction(original)
