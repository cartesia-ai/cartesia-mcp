from unittest.mock import MagicMock, patch

import cartesia_mcp.extra_api as extra_api
import cartesia_mcp.server as server


def test_extra_api_list_models_passes_capability() -> None:
    client = MagicMock()
    client.get.return_value = {"data": []}
    extra_api.list_models(client, capability="stt")
    assert client.get.call_args.args[0] == "/models"
    assert client.get.call_args.kwargs["options"] == {"params": {"capability": "stt"}}


def test_extra_api_list_models_omits_capability_param() -> None:
    client = MagicMock()
    client.get.return_value = {"data": []}
    extra_api.list_models(client)
    assert client.get.call_args.kwargs["options"] == {"params": {}}


@patch("cartesia_mcp.server.extra_api.list_models")
@patch("cartesia_mcp.server.client")
def test_list_models_tool(mock_client: MagicMock, mock_list_models: MagicMock) -> None:
    mock_list_models.return_value = {
        "data": [
            {"id": "sonic-3.6", "capability": "tts"},
            {"id": "ink-2", "capability": "stt", "modes": ["stream"]},
        ]
    }

    result = server.list_models(capability="tts")

    mock_list_models.assert_called_once()
    assert mock_list_models.call_args.args[0] is mock_client
    assert mock_list_models.call_args.kwargs["capability"] == "tts"
    assert result["data"][0]["id"] == "sonic-3.6"
