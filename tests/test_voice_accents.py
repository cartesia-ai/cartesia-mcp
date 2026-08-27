from unittest.mock import MagicMock, patch

import cartesia_mcp.server as server


@patch("cartesia_mcp.server.client")
def test_add_voice_accents_calls_sdk(mock_client: MagicMock) -> None:
    mock_client.voices.add_accents.return_value = MagicMock()

    server.add_voice_accents(voice_id="voice-id", accents=["british", "parisian"])

    mock_client.voices.add_accents.assert_called_once()
    kwargs = mock_client.voices.add_accents.call_args.kwargs
    assert kwargs["id"] == "voice-id"
    assert kwargs["accents"] == ["british", "parisian"]


@patch("cartesia_mcp.server.client")
def test_delete_voice_accent_calls_sdk(mock_client: MagicMock) -> None:
    mock_client.voices.delete_accent.return_value = MagicMock()

    server.delete_voice_accent(voice_id="voice-id", accent="british")

    mock_client.voices.delete_accent.assert_called_once()
    args, kwargs = mock_client.voices.delete_accent.call_args
    assert args == ("british",)
    assert kwargs["id"] == "voice-id"
