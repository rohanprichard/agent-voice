import hashlib
import io
import sys
import types
import wave

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from talktome import voice_providers
from talktome.app import create_app
from talktome.speech import Speech
from talktome.streaming import ElevenLabsStream


class FakeKeyringError(Exception):
    pass


class FakeKeyring:
    class errors:
        KeyringError = FakeKeyringError

    def __init__(self, saved=None, fail=None):
        self.saved = saved
        self.fail = fail
        self.calls = []

    def get_password(self, service, account):
        self.calls.append(("get", service, account))
        if self.fail == "get":
            raise FakeKeyringError()
        return self.saved

    def set_password(self, service, account, password):
        self.calls.append(("set", service, account, password))
        if self.fail == "set":
            raise FakeKeyringError()
        self.saved = password

    def delete_password(self, service, account):
        self.calls.append(("delete", service, account))
        if self.fail == "delete":
            raise FakeKeyringError()
        self.saved = None


def install_keyring(monkeypatch, keyring):
    module = types.ModuleType("keyring")
    module.errors = keyring.errors
    module.get_password = keyring.get_password
    module.set_password = keyring.set_password
    module.delete_password = keyring.delete_password
    monkeypatch.setitem(sys.modules, "keyring", module)


def fake_client(monkeypatch, handler):
    client_class = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        voice_providers.httpx,
        "Client",
        lambda **kwargs: client_class(transport=transport, **kwargs),
    )


def test_kokoro_rejects_checksum_failure(tmp_path, monkeypatch):
    content = b"bad model bytes"
    monkeypatch.setattr(
        voice_providers,
        "KOKORO_FILES",
        [("model.onnx", len(content), hashlib.sha256(b"good").hexdigest())],
    )
    monkeypatch.setattr(voice_providers, "KOKORO_URL", "https://models.test")

    def handle(request):
        assert request.url == "https://models.test/model.onnx"
        return httpx.Response(200, content=content)

    fake_client(monkeypatch, handle)
    provider = voice_providers.KokoroVoice(tmp_path)
    provider.setup()

    assert provider.state["status"] == "error"
    assert provider.state["error"] == "Kokoro did not load. Try the download again."
    assert not (provider.directory / "model.onnx").exists()
    assert (provider.directory / "model.onnx.part").read_bytes() == content


def test_kokoro_uses_valid_cached_files_without_network(tmp_path, monkeypatch):
    files = [("model.onnx", b"model"), ("voices.bin", b"voices")]
    monkeypatch.setattr(
        voice_providers,
        "KOKORO_FILES",
        [(name, len(data), hashlib.sha256(data).hexdigest()) for name, data in files],
    )
    provider = voice_providers.KokoroVoice(tmp_path)
    provider.directory.mkdir(parents=True)
    for name, data in files:
        (provider.directory / name).write_bytes(data)
    calls = []

    def no_network(request):
        calls.append(request)
        raise AssertionError("The cached files must not need a network request.")

    fake_client(monkeypatch, no_network)
    fake_model = types.ModuleType("kokoro_onnx")
    fake_model.Kokoro = lambda *args: types.SimpleNamespace(
        get_voices=lambda: ["af_heart", "bf_emma", "zz_other"]
    )
    monkeypatch.setitem(sys.modules, "kokoro_onnx", fake_model)

    provider.setup()

    assert calls == []
    assert provider.state["status"] == "ready"
    assert [voice["id"] for voice in provider.voices()] == ["af_heart", "bf_emma"]
    assert provider.voices()[0]["language"] == "en-US"
    assert provider.voices()[1]["language"] == "en-GB"


def test_elevenlabs_remember_and_forget_use_mocked_keyring(tmp_path, monkeypatch):
    keyring = FakeKeyring()
    install_keyring(monkeypatch, keyring)
    provider = voice_providers.ElevenLabs(tmp_path)
    provider.fetch_voices = lambda key=None: [{"id": "voice-1", "name": "Test", "language": "en"}]

    provider.configure("test-secret", remember=True)
    assert provider.key == "test-secret"
    assert provider.remembered is True
    assert keyring.saved == "test-secret"
    assert provider.voice_cache[0]["id"] == "voice-1"

    provider.forget()
    assert provider.key is None
    assert provider.remembered is False
    assert provider.voice_cache == []
    assert keyring.saved is None
    # A leading delete clears any item an earlier build left behind, which the
    # keychain refuses to overwrite once the app's signature has changed.
    assert [call[0] for call in keyring.calls] == ["delete", "set", "delete"]


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (
            401,
            (
                "ElevenLabs rejected the API key. A restricted key needs the voices_read "
                "permission to list voices."
            ),
        ),
        (403, "ElevenLabs denied this request. Examine the key permissions and account plan."),
        (
            429,
            "ElevenLabs reached a request or credit limit. Examine your account, then try again.",
        ),
        (500, "ElevenLabs could not process the request. Try again."),
    ],
)
def test_elevenlabs_sanitizes_http_errors(tmp_path, monkeypatch, status, message):
    secret = "private-test-key"
    fake_client(monkeypatch, lambda request: httpx.Response(status, text=secret))
    provider = voice_providers.ElevenLabs(tmp_path)
    provider.key = secret

    with pytest.raises(ValueError) as error:
        provider.request("GET", "/v2/voices")

    assert str(error.value) == message
    assert secret not in str(error.value)


