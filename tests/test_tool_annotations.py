"""Directory clients receive explicit tool safety hints and annotation titles."""

from __future__ import annotations

import asyncio

import cartesia_mcp.server as server


def test_all_tools_have_annotation_title_and_hint(monkeypatch):
    monkeypatch.setattr("cartesia_mcp.tool_visibility.admin_tools_available", lambda: True)
    tools = asyncio.run(server.mcp.list_tools())
    assert len(tools) == 85

    for tool in tools:
        assert tool.annotations is not None, f"{tool.name} is missing annotations"
        assert tool.annotations.title, f"{tool.name} is missing annotations.title"
        assert tool.annotations.read_only_hint is not None, (
            f"{tool.name} must set read_only_hint explicitly"
        )
        assert tool.annotations.destructive_hint is not None, tool.name
        assert tool.annotations.open_world_hint is not None, tool.name
        if tool.annotations.read_only_hint:
            assert tool.annotations.destructive_hint is False, (
                f"{tool.name} is read-only but sets destructive_hint"
            )


def test_read_only_tools():
    read_only = {
        "get_voice",
        "list_accents",
        "list_agent_models",
        "list_agents",
        "get_agent",
        "list_agent_calls",
        "get_agent_call",
        "list_agent_versions",
        "get_agent_version",
        "list_phone_numbers",
        "get_phone_number",
        "list_agent_tools",
        "get_agent_tool",
        "list_models",
        "list_voices",
        "get_credit_usage",
        "list_pronunciation_dicts",
        "get_pronunciation_dict",
        "list_knowledge_folders",
        "get_knowledge_folder",
        "list_knowledge_documents",
        "get_knowledge_document",
        "list_event_webhooks",
        "get_event_webhook",
        "list_agent_metrics",
        "get_agent_metric",
        "list_agent_metric_results",
        "export_agent_metric_results",
        "list_phone_providers",
        "get_phone_provider",
        "list_call_batches",
        "get_call_batch",
        "get_agent_usage",
    }
    tools = {tool.name: tool for tool in server.mcp._tool_manager.list_tools()}
    for name in read_only:
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.read_only_hint is True
        assert annotations.destructive_hint is False


def test_additive_tools():
    additive_tools = {
        "download_file",
        "speech_to_text",
        "text_to_speech",
        "localize_voice",
        "clone_voice",
        "add_voice_accents",
        "create_pronunciation_dict",
        "create_agent",
        "create_agent_tool",
        "attach_agent_tool",
        "create_knowledge_folder",
        "create_knowledge_documents",
        "attach_knowledge_folder",
        "attach_knowledge_document",
        "retry_knowledge_document",
        "create_event_webhook",
        "create_agent_metric",
        "attach_agent_metric",
        "import_phone_number",
    }
    tools = {tool.name: tool for tool in server.mcp._tool_manager.list_tools()}
    for name in additive_tools:
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.read_only_hint is False
        assert annotations.destructive_hint is False


def test_destructive_tools():
    destructive_tools = {
        "delete_voice",
        "update_voice",
        "delete_voice_accent",
        "update_pronunciation_dict",
        "delete_pronunciation_dict",
        "update_agent",
        "delete_agent",
        "update_agent_tool",
        "delete_agent_tool",
        "update_knowledge_folder",
        "delete_knowledge_folder",
        "update_knowledge_document",
        "delete_knowledge_document",
        "update_event_webhook",
        "delete_event_webhook",
        "delete_agent_metric",
        "detach_agent_metric",
        "detach_agent_tool",
        "detach_knowledge_folder",
        "detach_knowledge_document",
        "update_phone_number",
        "delete_phone_number",
        "update_phone_provider",
        "delete_phone_provider",
        "cancel_agent_call",
        "delete_agent_call",
        "cancel_call_batch",
    }
    tools = {tool.name: tool for tool in server.mcp._tool_manager.list_tools()}
    for name in destructive_tools:
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.read_only_hint is False
        assert annotations.destructive_hint is True


REAL_WORLD_TOOLS = {
    "provision_phone_number",
    "create_agent_calls",
    "create_call_batch",
    "retry_call_batch",
}


def test_real_world_tools_are_destructive_and_not_safe_to_retry():
    tools = {tool.name: tool for tool in server.mcp._tool_manager.list_tools()}
    for name in REAL_WORLD_TOOLS:
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.read_only_hint is False
        assert annotations.destructive_hint is True
        assert annotations.idempotent_hint is False
        assert annotations.open_world_hint is True


def test_real_world_tools_require_user_confirmation_in_description():
    tools = {tool.name: tool for tool in server.mcp._tool_manager.list_tools()}
    for name in REAL_WORLD_TOOLS:
        assert "confirmed" in tools[name].description, name


def test_wire_format_exposes_annotation_title():
    tools = asyncio.run(server.mcp.list_tools())
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.title


def test_text_to_speech_voice_id_has_string_type():
    tools = asyncio.run(server.mcp.list_tools())
    tts = next(tool for tool in tools if tool.name == "text_to_speech")
    voice_id = tts.input_schema["properties"]["voice_id"]
    assert voice_id["type"] == "string"


def test_all_tools_set_idempotent_and_open_world_hints():
    open_world_tools = REAL_WORLD_TOOLS | {
        "create_agent_tool",
        "update_agent_tool",
        "create_event_webhook",
        "update_event_webhook",
        "text_to_speech",
    }
    non_idempotent_tools = REAL_WORLD_TOOLS | {"update_agent"}
    for tool in asyncio.run(server.mcp.list_tools()):
        annotations = tool.annotations
        assert annotations is not None
        assert annotations.open_world_hint is (tool.name in open_world_tools), tool.name
        if tool.name in non_idempotent_tools:
            assert annotations.idempotent_hint is False, tool.name
        elif annotations.read_only_hint or annotations.destructive_hint:
            assert annotations.idempotent_hint is True, tool.name


def test_all_tool_parameters_have_descriptions():
    tools = asyncio.run(server.mcp.list_tools())
    for tool in tools:
        properties = tool.input_schema.get("properties", {})
        assert "request_options" not in properties, tool.name
        for name, prop in properties.items():
            assert prop.get("description"), f"{tool.name}.{name} has no description"
        assert "Parameters\n" not in (tool.description or ""), tool.name
