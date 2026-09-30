from unittest.mock import MagicMock, patch

from cartesia.types import ListAccentsResponse

import cartesia_mcp.server as server


@patch("cartesia_mcp.server.client")
def test_list_accents_returns_catalog_ids(mock_client: MagicMock) -> None:
    mock_client.voices.list_accents.return_value = ListAccentsResponse(
        accents=[
            {
                "id": "british",
                "name": "British English",
                "language": "en",
                "locale": "en-GB",
                "is_locale_default": False,
                "is_localizable": True,
            },
            {
                "id": "standard-japanese",
                "name": "Standard Japanese",
                "language": "ja",
                "locale": "ja-JP",
                "is_locale_default": True,
                "is_localizable": True,
            },
        ]
    )

    result = server.list_accents()

    mock_client.voices.list_accents.assert_called_once_with()
    assert [accent.id for accent in result.accents] == ["british", "standard-japanese"]


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
