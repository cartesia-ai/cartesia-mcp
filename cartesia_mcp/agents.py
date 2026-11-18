"""Managed Agents tools and prompts: agents, calls, versions, knowledge base, webhooks, metrics, phone numbers, and batches."""

import typing

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
        `list_models` (`sonic-*`, `ink-*`). Those are speech models. Each row
        includes provider, display name, latency, and token pricing. Returns
        the full catalog (pagination is followed server-side).
        """)
def list_agent_models() -> dict[str, typing.Any]:
    return extra_api.list_agent_models(
        _api_client(),
    )


AgentCallDetail = typing.Literal["condensed", "full"]
PhoneNumberProviderType = typing.Literal["twilio", "cartesia", "sip_trunk"]


def _or_omit(value: typing.Any) -> typing.Any:
    return omit if value is None else value


def _agent_with_playground_url(agent: typing.Any) -> dict[str, typing.Any]:
    result = agent.to_dict(mode="json")
    result["playground_url"] = playground_agent_url(result["id"])
    return result


@mcp.tool(
    annotations=_read_only_tool("List agents"),
    description="""
        List the account's Managed Agents, newest first.

        Rows have `id`, `name`, `description`, `version_id` (the current
        config version), and timestamps. Call `get_agent` for the config.
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
        Get a Managed Agent: name, description, the current `config`
        (instructions, initial message, model, voice, tools, system tools,
        turn-taking, variables), the current `version`, and `playground_url`
        for trying the agent in the browser.
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
          enable them under `config.system_tools`. There are no separate
          transfer or end-call endpoints.
        - `config.tools` takes ids from `create_agent_tool` or `list_agent_tools`.
        - `config.knowledge_base_folders` and `config.knowledge_base_documents`
          take ids from `list_knowledge_folders` and `list_knowledge_documents`.
        - `config.event_webhook_id` takes an id from `list_event_webhooks`.

        There is no API to simulate a call. Open the returned `playground_url`
        to talk to the agent.
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
    annotations=_destructive_tool("Update agent"),
    description="""
        Update a Managed Agent. Send only the fields to change.

        Inside `config`, list and map fields (`tools`, `keyterms`,
        `knowledge_base_documents`, `dynamic_variable_placeholders`, ...)
        replace the existing value, so send the full list. Call `get_agent`
        first when editing one.

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
        List a Managed Agent's calls, newest first, to debug them.

        Each row has the call `id`, `status`, `end_reason`, `error_message`,
        start and end times, `summary`, and `agent_version_id` (the config that
        ran). Pass a call `id` to `get_agent_call` for the transcript.

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
) -> dict[str, typing.Any]:
    return agent_call_list_to_result(
        sdk_page_to_result(
            _api_client().agents.calls.list(
                agent_id=agent_id,
                limit=_or_omit(limit),
                starting_after=_or_omit(starting_after),
                ending_before=_or_omit(ending_before),
            )
        )
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
        truncated; `result_chars` is the full length). Pass `detail="full"` for the raw API payload.

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

        Filter by `agent_id` to check whether an agent answers any number. Read
        only: this server does not provision, import, or reassign numbers, and
        does not place outbound calls.
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
    annotations=_additive_tool("Create agent tool"),
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
    annotations=_destructive_tool("Update agent tool"),
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


@mcp.tool(
    annotations=_additive_tool("Create knowledge documents"),
    description="""
        Upload 1 to 100 text documents agents can search during calls. Each needs
        `content` (up to 1 MB) and may set `name`, `folder_id`, and `metadata`
        (string values, used to filter retrieval). Use `file_id` instead of
        `content` only for a file already uploaded with purpose
        `knowledge_base_document`.

        Documents start as `processing`. Check `status` with
        `get_knowledge_document`, and use `retry_knowledge_document` on a
        `failed` one. Returns each document without its text.
        """,
)
def create_knowledge_documents(
    documents: typing.Annotated[
        list[KnowledgeDocumentInput],
        Field(min_length=1, max_length=100, description="Documents to upload."),
    ],
) -> dict[str, typing.Any]:
    created = _api_client().agents.knowledge_base.documents.create_bulk(
        documents=documents
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
    annotations=_additive_tool("Create event webhook"),
    description="""
        Create an event webhook. Cartesia POSTs call events to `url` and sends
        `secret` back in the `X-Webhook-Secret` header so your endpoint can verify
        the request. The secret is write-only and is not echoed in the result.
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
    annotations=_destructive_tool("Update event webhook"),
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
        List evaluation scores for finished calls, newest first. Each result has
        `metricName`, `status`, `result`, `summary`, and `value`. Filter by agent,
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
    annotations=_real_world_tool("Provision phone number"),
    description="""
        Buy a new Cartesia-managed phone number. This can incur charges and cannot
        be undone from here. Only call it after the user has confirmed, in this
        conversation, that they want a new number, plus its label and the agent
        that should answer it.

        Cartesia numbers take inbound calls and outbound calls to US numbers. Pass
        `agent_id` to answer inbound calls with that agent; omit it to keep the
        number outbound-only.
        """,
)
def provision_phone_number(
    label: typing.Annotated[
        str,
        Field(min_length=1, description="Human-readable name for the number."),
    ],
    agent_id: typing.Annotated[
        typing.Optional[str],
        Field(description="Agent that answers inbound calls. Omit for outbound-only."),
    ] = None,
) -> dict[str, typing.Any]:
    return (
        _api_client()
        .agents.phone_numbers.provision(label=label, agent_id=_or_omit(agent_id))
        .to_dict(mode="json")
    )


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
        Returns Managed Agents usage over time (`GET /usage/agents`): `cents`
        spent, `minutes` of calls, and number of `calls` per bucket.

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
    return extra_api.get_usage_agents(
        _require_admin_client(), start_ts=start_ts, end_ts=end_ts, interval=interval
    )


