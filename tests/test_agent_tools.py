import json
import typing
from collections.abc import Callable, Iterator
from unittest.mock import patch

import httpx
import pytest
from cartesia import Cartesia

import cartesia_mcp.server as server
from cartesia_mcp.utils import CONDENSED_TOOL_RESULT_CHARS, condense_agent_call

CALL = {
    "id": "ac_1",
    "agent_id": "agent_1",
    "agent_name": "support",
    "agent_version_id": "av_1",
    "status": "failed",
    "end_reason": "call_inactivity",
    "error_message": "Call terminated due to call inactivity timeout",
    "start_time": "2026-09-15T02:30:24Z",
    "end_time": "2026-09-15T02:34:35Z",
    "summary": "Caller said nothing.",
    "zdr_enabled": False,
    "telephony_params": {
        "from": "websocket",
        "to": "agent_1",
        "call_sid": "sid_1",
        "connection_type": "websocket",
    },
    "dynamic_variables": {"patient_name": "Ada"},
    "transcript": [
        {
            "id": 1,
            "role": "assistant",
            "text": "Hi, how can I help?",
            "start_timestamp": 0.06,
            "end_timestamp": 3.7,
            "was_interrupted": False,
            "tts_ttfb": 0.062,
        },
        {
            "id": 2,
            "role": "user",
            "text": "Look up my order.",
            "start_timestamp": 5.0,
            "end_timestamp": 6.0,
            "was_interrupted": True,
            "tool_calls": [
                {
                    "id": "tc_1",
                    "name": "lookup_order",
                    "arguments": {"order_id": "42"},
                    "result": "x" * (CONDENSED_TOOL_RESULT_CHARS + 10),
                }
            ],
        },
    ],
}

AGENT = {
    "id": "agent_1",
    "name": "Support",
    "description": None,
    "created_at": "2026-08-28T18:33:03Z",
    "updated_at": "2026-08-28T18:33:03Z",
    "config": {"instructions": "Help callers."},
    "version": {"id": "av_1", "created_at": "2026-08-28T18:33:03Z"},
}

Handler = Callable[[httpx.Request], typing.Any]


