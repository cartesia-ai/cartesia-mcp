"""Managed Agents tools and prompts: agents, calls, versions, knowledge base, webhooks, metrics, phone numbers, and batches."""

import typing
from pathlib import Path

from cartesia import omit
from cartesia.types.agent_create_params import Config as AgentCreateConfig
from cartesia.types.agent_update_params import Config as AgentUpdateConfig
from cartesia.types.agents.call_create_params import OutboundCall
from cartesia.types.agents.knowledge_base.document_create_bulk_params import (
    Document as KnowledgeDocumentInput,
)
from cartesia.types.agents.phone_number_import_params import Provider as ImportProvider
from cartesia.types.agents.phone_numbers.provider_update_params import (
    ProviderUpdateParams,
)
from cartesia.types.agents.tool_create_params import ToolCreateParams
from cartesia.types.agents.tool_update_params import ToolUpdateParams
from pydantic import Field

from cartesia_mcp import extra_api
from cartesia_mcp.branding import (
    playground_agent_url,
)
from cartesia_mcp.extra_api import (
    UsageInterval,
)
from cartesia_mcp.mcp_app import (
    _additive_tool,
    _api_client,
    _destructive_tool,
    _is_hosted,
    _read_only_tool,
    _real_world_tool,
    _require_admin_client,
    mcp,
)
from cartesia_mcp.utils import (
    agent_call_list_to_result,
    agent_version_list_to_result,
    condense_agent_call,
    list_response_to_result,
    page_result,
    sdk_page_to_result,
)


@mcp.tool(
    annotations=_read_only_tool("List agent models"),
    description="""
        List LLMs available for Managed Agents from GET /v1/agents/models.

        Use these `id` values for an agent's `model.id` (and explicit fallback
        model ids). Do not invent model ids, and do not use ids from
        `list_models` (`sonic-*`, `ink-*`). Those are speech models. Returns
        the full catalog (pagination is followed server-side).
        """)
def list_agent_models() -> dict[str, typing.Any]:
    return extra_api.list_agent_models(
        _api_client(),
    )


AgentCallDetail = typing.Literal["condensed", "full"]
PhoneNumberProviderType = typing.Literal["twilio", "cartesia", "sip_trunk"]
AGENT_CALL_LOGS_MAX_CHARS = 100_000
AGENT_CALLS_WITH_TRANSCRIPTS_MAX_LIMIT = 20
KNOWLEDGE_FILE_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".docx",
        ".html",
        ".md",
        ".csv",
        ".txt",
        ".json",
        ".yaml",
        ".yml",
        ".xml",
        ".tsv",
        ".log",
    }
)
KNOWLEDGE_FILE_MAX_BYTES = 20_000_000


def _or_omit(value: typing.Any) -> typing.Any:
    return omit if value is None else value


def _agent_with_playground_url(agent: typing.Any) -> dict[str, typing.Any]:
    result = agent.to_dict(mode="json")
    result["playground_url"] = playground_agent_url(result["id"])
    return result


@mcp.tool(
    annotations=_read_only_tool("List agents"),
    description="""
        List the account's Managed Agents, newest first. Call `get_agent` for
        the config.
        """)
def list_agents(
    q: typing.Annotated[
        typing.Optional[str],
        Field(description="Search agents by name."),
    ] = None,
    limit: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, le=100, description="Agents per page."),
    ] = 10,
    starting_after: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: `next_page` from the previous result."),
    ] = None,
    ending_before: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: agent ID to end before (previous page)."),
    ] = None,
) -> dict[str, typing.Any]:
    return sdk_page_to_result(
        _api_client().agents.list(
            q=_or_omit(q),
            limit=_or_omit(limit),
            starting_after=_or_omit(starting_after),
            ending_before=_or_omit(ending_before),
        )
    )


@mcp.tool(
    annotations=_read_only_tool("Get agent"),
    description="""
        Get a Managed Agent: the current `config`, the current `version`, and
        `playground_url` for trying the agent in the browser.

        `config.tools`, `config.knowledge_base_folders`, and
        `config.knowledge_base_documents` are `{id}` references, not
        definitions. Fetch each one with `get_agent_tool`, `get_knowledge_folder`,
        or `get_knowledge_document`.
        """)
def get_agent(
    agent_id: typing.Annotated[
        str,
        Field(min_length=1, description="Managed Agent ID (`agent_...`)."),
    ],
) -> dict[str, typing.Any]:
    return _agent_with_playground_url(_api_client().agents.retrieve(agent_id))


@mcp.tool(
    annotations=_additive_tool("Create agent"),
    description="""
        Create a Managed Agent: a hosted voice agent Cartesia runs for web,
        phone, and websocket calls.

        Write `config.instructions` for what the user described (role, goal,
        tone, steps, what to collect, when to end or transfer). An agent with
        no instructions runs a generic default prompt.

        - `config.model.id`: an id from `list_agent_models`.
        - `config.audio.output.voice_id`: a voice from `list_voices`.
        - `config.initial_message`: what the agent says first, or null to wait.
        - Per-caller context: reference `{{name}}` in instructions or the
          initial message, pass values when the call starts, and put sample
          values in `config.dynamic_variable_placeholders` for test calls.
        - Ending, transferring, DTMF, and voicemail detection are built in:
          enable them under `config.system_tools`.
        - `config.tools` takes ids from `create_agent_tool` or `list_agent_tools`.
        - `config.knowledge_base_folders` and `config.knowledge_base_documents`
          take ids from `list_knowledge_folders` and `list_knowledge_documents`.
        - `config.event_webhook_id` takes an id from `list_event_webhooks`.

        Open the returned `playground_url` to talk to the agent.
        """)
def create_agent(
    name: typing.Annotated[
        str,
        Field(min_length=1, description="Agent name. It does not need to be unique."),
    ],
    description: typing.Annotated[
        typing.Optional[str],
        Field(description="Short description of what the agent does."),
    ] = None,
    config: typing.Annotated[
        typing.Optional[AgentCreateConfig],
        Field(description="Agent config. Omitted fields use the API defaults."),
    ] = None,
) -> dict[str, typing.Any]:
    return _agent_with_playground_url(
        _api_client().agents.create(
            name=name,
            description=_or_omit(description),
            config=_or_omit(config),
        )
    )


@mcp.tool(
    annotations=_destructive_tool("Update agent", idempotent=False),
    description="""
        Update a Managed Agent. Send only the fields to change.

        Inside `config`, list and map fields (`tools`, `keyterms`,
        `knowledge_base_documents`, `dynamic_variable_placeholders`, ...)
        replace the existing value, so send the full list. Call `get_agent`
        first when editing one. To add or remove one tool or knowledge id,
        use `attach_agent_tool`, `detach_agent_tool`, `attach_knowledge_folder`,
        `detach_knowledge_folder`, `attach_knowledge_document`, or
        `detach_knowledge_document`. Those keep the other ids.

        Each `config` change publishes a new version, which live calls use
        right away. Describe it with `version_description`. Name and
        description changes do not create a version.
        """)
def update_agent(
    agent_id: typing.Annotated[
        str,
        Field(min_length=1, description="Managed Agent ID (`agent_...`)."),
    ],
    name: typing.Annotated[
        typing.Optional[str],
        Field(min_length=1, description="New agent name."),
    ] = None,
    description: typing.Annotated[
        typing.Optional[str],
        Field(description="New agent description."),
    ] = None,
    config: typing.Annotated[
        typing.Optional[AgentUpdateConfig],
        Field(description="Config fields to change."),
    ] = None,
    version_description: typing.Annotated[
        typing.Optional[str],
        Field(description="What changed, shown in version history. Only with `config`."),
    ] = None,
) -> dict[str, typing.Any]:
    if name is None and description is None and config is None:
        raise ValueError("Provide at least one of `name`, `description`, or `config`.")
    return _agent_with_playground_url(
        _api_client().agents.update(
            agent_id,
            name=_or_omit(name),
            description=_or_omit(description),
            config=_or_omit(config),
            version_description=_or_omit(version_description),
        )
    )


def _reference_ids(config: dict[str, typing.Any], key: str) -> list[str]:
    values = config.get(key) or []
    if not isinstance(values, list):
        return []
    return [
        value["id"]
        for value in values
        if isinstance(value, dict) and isinstance(value.get("id"), str)
    ]


def _set_agent_reference(
    agent_id: str, key: str, ref_id: str, *, attach: bool
) -> dict[str, typing.Any]:
    """Add or remove one `{id}` on an agent without replacing the other ids."""
    agent = _api_client().agents.retrieve(agent_id).to_dict(mode="json")
    config = agent.get("config")
    if not isinstance(config, dict):
        config = {}
    ids = _reference_ids(config, key)
    if attach:
        changed = ref_id not in ids
        if changed:
            ids.append(ref_id)
    else:
        changed = ref_id in ids
        ids = [existing for existing in ids if existing != ref_id]
    if not changed:
        agent["playground_url"] = playground_agent_url(str(agent["id"]))
        return agent
    return _agent_with_playground_url(
        _api_client().agents.update(
            agent_id,
            config=typing.cast(
                AgentUpdateConfig, {key: [{"id": item} for item in ids]}
            ),
        )
    )


