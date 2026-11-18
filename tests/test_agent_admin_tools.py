"""Knowledge base, webhooks, metrics, phone numbers, outbound calls, and batches."""

import json

import pytest
from conftest import Api

import cartesia_mcp.agents as agents

DOCUMENT = {
    "id": "kbdoc_1",
    "content": "Returns are accepted within 30 days.",
    "created_at": "2026-11-01T00:00:00Z",
    "error": None,
    "metadata": {"k": "v"},
    "name": "returns",
    "status": "ready",
}


def _body(api: Api) -> dict:
    return json.loads(api.last.content)


def _query(api: Api) -> dict[str, str]:
    return dict(api.last.url.params)


# Knowledge base


def test_list_knowledge_folders_scopes_to_parent_and_keeps_root_documents(api: Api) -> None:
    api.on(
        "GET",
        "/agents/folders",
        {
            "data": [
                {
                    "id": "kbfldr_1",
                    "agents": [],
                    "created_at": "2026-11-01T00:00:00Z",
                    "documents": [],
                    "name": "Policies",
                    "parent_id": "kbfldr_0",
                    "children": [],
                }
            ],
            "has_more": True,
            "next_page": "kbfldr_1",
            "root_documents": [
                {
                    "id": "kbdoc_9",
                    "agents": [],
                    "created_at": "2026-11-01T00:00:00Z",
                    "metadata": {},
                    "status": "ready",
                }
            ],
        },
    )

    result = agents.list_knowledge_folders(parent_id="kbfldr_0", depth=2)

    assert _query(api)["parent_ids"] == "kbfldr_0"
    assert _query(api)["depth"] == "2"
    assert result["has_more"] is True
    assert result["next_page"] == "kbfldr_1"
    assert result["root_documents"][0]["id"] == "kbdoc_9"


def test_update_knowledge_folder_requires_a_change(api: Api) -> None:
    with pytest.raises(ValueError, match="at least one"):
        agents.update_knowledge_folder("kbfldr_1")
    assert api.requests == []


def test_delete_knowledge_folder_only_forces_when_asked(api: Api) -> None:
    api.on("DELETE", "/agents/folders/kbfldr_1", None)

    assert agents.delete_knowledge_folder("kbfldr_1") == {"success": True}
    assert "force" not in _query(api)

    agents.delete_knowledge_folder("kbfldr_1", force=True)
    assert _query(api)["force"] == "true"


def test_folder_id_stays_one_path_segment(api: Api) -> None:
    api.on("GET", "/agents/folders/a%2Fb", {"id": "x"})

    agents.get_knowledge_folder("a/b")

    assert api.last.url.raw_path.decode() == "/agents/folders/a%2Fb"


def test_create_knowledge_document_from_file_path_uploads_then_creates(
    api: Api, tmp_path
) -> None:
    source = tmp_path / "returns.pdf"
    source.write_bytes(b"%PDF-1.4")
    api.on("POST", "/files", {"id": "file_1", "filename": "returns.pdf"})
    api.on("POST", "/agents/documents/bulk", [DOCUMENT])

    agents.create_knowledge_documents(
        [{"file_path": str(source), "name": "returns", "folder_id": "kbfldr_1"}]
    )

    upload, create = api.requests
    assert upload.url.path == "/files"
    assert b"knowledge_base_document" in upload.content
    assert b"returns.pdf" in upload.content
    assert json.loads(create.content) == {
        "documents": [
            {"name": "returns", "folder_id": "kbfldr_1", "file_id": "file_1"}
        ]
    }


def test_create_knowledge_document_rejects_file_path_on_hosted(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agents, "_is_hosted", True)
    with pytest.raises(ValueError, match="Hosted MCP"):
        agents.create_knowledge_documents([{"file_path": "/tmp/returns.pdf"}])
    assert api.requests == []


@pytest.mark.parametrize(
    "relative", [".ssh/id_ed25519", ".env", ".aws/credentials", "credentials.pem"]
)
def test_create_knowledge_document_refuses_non_document_paths(
    api: Api, tmp_path, relative: str
) -> None:
    source = tmp_path / relative
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("secret")

    with pytest.raises(ValueError, match="must be one of"):
        agents.create_knowledge_documents([{"file_path": str(source)}])
    assert api.requests == []


def test_create_knowledge_document_checks_the_symlink_target(
    api: Api, tmp_path
) -> None:
    target = tmp_path / ".aws" / "credentials"
    target.parent.mkdir()
    target.write_text("secret")
    link = tmp_path / "notes.txt"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="must be one of"):
        agents.create_knowledge_documents([{"file_path": str(link)}])
    assert api.requests == []


