from unittest.mock import MagicMock

import cartesia_mcp.extra_api as extra_api


def test_get_usage_credits_forwards_group_by() -> None:
    client = MagicMock()
    client.get.return_value = {"data": []}

    extra_api.get_usage_credits(
        client,
        start_ts="2026-01-01T00:00:00Z",
        end_ts="2026-01-08T00:00:00Z",
        interval="day",
        group_by="model",
    )

    client.get.assert_called_once()
    assert client.get.call_args.kwargs["options"]["params"]["group_by"] == "model"
