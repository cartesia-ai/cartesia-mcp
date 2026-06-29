from unittest.mock import MagicMock, patch

import cartesia_mcp.server as server


@patch("cartesia_mcp.server.client")
def test_list_voices_passes_is_starred_via_extra_query(mock_client: MagicMock) -> None:
    mock_client.voices.list.return_value = MagicMock(data=[])

    server.list_voices(is_starred=True, language="it")

    kwargs = mock_client.voices.list.call_args.kwargs
    assert "is_starred" not in kwargs
    assert kwargs["extra_query"] == {"language": "it", "is_starred": True}