def test_create_knowledge_document_uploads_from_hidden_project_folder(
    api: Api, tmp_path
) -> None:
    source = tmp_path / ".cursor" / "worktrees" / "app" / "faq.md"
    source.parent.mkdir(parents=True)
    source.write_text("# FAQ")
    api.on("POST", "/files", {"id": "file_1", "filename": "faq.md"})
    api.on("POST", "/agents/documents/bulk", [DOCUMENT])

    agents.create_knowledge_documents([{"file_path": str(source)}])

    assert [request.url.path for request in api.requests] == [
        "/files",
        "/agents/documents/bulk",
    ]


def test_create_knowledge_documents_checks_every_path_before_uploading(
    api: Api, tmp_path
) -> None:
    good = tmp_path / "returns.pdf"
    good.write_bytes(b"%PDF-1.4")
    bad = tmp_path / "id_ed25519"
    bad.write_text("secret")

    with pytest.raises(ValueError, match="must be one of"):
        agents.create_knowledge_documents(
            [{"file_path": str(good)}, {"file_path": str(bad)}]
        )
    assert api.requests == []


def test_create_knowledge_document_refuses_oversized_file(
    api: Api, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agents, "KNOWLEDGE_FILE_MAX_BYTES", 4)
    source = tmp_path / "big.txt"
    source.write_text("12345")

    with pytest.raises(ValueError, match="20 MB"):
        agents.create_knowledge_documents([{"file_path": str(source)}])
    assert api.requests == []


def test_create_knowledge_documents_sends_bulk_body_without_echoing_text(api: Api) -> None:
    api.on("POST", "/agents/documents/bulk", [DOCUMENT])

    result = agents.create_knowledge_documents(
        [{"content": DOCUMENT["content"], "name": "returns", "folder_id": "kbfldr_1"}]
    )

    assert _body(api) == {
        "documents": [
            {"content": DOCUMENT["content"], "name": "returns", "folder_id": "kbfldr_1"}
        ]
    }
    [row] = result["data"]
    assert "content" not in row
    assert row["content_chars"] == len(DOCUMENT["content"])


def test_list_documents_reports_size_not_text_and_get_returns_text(api: Api) -> None:
    api.on("GET", "/agents/documents", {"data": [DOCUMENT], "has_more": False})
    api.on("GET", "/agents/documents/kbdoc_1", DOCUMENT)

    [row] = agents.list_knowledge_documents()["data"]
    assert "content" not in row
    assert row["content_chars"] == len(DOCUMENT["content"])

    assert agents.get_knowledge_document("kbdoc_1")["content"] == DOCUMENT["content"]


def test_update_knowledge_document_sends_only_given_fields(api: Api) -> None:
    api.on("PATCH", "/agents/documents/kbdoc_1", DOCUMENT)

    agents.update_knowledge_document("kbdoc_1", name="returns v2")
    assert _body(api) == {"name": "returns v2"}

    with pytest.raises(ValueError, match="at least one"):
        agents.update_knowledge_document("kbdoc_1")


def test_delete_knowledge_document_only_forces_when_asked(api: Api) -> None:
    api.on("DELETE", "/agents/documents/kbdoc_1", None)

    assert agents.delete_knowledge_document("kbdoc_1") == {"success": True}
    assert "force" not in _query(api)
    agents.delete_knowledge_document("kbdoc_1", force=True)
    assert _query(api)["force"] == "true"


# Event webhooks


WEBHOOK = {
    "id": "agent_webhook_1",
    "created_at": "2026-11-01T00:00:00Z",
    "updated_at": "2026-11-01T00:00:00Z",
    "url": "https://example.com/hook",
    "display_name": "prod",
    "secret": "s3cret",
}


def test_create_event_webhook_sends_secret_but_does_not_return_it(api: Api) -> None:
    api.on("POST", "/agents/webhooks", WEBHOOK)

    result = agents.create_event_webhook("https://example.com/hook", "s3cret", display_name="prod")

    assert _body(api) == {
        "url": "https://example.com/hook",
        "secret": "s3cret",
        "display_name": "prod",
    }
    assert result["id"] == "agent_webhook_1"
    assert "secret" not in result


def test_update_event_webhook_keeps_secret_unless_given(api: Api) -> None:
    api.on("PATCH", "/agents/webhooks/agent_webhook_1", WEBHOOK)

    assert agents.update_event_webhook("agent_webhook_1", "https://example.com/new") == {
        "success": True
    }
    assert _body(api) == {"url": "https://example.com/new"}


# Evaluation metrics


