"""text_to_speech passes on a message from Cartesia about the account (GET /notices)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import cartesia_mcp.extra_api as extra_api
import cartesia_mcp.server as server

NOTICE = (
    "Cartesia's product team would love to hear what you're building. Tell us on a "
    "30-minute call and get $100 in free credits: https://play.cartesia.ai/dashboard?research_invite=open"
)


def _wav_format() -> dict[str, object]:
    return {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 44100}


@pytest.fixture(autouse=True)
def _fresh_notice_checks() -> None:
    server._notice_checked_at.clear()


def _client_answering(body: object) -> MagicMock:
    sdk = MagicMock()
    sdk.with_options.return_value.get.return_value = body
    return sdk


def test_get_account_notice_asks_the_backend_and_trims() -> None:
    sdk = _client_answering({"notice": f"  {NOTICE} "})
    assert extra_api.get_account_notice(sdk) == NOTICE
    url = sdk.with_options.return_value.get.call_args.args[0]
    assert url == "https://backend.cartesia.ai/notices"
    assert sdk.with_options.call_args.kwargs == {"timeout": 3.0, "max_retries": 0}


@pytest.mark.parametrize("body", [{"notice": None}, {"notice": "   "}, {}, "not json"])
def test_get_account_notice_is_none_when_theres_nothing(body: object) -> None:
    assert extra_api.get_account_notice(_client_answering(body)) is None


def test_backend_url_can_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARTESIA_BACKEND_BASE_URL", "http://localhost:10000/")
    sdk = _client_answering({"notice": None})
    extra_api.get_account_notice(sdk)
    assert sdk.with_options.return_value.get.call_args.args[0] == "http://localhost:10000/notices"


@patch("cartesia_mcp.server.resolve_api_credential", return_value="sk_car_a")
@patch("cartesia_mcp.server.extra_api.get_account_notice", return_value=NOTICE)
def test_asks_once_per_key_until_the_wait_is_over(get_notice: MagicMock, _cred: MagicMock) -> None:
    with patch("cartesia_mcp.server.time.monotonic", return_value=1000.0):
        assert server._account_notice() == NOTICE
        assert server._account_notice() is None
    with patch(
        "cartesia_mcp.server.time.monotonic",
        return_value=1000.0 + server.NOTICE_CHECK_SECONDS,
    ):
        assert server._account_notice() == NOTICE
    assert get_notice.call_count == 2


@patch("cartesia_mcp.server.extra_api.get_account_notice", return_value=NOTICE)
def test_each_key_is_asked_on_its_own(get_notice: MagicMock) -> None:
    with patch("cartesia_mcp.server.time.monotonic", return_value=1000.0):
        with patch("cartesia_mcp.server.resolve_api_credential", return_value="sk_car_a"):
            server._account_notice()
        with patch("cartesia_mcp.server.resolve_api_credential", return_value="sk_car_b"):
            server._account_notice()
    assert get_notice.call_count == 2


@patch("cartesia_mcp.server.resolve_api_credential", return_value="sk_car_a")
@patch("cartesia_mcp.server.extra_api.get_account_notice", side_effect=RuntimeError("backend down"))
def test_a_failed_check_never_breaks_the_tool(_get: MagicMock, _cred: MagicMock) -> None:
    assert server._account_notice() is None


@patch("cartesia_mcp.server._account_notice", return_value=NOTICE)
@patch("cartesia_mcp.server._try_create_download_link", return_value="https://files.cartesia.ai/link/l1")
@patch("cartesia_mcp.server.client")
def test_saved_generation_carries_the_notice(
    mock_client: MagicMock, _link: MagicMock, _notice: MagicMock
) -> None:
    response = MagicMock(read=lambda: b"audio-bytes")
    response.headers = {"Cartesia-File-ID": "file_new"}
    mock_client.tts.generate.return_value = response

    with patch("cartesia_mcp.server._write_audio_output", return_value="/tmp/out.wav"):
        result = server.text_to_speech(
            transcript="Hello",
            voice_id="voice_abc",
            output_format=_wav_format(),
            save=True,
        )

    assert result["notice"] == NOTICE
    assert result["file_id"] == "file_new"


@patch("cartesia_mcp.server._account_notice", return_value=NOTICE)
@patch("cartesia_mcp.server.client")
def test_unsaved_generation_carries_the_notice(mock_client: MagicMock, _notice: MagicMock) -> None:
    response = MagicMock(read=lambda: b"audio-bytes")
    response.headers = {}
    mock_client.tts.generate.return_value = response

    with patch("cartesia_mcp.server._write_audio_output", return_value="/tmp/out.wav"):
        result = server.text_to_speech(
            transcript="Hello",
            voice_id="voice_abc",
            output_format=_wav_format(),
            save=False,
        )

    assert result == {"file_path": "/tmp/out.wav", "notice": NOTICE}


@patch("cartesia_mcp.server._account_notice", return_value=None)
@patch("cartesia_mcp.server.client")
def test_no_notice_leaves_the_result_unchanged(mock_client: MagicMock, _notice: MagicMock) -> None:
    response = MagicMock(read=lambda: b"audio-bytes")
    response.headers = {}
    mock_client.tts.generate.return_value = response

    with patch("cartesia_mcp.server._write_audio_output", return_value="/tmp/out.wav"):
        result = server.text_to_speech(
            transcript="Hello",
            voice_id="voice_abc",
            output_format=_wav_format(),
            save=False,
        )

    assert result == {"file_path": "/tmp/out.wav"}
