import functools
import io
import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import httpx

from .voice_providers import ElevenLabs, KokoroVoice, wav_audio

logger = logging.getLogger(__name__)

MODELS = [
    {
        "id": "small",
        "name": "Whisper Small",
        "size_mb": 484,
        "languages": "Multilingual",
        "description": "Recommended. Better recognition for conversation.",
        "recommended": True,
    },
    {
        "id": "base.en",
        "name": "Whisper Base · English",
        "size_mb": 145,
        "languages": "English",
        "description": "Less memory and a faster response. Lower accuracy.",
        "recommended": False,
    },
]


class Speech:
    def __init__(self, directory: Path):
        self.directory = directory
        self.model = None
        self.model_id = None
        self.lock = threading.Lock()
        self.settings_lock = threading.Lock()
        self._settings = None
        self.state = {"status": "needs_model", "progress": 0, "error": None, "model_id": None}
        self.kokoro = KokoroVoice(directory)
        self.elevenlabs = ElevenLabs(directory)
        # System voices already confirmed installed. Listing them runs `say -v ?`,
        # which is too slow to repeat before each spoken sentence.
        self.system_voices = set()

    def restore_providers(self):
        if self.settings().get("remember_elevenlabs"):
            self.elevenlabs.restore()
        if self.kokoro.directory.exists():
            self.kokoro.setup()

    def provider(self):
        return self.settings().get("tts_provider", "system")

    def recognition_provider(self):
        return self.settings().get("stt_provider", "whisper")

    def saved_model(self):
        return self.settings().get("model_id")

    def settings(self):
        # status() runs for every event a client reads, so the file is read once
        # and save_settings keeps this copy current.
        if self._settings is None:
            try:
                self._settings = json.loads((self.directory / "settings.json").read_text())
            except (OSError, ValueError):
                self._settings = {}
        return dict(self._settings)

    def saved_voice(self):
        return self.settings().get("voice", "default")

    def save_settings(self, **changes):
        with self.settings_lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            settings = {**self.settings(), **changes}
            temporary = self.directory / "settings.json.tmp"
            temporary.write_text(json.dumps(settings))
            temporary.replace(self.directory / "settings.json")
            self._settings = settings

    def status(self):
        settings = self.settings()
        provider = settings.get("tts_provider", "system")
        recognition = settings.get("stt_provider", "whisper")
        available = {
            "system": bool(self.tts_command()),
            "kokoro": self.kokoro.state["status"] == "ready",
            "elevenlabs": bool(self.elevenlabs.key),
        }
        state = dict(self.state)
        if recognition == "elevenlabs":
            state.update(status="ready" if self.elevenlabs.key else "needs_key", error=None)
        return {
            **state,
            "tts_available": available[provider],
            "engine": "faster-whisper" if recognition == "whisper" else "scribe_v2",
            "stt_provider": recognition,
            "tts_provider": provider,
            "local_stt": dict(self.state),
            "kokoro": dict(self.kokoro.state),
            "elevenlabs": {
                "configured": bool(self.elevenlabs.key),
                "remembered": self.elevenlabs.remembered,
            },
        }

    @staticmethod
    @functools.cache
    def tts_command():
        return (
            shutil.which("say")
            if sys.platform == "darwin"
            else (shutil.which("espeak-ng") or shutil.which("espeak"))
        )

    def setup(self, model_id):
        from faster_whisper import WhisperModel
        from huggingface_hub import HfApi, hf_hub_url

        with self.lock:
            self.state = {
                "status": "downloading",
                "progress": 0,
                "error": None,
                "model_id": model_id,
                "downloaded_bytes": 0,
                "total_bytes": 0,
            }
            try:
                target = self.directory / "models" / model_id
                marker = target / ".complete"
                if not marker.exists():
                    target.mkdir(parents=True, exist_ok=True)
                    repo = f"Systran/faster-whisper-{model_id}"
                    info = HfApi().model_info(repo, files_metadata=True)
                    files = [
                        f
                        for f in info.siblings
                        if f.rfilename
                        in {
                            "config.json",
                            "model.bin",
                            "tokenizer.json",
                            "vocabulary.json",
                            "vocabulary.txt",
                        }
                    ]
                    if not {"config.json", "model.bin", "tokenizer.json"}.issubset(
                        {f.rfilename for f in files}
                    ):
                        raise ValueError("The model download has missing files.")
                    total = sum(f.size or 0 for f in files)
                    done = 0
                    self.state["total_bytes"] = total
                    with httpx.Client(follow_redirects=True, timeout=60) as client:
                        for entry in files:
                            dest = target / entry.rfilename
                            if dest.exists() and dest.stat().st_size == entry.size:
                                done += entry.size
                                continue
                            part = dest.with_suffix(dest.suffix + ".part")
                            url = hf_hub_url(repo, entry.rfilename, revision=info.sha)
                            with client.stream("GET", url) as response:
                                response.raise_for_status()
                                with part.open("wb") as file:
                                    for chunk in response.iter_bytes(256 * 1024):
                                        file.write(chunk)
                                        done += len(chunk)
                                        self.state.update(
                                            downloaded_bytes=done,
                                            progress=round(done / max(total, 1) * 100, 1),
                                        )
                            if entry.size and part.stat().st_size != entry.size:
                                raise ValueError("The model download is incomplete. Try again.")
                            part.replace(dest)
                    marker.write_text(info.sha)
                self.state.update(status="loading", progress=100)
                self.model = None
                self.model_id = None
                self.model = WhisperModel(
                    str(target),
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=4,
                    local_files_only=True,
                )
                self.model_id = model_id
                self.directory.mkdir(parents=True, exist_ok=True)
                self.save_settings(model_id=model_id)
                self.state.update(status="ready", error=None)
            except Exception:
                logger.exception("The speech model did not load.")
                self.state.update(
                    status="error",
                    error="The model did not load. Examine the server log, then try again.",
                )

    def listen(self, samples, prompt=""):
        """One streaming run: transcribe what has been heard so far, and cheaply.

        Greedy rather than the batch path's beam search. This runs every eight
        tenths of a second over everything heard so far, so the cost of a run is
        paid over and over — and a partial that is a little less certain is worth
        far more than a partial that arrives late.

        `prompt` is the text already agreed, which stops the model from transcribing
        the same words again as it re-hears them.
        """
        with self.lock:
            if self.model is None:
                raise ValueError("Download a speech model before you use the microphone.")
            segments, _ = self.model.transcribe(
                samples,
                beam_size=1,
                vad_filter=False,
                condition_on_previous_text=False,
                initial_prompt=prompt or None,
            )
            return " ".join(segment.text.strip() for segment in segments).strip()

    def transcribe(self, audio: bytes):
        from faster_whisper.audio import decode_audio

        with self.lock:
            try:
                samples = decode_audio(io.BytesIO(audio), sampling_rate=16000)
            except Exception as exc:
                raise ValueError("The audio file is invalid. Use WAV, WebM, or MP4 audio.") from exc
            duration = len(samples) / 16000
            if duration > 35:
                raise ValueError("The audio exceeds 35 seconds. Send a shorter recording.")
            if self.recognition_provider() == "elevenlabs":
                return self.elevenlabs.transcribe(wav_audio(samples, 16000), round(duration * 1000))
            if self.model is None:
                raise ValueError("Download a speech model before you use the microphone.")
            segments, info = self.model.transcribe(
                samples, beam_size=3, vad_filter=True, condition_on_previous_text=False
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
            return {"text": text, "language": info.language, "duration_ms": round(duration * 1000)}

    def voices(self):
        if self.provider() == "kokoro":
            return self.kokoro.voices()
        if self.provider() == "elevenlabs":
            return self.elevenlabs.voices()
        command = self.tts_command()
        if not command:
            return []
        if sys.platform != "darwin":
            return [{"id": "default", "name": "System voice", "language": "en"}]
        output = subprocess.run(
            [command, "-v", "?"], capture_output=True, text=True, timeout=10, check=True
        ).stdout
        voices = []
        seen = set()
        for line in output.splitlines():
            match = re.match(r"^(.+?)\s+([a-z]{2,3}_[A-Z]{2})\s+#", line)
            if match and match[1].strip() not in seen:
                seen.add(match[1].strip())
                voices.append(
                    {"id": match[1].strip(), "name": match[1].strip(), "language": match[2]}
                )
        return [{"id": "default", "name": "System default", "language": ""}, *voices]

    def withheld_voices(self):
        """Voices the provider would return but refuse to speak with, and why.

        Only ElevenLabs has this: it lists library voices for an account that cannot
        use them, so the list and the usable set are different, and the difference
        has to be explained rather than silently applied.
        """
        if self.provider() != "elevenlabs":
            return {"count": 0, "reason": ""}
        return self.elevenlabs.withheld()

    def open_stream(self, voice, on_audio):
        """Return a streaming session, or None when text must be synthesized whole.

        Only ElevenLabs can take text a piece at a time as the agent writes it. Kokoro
        does have `create_stream`, but it yields one chunk per 510 characters of
        phonemes, which at a spoken reply's length is a single chunk — the first chunk
        is the whole utterance, so it buys nothing. Local engines therefore keep the
        sentence path, which starts speaking at the first complete sentence rather
        than at the end of the reply.
        """
        if self.provider() != "elevenlabs" or not self.elevenlabs.key:
            return None
        from .streaming import ElevenLabsStream, default_connect

        try:
            resolved = self.elevenlabs.resolve_voice(voice)
        except ValueError:
            return None
        return ElevenLabsStream(
            default_connect,
            voice=resolved,
            api_key=self.elevenlabs.key,
            on_audio=on_audio,
        )

    def synthesize(self, text, voice="default"):
        if self.provider() == "kokoro":
            return self.kokoro.synthesize(text, voice)
        if self.provider() == "elevenlabs":
            return self.elevenlabs.synthesize(text, voice)
        command = self.tts_command()
        if not command:
            raise ValueError("No local voice engine is available. Install eSpeak NG on Linux.")
        if voice != "default" and voice not in self.system_voices:
            if voice not in {v["id"] for v in self.voices()}:
                raise ValueError("Select an installed voice.")
            self.system_voices.add(voice)
        with tempfile.TemporaryDirectory(prefix="talktome-voice-") as directory:
            output = Path(directory) / "reply.wav"
            if sys.platform == "darwin":
                source = Path(directory) / "text.txt"
                source.write_text(text)
                args = [command, "-o", str(output), "--data-format=LEI16@22050", "-f", str(source)]
                if voice != "default":
                    args += ["-v", voice]
                subprocess.run(args, check=True, capture_output=True, timeout=60)
            else:
                subprocess.run(
                    [command, "-w", str(output), "--stdin"],
                    input=text.encode(),
                    check=True,
                    capture_output=True,
                    timeout=60,
                )
            return output.read_bytes()