def test_attach_and_detach_metric_use_agent_scoped_routes(api: Api) -> None:
    api.on("POST", "/agents/agent_1/metrics/am_1", None)
    api.on("DELETE", "/agents/agent_1/metrics/am_1", None)

    assert agents.attach_agent_metric("am_1", "agent_1") == {"success": True}
    assert api.last.method == "POST"
    assert agents.detach_agent_metric("am_1", "agent_1") == {"success": True}
    assert api.last.method == "DELETE"


def test_list_agent_metrics_returns_cursor(api: Api) -> None:
    api.on(
        "GET",
        "/agents/metrics",
        {
            "data": [
                {
                    "id": "am_1",
                    "created_at": "2026-11-01T00:00:00Z",
                    "name": "greeted",
                    "prompt": "Did the agent greet the caller?",
                }
            ],
            "has_more": True,
        },
    )

    result = agents.list_agent_metrics(limit=1)

    assert result["next_page"] == "am_1"
    assert _query(api)["limit"] == "1"


def test_list_agent_metric_results_forwards_filters(api: Api) -> None:
    api.on("GET", "/agents/metrics/results", {"data": [], "has_more": False})

    agents.list_agent_metric_results(
        agent_id="agent_1", metric_id="am_1", start_date="2026-11-01T00:00:00Z"
    )

    query = _query(api)
    assert query["agent_id"] == "agent_1"
    assert query["metric_id"] == "am_1"
    assert query["start_date"].startswith("2026-11-01T00:00:00")


def test_export_agent_metric_results_truncates_long_csv(api: Api) -> None:
    long_csv = "row\n" * agents.EXPORT_RESULTS_MAX_CHARS
    api.on("GET", "/agents/metrics/results/export", long_csv)

    result = agents.export_agent_metric_results(agent_id="agent_1")

    assert result["truncated"] is True
    assert len(result["csv"]) == agents.EXPORT_RESULTS_MAX_CHARS
    assert result["total_chars"] > agents.EXPORT_RESULTS_MAX_CHARS


# Phone numbers and providers


def test_update_phone_number_unassigns_with_explicit_null(api: Api) -> None:
    api.on("PATCH", "/agents/phone-numbers/pn_1", {"id": "pn_1"})

    agents.update_phone_number("pn_1", unassign_agent=True)

    assert _body(api) == {"agent_id": None}


def test_update_phone_number_sends_new_agent_and_provider(api: Api) -> None:
    api.on("PATCH", "/agents/phone-numbers/pn_1", {"id": "pn_1"})

    agents.update_phone_number("pn_1", agent_id="agent_2", provider_id="prov_1")

    assert _body(api) == {"agent_id": "agent_2", "provider": {"id": "prov_1"}}


def test_update_phone_number_rejects_ambiguous_or_empty_changes(api: Api) -> None:
    with pytest.raises(ValueError, match="not both"):
        agents.update_phone_number("pn_1", agent_id="agent_2", unassign_agent=True)
    with pytest.raises(ValueError, match="at least one"):
        agents.update_phone_number("pn_1")
    assert api.requests == []


def test_provision_and_import_send_expected_bodies(api: Api) -> None:
    number = {
        "id": "pn_1",
        "created_at": "2026-11-01T00:00:00Z",
        "updated_at": "2026-11-01T00:00:00Z",
        "number": "+14155551234",
    }
    api.on("POST", "/agents/phone-numbers/provision", number)
    api.on("POST", "/agents/phone-numbers", number)

    agents.provision_phone_number("Support line")
    assert _body(api) == {"label": "Support line"}

    agents.import_phone_number("Mine", "+14155551234", {"id": "prov_1"})
    assert _body(api) == {
        "label": "Mine",
        "number": "+14155551234",
        "provider": {"id": "prov_1"},
    }


def test_list_phone_providers_returns_data_list(api: Api) -> None:
    api.on(
        "GET",
        "/agents/phone-numbers/providers",
        [
            {
                "id": "prov_1",
                "type": "twilio",
                "account_sid": "AC1",
                "api_key_sid": "SK1",
                "region": "us1",
                "label": "main",
            }
        ],
    )

    result = agents.list_phone_providers(type="twilio")

    assert result["data"][0]["id"] == "prov_1"
    assert "api_key_secret" not in result["data"][0]
    assert _query(api)["type"] == "twilio"


def test_create_twilio_provider_and_update_sip_provider(api: Api) -> None:
    provider = {
        "id": "prov_1",
        "type": "twilio",
        "account_sid": "AC1",
        "api_key_sid": "SK1",
        "region": "us1",
    }
    api.on("POST", "/agents/phone-numbers/providers", provider)
    api.on("PATCH", "/agents/phone-numbers/providers/prov_1", provider)

    agents.create_twilio_provider("AC1", "SK1", "secret", region="ie1")
    assert _body(api) == {
        "type": "twilio",
        "account_sid": "AC1",
        "api_key_sid": "SK1",
        "api_key_secret": "secret",
        "region": "ie1",
    }

    agents.update_phone_provider("prov_1", {"type": "sip_trunk", "label": "new"})
    assert _body(api) == {"type": "sip_trunk", "label": "new"}