def test_elevenlabs_reports_the_provider_reason_without_the_key(tmp_path, monkeypatch):
    secret = "private-test-key"
    fake_client(
        monkeypatch,
        lambda request: httpx.Response(
            401,
            json={
                "detail": {
                    "status": "missing_permissions",
                    "message": "The API key is missing the permission voices_read",
                }
            },
        ),
    )
    provider = voice_providers.ElevenLabs(tmp_path)
    provider.key = secret

    with pytest.raises(ValueError) as error:
        provider.request("GET", "/v2/voices")

    assert "missing_permissions" in str(error.value) or "voices_read" in str(error.value)
    assert secret not in str(error.value)


def test_elevenlabs_voice_listing_and_tts_audio(tmp_path, monkeypatch):
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.path == "/v2/voices":
            return httpx.Response(
                200,
                json={
                    "voices": [
                        {"voice_id": "voice-1", "name": "Test Voice", "labels": {"language": "en"}}
                    ],
                    "has_more": False,
                },
            )
        return httpx.Response(200, content=b"fake-mp3")

    fake_client(monkeypatch, handle)
    audio_module = types.ModuleType("faster_whisper.audio")
    audio_module.decode_audio = lambda source, sampling_rate: np.array([0.0, 0.5, -0.5])
    monkeypatch.setitem(sys.modules, "faster_whisper.audio", audio_module)
    provider = voice_providers.ElevenLabs(tmp_path)
    provider.key = "private-test-key"

    assert provider.voices() == [
        {"id": "voice-1", "name": "Test Voice", "language": "en", "library": False}
    ]
    audio = provider.synthesize("Hello", "voice-1")
    with wave.open(io.BytesIO(audio), "rb") as wav:
        assert wav.getframerate() == 24000
        assert wav.getnchannels() == 1
        assert wav.getnframes() == 3
    assert calls[-1].method == "POST"
    assert calls[-1].url.path == "/v1/text-to-speech/voice-1"
    assert "xi-api-key" in calls[-1].headers
    assert calls[-1].headers["xi-api-key"] == "private-test-key"


def test_elevenlabs_stt_request_format(tmp_path, monkeypatch):
    captured = []

    def handle(request):
        captured.append(request)
        return httpx.Response(200, json={"text": "recognized", "language_code": "en"})

    fake_client(monkeypatch, handle)
    provider = voice_providers.ElevenLabs(tmp_path)
    provider.key = "private-test-key"

    result = provider.transcribe(b"wav-data", 1250)

    request = captured[0]
    assert request.method == "POST"
    assert request.url.path == "/v1/speech-to-text"
    assert request.headers["xi-api-key"] == "private-test-key"
    body = request.read()
    assert b'name="model_id"' in body and b"scribe_v2" in body
    assert b'name="tag_audio_events"' in body and b"false" in body
    assert b'name="diarize"' in body and b"false" in body
    assert b'name="file"; filename="speech.wav"' in body
    assert b"Content-Type: audio/wav" in body
    assert b"wav-data" in body
    assert result == {"text": "recognized", "language": "en", "duration_ms": 1250}