class Api:
    """Fake Cartesia API: records requests and answers from a route table."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: dict[tuple[str, str], Handler] = {}

    def on(self, method: str, path: str, body: typing.Any) -> None:
        self.routes[(method, path)] = lambda _request: body

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        handler = self.routes.get((request.method, request.url.raw_path.decode().split("?")[0]))
        if handler is None:
            return httpx.Response(404, json={"error": "not found"})
        body = handler(request)
        return httpx.Response(204) if body is None else httpx.Response(200, json=body)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]


@pytest.fixture
def api() -> Iterator[Api]:
    fake = Api()
    sdk = Cartesia(
        api_key="sk_test",
        base_url="https://api.test",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(fake._handle)),
    )
    with patch("cartesia_mcp.server.client", sdk):
        yield fake


def _query(request: httpx.Request) -> dict[str, str]:
    return dict(request.url.params)


def test_get_agent_call_condenses_by_default(api: Api) -> None:
    api.on("GET", "/agents/calls/ac_1", CALL)

    result = server.get_agent_call("ac_1")

    assert result["status"] == "failed"
    assert result["end_reason"] == "call_inactivity"
    assert result["agent_version_id"] == "av_1"
    assert result["dynamic_variables"] == {"patient_name": "Ada"}
    assert result["connection"] == {
        "connection_type": "websocket",
        "from": "websocket",
        "to": "agent_1",
    }
    assert "transcript" not in result
    assert "zdr_enabled" not in result

    first, second = result["turns"]
    assert first == {
        "role": "assistant",
        "text": "Hi, how can I help?",
        "start_s": 0.06,
        "end_s": 3.7,
        "interrupted": False,
        "tts_ttfb_s": 0.062,
    }
    assert second["interrupted"] is True
    tool_call = second["tool_calls"][0]
    assert tool_call["name"] == "lookup_order"
    assert tool_call["arguments"] == {"order_id": "42"}
    assert len(tool_call["result"]) == CONDENSED_TOOL_RESULT_CHARS
    assert tool_call["result_truncated"] is True
    assert tool_call["result_chars"] == CONDENSED_TOOL_RESULT_CHARS + 10


def test_get_agent_call_full_keeps_fields_the_sdk_does_not_model(api: Api) -> None:
    api.on("GET", "/agents/calls/ac_1", CALL)

    result = server.get_agent_call("ac_1", detail="full")

    assert result["transcript"][1]["tool_calls"][0]["result"] == CALL["transcript"][1][
        "tool_calls"
    ][0]["result"]
    assert result["telephony_params"]["call_sid"] == "sid_1"


def test_list_agent_calls_sends_filters_omits_transcript_and_sets_cursor(api: Api) -> None:
    api.on("GET", "/agents/calls", {"data": [CALL], "has_more": True})

    result = server.list_agent_calls("agent_1", limit=5, starting_after="ac_9")

    assert _query(api.last) == {"agent_id": "agent_1", "limit": "5", "starting_after": "ac_9"}
    row = result["data"][0]
    assert row["id"] == "ac_1"
    assert row["end_reason"] == "call_inactivity"
    assert "transcript" not in row
    assert result["has_more"] is True
    assert result["next_page"] == "ac_1"


def test_list_agent_versions_drops_config(api: Api) -> None:
    api.on(
        "GET",
        "/v1/agents/agent_1/versions",
        {
            "data": [
                {
                    "id": "av_1",
                    "created_at": "2026-08-28T18:33:03Z",
                    "description": "v1",
                    "config": {"instructions": "long prompt"},
                }
            ],
            "has_more": False,
        },
    )

    result = server.list_agent_versions("agent_1")

    assert result == {
        "data": [{"id": "av_1", "created_at": "2026-08-28T18:33:03Z", "description": "v1"}],
        "has_more": False,
    }


def test_get_agent_version_path(api: Api) -> None:
    api.on("GET", "/v1/agents/agent_1/versions/av_1", {"id": "av_1", "config": {}})

    assert server.get_agent_version("agent_1", "av_1")["id"] == "av_1"


def test_list_phone_numbers_filters_and_cursor(api: Api) -> None:
    api.on(
        "GET",
        "/agents/phone-numbers",
        {"data": [{"id": "pn_1", "number": "+15550100", "agent": None}], "has_more": True},
    )

    result = server.list_phone_numbers(agent_id="agent_1", type="sip_trunk")

    assert _query(api.last) == {"agent_id": "agent_1", "type": "sip_trunk", "limit": "10"}
    assert result["data"][0]["number"] == "+15550100"
    assert result["next_page"] == "pn_1"


def test_ids_stay_one_path_segment(api: Api) -> None:
    for call in (
        lambda: server.get_agent_call("ac_1/logs?x=1"),
        lambda: server.get_agent_version("../agents", "av_1"),
        lambda: server.get_phone_number("pn_1/../x"),
        lambda: server.delete_agent("agent_1/versions"),
    ):
        with pytest.raises(Exception):
            call()

    paths = [request.url.raw_path.decode() for request in api.requests]
    assert paths == [
        "/agents/calls/ac_1%2Flogs%3Fx=1",
        "/v1/agents/..%2Fagents/versions/av_1",
        "/agents/phone-numbers/pn_1%2F..%2Fx",
        "/v1/agents/agent_1%2Fversions",
    ]


def test_list_agents_returns_summaries_and_cursor(api: Api) -> None:
    summary = {key: AGENT[key] for key in ("id", "name", "description", "created_at")}
    api.on("GET", "/v1/agents", {"data": [summary], "has_more": True})

    result = server.list_agents(q="support")

    assert _query(api.last) == {"q": "support", "limit": "10"}
    assert result["data"][0]["name"] == "Support"
    assert result["next_page"] == "agent_1"


def test_get_agent_adds_playground_url(api: Api) -> None:
    api.on("GET", "/v1/agents/agent_1", AGENT)

    result = server.get_agent("agent_1")

    assert result["config"] == {"instructions": "Help callers."}
    assert result["playground_url"] == "https://play.cartesia.ai/agents/agent_1"


def test_create_agent_sends_config_and_returns_playground_url(api: Api) -> None:
    api.on("POST", "/v1/agents", AGENT)

    result = server.create_agent(
        name="Support",
        config={
            "instructions": "Help callers.",
            "model": {"id": "claude-haiku-4.5"},
            "system_tools": {"end_call": {}},
        },
    )

    assert json.loads(api.last.content) == {
        "name": "Support",
        "config": {
            "instructions": "Help callers.",
            "model": {"id": "claude-haiku-4.5"},
            "system_tools": {"end_call": {}},
        },
    }
    assert result["id"] == "agent_1"
    assert result["playground_url"] == "https://play.cartesia.ai/agents/agent_1"


def test_update_agent_sends_only_given_fields(api: Api) -> None:
    api.on("PATCH", "/v1/agents/agent_1", AGENT)

    server.update_agent(
        "agent_1",
        config={"initial_message": "Hello!"},
        version_description="Shorter greeting",
    )

    assert api.last.method == "PATCH"
    assert json.loads(api.last.content) == {
        "config": {"initial_message": "Hello!"},
        "version_description": "Shorter greeting",
    }


def test_update_agent_requires_a_change(api: Api) -> None:
    with pytest.raises(ValueError, match="at least one"):
        server.update_agent("agent_1")
    assert api.requests == []


def test_delete_agent(api: Api) -> None:
    api.on("DELETE", "/v1/agents/agent_1", None)

    assert server.delete_agent("agent_1") == {"success": True}
    assert api.last.method == "DELETE"


def _metric(name: str, value: float) -> dict:
    return {
        "role": "system",
        "start_timestamp": 1.0,
        "end_timestamp": 1.0,
        "was_interrupted": False,
        "log_metric": {"name": name, "value": value, "timestamp": 1.0},
    }


def test_condense_folds_metric_turns_into_latency_summary() -> None:
    call = {
        **CALL,
        "transcript": [
            _metric("agent_turn_ms", 800.04),
            {"role": "assistant", "text": "Hi", "was_interrupted": False},
            _metric("agent_turn_ms", 1200.0),
            _metric("llm_first_chunk_ms", 450.0),
        ],
    }

    result = condense_agent_call(call)

    assert [turn["role"] for turn in result["turns"]] == ["assistant"]
    assert result["latency_ms"] == {
        "agent_turn_ms": {"count": 2, "mean": 1000.0, "max": 1200.0},
        "llm_first_chunk_ms": {"count": 1, "mean": 450.0, "max": 450.0},
    }


def test_condense_tolerates_missing_and_malformed_fields() -> None:
    result = condense_agent_call({"id": "ac_2", "status": "completed"})

    assert result["turns"] == []
    assert result["latency_ms"] == {}
    assert result["dynamic_variables"] == {}
    assert "connection" not in result
    assert result["end_reason"] is None

    odd = condense_agent_call(
        {
            "id": "ac_3",
            "transcript": [
                "not a turn",
                {"role": "user", "text": "hi", "tool_calls": [None, {"name": "t"}]},
                {"log_metric": {"name": "x", "value": "NaN"}},
                {"role": "system", "log_metric": "oops"},
                {"role": "system", "log_metric": None},
            ],
        }
    )
    assert len(odd["turns"]) == 1
    assert odd["turns"][0]["tool_calls"] == [{"name": "t", "arguments": None}]
    assert odd["latency_ms"] == {}


def test_condense_keeps_tool_call_variable_updates_and_short_results() -> None:
    updates = [{"name": "tier", "value": "gold"}]
    call = {
        "id": "ac_4",
        "transcript": [
            {
                "role": "assistant",
                "text": "",
                "tool_calls": [
                    {
                        "name": "set_tier",
                        "arguments": {},
                        "result": "ok",
                        "dynamic_variable_updates": updates,
                    },
                    {"name": "no_result", "arguments": {"a": 1}},
                ],
            }
        ],
    }

    first, second = condense_agent_call(call)["turns"][0]["tool_calls"]

    assert first == {
        "name": "set_tier",
        "arguments": {},
        "result": "ok",
        "dynamic_variable_updates": updates,
    }
    assert "result" not in second
    assert "result_truncated" not in first
    assert "result_chars" not in first