@mcp.tool(
    annotations=_additive_tool("Attach agent tool"),
    description="""
        Add one tool id to an agent and keep the tools already attached. Prefer
        this over `update_agent` when adding a single tool. `config.tools`
        replaces the whole list. Publishes a new version when the tool was not
        already attached. Live calls use that version right away.
        """,
)
def attach_agent_tool(
    agent_id: typing.Annotated[
        str,
        Field(min_length=1, description="Managed Agent ID (`agent_...`)."),
    ],
    tool_id: typing.Annotated[
        str,
        Field(min_length=1, description="Tool ID from `create_agent_tool` or `list_agent_tools`."),
    ],
) -> dict[str, typing.Any]:
    return _set_agent_reference(agent_id, "tools", tool_id, attach=True)


@mcp.tool(
    annotations=_destructive_tool("Detach agent tool"),
    description="""
        Remove one tool id from an agent and keep the others. Confirm the tool
        and the agent with the user first. Publishes a new version when the
        tool was attached. Live calls use that version right away.
        """,
)
def detach_agent_tool(
    agent_id: typing.Annotated[
        str,
        Field(min_length=1, description="Managed Agent ID (`agent_...`)."),
    ],
    tool_id: typing.Annotated[
        str,
        Field(min_length=1, description="Tool ID currently in the agent's `config.tools`."),
    ],
) -> dict[str, typing.Any]:
    return _set_agent_reference(agent_id, "tools", tool_id, attach=False)


@mcp.tool(
    annotations=_additive_tool("Attach knowledge folder"),
    description="""
        Let an agent search one more knowledge folder, and keep the folders
        already attached. Prefer this over `update_agent`, which replaces
        `config.knowledge_base_folders`. Publishes a new version when the
        folder was not already attached.
        """,
)
def attach_knowledge_folder(
    agent_id: typing.Annotated[
        str,
        Field(min_length=1, description="Managed Agent ID (`agent_...`)."),
    ],
    folder_id: typing.Annotated[
        str,
        Field(min_length=1, description="Folder ID from `list_knowledge_folders`."),
    ],
) -> dict[str, typing.Any]:
    return _set_agent_reference(
        agent_id, "knowledge_base_folders", folder_id, attach=True
    )


@mcp.tool(
    annotations=_destructive_tool("Detach knowledge folder"),
    description="""
        Stop an agent searching one knowledge folder, and keep the others.
        Confirm the folder and the agent with the user first. Does not delete
        the folder. Publishes a new version when the folder was attached.
        """,
)
def detach_knowledge_folder(
    agent_id: typing.Annotated[
        str,
        Field(min_length=1, description="Managed Agent ID (`agent_...`)."),
    ],
    folder_id: typing.Annotated[
        str,
        Field(min_length=1, description="Folder ID currently on the agent."),
    ],
) -> dict[str, typing.Any]:
    return _set_agent_reference(
        agent_id, "knowledge_base_folders", folder_id, attach=False
    )


@mcp.tool(
    annotations=_additive_tool("Attach knowledge document"),
    description="""
        Let an agent search one more knowledge document, and keep the documents
        already attached. Prefer this over `update_agent`, which replaces
        `config.knowledge_base_documents`. Publishes a new version when the
        document was not already attached.
        """,
)
def attach_knowledge_document(
    agent_id: typing.Annotated[
        str,
        Field(min_length=1, description="Managed Agent ID (`agent_...`)."),
    ],
    document_id: typing.Annotated[
        str,
        Field(min_length=1, description="Document ID from `list_knowledge_documents`."),
    ],
) -> dict[str, typing.Any]:
    return _set_agent_reference(
        agent_id, "knowledge_base_documents", document_id, attach=True
    )


@mcp.tool(
    annotations=_destructive_tool("Detach knowledge document"),
    description="""
        Stop an agent searching one knowledge document, and keep the others.
        Confirm the document and the agent with the user first. Does not delete
        the document. Publishes a new version when the document was attached.
        """,
)
def detach_knowledge_document(
    agent_id: typing.Annotated[
        str,
        Field(min_length=1, description="Managed Agent ID (`agent_...`)."),
    ],
    document_id: typing.Annotated[
        str,
        Field(min_length=1, description="Document ID currently on the agent."),
    ],
) -> dict[str, typing.Any]:
    return _set_agent_reference(
        agent_id, "knowledge_base_documents", document_id, attach=False
    )


@mcp.tool(
    annotations=_destructive_tool("Delete agent"),
    description="""
        Permanently delete a Managed Agent. Confirm the agent's name with the
        user before calling this.
        """)
def delete_agent(
    agent_id: typing.Annotated[
        str,
        Field(min_length=1, description="Managed Agent ID (`agent_...`)."),
    ],
) -> dict[str, typing.Any]:
    _api_client().agents.delete(agent_id)
    return {"success": True}


@mcp.tool(
    annotations=_read_only_tool("List agent calls"),
    description="""
        List a Managed Agent's calls, newest first, to debug them. Pass a call
        `id` to `get_agent_call` for one call's transcript.

        For a complaint with no call ID, set `include_transcripts` to get each
        call's condensed transcript in one request (same view as
        `get_agent_call`). Narrow with `start_time_gte`, `start_time_lte`, and
        `batch_id` first. With transcripts, `limit` is capped at 20.

        Apps should not poll this for new calls; configure an event webhook
        on the agent instead.
        """)
def list_agent_calls(
    agent_id: typing.Annotated[
        str,
        Field(min_length=1, description="Managed Agent ID (`agent_...`). The API requires it."),
    ],
    limit: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, le=100, description="Calls per page."),
    ] = 10,
    starting_after: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: `next_page` from the previous result."),
    ] = None,
    ending_before: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: call ID to end before (previous page)."),
    ] = None,
    include_transcripts: typing.Annotated[
        bool,
        Field(
            description="Include each call's condensed transcript (same view as `get_agent_call`)."
        ),
    ] = False,
    start_time_gte: typing.Annotated[
        typing.Optional[str],
        Field(description="Only calls that started at or after this RFC 3339 time."),
    ] = None,
    start_time_lte: typing.Annotated[
        typing.Optional[str],
        Field(description="Only calls that started at or before this RFC 3339 time."),
    ] = None,
    batch_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Only calls from this call batch ID."),
    ] = None,
) -> dict[str, typing.Any]:
    if include_transcripts and limit is not None and limit > AGENT_CALLS_WITH_TRANSCRIPTS_MAX_LIMIT:
        raise ValueError(
            f"Use `limit` of {AGENT_CALLS_WITH_TRANSCRIPTS_MAX_LIMIT} or less "
            "with `include_transcripts`."
        )
    time_and_batch = {
        key: value
        for key, value in {
            "start_time_gte": start_time_gte,
            "start_time_lte": start_time_lte,
            "batch_id": batch_id,
        }.items()
        if value is not None
    }
    return agent_call_list_to_result(
        sdk_page_to_result(
            _api_client().agents.calls.list(
                agent_id=agent_id,
                limit=_or_omit(limit),
                starting_after=_or_omit(starting_after),
                ending_before=_or_omit(ending_before),
                expand=_or_omit("transcript" if include_transcripts else None),
                extra_query=time_and_batch or None,
            )
        ),
        condensed=include_transcripts,
    )


@mcp.tool(
    annotations=_read_only_tool("Get agent call"),
    description="""
        Get one Managed Agent call to debug it.

        By default (`detail="condensed"`) returns the outcome (`status`,
        `end_reason`, `error_message`, `summary`), `agent_version_id`,
        `dynamic_variables`, the connection, `latency_ms` (count, mean and max
        per metric, such as `llm_first_text_ms` and `agent_turn_ms`), and each
        turn's role, text, timing in seconds, interruption, TTS time to first
        byte, and tool calls with arguments and results (long results are
        truncated; `result_chars` is the full length). Pass `detail="full"` for
        the raw API payload. Runtime log lines are in `get_agent_call_logs`.

        The agent's current config may have changed since the call. To read
        the config that actually ran, pass `agent_id` and `agent_version_id`
        to `get_agent_version`.
        """)