def test_provider_settings_api_hides_key_and_rejects_changes_during_call(tmp_path, monkeypatch):
    keyring = FakeKeyring()
    install_keyring(monkeypatch, keyring)
    engine = Speech(tmp_path)
    engine.elevenlabs.fetch_voices = lambda key=None: [
        {"id": "voice-1", "name": "Voice", "language": "en"}
    ]
    app = create_app(token="test-token", speech=engine)
    secret = "private-test-key"

    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as client:
        response = client.post("/v1/speech/elevenlabs", json={"api_key": secret, "remember": True})
        assert response.status_code == 200
        assert secret not in response.text
        state = client.get("/v1/state")
        assert state.status_code == 200
        assert secret not in state.text
        assert state.json()["speech"]["elevenlabs"] == {"configured": True, "remembered": True}

        invalid_key = client.post(
            "/v1/speech/elevenlabs",
            json={"api_key": secret + "x" * 512, "remember": True},
        )
        assert invalid_key.status_code == 422
        assert secret not in invalid_key.text

        invalid = client.post(
            "/v1/speech/providers",
            json={"stt_provider": "invalid", "tts_provider": "system"},
        )
        assert invalid.status_code == 400
        assert secret not in invalid.text

        client.portal.call(app.state.room.start)
        settings_before = engine.settings()
        blocked = client.post(
            "/v1/speech/providers",
            json={"stt_provider": "elevenlabs", "tts_provider": "elevenlabs"},
        )
        assert blocked.status_code == 409
        assert secret not in blocked.text
        assert engine.settings() == settings_before

        removed = client.delete("/v1/speech/elevenlabs")
        assert removed.status_code == 409
        client.post(
            "/v1/call/end", json={"call_id": client.get("/v1/state").json()["room"]["call_id"]}
        )
        removed = client.delete("/v1/speech/elevenlabs")
        assert removed.status_code == 200
        assert secret not in removed.text
        assert keyring.saved is None
        assert engine.status()["elevenlabs"] == {"configured": False, "remembered": False}


def test_open_stream_needs_the_elevenlabs_provider_and_a_key(tmp_path):
    engine = Speech(tmp_path)
    engine.elevenlabs.fetch_voices = lambda key=None: [
        {"id": "voice-1", "name": "V", "language": "en"}
    ]
    engine.save_settings(tts_provider="system", voice="default")
    assert engine.open_stream("default", None) is None

    engine.save_settings(tts_provider="elevenlabs")
    assert engine.open_stream("default", None) is None  # no key yet

    engine.elevenlabs.key = "key-1"
    stream = engine.open_stream("default", None)
    assert isinstance(stream, ElevenLabsStream)
    assert stream.voice == "voice-1"
    assert stream.api_key == "key-1"
    assert "pcm_24000" in stream.url()


def test_open_stream_stays_quiet_when_the_voice_is_unusable(tmp_path):
    engine = Speech(tmp_path)
    engine.elevenlabs.fetch_voices = lambda key=None: [
        {"id": "voice-1", "name": "V", "language": "en"}
    ]
    engine.elevenlabs.key = "key-1"
    engine.save_settings(tts_provider="elevenlabs", voice="missing-voice")
    # No stream rather than an exception: the turn falls back to sentence speech.
    assert engine.open_stream("missing-voice", None) is None


def test_a_keychain_that_refuses_does_not_cost_the_user_the_key(tmp_path, monkeypatch):
    # Remembering is a convenience, and the key has already been accepted by the
    # provider. Failing the whole request threw away a working key because an
    # optional extra could not be stored, which is worse than forgetting.
    import keyring

    engine = Speech(tmp_path)
    engine.elevenlabs.fetch_voices = lambda key=None: [{"id": "v1", "name": "V", "language": "en"}]

    def refuse(*args, **kwargs):
        raise keyring.errors.PasswordSetError("the keychain said no")

    monkeypatch.setattr(keyring, "set_password", refuse)
    saved = engine.elevenlabs.configure("secret-key", remember=True)

    assert engine.elevenlabs.key == "secret-key", "the key must survive the keychain refusing"
    assert saved["remembered"] is False
    assert "the keychain said no" in saved["reason"]


def test_remembering_reports_success(tmp_path, monkeypatch):
    import keyring

    engine = Speech(tmp_path)
    engine.elevenlabs.fetch_voices = lambda key=None: [{"id": "v1", "name": "V", "language": "en"}]
    monkeypatch.setattr(keyring, "set_password", lambda *a, **k: None)
    saved = engine.elevenlabs.configure("secret-key", remember=True)
    assert saved["remembered"] is True
    assert saved["reason"] == ""


def test_a_stale_keychain_item_is_cleared_before_writing(tmp_path, monkeypatch):
    # Without a stable signature every build looks like a different application, so
    # writing over an item an earlier build created reads as an owner change and is
    # refused with -25244. Deleting first is what makes the write succeed.
    import keyring

    engine = Speech(tmp_path)
    engine.elevenlabs.fetch_voices = lambda key=None: [{"id": "v1", "name": "V", "language": "en"}]
    calls = []

    def failing_set(service, account, secret):
        if not calls:
            raise keyring.errors.PasswordSetError("(-25244, 'Unknown Error')")
        calls.append("set")

    monkeypatch.setattr(keyring, "set_password", failing_set)
    monkeypatch.setattr(keyring, "delete_password", lambda *a, **k: calls.append("delete"))

    saved = engine.elevenlabs.configure("secret-key", remember=True)
    assert calls == ["delete", "set"], calls
    assert saved["remembered"] is True
    assert engine.elevenlabs.key == "secret-key"


