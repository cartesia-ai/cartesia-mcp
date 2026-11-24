"""Every Managed Agents SDK method is either a tool or excluded on purpose.

A new SDK method fails this test until it is mapped to a tool or given a reason here.
"""

from __future__ import annotations

import inspect

from cartesia import Cartesia

import cartesia_mcp.server as server

SDK_TO_TOOL = {
    "agents.calls.batches.cancel": "cancel_call_batch",
    "agents.calls.batches.create": "create_call_batch",
    "agents.calls.batches.list": "list_call_batches",
    "agents.calls.batches.retrieve": "get_call_batch",
    "agents.calls.batches.retry": "retry_call_batch",
    "agents.calls.cancel": "cancel_agent_call",
    "agents.calls.create": "create_agent_calls",
    "agents.calls.delete": "delete_agent_call",
    "agents.calls.list": "list_agent_calls",
    "agents.calls.logs": "get_agent_call_logs",
    "agents.calls.retrieve": "get_agent_call",
    "agents.create": "create_agent",
    "agents.delete": "delete_agent",
    "agents.knowledge_base.documents.create_bulk": "create_knowledge_documents",
    "agents.knowledge_base.documents.delete": "delete_knowledge_document",
    "agents.knowledge_base.documents.list": "list_knowledge_documents",
    "agents.knowledge_base.documents.retrieve": "get_knowledge_document",
    "agents.knowledge_base.documents.retry": "retry_knowledge_document",
    "agents.knowledge_base.documents.update": "update_knowledge_document",
    "agents.knowledge_base.folders.create": "create_knowledge_folder",
    "agents.knowledge_base.folders.delete": "delete_knowledge_folder",
    "agents.knowledge_base.folders.list": "list_knowledge_folders",
    "agents.knowledge_base.folders.retrieve": "get_knowledge_folder",
    "agents.knowledge_base.folders.update": "update_knowledge_folder",
    "agents.list": "list_agents",
    "agents.metrics.add_to_agent": "attach_agent_metric",
    "agents.metrics.create": "create_agent_metric",
    "agents.metrics.delete": "delete_agent_metric",
    "agents.metrics.list": "list_agent_metrics",
    "agents.metrics.remove_from_agent": "detach_agent_metric",
    "agents.metrics.results.export": "export_agent_metric_results",
    "agents.metrics.results.list": "list_agent_metric_results",
    "agents.metrics.retrieve": "get_agent_metric",
    "agents.models.list": "list_agent_models",
    "agents.phone_numbers.delete": "delete_phone_number",
    "agents.phone_numbers.import_": "import_phone_number",
    "agents.phone_numbers.list": "list_phone_numbers",
    "agents.phone_numbers.providers.create": "create_twilio_provider",
    "agents.phone_numbers.providers.delete": "delete_phone_provider",
    "agents.phone_numbers.providers.list": "list_phone_providers",
    "agents.phone_numbers.providers.retrieve": "get_phone_provider",
    "agents.phone_numbers.providers.update": "update_phone_provider",
    "agents.phone_numbers.provision": "provision_phone_number",
    "agents.phone_numbers.provisioning_usage": "get_phone_provisioning_usage",
    "agents.phone_numbers.retrieve": "get_phone_number",
    "agents.phone_numbers.update": "update_phone_number",
    "agents.retrieve": "get_agent",
    "agents.tools.create": "create_agent_tool",
    "agents.tools.delete": "delete_agent_tool",
    "agents.tools.list": "list_agent_tools",
    "agents.tools.retrieve": "get_agent_tool",
    "agents.tools.update": "update_agent_tool",
    "agents.update": "update_agent",
    "agents.versions.list": "list_agent_versions",
    "agents.versions.retrieve": "get_agent_version",
    "agents.webhooks.delete": "delete_event_webhook",
    "agents.webhooks.list": "list_event_webhooks",
    "agents.webhooks.retrieve": "get_event_webhook",
    "usage.agents.retrieve": "get_agent_usage",
}

OUT_OF_SCOPE = {
    "agents.calls.download_audio": "Call audio is binary WAV; this server does not proxy recordings.",
    "agents.knowledge_base.documents.create": "Single-document create; `create_knowledge_documents` covers one or many.",
    "agents.models.retrieve": "Single-model lookup; `list_agent_models` returns the catalog.",
    "agents.sessions.create_webrtc": "A coding agent cannot join a live WebRTC session.",
    "agents.sessions.create_websocket": "A coding agent cannot join a live WebSocket session.",
    "agents.webhooks.create": "Takes a shared secret; users create event webhooks in the Playground.",
    "agents.webhooks.update": "Takes a shared secret; users update event webhooks in the Playground.",
}


def _sdk_methods(resource: object, prefix: str) -> set[str]:
    methods: set[str] = set()
    for name in dir(resource):
        if name.startswith("_") or name.startswith("with_"):
            continue
        attr = getattr(resource, name)
        path = f"{prefix}.{name}"
        if inspect.ismethod(attr) or inspect.isfunction(attr):
            methods.add(path)
        elif type(attr).__module__.startswith("cartesia.resources"):
            methods |= _sdk_methods(attr, path)
    return methods


def _all_sdk_agent_methods() -> set[str]:
    client = Cartesia(api_key="sk_test", base_url="https://api.test")
    return _sdk_methods(client.agents, "agents") | _sdk_methods(
        client.usage.agents, "usage.agents"
    )


def test_every_sdk_agent_method_is_a_tool_or_excluded_with_a_reason() -> None:
    unaccounted = _all_sdk_agent_methods() - SDK_TO_TOOL.keys() - OUT_OF_SCOPE.keys()
    assert not unaccounted, f"map these to a tool or add a reason: {sorted(unaccounted)}"


def test_mappings_point_at_real_sdk_methods_and_registered_tools() -> None:
    sdk_methods = _all_sdk_agent_methods()
    assert not (SDK_TO_TOOL.keys() - sdk_methods), "SDK_TO_TOOL names a removed SDK method"
    assert not (OUT_OF_SCOPE.keys() - sdk_methods), "OUT_OF_SCOPE names a removed SDK method"
    registered = {tool.name for tool in server.mcp._tool_manager.list_tools()}
    assert set(SDK_TO_TOOL.values()) <= registered
