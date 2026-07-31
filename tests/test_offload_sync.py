"""Tests for offloading sync MCP tools off the uvicorn event loop."""

from __future__ import annotations

import asyncio
import threading
import time
import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from cartesia_mcp.mcpserver import CartesiaMCP
from cartesia_mcp.offload_sync import is_offloaded_sync_tool, offload_sync_callable


def test_offload_sync_callable_leaves_async_unchanged():
    async def already_async() -> str:
        return "ok"

    assert offload_sync_callable(already_async) is already_async


def test_offload_sync_callable_runs_in_worker_thread():
    main_thread = threading.get_ident()
    seen: dict[str, int] = {}

    def blocking() -> str:
        seen["thread"] = threading.get_ident()
        return "done"

    wrapped = offload_sync_callable(blocking)
    assert is_offloaded_sync_tool(wrapped)
    assert asyncio.run(wrapped()) == "done"
    assert seen["thread"] != main_thread


def test_offload_sync_callable_preserves_contextvars():
    from contextvars import ContextVar

    token_var: ContextVar[str] = ContextVar("token_var")
    token_var.set("hosted-key")

    def read_token() -> str:
        return token_var.get()

    wrapped = offload_sync_callable(read_token)
    assert asyncio.run(wrapped()) == "hosted-key"


def test_cartesia_mcp_registers_sync_tools_as_offloaded():
    mcp = CartesiaMCP("test-offload")

    @mcp.tool()
    def sleepy(seconds: float = 0.01) -> str:
        time.sleep(seconds)
        return "awake"

    tool = mcp._tool_manager.get_tool("sleepy")
    assert tool is not None
    assert tool.is_async is True
    assert is_offloaded_sync_tool(tool.fn)


def test_health_stays_responsive_while_sync_tool_runs():
    """Regression for Render health timeouts during long sync SDK tool calls."""

    async def _run() -> None:
        mcp = CartesiaMCP("test-health")
        started = threading.Event()
        release = threading.Event()

        @mcp.tool()
        def block_until_released() -> str:
            started.set()
            assert release.wait(timeout=5), "test timed out waiting for release"
            return "ok"

        async def health(_: Request) -> Response:
            return JSONResponse({"status": "ok"})

        app = Starlette(routes=[Route("/health", endpoint=health, methods=["GET"])])
        tool = mcp._tool_manager.get_tool("block_until_released")
        assert tool is not None

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # Call the offloaded tool body directly (Tool.run requires a Context).
            tool_task = asyncio.create_task(tool.fn())
            deadline = time.monotonic() + 2
            while not started.is_set():
                if time.monotonic() > deadline:
                    raise AssertionError("tool never started")
                await asyncio.sleep(0.01)

            health_times: list[float] = []
            for _ in range(5):
                t0 = time.perf_counter()
                response = await client.get("/health")
                health_times.append(time.perf_counter() - t0)
                assert response.status_code == 200
                assert response.json() == {"status": "ok"}
                await asyncio.sleep(0.05)

            release.set()
            result = await asyncio.wait_for(tool_task, timeout=2)

        assert result == "ok"
        # Health must not wait on the blocked sync tool (Render timeout is 5s).
        assert max(health_times) < 0.5

    asyncio.run(_run())


def test_server_tools_are_offloaded_async():
    import cartesia_mcp.server as server

    tools = server.mcp._tool_manager.list_tools()
    assert tools
    for tool in tools:
        assert tool.is_async, f"{tool.name} should be registered as async"
        assert is_offloaded_sync_tool(tool.fn), f"{tool.name} should offload sync work"
