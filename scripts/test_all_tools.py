#!/usr/bin/env python3
"""Smoke-test all cartesia-mcp tool handlers (direct function calls).

Safety: only delete voices and pronunciation dicts created in this run (clone/localize/create).
Never delete catalog or pre-existing user resources — use public voice IDs for read/generation
only, then create ephemeral test resources and delete those by ID.
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from typing import Any

# Run from repo root: uv run python scripts/test_all_tools.py

OUTPUT_DIR = os.environ.get(
    "OUTPUT_DIRECTORY", os.path.join(os.path.dirname(__file__), "..", "test-output")
)
# Public catalog voices — read / TTS / voice_change only; never delete.
SAMPLE_VOICE_ID = "ef191366-f52f-447a-a398-ed8c0f2943a1"  # Archie
ALT_VOICE_ID = "47c38ca4-5f35-497b-b1a3-415245fb35e1"  # Daniel
PROTECTED_VOICE_IDS = frozenset({SAMPLE_VOICE_ID, ALT_VOICE_ID})
TEST_VOICE_NAME_PREFIX = "MCP Test"
TEST_LOCALIZED_NAME_PREFIX = "MCP Localized"
TEST_DICT_NAME_PREFIX = "MCP Test Dict"
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


def assert_safe_to_delete(voice_id: str, name: str, *, created_this_run: bool) -> None:
    if voice_id in PROTECTED_VOICE_IDS:
        raise RuntimeError(f"refusing to delete protected catalog voice {voice_id}")
    if not created_this_run:
        raise RuntimeError(f"refusing to delete voice not created in this run: {voice_id}")
    if not (name.startswith(TEST_VOICE_NAME_PREFIX) or name.startswith(TEST_LOCALIZED_NAME_PREFIX)):
        raise RuntimeError(f"refusing to delete voice with unexpected name {name!r}")


def assert_safe_to_delete_dict(dict_id: str, *, created_this_run: bool) -> None:
    if not created_this_run:
        raise RuntimeError(f"refusing to delete dict not created in this run: {dict_id}")


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
    cloned_voice_name: str | None = None
    localized_voice_id: str | None = None
    localized_voice_name: str | None = None
    dict_id: str | None = None
    dict_name: str | None = None
    tts_path: str | None = None
    run_id = str(int(time.time()))

    def run(name: str, fn, *, optional: bool = False) -> Any:
        try:
            result = fn()
            ok(name)
            return result
        except Exception as e:  # noqa: BLE001
            if optional:
                print(f"  SKIP {name} — {e}")
                return None
            fail(name, e)
            failures.append(name)
            return None

    print(f"Output directory: {os.environ['OUTPUT_DIRECTORY']}\n")

    result = run("list_voices", lambda: s.list_voices(limit=3))
    if result is not None:
        items = result.get("data", []) if isinstance(result, dict) else []
        if not items:
            failures.append("list_voices(empty)")
            print("  FAIL list_voices: no items")
        else:
            ok("list_voices", f"{len(items)} voices")

    it_result = run(
        "list_voices(language=it)",
        lambda: s.list_voices(language="it", is_owner=False, limit=20),
    )
    if it_result is not None:
        items = it_result.get("data", [])
        if not items or any(v.get("language") != "it" for v in items):
            failures.append("list_voices(language=it)")
            print("  FAIL list_voices(language=it): missing or non-Italian voices")
        else:
            ok("list_voices(language=it)", f"{len(items)} Italian catalog voices")

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
            speed=1.0,
            emotion="neutral",
        ),
    )
    if tts_result:
        try:
            tts_path = assert_str_path(tts_result, "text_to_speech")
            ok("text_to_speech output", tts_path)
        except Exception as e:  # noqa: BLE001
            fail("text_to_speech validation", e)
            failures.append("text_to_speech(validation)")

    if tts_path and os.path.isfile(tts_path):
        stt_result = run(
            "speech_to_text",
            lambda: s.speech_to_text(file_path=tts_path, language="en"),
        )
        if stt_result is not None:
            text = getattr(stt_result, "text", None) or (
                stt_result.get("text") if isinstance(stt_result, dict) else None
            )
            if not text:
                failures.append("speech_to_text(empty)")
                print("  FAIL speech_to_text: empty transcript")

    if os.environ.get("CARTESIA_ADMIN_API_KEY"):
        run("get_credit_usage", lambda: s.get_credit_usage())
    else:
        print("  SKIP get_credit_usage — set CARTESIA_ADMIN_API_KEY to test")

    dict_name = f"{TEST_DICT_NAME_PREFIX} {run_id}"
    create_dict = run(
        "create_pronunciation_dict",
        lambda: s.create_pronunciation_dict(
            name=dict_name,
            items=[{"text": "Cartesia", "pronunciation": "kar-TEE-zhuh"}],
        ),
    )
    if create_dict:
        dict_id = create_dict.get("id")
        ok("create_pronunciation_dict", f"id={dict_id}")

        if dict_id:
            run(
                "get_pronunciation_dict",
                lambda: s.get_pronunciation_dict(dict_id),
            )
            run(
                "list_pronunciation_dicts",
                lambda: s.list_pronunciation_dicts(limit=5),
            )
            run(
                "update_pronunciation_dict",
                lambda: s.update_pronunciation_dict(
                    dict_id,
                    name=f"{dict_name} (updated)",
                    items=[{"text": "Cartesia", "pronunciation": "kar-TEE-zha"}],
                ),
            )
            run(
                "text_to_speech(pronunciation_dict)",
                lambda: s.text_to_speech(
                    transcript="Welcome to Cartesia.",
                    voice={"mode": "id", "id": SAMPLE_VOICE_ID},
                    output_format=WAV_FORMAT,
                    pronunciation_dict_id=dict_id,
                ),
            )

    # clone_voice needs ~5s+ audio; use TTS output when available.
    sample_wav = tts_path or os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "hi-grant-archie.wav")
    )

    if tts_path and os.path.isfile(tts_path):
        clone_name = f"{TEST_VOICE_NAME_PREFIX} Clone {run_id}"
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
            cloned_voice_name = getattr(clone_result, "name", clone_name)
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

    localized_name = f"{TEST_LOCALIZED_NAME_PREFIX} {run_id}"
    loc_result = run(
        "localize_voice",
        lambda: s.localize_voice(
            voice_id=SAMPLE_VOICE_ID,
            name=localized_name,
            description="Temporary localized voice from MCP test",
            language="es",
            original_speaker_gender="male",
        ),
    )
    if loc_result:
        localized_voice_id = getattr(loc_result, "id", None)
        localized_voice_name = getattr(loc_result, "name", localized_name)
        ok("localize_voice", f"id={localized_voice_id}")

    if dict_id:
        try:
            assert_safe_to_delete_dict(dict_id, created_this_run=True)
            run(
                "delete_pronunciation_dict",
                lambda: s.delete_pronunciation_dict(dict_id),
            )
        except RuntimeError as e:
            fail("delete_pronunciation_dict precheck", e)
            failures.append("delete_pronunciation_dict")

    # Only delete voices we created above — never catalog or existing user voices.
    for vid, name, label in [
        (localized_voice_id, localized_voice_name, "localized"),
        (cloned_voice_id, cloned_voice_name, "cloned"),
    ]:
        if not vid or not name:
            continue
        try:
            assert_safe_to_delete(vid, name, created_this_run=True)
        except RuntimeError as e:
            fail(f"delete_voice({label}) precheck", e)
            failures.append(f"delete_voice({label})")
            continue
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