def test_update_phone_provider_requires_a_change(api: Api) -> None:
    with pytest.raises(ValueError, match="at least one field"):
        agents.update_phone_provider("prov_1", {"type": "sip_trunk"})
    assert api.requests == []


# Outbound calls and batches


def test_create_agent_calls_sends_destinations_and_variables(api: Api) -> None:
    api.on(
        "POST",
        "/agents/calls",
        {"calls": [{"number": "+14155550100", "agent_call_id": "ac_9"}]},
    )

    result = agents.create_agent_calls(
        "agent_1",
        "pn_1",
        [{"to_number": "+14155550100", "dynamic_variables": {"name": "Ada"}}],
        ringing_timeout_seconds=30,
    )

    assert _body(api) == {
        "agent_id": "agent_1",
        "from_number_id": "pn_1",
        "outbound_calls": [{"to_number": "+14155550100", "dynamic_variables": {"name": "Ada"}}],
        "ringing_timeout_seconds": 30,
    }
    assert result["calls"][0]["agent_call_id"] == "ac_9"


def test_cancel_and_delete_agent_call(api: Api) -> None:
    api.on("POST", "/agents/calls/ac_1/cancel", {"cancelled": True})
    api.on("DELETE", "/agents/calls/ac_1", None)

    assert agents.cancel_agent_call("ac_1") == {"cancelled": True}
    assert agents.delete_agent_call("ac_1") == {"success": True}


BATCH = {
    "id": "batch_1",
    "agent_id": "agent_1",
    "created_at": "2026-11-01T00:00:00Z",
    "from_number_id": "pn_1",
    "last_updated_at": "2026-11-01T00:00:00Z",
    "name": "Follow-ups",
    "region": "US",
    "retry_count": 0,
    "status": "pending",
    "target_concurrency_limit": 5,
    "total_calls_dispatched": 0,
    "total_calls_finished": 0,
    "total_calls_scheduled": 1,
    "recipients": [
        {
            "id": "r1",
            "created_at": "2026-11-01T00:00:00Z",
            "status": "pending",
            "to_number": "+14155550100",
        }
    ],
}


def test_list_call_batches_drops_recipients_and_get_keeps_them(api: Api) -> None:
    api.on("GET", "/agents/calls/batches", {"data": [BATCH], "has_more": False})
    api.on("GET", "/agents/calls/batches/batch_1", BATCH)

    [row] = agents.list_call_batches(agent_id="agent_1")["data"]
    assert "recipients" not in row
    assert row["total_calls_scheduled"] == 1

    assert agents.get_call_batch("batch_1")["recipients"][0]["to_number"] == "+14155550100"


def test_create_call_batch_schedules_and_caps_concurrency(api: Api) -> None:
    api.on("POST", "/agents/calls/batches", BATCH)

    agents.create_call_batch(
        "agent_1",
        "pn_1",
        "Follow-ups",
        [{"to_number": "+14155550100"}],
        scheduled_at="2030-01-01T00:00:00Z",
        target_concurrency_limit=2,
    )

    body = _body(api)
    assert body["scheduled_at"] == "2030-01-01T00:00:00Z"
    assert body["target_concurrency_limit"] == 2
    assert body["recipients"] == [{"to_number": "+14155550100"}]


def test_cancel_and_retry_call_batch_post_to_their_routes(api: Api) -> None:
    api.on("POST", "/agents/calls/batches/batch_1/cancel", BATCH)
    api.on("POST", "/agents/calls/batches/batch_1/retry", BATCH)

    agents.cancel_call_batch("batch_1")
    assert api.last.url.path.endswith("/cancel")
    agents.retry_call_batch("batch_1")
    assert api.last.url.path.endswith("/retry")


# Agent usage


def test_get_agent_usage_calls_the_usage_route_with_filters(api: Api) -> None:
    api.on("GET", "/usage/agents", {"data": []})

    agents.get_agent_usage(
        start_ts="2026-11-01T00:00:00Z",
        end_ts="2026-11-08T00:00:00Z",
        interval="day",
    )

    assert api.last.url.path == "/usage/agents"
    assert _query(api) == {
        "start_ts": "2026-11-01T00:00:00Z",
        "end_ts": "2026-11-08T00:00:00Z",
        "interval": "day",
    }
