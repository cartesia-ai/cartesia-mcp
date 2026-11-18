import json

import httpx
import pytest
from conftest import Api

import cartesia_mcp.agents as agents
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

def _query(request: httpx.Request) -> dict[str, str]:
    return dict(request.url.params)


def test_get_agent_call_condenses_by_default(api: Api) -> None:
    api.on("GET", "/agents/calls/ac_1", CALL)

    result = agents.get_agent_call("ac_1")

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

    result = agents.get_agent_call("ac_1", detail="full")

    assert result["transcript"][1]["tool_calls"][0]["result"] == CALL["transcript"][1][
        "tool_calls"
    ][0]["result"]
    assert result["telephony_params"]["call_sid"] == "sid_1"


def test_list_agent_calls_sends_filters_omits_transcript_and_sets_cursor(api: Api) -> None:
    api.on("GET", "/agents/calls", {"data": [CALL], "has_more": True})

    result = agents.list_agent_calls("agent_1", limit=5, starting_after="ac_9")

    assert _query(api.last) == {"agent_id": "agent_1", "limit": "5", "starting_after": "ac_9"}
    row = result["data"][0]
    assert row["id"] == "ac_1"
    assert row["end_reason"] == "call_inactivity"
    assert "transcript" not in row
    assert result["has_more"] is True
    assert result["next_page"] == "ac_1"


def test_list_agent_calls_with_transcripts_condenses_rows_and_sends_time_and_batch(
    api: Api,
) -> None:
    row = {**CALL, "transcript": [{"role": "user", "text": "hi", "start_timestamp": 0.0}]}
    api.on("GET", "/agents/calls", {"data": [row], "has_more": False})

    result = agents.list_agent_calls(
        "agent_1",
        include_transcripts=True,
        start_time_gte="2026-11-01T00:00:00Z",
        start_time_lte="2026-11-02T00:00:00Z",
        batch_id="cb_1",
    )

    assert _query(api.last) == {
        "agent_id": "agent_1",
        "limit": "10",
        "expand": "transcript",
        "start_time_gte": "2026-11-01T00:00:00Z",
        "start_time_lte": "2026-11-02T00:00:00Z",
        "batch_id": "cb_1",
    }
    assert result["data"][0]["turns"][0]["text"] == "hi"


def test_list_agent_calls_with_transcripts_caps_the_page_size(api: Api) -> None:
    with pytest.raises(ValueError, match="20"):
        agents.list_agent_calls("agent_1", limit=21, include_transcripts=True)
    assert api.requests == []


def test_get_agent_call_logs_stops_at_the_character_budget(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agents, "AGENT_CALL_LOGS_MAX_CHARS", 10)
    api.on(
        "GET",
        "/agents/calls/ac_1/logs",
        {"call_id": "ac_1", "logs": ["abcdef", "ghijkl", "m"], "updated_at": "2026-11-01T00:00:00Z"},
    )

    result = agents.get_agent_call_logs("ac_1")

    assert result["call_id"] == "ac_1"
    assert result["logs"] == ["abcdef"]
    assert result["truncated"] is True


def test_get_phone_provisioning_usage_reads_the_monthly_quota(api: Api) -> None:
    api.on(
        "GET",
        "/agents/phone-numbers/provision",
        {"monthly_usage": 3, "monthly_limit": 5, "remaining": 2},
    )

    assert agents.get_phone_provisioning_usage() == {
        "monthly_usage": 3,
        "monthly_limit": 5,
        "remaining": 2,
    }


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

    result = agents.list_agent_versions("agent_1")

    assert result == {
        "data": [{"id": "av_1", "created_at": "2026-08-28T18:33:03Z", "description": "v1"}],
        "has_more": False,
    }


def test_get_agent_version_path(api: Api) -> None:
    api.on("GET", "/v1/agents/agent_1/versions/av_1", {"id": "av_1", "config": {}})

    assert agents.get_agent_version("agent_1", "av_1")["id"] == "av_1"


def test_list_phone_numbers_filters_and_cursor(api: Api) -> None:
    api.on(
        "GET",
        "/agents/phone-numbers",
        {"data": [{"id": "pn_1", "number": "+15550100", "agent": None}], "has_more": True},
    )

    result = agents.list_phone_numbers(agent_id="agent_1", type="sip_trunk")

    assert _query(api.last) == {"agent_id": "agent_1", "type": "sip_trunk", "limit": "10"}
    assert result["data"][0]["number"] == "+15550100"
    assert result["next_page"] == "pn_1"


