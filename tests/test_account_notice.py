"""Any tool result can carry a message from Cartesia for the user (GET /notices)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent

import cartesia_mcp.extra_api as extra_api
import cartesia_mcp.notices as notices
from cartesia_mcp.mcpserver import CartesiaMCP

NOTICE = (
    "Cartesia's product team would love to hear what you're building. Tell us on a "
    "30-minute call and get $100 in free credits: https://play.cartesia.ai/agents?research_invite=open"
)


@pytest.fixture(autouse=True)
def _fresh_notice_checks() -> None:
    notices._checked_at.clear()


def _client_answering(body: object) -> MagicMock:
    sdk = MagicMock()
    sdk.with_options.return_value.get.return_value = body
    return sdk


def test_get_account_notice_asks_the_backend_and_trims() -> None:
    sdk = _client_answering({"notice": f"  {NOTICE} "})
    assert extra_api.get_account_notice(sdk) == NOTICE
    url = sdk.with_options.return_value.get.call_args.args[0]
    assert url == "https://backend.cartesia.ai/notices"
    assert sdk.with_options.call_args.kwargs == {"timeout": 3.0, "max_retries": 0}


@pytest.mark.parametrize("body", [{"notice": None}, {"notice": "   "}, {}, "not json"])
def test_get_account_notice_is_none_when_theres_nothing(body: object) -> None:
    assert extra_api.get_account_notice(_client_answering(body)) is None


def test_backend_url_can_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARTESIA_BACKEND_BASE_URL", "http://localhost:10000/")
    sdk = _client_answering({"notice": None})
    extra_api.get_account_notice(sdk)
    assert sdk.with_options.return_value.get.call_args.args[0] == "http://localhost:10000/notices"


@patch("cartesia_mcp.notices.resolve_api_credential", return_value="sk_car_a")
@patch("cartesia_mcp.notices.extra_api.get_account_notice", return_value=NOTICE)
def test_asks_once_per_key_until_the_wait_is_over(get_notice: MagicMock, _cred: MagicMock) -> None:
    with patch("cartesia_mcp.notices.time.monotonic", return_value=1000.0):
        assert notices.account_notice() == NOTICE
        assert notices.account_notice() is None
    with patch(
        "cartesia_mcp.notices.time.monotonic",
        return_value=1000.0 + notices.NOTICE_CHECK_SECONDS,
    ):
        assert notices.account_notice() == NOTICE
    assert get_notice.call_count == 2


@patch("cartesia_mcp.notices.extra_api.get_account_notice", return_value=NOTICE)
def test_each_key_is_asked_on_its_own(get_notice: MagicMock) -> None:
    with patch("cartesia_mcp.notices.time.monotonic", return_value=1000.0):
        with patch("cartesia_mcp.notices.resolve_api_credential", return_value="sk_car_a"):
            notices.account_notice()
        with patch("cartesia_mcp.notices.resolve_api_credential", return_value="sk_car_b"):
            notices.account_notice()
    assert get_notice.call_count == 2


@patch("cartesia_mcp.notices.resolve_api_credential", return_value="sk_car_a")
@patch("cartesia_mcp.notices.extra_api.get_account_notice", side_effect=RuntimeError("backend down"))
def test_a_failed_check_is_no_notice(_get: MagicMock, _cred: MagicMock) -> None:
    assert notices.account_notice() is None


@patch("cartesia_mcp.notices.resolve_api_credential", side_effect=ValueError("no credential"))
def test_no_credential_is_no_notice(_cred: MagicMock) -> None:
    assert notices.account_notice() is None


def test_with_notice_adds_its_own_block_and_keeps_the_result() -> None:
    original = CallToolResult(
        content=[TextContent(type="text", text="{}")],
        structured_content={"voices": []},
    )
    result = notices.with_notice(original, NOTICE)
    assert result.content[0] == original.content[0]
    assert isinstance(result.content[1], TextContent)
    assert result.content[1].text.endswith(NOTICE)
    assert result.structured_content == {"voices": []}


def _server() -> CartesiaMCP:
    server = CartesiaMCP("test")

    def list_things() -> dict[str, list[str]]:
        return {"things": ["a"]}

    def broken() -> str:
        raise RuntimeError("nope")

    server.add_tool(list_things, name="list_things")
    server.add_tool(broken, name="broken")
    return server


@patch("cartesia_mcp.mcpserver.account_notice", return_value=NOTICE)
def test_any_tool_result_carries_the_notice(_notice: MagicMock) -> None:
    result = asyncio.run(_server().call_tool("list_things", {}))
    assert isinstance(result, CallToolResult)
    assert isinstance(result.content[-1], TextContent)
    assert result.content[-1].text.endswith(NOTICE)


@patch("cartesia_mcp.mcpserver.account_notice", return_value=None)
def test_no_notice_leaves_the_result_unchanged(_notice: MagicMock) -> None:
    result = asyncio.run(_server().call_tool("list_things", {}))
    assert isinstance(result, CallToolResult)
    assert len(result.content) == 1


@patch("cartesia_mcp.mcpserver.account_notice", return_value=NOTICE)
def test_a_failed_tool_never_asks(notice: MagicMock) -> None:
    with pytest.raises(ToolError):
        asyncio.run(_server().call_tool("broken", {}))
    notice.assert_not_called()
