import contextlib
import hashlib
import io
import logging
import threading
import wave

import httpx

logger = logging.getLogger(__name__)

KOKORO_FILES = [
    (
        "kokoro-v1.0.int8.onnx",
        114119327,
        "ae315a79b623f244700e4afb9246c46a26066782e049ba174bf3ba433970ee9c",
    ),
    (
        "voices-v1.0.bin",
        28214398,
        "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
    ),
]
KOKORO_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"


def wav_audio(samples, sample_rate):
    import numpy as np

    output = io.BytesIO()
    with wave.open(output, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(sample_rate)
        file.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return output.getvalue()


class KokoroVoice:
    def __init__(self, directory):
        self.directory = directory / "models" / "kokoro"
        self.model = None
        self.lock = threading.Lock()
        # The size is known before the download, so setup can show it first.
        self.state = {
            "status": "needs_model",
            "progress": 0,
            "error": None,
            "total_bytes": sum(size for _, size, _ in KOKORO_FILES),
        }

    def setup(self):
        with self.lock:
            total = sum(size for _, size, _ in KOKORO_FILES)
            self.state.update(
                status="downloading",
                progress=0,
                error=None,
                downloaded_bytes=0,
                total_bytes=total,
            )
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                done = 0
                with httpx.Client(follow_redirects=True, timeout=60) as client:
                    for name, size, checksum in KOKORO_FILES:
                        destination = self.directory / name
                        if destination.exists():
                            with destination.open("rb") as file:
                                valid = hashlib.file_digest(file, "sha256").hexdigest() == checksum
                            if valid:
                                done += size
                                continue
                        partial = destination.with_suffix(destination.suffix + ".part")
                        digest = hashlib.sha256()
                        with client.stream("GET", f"{KOKORO_URL}/{name}") as response:
                            response.raise_for_status()
                            with partial.open("wb") as file:
                                for chunk in response.iter_bytes(256 * 1024):
                                    file.write(chunk)
                                    digest.update(chunk)
                                    done += len(chunk)
                                    self.state.update(
                                        downloaded_bytes=done,
                                        progress=round(done / total * 100, 1),
                                    )
                        if partial.stat().st_size != size or digest.hexdigest() != checksum:
                            raise ValueError("The Kokoro file is incomplete or changed. Try again.")
                        partial.replace(destination)
                self.state.update(status="loading", progress=100, downloaded_bytes=total)
                from kokoro_onnx import Kokoro

                self.model = Kokoro(
                    str(self.directory / KOKORO_FILES[0][0]),
                    str(self.directory / KOKORO_FILES[1][0]),
                )
                self.state.update(status="ready")
            except Exception:
                logger.exception("Kokoro did not load.")
                self.state.update(
                    status="error", error="Kokoro did not load. Try the download again."
                )

    def voices(self):
        if self.model is None:
            return []
        return [
            {
                "id": name,
                "name": name[3:].replace("_", " ").title(),
                "language": "en-US" if name.startswith("a") else "en-GB",
            }
            for name in self.model.get_voices()
            if name.startswith(("a", "b"))
        ]

    def synthesize(self, text, voice):
        with self.lock:
            if self.model is None or self.state["status"] != "ready":
                raise ValueError("Download Kokoro in Settings before you select a Kokoro voice.")
            if voice == "default":
                voice = "af_heart"
            if voice not in {item["id"] for item in self.voices()}:
                raise ValueError("Select a Kokoro voice from the list.")
            samples, rate = self.model.create(
                text,
                voice=voice,
                speed=1.0,
                lang="en-gb" if voice.startswith("b") else "en-us",
            )
            return wav_audio(samples, rate)


# Nothing has been asked of the account yet, as opposed to asked and refused.
UNKNOWN = object()


class ElevenLabs:
    # Library voices — community voices added to an account — are refused for a free
    # account, and the refusal arrives on the first spoken word of a call rather than
    # when the voice is chosen. Measured against a free account:
    #
    #     premade          200
    #     copied library   402  "Free users cannot use library voices via the API."
    #
    # `sharing.free_users_allowed` does not predict it. Both refused voices reported
    # `true`, because that field describes the owner's sharing setting rather than the
    # account asking for it. So a library voice is offered only when the account is
    # known to be paid, and left out when that cannot be established: a call that dies
    # mid-sentence is far worse than a voice that is not in the list.
    LIBRARY = frozenset({"copied", "copied_disabled"})

    def __init__(self, directory):
        self.key = None
        self.remembered = False
        self.voice_cache = []
        # The account's plan, asked once. `UNKNOWN` means it has not been asked;
        # None means the key would not say, which is treated as "not known paid".
        self.tier_cache = UNKNOWN
        # Why the keychain refused, when it did. Empty means it did not.
        self.remember_error = ""
        self.account = hashlib.sha256(str(directory.resolve()).encode()).hexdigest()

    def restore(self):
        import keyring

        try:
            self.key = keyring.get_password("talktome-elevenlabs", self.account)
            self.remembered = bool(self.key)
        except keyring.errors.KeyringError:
            self.key = None

    def request(self, method, route, *, key=None, timeout=60, **kwargs):
        credential = key or self.key
        if not credential:
            raise ValueError("Enter your ElevenLabs API key in Settings.")
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.request(
                    method,
                    f"https://api.elevenlabs.io{route}",
                    headers={"xi-api-key": credential},
                    **kwargs,
                )
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            messages = {
                401: (
                    "ElevenLabs rejected the API key. A restricted key needs the voices_read "
                    "permission to list voices."
                ),
                403: "ElevenLabs denied this request. Examine the key permissions and account plan.",
                429: "ElevenLabs reached a request or credit limit. Examine your account, then try again.",
            }
            message = messages.get(
                exc.response.status_code, "ElevenLabs could not process the request. Try again."
            )
            reason = self.reason(exc.response)
            raise ValueError(f"{message} {reason}".strip()) from None
        except httpx.RequestError:
            raise ValueError(
                "ElevenLabs is unavailable. Examine your internet connection."
            ) from None

    @staticmethod
    def reason(response):
        """Return the provider's own explanation, without echoing the credential."""
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            return ""
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("status") or ""
        if not isinstance(detail, str):
            return ""
        return " ".join(detail.split())[:200]

    def fetch_voices(self, key=None):
        voices = []
        token = None
        for _ in range(20):
            params = {"page_size": 100}
            if token:
                params["next_page_token"] = token
            data = self.request("GET", "/v2/voices", key=key, params=params).json()
            voices.extend(
                {
                    "id": item["voice_id"],
                    "name": item["name"],
                    "language": item.get("labels", {}).get("language", ""),
                    # A community voice the account has added. The one property that
                    # decides whether a free account may speak with it.
                    "library": (item.get("sharing") or {}).get("status") in self.LIBRARY,
                }
                for item in data.get("voices", [])
            )
            token = data.get("next_page_token")
            if not data.get("has_more") or not token:
                break
        return voices

    def tier(self, key=None):
        """The account's plan, or None when the key will not say.

        A restricted key without `user_read` is refused here, which is why the answer
        is optional: not knowing is normal, and the consequence is only that library
        voices stay out of the list. Asked once, because it cannot change mid-session
        in any way this app acts on.
        """
        if self.tier_cache is UNKNOWN:
            try:
                subscription = self.request("GET", "/v1/user/subscription", key=key).json()
                self.tier_cache = (subscription or {}).get("tier")
            except ValueError:
                self.tier_cache = None
        return self.tier_cache

    def paid(self):
        """Whether the account is known to be on a plan that can use library voices."""
        tier = self.tier()
        return bool(tier) and str(tier).lower() not in {"free", "unknown"}

    def configure(self, key, remember=False):
        import keyring

        voices = self.fetch_voices(key)
        try:
            if remember:
                # Clear any earlier item first. Without a stable code signature every
                # build looks like a different application to the keychain, so
                # overwriting an item an earlier build created reads as an attempt to
                # change its owner and is refused with -25244. The item is this app's
                # own and is being replaced, so removing it first is the fix.
                with contextlib.suppress(keyring.errors.KeyringError):
                    keyring.delete_password("talktome-elevenlabs", self.account)
                keyring.set_password("talktome-elevenlabs", self.account, key)
            elif self.remembered:
                keyring.delete_password("talktome-elevenlabs", self.account)
        except keyring.errors.KeyringError as exc:
            # Remembering is a convenience, and the key itself has already been
            # accepted. Failing the whole request here threw away a working key
            # because an optional extra could not be stored, which is a worse
            # outcome than forgetting: the session works either way, and the user
            # is told the remembering part did not.
            #
            # The reason is logged because keyring raises the same class for no
            # backend as for a locked keychain, and the two need opposite responses.
            logger.warning(
                "The system keychain refused to store the key: %s: %s", type(exc).__name__, exc
            )
            self.remember_error = " ".join(str(exc).split())[:200]
            remember = False
        self.key, self.remembered, self.voice_cache = key, remember, voices
        # A different key is a different account, and possibly a different plan.
        self.tier_cache = UNKNOWN
        return {"remembered": self.remembered, "reason": self.remember_error}

    def forget(self):
        import keyring

        if self.remembered:
            try:
                keyring.delete_password("talktome-elevenlabs", self.account)
            except keyring.errors.KeyringError:
                raise ValueError("The keychain could not remove the key. Try again.") from None
        self.key, self.remembered, self.voice_cache = None, False, []
        self.tier_cache = UNKNOWN
        self.remember_error = ""

    def voices(self):
        """The voices this account can actually speak with.

        A library voice is held back unless the account is known to be paid, so the
        list is the set the API will accept rather than the set it will return.
        """
        if not self.key:
            return []
        if not self.voice_cache:
            self.voice_cache = self.fetch_voices()
        if self.paid():
            return self.voice_cache
        return [item for item in self.voice_cache if not item.get("library")]

    def withheld(self):
        """How many voices were held back, and why, for the settings screen.

        A voice that is in the account but missing from the list looks like a bug
        unless the screen says where it went.
        """
        if not self.voice_cache or self.paid():
            return {"count": 0, "reason": ""}
        count = sum(1 for item in self.voice_cache if item.get("library"))
        if not count:
            return {"count": 0, "reason": ""}
        return {
            "count": count,
            "reason": (
                "Library voices are hidden because ElevenLabs refuses them for free "
                "accounts. They need a paid plan, and the key did not say which plan "
                "this is."
            ),
        }

    def resolve_voice(self, voice):
        """Turn a setting into a voice id, or explain why it cannot be used."""
        voices = self.voices()
        if voice == "default":
            if not voices:
                raise ValueError("No ElevenLabs voices are available for this key.")
            return voices[0]["id"]
        if voice not in {item["id"] for item in voices}:
            # A voice that is in the account but no longer offered — a library voice
            # on a free plan, most often — needs to be told apart from a stale id,
            # because the two want opposite advice.
            if voice in {item["id"] for item in self.voice_cache if item.get("library")}:
                raise ValueError(
                    "That is a library voice, and ElevenLabs refuses library voices for "
                    "free accounts. Choose a different voice, or upgrade the plan."
                )
            raise ValueError("Select an ElevenLabs voice from the list.")
        return voice

    def synthesize(self, text, voice):
        from faster_whisper.audio import decode_audio

        voice = self.resolve_voice(voice)
        response = self.request(
            "POST",
            f"/v1/text-to-speech/{voice}",
            params={"output_format": "mp3_44100_128"},
            json={"text": text, "model_id": "eleven_flash_v2_5"},
        )
        return wav_audio(decode_audio(io.BytesIO(response.content), sampling_rate=24000), 24000)

    def transcribe(self, audio, duration_ms):
        data = self.request(
            "POST",
            "/v1/speech-to-text",
            data={"model_id": "scribe_v2", "tag_audio_events": "false", "diarize": "false"},
            files={"file": ("speech.wav", audio, "audio/wav")},
        ).json()
        return {"text": data["text"], "language": data["language_code"], "duration_ms": duration_ms}

    def realtime_token(self):
        """Get one browser token. Keep the API key on the server."""
        data = self.request("POST", "/v1/single-use-token/realtime_scribe", timeout=5).json()
        token = data.get("token") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token:
            raise ValueError("ElevenLabs did not return a speech token.")
        return token