def test_clearing_a_missing_item_is_not_an_error(tmp_path, monkeypatch):
    import keyring

    engine = Speech(tmp_path)
    engine.elevenlabs.fetch_voices = lambda key=None: [{"id": "v1", "name": "V", "language": "en"}]

    def nothing_to_delete(*args, **kwargs):
        raise keyring.errors.PasswordDeleteError("no such item")

    monkeypatch.setattr(keyring, "delete_password", nothing_to_delete)
    monkeypatch.setattr(keyring, "set_password", lambda *a, **k: None)
    assert engine.elevenlabs.configure("k", remember=True)["remembered"] is True


# ------------------------------- voices the account cannot actually speak with

PREMADE = {"id": "v-premade", "name": "Bella", "language": "en", "library": False}
LIBRARY = {"id": "v-library", "name": "Veda Sky", "language": "en", "library": True}


def elevenlabs(tmp_path, voices=(PREMADE, LIBRARY), tier=None):
    provider = voice_providers.ElevenLabs(tmp_path)
    provider.key = "test-secret"
    provider.voice_cache = list(voices)
    provider.tier_cache = tier
    return provider


def test_a_library_voice_is_not_offered_to_a_free_account(tmp_path):
    """Measured against a real free account: premade voices answer 200 and copied
    library voices answer 402, and the refusal only arrives on the first spoken
    word of a call. Offering the voice is what makes that failure possible."""
    provider = elevenlabs(tmp_path, tier="free")
    assert [voice["id"] for voice in provider.voices()] == ["v-premade"]


def test_a_library_voice_is_not_offered_when_the_plan_cannot_be_read(tmp_path):
    # A restricted key without `user_read` is refused by the subscription endpoint,
    # and not knowing is normal. Leaving the voice out costs a paid user nothing;
    # leaving it in costs a free user the call.
    provider = elevenlabs(tmp_path, tier=None)
    assert [voice["id"] for voice in provider.voices()] == ["v-premade"]


def test_a_paid_account_still_gets_its_library_voices(tmp_path):
    provider = elevenlabs(tmp_path, tier="creator")
    assert [voice["id"] for voice in provider.voices()] == ["v-premade", "v-library"]


def test_a_voice_that_was_left_out_is_explained_rather_than_silently_missing(tmp_path):
    provider = elevenlabs(tmp_path, tier="free")
    assert provider.voices()
    withheld = provider.withheld()
    assert withheld["count"] == 1
    assert "paid plan" in withheld["reason"]


def test_nothing_is_reported_withheld_when_nothing_was(tmp_path):
    provider = elevenlabs(tmp_path, voices=(PREMADE,), tier="free")
    assert provider.voices()
    assert provider.withheld()["count"] == 0


def test_a_chosen_voice_that_is_no_longer_offered_says_which_kind_it_is(tmp_path):
    # The user's saved voice is a library voice on a free plan. "Select a voice from
    # the list" would send them looking for a voice that is not there.
    provider = elevenlabs(tmp_path, tier="free")
    with pytest.raises(ValueError) as error:
        provider.resolve_voice("v-library")
    assert "library voice" in str(error.value)
    assert "upgrade" in str(error.value)


def test_a_voice_that_was_never_in_the_account_still_reads_plainly(tmp_path):
    provider = elevenlabs(tmp_path, tier="free")
    with pytest.raises(ValueError) as error:
        provider.resolve_voice("v-somebody-elses")
    assert "Select an ElevenLabs voice from the list." in str(error.value)


def test_speech_status_reads_the_settings_file_once(tmp_path, monkeypatch):
    engine = Speech(tmp_path)
    engine.save_settings(tts_provider="system", stt_provider="whisper")
    reads = []
    real = type(tmp_path).read_text

    def read_text(path, *args, **kwargs):
        reads.append(path.name)
        return real(path, *args, **kwargs)

    monkeypatch.setattr(type(tmp_path), "read_text", read_text)
    for _ in range(5):
        engine.status()
    assert "settings.json" not in reads
    engine.save_settings(tts_provider="kokoro")
    assert engine.status()["tts_provider"] == "kokoro"
    # A new engine reads what the last one saved.
    assert Speech(tmp_path).settings()["tts_provider"] == "kokoro"
