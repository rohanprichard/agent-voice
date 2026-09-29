"""Measure how soon speech starts, streaming against the whole-reply request.

This is the test behind the streaming decision. It renders the same reply twice
through the real ElevenLabs account: once through the blocking
`POST /v1/text-to-speech/{voice}` that returns a complete file, and once through
the WebSocket endpoint that accepts an agent's text as it is written.

The number that matters is time to first audio, measured from the moment the
reply text exists, not from the moment the network call starts. Text is fed to
the socket in small pieces with a short pause between them so the run resembles
an agent writing a reply rather than one large paste.

    npm run test:stream
    npm run test:stream -- --deltas 0        # paste the whole reply at once
    npm run test:stream -- --voice <id>

The key comes from the running app's settings when Remember key was used, or from
TALKTOME_ELEVENLABS_KEY. Both WAV files are kept so the result can be heard.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import wave
from io import BytesIO
from pathlib import Path

from talktome.config import data_dir
from talktome.speech import Speech
from talktome.streaming import ElevenLabsStream, default_connect

REPLY = (
    "I read the session handler. The token check runs before the session is loaded, "
    "so an expired token reaches the lookup with nothing to match against. "
    "That is the whole bug. Do you want me to move the check after the load?"
)

# Roughly an agent's token cadence: a few characters at a time, not sentences.
DELTA_CHARS = 9
DELTA_PAUSE = 0.025


def duration(data: bytes) -> float:
    with wave.open(BytesIO(data)) as file:
        return file.getnframes() / file.getframerate()


def combine(chunks: list[bytes]) -> bytes:
    """Join WAV chunks into one file, since every chunk carries its own header."""
    frames = bytearray()
    rate = 0
    for chunk in chunks:
        with wave.open(BytesIO(chunk)) as file:
            rate = file.getframerate()
            frames.extend(file.readframes(file.getnframes()))
    output = BytesIO()
    with wave.open(output, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(bytes(frames))
    return output.getvalue()


def resolve_key(engine: Speech) -> str:
    key = os.environ.get("TALKTOME_ELEVENLABS_KEY", "").strip()
    if key:
        return key
    engine.restore_providers()
    if engine.elevenlabs.key:
        return engine.elevenlabs.key
    raise SystemExit(
        "No ElevenLabs key was found.\n"
        "Enter it in Settings and turn on Remember key, or set TALKTOME_ELEVENLABS_KEY."
    )


def blocking_pass(engine: Speech, voice: str) -> dict:
    """One request, one complete file: the latency that was there before."""
    started = time.monotonic()
    audio = engine.synthesize(REPLY, voice)
    elapsed = time.monotonic() - started
    return {
        "seconds_to_first_audio": elapsed,
        "seconds_to_all_audio": elapsed,
        "chunks": 1,
        "audio_seconds": duration(audio),
        "audio": audio,
    }


async def streaming_pass(key: str, voice: str, deltas: int) -> dict:
    """The socket accepts text as it is written and returns audio as it is made."""
    chunks: list[bytes] = []
    started = time.monotonic()
    first: float | None = None

    async def on_audio(chunk: bytes):
        nonlocal first
        if first is None:
            first = time.monotonic() - started
        chunks.append(chunk)

    stream = ElevenLabsStream(default_connect, voice=voice, api_key=key, on_audio=on_audio)
    await stream.start()
    try:
        step = len(REPLY) if deltas <= 0 else max(1, len(REPLY) // deltas)
        for index in range(0, len(REPLY), step):
            stream.push(REPLY[index : index + step])
            if deltas > 0:
                await asyncio.sleep(DELTA_PAUSE)
        await stream.finish()
    finally:
        await stream.abort()
    if stream.error is not None:
        raise SystemExit(f"The socket failed: {stream.error}")
    return {
        "seconds_to_first_audio": first if first is not None else float("inf"),
        "seconds_to_all_audio": time.monotonic() - started,
        "chunks": len(chunks),
        "audio_seconds": sum(duration(chunk) for chunk in chunks),
        "audio": combine(chunks),
    }


async def run(args) -> int:
    engine = Speech(data_dir())
    key = resolve_key(engine)
    engine.elevenlabs.key = key
    voice = args.voice or engine.saved_voice()
    try:
        resolved = engine.elevenlabs.resolve_voice(voice)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None

    print(f"voice    {resolved}")
    print(f"reply    {len(REPLY)} characters, {len(REPLY.split())} words\n")

    whole = await asyncio.to_thread(blocking_pass, engine, resolved)
    streamed = await streaming_pass(key, resolved, args.deltas)

    for label, result in (("whole reply", whole), ("streamed", streamed)):
        print(
            f"{label:12s} first audio {result['seconds_to_first_audio']:6.2f}s   "
            f"all audio {result['seconds_to_all_audio']:6.2f}s   "
            f"{result['chunks']:3d} chunk(s)   {result['audio_seconds']:5.2f}s of speech"
        )

    saved = 0.0
    if streamed["seconds_to_first_audio"] < whole["seconds_to_first_audio"]:
        saved = whole["seconds_to_first_audio"] - streamed["seconds_to_first_audio"]
    print(f"\nstreaming started speech {saved:.2f}s sooner")

    out = Path(args.out) if args.out else data_dir() / "smoke"
    out.mkdir(parents=True, exist_ok=True)
    for name, result in (("whole.wav", whole), ("streamed.wav", streamed)):
        (out / name).write_bytes(result["audio"])
    print(f"wrote {out / 'whole.wav'}\n      {out / 'streamed.wav'}")
    print(json.dumps({"saved_seconds": round(saved, 3)}))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--voice", help="a voice id, or the saved one by default")
    parser.add_argument(
        "--deltas",
        type=int,
        default=18,
        help="how many pieces to feed the socket; 0 pastes the reply at once",
    )
    parser.add_argument("--out", help="a directory for the two WAV files")
    sys.exit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