def get_agent_call(
    call_id: typing.Annotated[
        str,
        Field(min_length=1, description="Call ID (`ac_...`) from `list_agent_calls`."),
    ],
    detail: typing.Annotated[
        AgentCallDetail,
        Field(description="`condensed` (default) or `full` for the raw call JSON."),
    ] = "condensed",
) -> dict[str, typing.Any]:
    call = _api_client().agents.calls.retrieve(call_id).to_dict(mode="json")
    if detail == "full":
        return call
    return condense_agent_call(call)


@mcp.tool(
    annotations=_read_only_tool("Get agent call logs"),
    description="""
        Get the runtime log lines for one Managed Agent call. The transcript
        does not include them. Check these first when a call failed or a tool
        did not run.

        Returns up to about 100,000 characters of lines; `truncated` is true
        when later lines were dropped.
        """)
def get_agent_call_logs(
    call_id: typing.Annotated[
        str,
        Field(min_length=1, description="Call ID (`ac_...`) from `list_agent_calls`."),
    ],
) -> dict[str, typing.Any]:
    response = _api_client().agents.calls.logs(call_id)
    kept: list[str] = []
    size = 0
    for line in response.logs:
        if size + len(line) > AGENT_CALL_LOGS_MAX_CHARS:
            break
        kept.append(line)
        size += len(line)
    return {
        **response.to_dict(mode="json"),
        "logs": kept,
        "truncated": len(kept) < len(response.logs),
    }


@mcp.tool(
    annotations=_read_only_tool("List agent versions"),
    description="""
        List a Managed Agent's config versions, newest first.

        Every config change creates an immutable version. Rows have `id`,
        `created_at`, and `description`; call `get_agent_version` for the
        config.
        """)
def list_agent_versions(
    agent_id: typing.Annotated[
        str,
        Field(min_length=1, description="Managed Agent ID (`agent_...`)."),
    ],
    limit: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, le=100, description="Versions per page."),
    ] = 10,
    starting_after: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: `next_page` from the previous result."),
    ] = None,
    ending_before: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: version ID to end before (previous page)."),
    ] = None,
) -> dict[str, typing.Any]:
    return agent_version_list_to_result(
        sdk_page_to_result(
            _api_client().agents.versions.list(
                agent_id,
                limit=_or_omit(limit),
                starting_after=_or_omit(starting_after),
                ending_before=_or_omit(ending_before),
            )
        )
    )


@mcp.tool(
    annotations=_read_only_tool("Get agent version"),
    description="""
        Get one Managed Agent config version: instructions, voice, model,
        tools, and the rest of the config as it was saved.

        Use the `agent_version_id` from `get_agent_call` to see the config a
        call ran with. Versions are read-only; there is no restore. To roll
        back, send this config to `update_agent`.
        """)
def get_agent_version(
    agent_id: typing.Annotated[
        str,
        Field(min_length=1, description="Managed Agent ID (`agent_...`)."),
    ],
    version_id: typing.Annotated[
        str,
        Field(min_length=1, description="Version ID (`av_...`)."),
    ],
) -> dict[str, typing.Any]:
    return (
        _api_client()
        .agents.versions.retrieve(version_id, agent_id=agent_id)
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_read_only_tool("List phone numbers"),
    description="""
        List the account's Managed Agents phone numbers and which agent each
        one routes inbound calls to (`agent`, or `null` when unassigned).

        Filter by `agent_id` to check whether an agent answers any number.
        """)
def list_phone_numbers(
    agent_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Only numbers assigned to this agent for inbound calls."),
    ] = None,
    type: typing.Annotated[
        typing.Optional[PhoneNumberProviderType],
        Field(description="Provider type: `cartesia`, `twilio`, or `sip_trunk`."),
    ] = None,
    q: typing.Annotated[
        typing.Optional[str],
        Field(description="Search by number or label."),
    ] = None,
    limit: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, le=100, description="Numbers per page."),
    ] = 10,
    starting_after: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: `next_page` from the previous result."),
    ] = None,
    ending_before: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: phone number ID to end before (previous page)."),
    ] = None,
) -> dict[str, typing.Any]:
    page = _api_client().agents.phone_numbers.list(
        agent_id=_or_omit(agent_id),
        type=_or_omit(type),
        q=_or_omit(q),
        limit=_or_omit(limit),
        starting_after=_or_omit(starting_after),
        ending_before=_or_omit(ending_before),
    )
    return page_result([number.to_dict(mode="json") for number in page.data], page.has_more)


@mcp.tool(
    annotations=_read_only_tool("Get phone number"),
    description="""
        Get one Managed Agents phone number: the number, label, assigned agent,
        and provider (SIP trunk passwords are never returned).
        """)
def get_phone_number(
    phone_number_id: typing.Annotated[
        str,
        Field(min_length=1, description="Phone number ID from `list_phone_numbers`."),
    ],
) -> dict[str, typing.Any]:
    return _api_client().agents.phone_numbers.retrieve(phone_number_id).to_dict(mode="json")


AgentToolType = typing.Literal["webhook", "client"]
TwilioRegion = typing.Literal["us1", "ie1", "au1"]


def _agent_tool_page(page: typing.Any) -> dict[str, typing.Any]:
    rows = []
    for tool in page.data:
        raw = tool.to_dict(mode="json")
        row = {key: raw.get(key) for key in ("id", "name", "description", "type")}
        if raw.get("agents") is not None:
            row["agents"] = raw["agents"]
        rows.append(row)
    return page_result(rows, page.has_more, page.next_page)


@mcp.tool(
    annotations=_read_only_tool("List agent tools"),
    description="""
        List tools an agent can call during a conversation: `webhook` (Cartesia
        calls your HTTPS endpoint) and `client` (the caller's app runs it).

        Rows have `id`, `name`, `description`, and `type`. Call `get_agent_tool`
        for the request schema. Pass `expand` as `agents` to see which agents
        use each tool. Attach an id with `config.tools` on `create_agent` or
        `update_agent`.
        """,
)
def list_agent_tools(
    agent_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Only tools this agent uses."),
    ] = None,
    type: typing.Annotated[
        typing.Optional[AgentToolType],
        Field(description="`webhook` or `client`."),
    ] = None,
    expand: typing.Annotated[
        typing.Optional[list[typing.Literal["agents"]]],
        Field(description="`agents` includes the agents that use each tool."),
    ] = None,
    limit: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, le=100, description="Tools per page."),
    ] = 10,
    starting_after: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: `next_page` from the previous result."),
    ] = None,
    ending_before: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: tool ID to end before (previous page)."),
    ] = None,
) -> dict[str, typing.Any]:
    return _agent_tool_page(
        _api_client().agents.tools.list(
            agent_id=_or_omit(agent_id),
            type=_or_omit(type),
            expand=_or_omit(expand),
            limit=_or_omit(limit),
            starting_after=_or_omit(starting_after),
            ending_before=_or_omit(ending_before),
        )
    )


@mcp.tool(
    annotations=_read_only_tool("Get agent tool"),
    description="""
        Get one agent tool: its name, description, and how it runs.

        A webhook tool includes its URL, method, and parameter schemas.
        Credentials are write-only, so `secret_value` is never returned. Pass
        `expand` as `agents` to see which agents use it.
        """,
)
def get_agent_tool(
    tool_id: typing.Annotated[
        str,
        Field(min_length=1, description="Tool ID from `list_agent_tools`."),
    ],
    expand: typing.Annotated[
        typing.Optional[list[typing.Literal["agents"]]],
        Field(description="`agents` includes the agents that use this tool."),
    ] = None,
) -> dict[str, typing.Any]:
    return (
        _api_client()
        .agents.tools.retrieve(tool_id, expand=_or_omit(expand))
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_additive_tool("Create agent tool", open_world=True),
    description="""
        Create a tool an agent can call, then attach the returned `id` in
        `config.tools` on `create_agent` or `update_agent`.

        `type` is `webhook` (Cartesia sends an HTTPS request; put the URL and
        parameters in `api_schema`) or `client` (the caller's app handles the
        call; describe the arguments in `parameters`). `name` is what the agent
        says when it calls the tool, and `description` says when to use it.

        Credentials go in `secret_value` and are never returned. Do not put a
        secret in `secret_description`.
        """,
)
def create_agent_tool(
    tool: typing.Annotated[
        ToolCreateParams,
        Field(description="Webhook or client tool."),
    ],
) -> dict[str, typing.Any]:
    # The SDK types this as two overloads, which a spread union does not match.
    return (
        _api_client()
        .agents.tools.create(**typing.cast(typing.Any, tool))
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_destructive_tool("Update agent tool", open_world=True),
    description="""
        Change an agent tool. Send only the fields to change.

        `api_schema`, `parameters`, and `assignments` replace the stored value,
        so send the whole object when editing one part. Call `get_agent_tool`
        first.
        """,
)
def update_agent_tool(
    tool_id: typing.Annotated[
        str,
        Field(min_length=1, description="Tool ID from `list_agent_tools`."),
    ],
    tool: typing.Annotated[
        ToolUpdateParams,
        Field(description="Fields to change."),
    ],
) -> dict[str, typing.Any]:
    if not tool:
        raise ValueError("Provide at least one field to change.")
    # The SDK types this as two overloads, which a spread union does not match.
    return (
        _api_client()
        .agents.tools.update(tool_id, **typing.cast(typing.Any, tool))
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_destructive_tool("Delete agent tool"),
    description="""
        Delete an agent tool that no agent uses. Detach it from every agent's
        `config.tools` first, and confirm the tool's name with the user.
        """,
)
def delete_agent_tool(
    tool_id: typing.Annotated[
        str,
        Field(min_length=1, description="Tool ID from `list_agent_tools`."),
    ],
) -> dict[str, typing.Any]:
    _api_client().agents.tools.delete(tool_id)
    return {"success": True}


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------


