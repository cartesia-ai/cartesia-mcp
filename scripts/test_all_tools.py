#!/usr/bin/env python3
"""Smoke-test all cartesia-mcp tool handlers (direct function calls)."""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from typing import Any

# Run from repo root: uv run python scripts/test_all_tools.py

OUTPUT_DIR = os.environ.get(
    "OUTPUT_DIRECTORY", os.path.join(os.path.dirname(__file__), "..", "test-output")
)
SAMPLE_VOICE_ID = "ef191366-f52f-447a-a398-ed8c0f2943a1"  # Archie
ALT_VOICE_ID = "47c38ca4-5f35-497b-b1a3-415245fb35e1"  # Daniel
WAV_FORMAT = {
    "container": "wav",
    "encoding": "pcm_s16le",
    "sample_rate": 44100,
}


def ok(name: str, detail: str = "") -> None:
    print(f"  OK  {name}" + (f" — {detail}" if detail else ""))


def fail(name: str, err: BaseException) -> None:
    print(f"  FAIL {name}: {err}")
    traceback.print_exc()


def assert_str_path(result: dict[str, Any], tool: str) -> str:
    path = result["file_path"]
    if not isinstance(path, str):
        raise TypeError(f"{tool}: file_path must be str, got {type(path)}")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"{tool}: missing output file {path}")
    return path


def main() -> int:
    if not os.environ.get("CARTESIA_API_KEY"):
        print("CARTESIA_API_KEY is required", file=sys.stderr)
        return 1

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.environ["OUTPUT_DIRECTORY"] = os.path.abspath(OUTPUT_DIR)

    # Import after OUTPUT_DIRECTORY is set (server reads env at import).
    import cartesia_mcp.server as s  # noqa: WPS433

    failures: list[str] = []
    cloned_voice_id: str | None = None
    localized_voice_id: str | None = None
    tts_path: str | None = None
    run_id = str(int(time.time()))

    def run(name: str, fn) -> Any:
        try:
            result = fn()
            ok(name)
            return result
        except Exception as e:  # noqa: BLE001
            fail(name, e)
            failures.append(name)
            return None

    print(f"Output directory: {os.environ['OUTPUT_DIRECTORY']}\n")

    pager = run("list_voices", lambda: s.list_voices(limit=3))
    if pager is not None:
        items = list(pager.items) if hasattr(pager, "items") else list(pager)
        if not items:
            failures.append("list_voices(empty)")
            print("  FAIL list_voices: no items")
        else:
            ok("list_voices", f"{len(items)} voices")

    run(
        "get_voice",
        lambda: s.get_voice(voice_id=SAMPLE_VOICE_ID),
    )

    tts_result = run(
        "text_to_speech",
        lambda: s.text_to_speech(
            transcript=(
                "This is a longer Cartesia MCP smoke test clip. "
                "We need several seconds of speech for voice cloning to succeed."
            ),
            voice={"mode": "id", "id": SAMPLE_VOICE_ID},
            output_format=WAV_FORMAT,
            language="en",
        ),
    )
    if tts_result:
        try:
            tts_path = assert_str_path(tts_result, "text_to_speech")
            ok("text_to_speech output", tts_path)
        except Exception as e:  # noqa: BLE001
            fail("text_to_speech validation", e)
            failures.append("text_to_speech(validation)")

    # clone_voice needs ~5s+ audio; use TTS output when available.
    sample_wav = tts_path or os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "hi-grant-archie.wav")
    )

    if tts_path and os.path.isfile(tts_path):
        clone_name = f"MCP Test Clone {run_id}"
        clone_result = run(
            "clone_voice",
            lambda: s.clone_voice(
                file_path=sample_wav,
                name=clone_name,
                language="en",
                mode="similarity",
                description="Temporary MCP integration test voice",
            ),
        )
        if clone_result:
            cloned_voice_id = getattr(clone_result, "id", None)
            ok("clone_voice", f"id={cloned_voice_id}")

            if cloned_voice_id:
                run(
                    "update_voice",
                    lambda: s.update_voice(
                        voice_id=cloned_voice_id,
                        name=f"{clone_name} (updated)",
                        description="Updated by MCP smoke test",
                    ),
                )
    else:
        print(f"  SKIP clone_voice / update_voice — no sample wav at {sample_wav}")
        failures.append("clone_voice(skipped)")

    if tts_path and os.path.isfile(tts_path):
        run(
            "voice_change",
            lambda: s.voice_change(
                file_path=tts_path,
                voice_id=ALT_VOICE_ID,
                output_format_container="wav",
                output_format_sample_rate=44100,
                output_format_encoding="pcm_s16le",
            ),
        )
        infill_result = run(
            "infill",
            lambda: s.infill(
                language="en",
                transcript=" and ",
                voice_id=SAMPLE_VOICE_ID,
                output_format_container="wav",
                output_format_sample_rate=44100,
                output_format_encoding="pcm_s16le",
                left_audio_file_path=tts_path,
                right_audio_file_path=tts_path,
            ),
        )
        if infill_result:
            try:
                assert_str_path(infill_result, "infill")
            except Exception as e:  # noqa: BLE001
                fail("infill validation", e)
                failures.append("infill(validation)")

    loc_result = run(
        "localize_voice",
        lambda: s.localize_voice(
            voice_id=SAMPLE_VOICE_ID,
            name=f"MCP Localized {run_id}",
            description="Temporary localized voice from MCP test",
            language="es",
            original_speaker_gender="male",
        ),
    )
    if loc_result:
        localized_voice_id = getattr(loc_result, "id", None)
        ok("localize_voice", f"id={localized_voice_id}")

    for vid, label in [
        (localized_voice_id, "localized"),
        (cloned_voice_id, "cloned"),
    ]:
        if vid:
            run(
                f"delete_voice({label})",
                lambda voice_id=vid: s.delete_voice(voice_id=voice_id),
            )

    print()
    if failures:
        print(f"Failed: {', '.join(failures)}")
        return 1
    print("All tools passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