def test_ids_stay_one_path_segment(api: Api) -> None:
    for call in (
        lambda: agents.get_agent_call("ac_1/logs?x=1"),
        lambda: agents.get_agent_version("../agents", "av_1"),
        lambda: agents.get_phone_number("pn_1/../x"),
        lambda: agents.delete_agent("agent_1/versions"),
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

    result = agents.list_agents(q="support")

    assert _query(api.last) == {"q": "support", "limit": "10"}
    assert result["data"][0]["name"] == "Support"
    assert result["next_page"] == "agent_1"


def test_get_agent_adds_playground_url(api: Api) -> None:
    api.on("GET", "/v1/agents/agent_1", AGENT)

    result = agents.get_agent("agent_1")

    assert result["config"] == {"instructions": "Help callers."}
    assert result["playground_url"] == "https://play.cartesia.ai/agents/agent_1"


def test_create_agent_sends_config_and_returns_playground_url(api: Api) -> None:
    api.on("POST", "/v1/agents", AGENT)

    result = agents.create_agent(
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

    result = agents.update_agent(
        "agent_1",
        config={"initial_message": "Hello!"},
        version_description="Shorter greeting",
    )

    assert api.last.method == "PATCH"
    assert json.loads(api.last.content) == {
        "config": {"initial_message": "Hello!"},
        "version_description": "Shorter greeting",
    }
    assert result["playground_url"] == "https://play.cartesia.ai/agents/agent_1"


def test_attach_agent_tool_keeps_existing_ids(api: Api) -> None:
    current = {
        **AGENT,
        "config": {"tools": [{"id": "tool_old"}], "instructions": "Help callers."},
    }
    api.on("GET", "/v1/agents/agent_1", current)
    api.on("PATCH", "/v1/agents/agent_1", current)

    agents.attach_agent_tool("agent_1", "tool_new")

    assert json.loads(api.last.content) == {
        "config": {"tools": [{"id": "tool_old"}, {"id": "tool_new"}]}
    }


def test_attach_agent_tool_skips_update_when_already_attached(api: Api) -> None:
    current = {**AGENT, "config": {"tools": [{"id": "tool_old"}]}}
    api.on("GET", "/v1/agents/agent_1", current)

    result = agents.attach_agent_tool("agent_1", "tool_old")

    assert [request.method for request in api.requests] == ["GET"]
    assert result["playground_url"] == "https://play.cartesia.ai/agents/agent_1"


def test_detach_knowledge_document_sends_the_remaining_ids(api: Api) -> None:
    current = {
        **AGENT,
        "config": {
            "knowledge_base_documents": [{"id": "kbdoc_1"}, {"id": "kbdoc_2"}]
        },
    }
    api.on("GET", "/v1/agents/agent_1", current)
    api.on("PATCH", "/v1/agents/agent_1", current)

    agents.detach_knowledge_document("agent_1", "kbdoc_1")

    assert json.loads(api.last.content) == {
        "config": {"knowledge_base_documents": [{"id": "kbdoc_2"}]}
    }


def test_update_agent_requires_a_change(api: Api) -> None:
    with pytest.raises(ValueError, match="at least one"):
        agents.update_agent("agent_1")
    assert api.requests == []


WEBHOOK_TOOL = {
    "id": "tool_1",
    "name": "lookup_order",
    "description": "Look up an order.",
    "type": "webhook",
    "execution_mode": "immediate",
    "pre_tool_speech": "auto",
    "response_timeout_secs": 20,
    "assignments": [],
    "created_at": "2026-08-28T18:33:03Z",
    "updated_at": "2026-08-28T18:33:03Z",
    "api_schema": {"method": "GET", "url": "https://example.com/orders/{order_id}"},
}


def test_list_agent_tools_summarizes_and_filters(api: Api) -> None:
    api.on("GET", "/v1/agents/tools", {"data": [WEBHOOK_TOOL], "has_more": True, "next_page": "tool_1"})

    result = agents.list_agent_tools(type="webhook", agent_id="agent_1")

    assert _query(api.last) == {
        "type": "webhook",
        "agent_id": "agent_1",
        "limit": "10",
    }
    assert result["data"] == [
        {
            "id": "tool_1",
            "name": "lookup_order",
            "description": "Look up an order.",
            "type": "webhook",
        }
    ]
    assert result["next_page"] == "tool_1"
    assert "api_schema" not in result["data"][0]


def test_get_agent_tool_keeps_schema_and_drops_nothing_secret(api: Api) -> None:
    api.on("GET", "/v1/agents/tools/tool_1", WEBHOOK_TOOL)

    result = agents.get_agent_tool("tool_1", expand=["agents"])

    assert _query(api.last) == {"expand": "agents"}
    assert result["api_schema"]["url"].startswith("https://example.com")


def test_create_agent_tool_sends_client_tool(api: Api) -> None:
    api.on("POST", "/v1/agents/tools", WEBHOOK_TOOL)
    tool = {
        "type": "client",
        "name": "lookup_order",
        "description": "Look up an order by id.",
        "execution_mode": "immediate",
        "expects_response": True,
        "pre_tool_speech": "auto",
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    }

    result = agents.create_agent_tool(tool)

    assert json.loads(api.last.content) == tool
    assert result["id"] == "tool_1"


def test_update_agent_tool_sends_only_given_fields(api: Api) -> None:
    api.on("PATCH", "/v1/agents/tools/tool_1", WEBHOOK_TOOL)

    agents.update_agent_tool("tool_1", {"description": "Look up an order by id."})

    assert json.loads(api.last.content) == {"description": "Look up an order by id."}


def test_update_agent_tool_requires_a_change(api: Api) -> None:
    with pytest.raises(ValueError, match="at least one"):
        agents.update_agent_tool("tool_1", {})
    assert api.requests == []


def test_delete_agent_tool(api: Api) -> None:
    api.on("DELETE", "/v1/agents/tools/tool_1", None)

    assert agents.delete_agent_tool("tool_1") == {"success": True}
    assert api.last.method == "DELETE"


def test_delete_agent(api: Api) -> None:
    api.on("DELETE", "/v1/agents/agent_1", None)

    assert agents.delete_agent("agent_1") == {"success": True}
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
                {"role": "user", "text": "hi", "log_metric": None, "tool_calls": [None, {"name": "t"}]},
                {"log_metric": {"name": "x", "value": "NaN"}},
                {"role": "system", "log_metric": "oops"},
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