def _without_content(document: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Documents can hold up to 1 MB of text. Rows report its size; `get_knowledge_document` has it."""
    content = document.pop("content", None)
    if isinstance(content, str):
        document["content_chars"] = len(content)
    return document


@mcp.tool(
    annotations=_read_only_tool("List knowledge folders"),
    description="""
        List knowledge base folders with their documents and the agents that can
        search them. Returns top-level folders unless `parent_id` is set; nested
        folders come back in `children` up to `depth`. Documents filed at the
        root are in `root_documents`.

        Give an agent access by putting a folder or document id in
        `config.knowledge_base_folders` or `config.knowledge_base_documents` on
        `create_agent` or `update_agent`.
        """,
)
def list_knowledge_folders(
    parent_id: typing.Annotated[
        typing.Optional[str],
        Field(
            description="Only subfolders of this folder. Omit for top-level folders."
        ),
    ] = None,
    depth: typing.Annotated[
        typing.Optional[int],
        Field(
            ge=1,
            le=3,
            description="Levels of nested `children` to include (default 3).",
        ),
    ] = None,
    limit: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, le=100, description="Top-level folders per page."),
    ] = 10,
    starting_after: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: `next_page` from the previous result."),
    ] = None,
    ending_before: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: folder ID to end before (previous page)."),
    ] = None,
) -> dict[str, typing.Any]:
    response = _api_client().agents.knowledge_base.folders.list(
        parent_ids=[parent_id] if parent_id else omit,
        depth=_or_omit(depth),
        limit=_or_omit(limit),
        starting_after=_or_omit(starting_after),
        ending_before=_or_omit(ending_before),
    )
    result = list_response_to_result(response)
    if response.root_documents:
        result["root_documents"] = [
            d.to_dict(mode="json") for d in response.root_documents
        ]
    return result


@mcp.tool(
    annotations=_read_only_tool("Get knowledge folder"),
    description="Get one knowledge base folder with its documents and the agents that can search it.",
)
def get_knowledge_folder(
    folder_id: typing.Annotated[
        str,
        Field(min_length=1, description="Folder ID from `list_knowledge_folders`."),
    ],
) -> dict[str, typing.Any]:
    return (
        _api_client()
        .agents.knowledge_base.folders.retrieve(folder_id)
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_additive_tool("Create knowledge folder"),
    description="""
        Create a knowledge base folder. Names must be unique among siblings.
        Add documents with `create_knowledge_documents`, then attach the folder
        to an agent through `config.knowledge_base_folders`.
        """,
)
def create_knowledge_folder(
    name: typing.Annotated[str, Field(min_length=1, description="Folder name.")],
    parent_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Parent folder ID. Omit for a top-level folder."),
    ] = None,
) -> dict[str, typing.Any]:
    return (
        _api_client()
        .agents.knowledge_base.folders.create(name=name, parent_id=_or_omit(parent_id))
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_destructive_tool("Update knowledge folder"),
    description="""
        Rename a knowledge base folder or move it under another folder. Send only
        the fields to change. To move a document, use `update_knowledge_document`.
        """,
)
def update_knowledge_folder(
    folder_id: typing.Annotated[
        str,
        Field(min_length=1, description="Folder ID from `list_knowledge_folders`."),
    ],
    name: typing.Annotated[
        typing.Optional[str],
        Field(description="New name, unique among siblings."),
    ] = None,
    parent_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Move the folder under this folder. Cannot create a cycle."),
    ] = None,
) -> dict[str, typing.Any]:
    if name is None and parent_id is None:
        raise ValueError("Provide at least one of name or parent_id.")
    return (
        _api_client()
        .agents.knowledge_base.folders.update(
            folder_id, name=_or_omit(name), parent_id=_or_omit(parent_id)
        )
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_destructive_tool("Delete knowledge folder"),
    description="""
        Permanently delete a knowledge base folder. Confirm the folder's name
        with the user first.

        Fails if the folder has subfolders or an agent can search it. Set `force`
        only after the user agrees: it also deletes every subfolder and document
        inside, and agents lose access to them.
        """,
)
def delete_knowledge_folder(
    folder_id: typing.Annotated[
        str,
        Field(min_length=1, description="Folder ID from `list_knowledge_folders`."),
    ],
    force: typing.Annotated[
        bool,
        Field(
            description="Delete even with subfolders or agents attached, and delete their contents."
        ),
    ] = False,
) -> dict[str, typing.Any]:
    _api_client().agents.knowledge_base.folders.delete(
        folder_id, force="true" if force else omit
    )
    return {"success": True}


@mcp.tool(
    annotations=_read_only_tool("List knowledge documents"),
    description="""
        List knowledge base documents. Rows have `id`, `name`, `status`
        (`processing`, `ready`, or `failed`), `error`, `metadata`, and
        `content_chars`. Call `get_knowledge_document` for the text.
        """,
)
def list_knowledge_documents(
    limit: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, le=100, description="Documents per page."),
    ] = 10,
    starting_after: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: `next_page` from the previous result."),
    ] = None,
    ending_before: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: document ID to end before (previous page)."),
    ] = None,
) -> dict[str, typing.Any]:
    result = sdk_page_to_result(
        _api_client().agents.knowledge_base.documents.list(
            limit=_or_omit(limit),
            starting_after=_or_omit(starting_after),
            ending_before=_or_omit(ending_before),
        )
    )
    result["data"] = [_without_content(row) for row in result["data"]]
    return result


@mcp.tool(
    annotations=_read_only_tool("Get knowledge document"),
    description="Get one knowledge base document, including its text and processing `status`.",
)
def get_knowledge_document(
    document_id: typing.Annotated[
        str,
        Field(min_length=1, description="Document ID from `list_knowledge_documents`."),
    ],
) -> dict[str, typing.Any]:
    return (
        _api_client()
        .agents.knowledge_base.documents.retrieve(document_id)
        .to_dict(mode="json")
    )


class KnowledgeDocumentUpload(typing.TypedDict, total=False):
    content: str
    file_id: str
    file_path: str
    folder_id: str
    name: str
    metadata: dict[str, str]


def _knowledge_file_path(document: KnowledgeDocumentUpload) -> Path | None:
    """The checked local file to upload for ``document``, or None if it has none."""
    sources = [
        key for key in ("content", "file_id", "file_path") if document.get(key)
    ]
    if len(sources) != 1:
        raise ValueError(
            "Each document needs exactly one of `content`, `file_id`, or `file_path`."
        )
    file_path = document.get("file_path")
    if not file_path:
        return None
    if _is_hosted:
        raise ValueError(
            "Hosted MCP cannot read `file_path`. Pass `content`, or a `file_id` "
            "from a file uploaded with purpose `knowledge_base_document`."
        )
    path = Path(file_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"`file_path` is not a file: {path}")
    # Document extensions keep keys, `.env`, and extensionless credential files
    # out. Hidden folders stay allowed because projects live in them (agent
    # worktrees, `~/.config`); the client's approval of this call covers the rest.
    if path.suffix.lower() not in KNOWLEDGE_FILE_EXTENSIONS:
        raise ValueError(
            "`file_path` must be one of: "
            + ", ".join(sorted(KNOWLEDGE_FILE_EXTENSIONS))
        )
    if path.stat().st_size > KNOWLEDGE_FILE_MAX_BYTES:
        raise ValueError("`file_path` is larger than 20 MB.")
    return path


def _knowledge_document_for_sdk(
    document: KnowledgeDocumentUpload, path: Path | None
) -> KnowledgeDocumentInput:
    prepared: dict[str, typing.Any] = {
        key: value
        for key, value in document.items()
        if key != "file_path" and value is not None
    }
    if path is not None:
        uploaded = extra_api.upload_file(
            _api_client(),
            filename=path.name,
            content=path.read_bytes(),
            purpose="knowledge_base_document",
        )
        file_id = uploaded.get("id")
        if not isinstance(file_id, str) or not file_id:
            raise RuntimeError("files API did not return a file id")
        prepared["file_id"] = file_id
    return typing.cast(KnowledgeDocumentInput, prepared)


@mcp.tool(
    annotations=_additive_tool("Create knowledge documents"),
    description="""
        Upload 1 to 100 documents agents can search during calls. Each needs
        exactly one of `content` (text, up to 1 MB), `file_id` (a file already
        uploaded with purpose `knowledge_base_document`), or `file_path` (an
        absolute path on the local MCP server). `file_path` is uploaded for
        you and must be a document under 20 MB (PDF, `.docx`, HTML, Markdown,
        text, CSV, JSON, YAML, or XML). Hosted MCP
        cannot read a path: pass `content` or `file_id`. Each document may set
        `name`, `folder_id`, and `metadata` (string values, used to filter
        retrieval).

        Documents start as `processing`. Check `status` with
        `get_knowledge_document`, and use `retry_knowledge_document` on a
        `failed` one. Returns each document without its text.
        """,
)
def create_knowledge_documents(
    documents: typing.Annotated[
        list[KnowledgeDocumentUpload],
        Field(min_length=1, max_length=100, description="Documents to upload."),
    ],
) -> dict[str, typing.Any]:
    paths = [_knowledge_file_path(document) for document in documents]
    created = _api_client().agents.knowledge_base.documents.create_bulk(
        documents=[
            _knowledge_document_for_sdk(document, path)
            for document, path in zip(documents, paths, strict=True)
        ]
    )
    return {"data": [_without_content(d.to_dict(mode="json")) for d in created]}


@mcp.tool(
    annotations=_destructive_tool("Update knowledge document"),
    description="""
        Change a knowledge base document's text, name, metadata, or folder. Send
        only the fields to change. New `content` replaces the old text and the
        document is processed again. Call `get_knowledge_document` first.
        """,
)
def update_knowledge_document(
    document_id: typing.Annotated[
        str,
        Field(min_length=1, description="Document ID from `list_knowledge_documents`."),
    ],
    content: typing.Annotated[
        typing.Optional[str],
        Field(description="Replacement text (up to 1 MB)."),
    ] = None,
    name: typing.Annotated[
        typing.Optional[str], Field(description="New display name.")
    ] = None,
    folder_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Move the document into this folder."),
    ] = None,
    metadata: typing.Annotated[
        typing.Optional[dict[str, str]],
        Field(description="Metadata for retrieval filters, string values only."),
    ] = None,
) -> dict[str, typing.Any]:
    if content is None and name is None and folder_id is None and metadata is None:
        raise ValueError("Provide at least one field to change.")
    updated = _api_client().agents.knowledge_base.documents.update(
        document_id,
        content=_or_omit(content),
        name=_or_omit(name),
        folder_id=_or_omit(folder_id),
        metadata=_or_omit(metadata),
    )
    return _without_content(updated.to_dict(mode="json"))


@mcp.tool(
    annotations=_destructive_tool("Delete knowledge document"),
    description="""
        Permanently delete a knowledge base document. Confirm its name with the
        user first. Fails if an agent can search it; set `force` only after the
        user agrees, and agents will stop using it.
        """,
)
def delete_knowledge_document(
    document_id: typing.Annotated[
        str,
        Field(min_length=1, description="Document ID from `list_knowledge_documents`."),
    ],
    force: typing.Annotated[
        bool,
        Field(description="Delete even if agents can search it."),
    ] = False,
) -> dict[str, typing.Any]:
    _api_client().agents.knowledge_base.documents.delete(
        document_id, force="true" if force else omit
    )
    return {"success": True}


@mcp.tool(
    annotations=_additive_tool("Retry knowledge document"),
    description="Process a knowledge base document again, for one whose `status` is `failed`.",
)
def retry_knowledge_document(
    document_id: typing.Annotated[
        str,
        Field(min_length=1, description="Document ID from `list_knowledge_documents`."),
    ],
) -> dict[str, typing.Any]:
    retried = _api_client().agents.knowledge_base.documents.retry(document_id)
    return _without_content(retried.to_dict(mode="json"))


# ---------------------------------------------------------------------------
# Event webhooks
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=_read_only_tool("List event webhooks"),
    description="""
        List event webhooks: HTTPS endpoints Cartesia POSTs call events to. Attach
        one to an agent with `config.event_webhook_id` on `create_agent` or
        `update_agent`. Secrets are write-only and never returned.
        """,
)
def list_event_webhooks(
    limit: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, le=100, description="Webhooks per page."),
    ] = 10,
    starting_after: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: `next_page` from the previous result."),
    ] = None,
    ending_before: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: webhook ID to end before (previous page)."),
    ] = None,
) -> dict[str, typing.Any]:
    return sdk_page_to_result(
        _api_client().agents.webhooks.list(
            limit=_or_omit(limit),
            starting_after=_or_omit(starting_after),
            ending_before=_or_omit(ending_before),
        )
    )


@mcp.tool(
    annotations=_read_only_tool("Get event webhook"),
    description="Get one event webhook's URL and name. The secret is never returned.",
)
def get_event_webhook(
    webhook_id: typing.Annotated[
        str,
        Field(min_length=1, description="Webhook ID from `list_event_webhooks`."),
    ],
) -> dict[str, typing.Any]:
    return _api_client().agents.webhooks.retrieve(webhook_id).to_dict(mode="json")


@mcp.tool(
    annotations=_additive_tool("Create event webhook", open_world=True),
    description="""
        Create an event webhook. Cartesia POSTs call events to `url` and sends
        `secret` back in the `X-Webhook-Secret` header so your endpoint can verify
        the request. The user chooses the secret and keeps their own copy. Ask
        them for it before calling. The result does not include it, and neither
        do `get_event_webhook` or `list_event_webhooks`.
        Attach the returned `id` to an agent with `config.event_webhook_id`.
        """,
)
def create_event_webhook(
    url: typing.Annotated[
        str, Field(min_length=1, description="HTTPS endpoint to receive events.")
    ],
    secret: typing.Annotated[
        str,
        Field(min_length=1, description="Shared secret sent in `X-Webhook-Secret`."),
    ],
    display_name: typing.Annotated[
        typing.Optional[str],
        Field(description="Name to identify the webhook."),
    ] = None,
) -> dict[str, typing.Any]:
    created = _api_client().agents.webhooks.create(
        url=url, secret=secret, display_name=_or_omit(display_name)
    )
    result = created.to_dict(mode="json")
    result.pop("secret", None)
    return result


@mcp.tool(
    annotations=_destructive_tool("Update event webhook", open_world=True),
    description="""
        Change an event webhook. `url` is required even when unchanged. Omit
        `secret` to keep the stored one. Agents using this webhook start sending
        events to the new URL right away, so confirm the change with the user.
        """,
)
def update_event_webhook(
    webhook_id: typing.Annotated[
        str,
        Field(min_length=1, description="Webhook ID from `list_event_webhooks`."),
    ],
    url: typing.Annotated[
        str, Field(min_length=1, description="HTTPS endpoint to receive events.")
    ],
    display_name: typing.Annotated[
        typing.Optional[str],
        Field(description="New name."),
    ] = None,
    secret: typing.Annotated[
        typing.Optional[str],
        Field(description="New shared secret. Omit to keep the current one."),
    ] = None,
) -> dict[str, typing.Any]:
    _api_client().agents.webhooks.update(
        webhook_id,
        url=url,
        display_name=_or_omit(display_name),
        secret=_or_omit(secret),
    )
    return {"success": True}


@mcp.tool(
    annotations=_destructive_tool("Delete event webhook"),
    description="""
        Permanently delete an event webhook. Confirm its name and URL with the
        user first, since agents using it stop sending events.
        """,
)
def delete_event_webhook(
    webhook_id: typing.Annotated[
        str,
        Field(min_length=1, description="Webhook ID from `list_event_webhooks`."),
    ],
) -> dict[str, typing.Any]:
    _api_client().agents.webhooks.delete(webhook_id)
    return {"success": True}


# ---------------------------------------------------------------------------
# Evaluation metrics
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=_read_only_tool("List agent metrics"),
    description="""
        List evaluation metrics. A metric is a prompt an LLM runs over finished
        calls to score them. Metrics apply to the agents they are attached to
        with `attach_agent_metric`; read scores with `list_agent_metric_results`.
        """,
)
def list_agent_metrics(
    limit: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, le=100, description="Metrics per page."),
    ] = 10,
    starting_after: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: `next_page` from the previous result."),
    ] = None,
) -> dict[str, typing.Any]:
    return list_response_to_result(
        _api_client().agents.metrics.list(
            limit=_or_omit(limit), starting_after=_or_omit(starting_after)
        )
    )


@mcp.tool(
    annotations=_read_only_tool("Get agent metric"),
    description="Get one evaluation metric with its `name` and scoring `prompt`.",
)
def get_agent_metric(
    metric_id: typing.Annotated[
        str,
        Field(min_length=1, description="Metric ID from `list_agent_metrics`."),
    ],
) -> dict[str, typing.Any]:
    return _api_client().agents.metrics.retrieve(metric_id).to_dict(mode="json")


@mcp.tool(
    annotations=_additive_tool("Create agent metric"),
    description="""
        Create an evaluation metric. `prompt` describes the task and the criteria
        an LLM uses to score a finished call, for example "Did the agent confirm
        the caller's appointment time?". `name` must be unique. The metric does
        nothing until you call `attach_agent_metric`.
        """,
)
def create_agent_metric(
    name: typing.Annotated[
        str,
        Field(min_length=1, description="Unique identifier for the metric."),
    ],
    prompt: typing.Annotated[
        str,
        Field(min_length=1, description="Task and scoring criteria."),
    ],
    display_name: typing.Annotated[
        typing.Optional[str],
        Field(description="Name shown in the playground."),
    ] = None,
) -> dict[str, typing.Any]:
    return (
        _api_client()
        .agents.metrics.create(
            name=name, prompt=prompt, display_name=_or_omit(display_name)
        )
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_destructive_tool("Delete agent metric"),
    description="""
        Permanently delete an evaluation metric. Confirm its name with the user
        first. Agents stop scoring calls with it.
        """,
)
def delete_agent_metric(
    metric_id: typing.Annotated[
        str,
        Field(min_length=1, description="Metric ID from `list_agent_metrics`."),
    ],
) -> dict[str, typing.Any]:
    _api_client().agents.metrics.delete(metric_id)
    return {"success": True}


@mcp.tool(
    annotations=_additive_tool("Attach agent metric"),
    description="Score an agent's finished calls with a metric from now on.",
)
def attach_agent_metric(
    metric_id: typing.Annotated[
        str,
        Field(min_length=1, description="Metric ID from `list_agent_metrics`."),
    ],
    agent_id: typing.Annotated[str, Field(min_length=1, description="Agent ID.")],
) -> dict[str, typing.Any]:
    _api_client().agents.metrics.add_to_agent(metric_id, agent_id=agent_id)
    return {"success": True}


@mcp.tool(
    annotations=_destructive_tool("Detach agent metric"),
    description="""
        Stop scoring an agent's calls with a metric. Existing results stay.
        Confirm the metric and agent with the user first.
        """,
)
def detach_agent_metric(
    metric_id: typing.Annotated[
        str,
        Field(min_length=1, description="Metric ID from `list_agent_metrics`."),
    ],
    agent_id: typing.Annotated[str, Field(min_length=1, description="Agent ID.")],
) -> dict[str, typing.Any]:
    _api_client().agents.metrics.remove_from_agent(metric_id, agent_id=agent_id)
    return {"success": True}


@mcp.tool(
    annotations=_read_only_tool("List agent metric results"),
    description="""
        List evaluation scores for finished calls, newest first. Filter by agent,
        call, metric, or `start_date` and `end_date` (ISO 8601). Use
        `export_agent_metric_results` for a CSV of many rows.
        """,
)
def list_agent_metric_results(
    agent_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Only results for this agent."),
    ] = None,
    call_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Only results for this call."),
    ] = None,
    metric_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Only results for this metric."),
    ] = None,
    start_date: typing.Annotated[
        typing.Optional[str],
        Field(description="Results created at or after this ISO 8601 time."),
    ] = None,
    end_date: typing.Annotated[
        typing.Optional[str],
        Field(description="Results created at or before this ISO 8601 time."),
    ] = None,
    limit: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, le=100, description="Results per page."),
    ] = 10,
    starting_after: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: `next_page` from the previous result."),
    ] = None,
    ending_before: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: result ID to end before (previous page)."),
    ] = None,
) -> dict[str, typing.Any]:
    return sdk_page_to_result(
        _api_client().agents.metrics.results.list(
            agent_id=_or_omit(agent_id),
            call_id=_or_omit(call_id),
            metric_id=_or_omit(metric_id),
            start_date=_or_omit(start_date),
            end_date=_or_omit(end_date),
            limit=_or_omit(limit),
            starting_after=_or_omit(starting_after),
            ending_before=_or_omit(ending_before),
        )
    )


EXPORT_RESULTS_MAX_CHARS = 100_000


@mcp.tool(
    annotations=_read_only_tool("Export agent metric results"),
    description="""
        Export evaluation scores as CSV text, up to 100k rows from the API and
        100,000 characters here. When `truncated` is true, narrow the filters.
        """,
)
def export_agent_metric_results(
    agent_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Only results for this agent."),
    ] = None,
    call_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Only results for this call."),
    ] = None,
    metric_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Only results for this metric."),
    ] = None,
    start_date: typing.Annotated[
        typing.Optional[str],
        Field(description="Results created at or after this ISO 8601 time."),
    ] = None,
    end_date: typing.Annotated[
        typing.Optional[str],
        Field(description="Results created at or before this ISO 8601 time."),
    ] = None,
) -> dict[str, typing.Any]:
    csv = _api_client().agents.metrics.results.export(
        agent_id=_or_omit(agent_id),
        call_id=_or_omit(call_id),
        metric_id=_or_omit(metric_id),
        start_date=_or_omit(start_date),
        end_date=_or_omit(end_date),
    )
    return {
        "csv": csv[:EXPORT_RESULTS_MAX_CHARS],
        "truncated": len(csv) > EXPORT_RESULTS_MAX_CHARS,
        "total_chars": len(csv),
    }


# ---------------------------------------------------------------------------
# Phone numbers and telephony providers
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=_read_only_tool("Get phone provisioning usage"),
    description="""
        Get this month's Cartesia-managed phone number provisioning usage:
        `monthly_usage`, `monthly_limit`, and `remaining`. Numbers deleted this
        month still count. A null limit means the plan has none.
        """)
def get_phone_provisioning_usage() -> dict[str, typing.Any]:
    return _api_client().agents.phone_numbers.provisioning_usage().to_dict(mode="json")


@mcp.tool(
    annotations=_real_world_tool("Provision phone number"),
    description="""
        Buy a new Cartesia-managed phone number. This can incur charges and cannot
        be undone from here. Only call it after the user has confirmed, in this
        conversation, that they want a new number and its label.

        The number is not assigned to an agent. Read `number` from the result
        back to the user. Assign it with `update_phone_number` only after they
        have confirmed that number.

        Check `remaining` from `get_phone_provisioning_usage` first. If it is 0,
        tell the user the monthly limit is reached instead of buying.

        Cartesia numbers take inbound calls and outbound calls to US numbers.
        """,
)
def provision_phone_number(
    label: typing.Annotated[
        str,
        Field(min_length=1, description="Human-readable name for the number."),
    ],
) -> dict[str, typing.Any]:
    return _api_client().agents.phone_numbers.provision(label=label).to_dict(mode="json")


@mcp.tool(
    annotations=_additive_tool("Import phone number"),
    description="""
        Link a number you already own to Cartesia through a provider from
        `list_phone_providers`. `provider` is `{"id": "<provider id>"}`, or
        `{"type": "twilio", "account_sid": "...", "region": "us1"}` to look the
        provider up by Twilio account. The number must be in that account.

        With `agent_id`, inbound calls to the number start answering with that
        agent, so confirm the number and agent with the user first.
        """,
)
def import_phone_number(
    label: typing.Annotated[
        str,
        Field(min_length=1, description="Human-readable name for the number."),
    ],
    number: typing.Annotated[
        str,
        Field(
            min_length=1,
            description="Phone number in E.164 format, such as `+14155551234`.",
        ),
    ],
    provider: typing.Annotated[
        ImportProvider,
        Field(description="Existing provider by id, or a Twilio account lookup."),
    ],
    agent_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Agent that answers inbound calls. Omit for outbound-only."),
    ] = None,
) -> dict[str, typing.Any]:
    return (
        _api_client()
        .agents.phone_numbers.import_(
            label=label, number=number, provider=provider, agent_id=_or_omit(agent_id)
        )
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_destructive_tool("Update phone number"),
    description="""
        Change a phone number's label, the agent answering its inbound calls, or
        its provider. Send only the fields to change.

        Changing the agent reroutes live inbound calls: confirm the number
        (`get_phone_number`) and the new agent with the user first. Set
        `unassign_agent` to stop answering inbound calls. Moving between provider
        types is not supported; delete and re-import instead.
        """,
)
def update_phone_number(
    phone_number_id: typing.Annotated[
        str,
        Field(min_length=1, description="Phone number ID from `list_phone_numbers`."),
    ],
    label: typing.Annotated[
        typing.Optional[str],
        Field(description="New name."),
    ] = None,
    agent_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Agent that answers inbound calls from now on."),
    ] = None,
    unassign_agent: typing.Annotated[
        bool,
        Field(
            description="Stop answering inbound calls. Cannot be combined with `agent_id`."
        ),
    ] = False,
    provider_id: typing.Annotated[
        typing.Optional[str],
        Field(
            description="Move the number to this provider ID from `list_phone_providers`."
        ),
    ] = None,
) -> dict[str, typing.Any]:
    if agent_id is not None and unassign_agent:
        raise ValueError("Pass agent_id or unassign_agent, not both.")
    if (
        label is None
        and agent_id is None
        and not unassign_agent
        and provider_id is None
    ):
        raise ValueError("Provide at least one field to change.")
    return (
        _api_client()
        .agents.phone_numbers.update(
            phone_number_id,
            label=_or_omit(label),
            agent_id=None if unassign_agent else _or_omit(agent_id),
            provider={"id": provider_id} if provider_id else omit,
        )
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_destructive_tool("Delete phone number"),
    description="""
        Permanently remove a phone number from Cartesia. A Cartesia-managed number
        may not be recoverable, and inbound calls to it stop working. Fetch it with
        `get_phone_number` and confirm the exact number with the user first.
        """,
)
def delete_phone_number(
    phone_number_id: typing.Annotated[
        str,
        Field(min_length=1, description="Phone number ID from `list_phone_numbers`."),
    ],
) -> dict[str, typing.Any]:
    _api_client().agents.phone_numbers.delete(phone_number_id)
    return {"success": True}


@mcp.tool(
    annotations=_read_only_tool("List phone providers"),
    description="""
        List telephony providers (Twilio accounts and SIP trunks) linked to your
        account. Secrets are write-only and never returned.
        """,
)
def list_phone_providers(
    type: typing.Annotated[
        typing.Optional[typing.Literal["twilio", "sip_trunk"]],
        Field(description="Only this provider type."),
    ] = None,
    account_sid: typing.Annotated[
        typing.Optional[str],
        Field(description="Only this Twilio account SID."),
    ] = None,
) -> dict[str, typing.Any]:
    providers = _api_client().agents.phone_numbers.providers.list(
        type=_or_omit(type), account_sid=_or_omit(account_sid)
    )
    return {"data": [p.to_dict(mode="json") for p in providers]}


@mcp.tool(
    annotations=_read_only_tool("Get phone provider"),
    description="Get one telephony provider. Secrets are never returned.",
)
def get_phone_provider(
    provider_id: typing.Annotated[
        str,
        Field(min_length=1, description="Provider ID from `list_phone_providers`."),
    ],
) -> dict[str, typing.Any]:
    return (
        _api_client()
        .agents.phone_numbers.providers.retrieve(provider_id)
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_additive_tool("Create Twilio provider"),
    description="""
        Link a Twilio account so its numbers can be imported with
        `import_phone_number`. Cartesia checks the credentials with Twilio first.
        Each account SID and region can be linked once. `api_key_secret` is
        write-only. SIP trunk providers are not supported here yet.
        """,
)
def create_twilio_provider(
    account_sid: typing.Annotated[
        str, Field(min_length=1, description="Twilio account SID.")
    ],
    api_key_sid: typing.Annotated[
        str, Field(min_length=1, description="Twilio API key SID.")
    ],
    api_key_secret: typing.Annotated[
        str,
        Field(min_length=1, description="Twilio API key secret."),
    ],
    region: typing.Annotated[
        typing.Optional[TwilioRegion],
        Field(description="Twilio region: `us1` (default), `ie1`, or `au1`."),
    ] = None,
    label: typing.Annotated[
        typing.Optional[str],
        Field(description="Human-readable name for the provider."),
    ] = None,
) -> dict[str, typing.Any]:
    return (
        _api_client()
        .agents.phone_numbers.providers.create(
            type="twilio",
            account_sid=account_sid,
            api_key_sid=api_key_sid,
            api_key_secret=api_key_secret,
            region=_or_omit(region),
            label=_or_omit(label),
        )
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_destructive_tool("Update phone provider"),
    description="""
        Change a telephony provider. `provider.type` is required: `twilio` takes
        new `api_key_sid` and `api_key_secret`; `sip_trunk` takes optional `label`,
        `inbound`, and `outbound` settings, and omitted fields stay as they are.
        Numbers on the provider use the new settings immediately, so confirm the
        provider with the user first. Call `get_phone_provider` beforehand.
        """,
)
def update_phone_provider(
    provider_id: typing.Annotated[
        str,
        Field(min_length=1, description="Provider ID from `list_phone_providers`."),
    ],
    provider: typing.Annotated[
        ProviderUpdateParams,
        Field(description="Twilio or SIP trunk fields to change."),
    ],
) -> dict[str, typing.Any]:
    if not any(key != "type" for key in provider):
        raise ValueError("Provide at least one field to change besides `type`.")
    # The SDK types this as overloads, which a spread union does not match.
    return (
        _api_client()
        .agents.phone_numbers.providers.update(
            provider_id, **typing.cast(typing.Any, provider)
        )
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_destructive_tool("Delete phone provider"),
    description="""
        Unlink a telephony provider. Numbers that use it stop working. Fetch it
        with `get_phone_provider` and confirm it with the user first.
        """,
)
def delete_phone_provider(
    provider_id: typing.Annotated[
        str,
        Field(min_length=1, description="Provider ID from `list_phone_providers`."),
    ],
) -> dict[str, typing.Any]:
    _api_client().agents.phone_numbers.providers.delete(provider_id)
    return {"success": True}


# ---------------------------------------------------------------------------
# Outbound calls and call batches
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=_real_world_tool("Create outbound agent calls"),
    description="""
        Place real outbound phone calls with an agent. Every destination rings a
        real person and may cost money, and a call cannot be recalled once placed
        (`cancel_agent_call` only stops one that has not connected). Only call
        this after the user has confirmed, in this conversation, the exact
        numbers to dial, the agent, and the number to call from.

        `from_number_id` comes from `list_phone_numbers`. Each entry in
        `outbound_calls` has `to_number` in E.164 format and optional
        `dynamic_variables` for the agent's welcome message. Each result in
        `calls` has an `agent_call_id` for `get_agent_call`, or an `error`. For
        many numbers use `create_call_batch`.
        """,
)
def create_agent_calls(
    agent_id: typing.Annotated[
        str,
        Field(min_length=1, description="Agent that handles the calls."),
    ],
    from_number_id: typing.Annotated[
        str,
        Field(min_length=1, description="Phone number ID to call from."),
    ],
    outbound_calls: typing.Annotated[
        list[OutboundCall],
        Field(min_length=1, description="Destinations and per-call dynamic variables."),
    ],
    max_call_duration_minutes: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, description="Maximum call length in minutes."),
    ] = None,
    ringing_timeout_seconds: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, description="Seconds to wait for an answer (default 60)."),
    ] = None,
) -> dict[str, typing.Any]:
    return (
        _api_client()
        .agents.calls.create(
            agent_id=agent_id,
            from_number_id=from_number_id,
            outbound_calls=outbound_calls,
            max_call_duration_minutes=_or_omit(max_call_duration_minutes),
            ringing_timeout_seconds=_or_omit(ringing_timeout_seconds),
        )
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_destructive_tool("Cancel agent call"),
    description="""
        Cancel an outbound call that has not connected yet. It does not hang up a
        call in progress. Confirm the call with the user first.
        """,
)
def cancel_agent_call(
    call_id: typing.Annotated[
        str,
        Field(
            min_length=1,
            description="Call ID from `create_agent_calls` or `list_agent_calls`.",
        ),
    ],
) -> dict[str, typing.Any]:
    return _api_client().agents.calls.cancel(call_id).to_dict(mode="json")


@mcp.tool(
    annotations=_destructive_tool("Delete agent call"),
    description="""
        Permanently delete a call record with its transcript and recording.
        Confirm the call (`get_agent_call`) with the user first.
        """,
)
def delete_agent_call(
    call_id: typing.Annotated[
        str,
        Field(min_length=1, description="Call ID from `list_agent_calls`."),
    ],
) -> dict[str, typing.Any]:
    _api_client().agents.calls.delete(call_id)
    return {"success": True}


@mcp.tool(
    annotations=_read_only_tool("List call batches"),
    description="""
        List outbound call batches, newest first, without per-recipient detail.
        Call `get_call_batch` for recipients.
        """,
)
def list_call_batches(
    agent_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Only batches for this agent."),
    ] = None,
    limit: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, le=100, description="Batches per page."),
    ] = 10,
    starting_after: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: `next_page` from the previous result."),
    ] = None,
    ending_before: typing.Annotated[
        typing.Optional[str],
        Field(description="Cursor: batch ID to end before (previous page)."),
    ] = None,
) -> dict[str, typing.Any]:
    result = sdk_page_to_result(
        _api_client().agents.calls.batches.list(
            agent_id=_or_omit(agent_id),
            limit=_or_omit(limit),
            starting_after=_or_omit(starting_after),
            ending_before=_or_omit(ending_before),
        )
    )
    for row in result["data"]:
        row.pop("recipients", None)
    return result


@mcp.tool(
    annotations=_read_only_tool("Get call batch"),
    description="""
        Get one call batch: its `status`, progress counters, and each recipient's
        status and `agent_call_id`.
        """,
)
def get_call_batch(
    batch_id: typing.Annotated[
        str,
        Field(min_length=1, description="Batch ID from `list_call_batches`."),
    ],
) -> dict[str, typing.Any]:
    return _api_client().agents.calls.batches.retrieve(batch_id).to_dict(mode="json")


@mcp.tool(
    annotations=_real_world_tool("Create call batch"),
    description="""
        Start an outbound call batch: one agent dials many recipients. Every
        recipient rings a real person and may cost money. Only call this after
        the user has confirmed, in this conversation, the full recipient list (or
        its count and source), the agent, the number to call from, and the start
        time. Use `cancel_call_batch` to stop dialing.

        Dialing starts immediately unless `scheduled_at` is set (RFC 3339 with a
        timezone, in the future, within 30 days). `from_number_id` comes from
        `list_phone_numbers`. `target_concurrency_limit` caps simultaneous calls
        and defaults to half the organization's limit. `region` applies to
        SIP-trunk numbers only.
        """,
)
def create_call_batch(
    agent_id: typing.Annotated[
        str,
        Field(min_length=1, description="Agent that handles the batch's calls."),
    ],
    from_number_id: typing.Annotated[
        str,
        Field(min_length=1, description="Phone number ID to call from."),
    ],
    name: typing.Annotated[
        str, Field(min_length=1, description="Label for the batch.")
    ],
    recipients: typing.Annotated[
        list[OutboundCall],
        Field(min_length=1, description="Destinations and per-call dynamic variables."),
    ],
    scheduled_at: typing.Annotated[
        typing.Optional[str],
        Field(description="Start time as RFC 3339 with timezone. Omit to dial now."),
    ] = None,
    target_concurrency_limit: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, description="Maximum simultaneous calls."),
    ] = None,
    max_call_duration_minutes: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, description="Maximum call length in minutes (default 480)."),
    ] = None,
    ringing_timeout_seconds: typing.Annotated[
        typing.Optional[int],
        Field(ge=1, description="Seconds to wait for an answer (default 60)."),
    ] = None,
    region: typing.Annotated[
        typing.Optional[typing.Literal["US", "EU", "APAC"]],
        Field(description="Dispatch region, for SIP-trunk numbers only."),
    ] = None,
) -> dict[str, typing.Any]:
    return (
        _api_client()
        .agents.calls.batches.create(
            agent_id=agent_id,
            from_number_id=from_number_id,
            name=name,
            recipients=recipients,
            scheduled_at=_or_omit(scheduled_at),
            target_concurrency_limit=_or_omit(target_concurrency_limit),
            max_call_duration_minutes=_or_omit(max_call_duration_minutes),
            ringing_timeout_seconds=_or_omit(ringing_timeout_seconds),
            region=_or_omit(region),
        )
        .to_dict(mode="json")
    )


@mcp.tool(
    annotations=_destructive_tool("Cancel call batch"),
    description="""
        Stop dialing a call batch. Calls already connected continue. Confirm the
        batch (`get_call_batch`) with the user first.
        """,
)
def cancel_call_batch(
    batch_id: typing.Annotated[
        str,
        Field(min_length=1, description="Batch ID from `list_call_batches`."),
    ],
) -> dict[str, typing.Any]:
    return _api_client().agents.calls.batches.cancel(batch_id).to_dict(mode="json")


@mcp.tool(
    annotations=_real_world_tool("Retry call batch"),
    description="""
        Dial a finished batch's failed recipients again. Those recipients ring
        real people and may cost money, so only call this after the user has
        confirmed which batch to retry. Check `get_call_batch` first.
        """,
)
def retry_call_batch(
    batch_id: typing.Annotated[
        str,
        Field(min_length=1, description="Batch ID from `list_call_batches`."),
    ],
) -> dict[str, typing.Any]:
    return _api_client().agents.calls.batches.retry(batch_id).to_dict(mode="json")


# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------


@mcp.tool(
    annotations=_read_only_tool("Get agent usage"),
    description="""
        Returns Managed Agents usage over time (`GET /usage/agents`): spend,
        minutes, and calls per bucket.

        Requires **CARTESIA_ADMIN_API_KEY** (admin API keys cannot be used as CARTESIA_API_KEY).
        Optional `start_ts` and `end_ts` are RFC 3339 datetimes, at most 366 days
        apart; `interval` buckets results by `day`, `week`, or `month`. Without
        `interval` the result is one total for the window.
        """,
)
def get_agent_usage(
    start_ts: typing.Annotated[
        typing.Optional[str],
        Field(description="Start of the usage window (ISO 8601 timestamp)."),
    ] = None,
    end_ts: typing.Annotated[
        typing.Optional[str],
        Field(description="End of the usage window (ISO 8601 timestamp)."),
    ] = None,
    interval: typing.Annotated[
        typing.Optional[UsageInterval],
        Field(description="Bucket size for the returned usage time series."),
    ] = None,
) -> dict[str, typing.Any]:
    return (
        _require_admin_client()
        .usage.agents.retrieve(
            start_ts=_or_omit(start_ts),
            end_ts=_or_omit(end_ts),
            interval=_or_omit(interval),
        )
        .to_dict(mode="json")
    )


@mcp.prompt(
    title="Create a voice agent",
    description="Build a Managed Agent from a plain-language description and share a link to try it.",
)
def create_voice_agent(description: str) -> str:
    return (
        f"Build a Cartesia Managed Agent for: {description!r}.\n"
        "1. Ask at most two questions if a key detail is missing, such as the business "
        "name, the facts the agent must know, or when it should transfer or hang up.\n"
        "2. Call `list_agent_models` and pick a model id. Call `list_voices` with a query "
        "that matches the persona and language, and pick a voice.\n"
        "3. Write `config.instructions` for the role, goal, steps, what to collect, and "
        "when to end or transfer. Set `config.initial_message` to what the agent says "
        "first, or leave it unset to wait.\n"
        "4. Use `{{variable}}` placeholders for anything that changes per caller and set "
        "test values in `config.dynamic_variable_placeholders`.\n"
        "5. Call `create_agent`, then give the user the `playground_url`. A config "
        "change is live immediately. Try it there before assigning a phone number.\n"
        "6. If the agent must look something up or take an action, call "
        "`create_agent_tool`, then `attach_agent_tool`. Ending, transferring, "
        "DTMF, and voicemail detection are `config.system_tools`.\n"
        "If it must answer from the user's documents, call `create_knowledge_folder` "
        "and `create_knowledge_documents`, then `attach_knowledge_folder` or "
        "`attach_knowledge_document`.\n"
        "7. After a test call, use `list_agent_calls`, `get_agent_call_logs`, and "
        "`get_agent_call` to review it. Change instructions with `update_agent`. "
        "Add or remove one tool or document with the attach and detach tools.\n"
    )


@mcp.prompt(
    title="Debug a voice agent call",
    description="Find why a Managed Agent call went wrong and propose a config fix.",
)
def debug_agent_call(agent_id: str = "", call_id: str = "") -> str:
    if call_id and agent_id:
        find_step = f"The call ID is {call_id!r} on agent {agent_id!r}."
    elif call_id:
        find_step = f"The call ID is {call_id!r}."
    elif agent_id:
        find_step = (
            f"Call `list_agent_calls` with agent_id={agent_id!r} and pick the call the "
            "user means (or the latest failed one)."
        )
    else:
        find_step = (
            "Call `list_agents` and pick the agent the user means. Then call "
            "`list_agent_calls` for it and pick the call they mean (or the latest failed one)."
        )
    return (
        f"{find_step}\n"
        "Call `get_agent_call_logs` for that call first: the runtime logs show errors "
        "and failed tool calls the transcript may not.\n"
        "Then call `get_agent_call` and check `status`, `end_reason`, and "
        "`error_message`, and read the turns for misunderstandings, interruptions, "
        "failed tool calls, and slow `latency_ms`.\n"
        "Call `get_agent_version` with the call's `agent_id` and "
        "`agent_version_id` to read the config that ran.\n"
        "Explain the cause, then propose the smallest config change. Apply it with "
        "`update_agent` only after the user agrees."
    )


