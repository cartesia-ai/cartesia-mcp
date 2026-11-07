from unittest.mock import MagicMock, patch

import cartesia_mcp.extra_api as extra_api
import cartesia_mcp.server as server


def test_extra_api_list_agent_models_single_page() -> None:
    client = MagicMock()
    client.get.return_value = {
        "data": [
            {"id": "gpt-5.5", "display_name": "GPT-5.5", "provider": "OpenAI"},
            {"id": "claude-haiku-4.5", "display_name": "Claude Haiku 4.5", "provider": "Anthropic"},
        ],
        "has_more": False,
        "next_page": None,
    }

    result = extra_api.list_agent_models(client)

    assert client.get.call_args.args[0] == "/v1/agents/models"
    assert client.get.call_args.kwargs["options"] == {"params": {"limit": "100"}}
    assert [row["id"] for row in result["data"]] == ["gpt-5.5", "claude-haiku-4.5"]


def test_extra_api_list_agent_models_follows_next_page() -> None:
    client = MagicMock()
    client.get.side_effect = [
        {
            "data": [{"id": "model-a"}],
            "has_more": True,
            "next_page": "model-a",
        },
        {
            "data": [{"id": "model-b"}],
            "has_more": False,
            "next_page": None,
        },
    ]

    result = extra_api.list_agent_models(client)

    assert client.get.call_count == 2
    assert client.get.call_args_list[0].kwargs["options"] == {
        "params": {"limit": "100"}
    }
    assert client.get.call_args_list[1].kwargs["options"] == {
        "params": {"limit": "100", "starting_after": "model-a"}
    }
    assert [row["id"] for row in result["data"]] == ["model-a", "model-b"]


@patch("cartesia_mcp.server.extra_api.list_agent_models")
@patch("cartesia_mcp.server.client")
def test_list_agent_models_tool(
    mock_client: MagicMock, mock_list_agent_models: MagicMock
) -> None:
    mock_list_agent_models.return_value = {
        "data": [{"id": "claude-sonnet-5", "provider": "Anthropic"}]
    }

    result = server.list_agent_models()

    mock_list_agent_models.assert_called_once()
    assert mock_list_agent_models.call_args.args[0] is mock_client
    assert result["data"][0]["id"] == "claude-sonnet-5"