_AGENT_USE_CASE_NOTES = """\
Notes for common agents:
- Inbound support or receptionist: greet with the business name, answer from the facts \
given, collect name and callback number, and enable `system_tools.transfer_to_number` \
for a human handoff.
- Restaurant or order taking: confirm each item, size, and quantity, read the full order \
back, and give a pickup time.
- Outbound sales or SDR: open with who is calling and why in one sentence, qualify with a \
few questions, and handle "not interested" politely. Put the lead's details in \
`{{variables}}`.
- Calling a business on the user's behalf: state the goal, enable \
`system_tools.send_dtmf` to navigate phone menus, and \
`system_tools.voicemail_detection` to hang up on voicemail.
- Interview, sales, or language practice: stay in character as the counterpart, keep \
turns short, and give feedback only when the user asks or the session ends.
- Companion or tutor: be warm, remember what the caller said earlier in the call, and \
ask one question at a time.
"""


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
        "3. Write `config.instructions` as a spoken-word system prompt: role, goal, tone, "
        "the steps of the conversation, what to collect, and when to end the call. Keep "
        "replies short and avoid formatting the caller cannot hear. Write a one-sentence "
        "`config.initial_message`.\n"
        "4. Use `{{variable}}` placeholders for anything that changes per caller and set "
        "test values in `config.dynamic_variable_placeholders`.\n"
        "5. If the agent must look something up or take an action, call "
        "`create_agent_tool` and put the returned id in `config.tools`. Ending, "
        "transferring, DTMF, and voicemail detection are `config.system_tools`.\n"
        "If it must answer from the user's documents, call `create_knowledge_folder` and "
        "`create_knowledge_documents`, then set `config.knowledge_base_folders`.\n"
        "6. Call `create_agent`, then give the user the `playground_url` to talk to it.\n"
        "7. After a test call, use `list_agent_calls` and `get_agent_call` to review the "
        "transcript, and refine the agent with `update_agent`.\n\n" + _AGENT_USE_CASE_NOTES
    )


@mcp.prompt(
    title="Debug a voice agent call",
    description="Find why a Managed Agent call went wrong and propose a config fix.",
)
def debug_agent_call(agent_id: str, call_id: str = "") -> str:
    call_step = (
        f"Call `get_agent_call` with call_id={call_id!r}."
        if call_id
        else f"Call `list_agent_calls` with agent_id={agent_id!r}, pick the call the user "
        "means (or the latest failed one), and call `get_agent_call` on it."
    )
    return (
        f"{call_step}\n"
        "Check `status`, `end_reason`, and `error_message`, then read the turns for "
        "misunderstandings, interruptions, failed tool calls, and slow `latency_ms`.\n"
        f"Call `get_agent_version` with agent_id={agent_id!r} and the call's "
        "`agent_version_id` to read the config that ran.\n"
        "Explain the cause, then propose the smallest config change. Apply it with "
        "`update_agent` only after the user agrees."
    )


