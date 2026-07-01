"""Assert cartesia-mcp identifies itself on REST and STT WebSocket paths."""

from __future__ import annotations

import pytest

from cartesia_mcp.client_headers import client_header
from cartesia_mcp.sdk_setup import create_cartesia_client


def test_create_cartesia_client_default_headers_match_attribution() -> None:
    client = create_cartesia_client("sk_car_test_key")
    header = client_header()

    assert client.default_headers["User-Agent"] == header
    assert client.default_headers["X-Cartesia-Client"] == header


def test_rest_httpx_identifies_as_cartesia_mcp() -> None:
    from cartesia._models import FinalRequestOptions

    client = create_cartesia_client("sk_car_test_key")
    request = client._build_request(FinalRequestOptions(method="get", url="/voices"))

    header = client_header()
    assert request.headers["User-Agent"] == header
    assert request.headers["X-Cartesia-Client"] == header


def test_stt_auto_finalize_connect_merges_default_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    client = create_cartesia_client("sk_car_test_key")
    captured: dict[str, object] = {}

    class FakeConnection:
        def recv(self, decode=False):  # noqa: ARG002
            raise StopIteration

        def send(self, _data):  # noqa: ANN001
            return None

        def close(self, *, code=1000, reason=""):  # noqa: ARG002
            return None

    def fake_connect(*_args, **kwargs):
        captured.update(kwargs)
        return FakeConnection()

    monkeypatch.setattr("websockets.sync.client.connect", fake_connect)

    with pytest.raises(StopIteration):
        with client.stt.auto_finalize.websocket(
            encoding="pcm_s16le",
            model="ink-2",
            sample_rate=16000,
        ) as connection:
            connection.recv()

    header = client_header()
    assert captured["user_agent_header"] == client.user_agent
    assert captured["additional_headers"]["User-Agent"] == header
    assert captured["additional_headers"]["X-Cartesia-Client"] == header
