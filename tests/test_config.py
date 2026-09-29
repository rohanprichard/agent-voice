import os

from talktome.config import announce_server, get_token, server_up
from talktome.speech import Speech


def test_token_is_private_and_persistent(tmp_path, monkeypatch):
    monkeypatch.setenv("TALKTOME_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("TALKTOME_TOKEN", raising=False)
    token = get_token()
    assert len(token) >= 32
    assert get_token() == token
    if os.name != "nt":
        assert (tmp_path / "token").stat().st_mode & 0o777 == 0o600


def test_voice_and_model_settings_survive_restart(tmp_path):
    first = Speech(tmp_path)
    first.save_settings(model_id="small")
    first.save_settings(voice="Samantha")
    second = Speech(tmp_path)
    assert second.saved_model() == "small"
    assert second.saved_voice() == "Samantha"


def test_nothing_is_listening_until_a_server_says_so():
    assert server_up() is False


def test_a_server_that_is_listening_can_be_told_without_the_network():
    # This is the whole point: a sandboxed command gets no answer from the
    # loopback interface, so "is the app up" has to be answerable some other way.
    with announce_server():
        assert server_up() is True
    assert server_up() is False


def test_the_claim_is_dropped_when_the_server_goes_away():
    # The kernel releases the lock when the process ends, so unlike a recorded
    # process id it cannot be left behind by a crash or inherited by a later
    # programme that happens to reuse the number.
    with announce_server():
        pass
    assert server_up() is False


def test_the_lock_file_is_private(tmp_path, monkeypatch):
    monkeypatch.setenv("TALKTOME_DATA_DIR", str(tmp_path))
    with announce_server():
        assert (tmp_path / "server.lock").stat().st_mode & 0o777 == 0o600


def test_asking_whether_the_app_is_up_does_not_try_to_write(tmp_path, monkeypatch):
    """The check has to survive the sandbox it is asked from.

    An agent's command can read the app's folder and not write it. Asking with
    `O_CREAT`, which is how the server takes the lock, failed on a running app and
    reported it closed — the same wrong answer this check was added to stop giving,
    one layer down.
    """
    monkeypatch.setenv("TALKTOME_DATA_DIR", str(tmp_path))
    real_open = os.open
    flags_used = []

    def refuse_to_write(path, flags, *args, **kwargs):
        flags_used.append(flags)
        if flags & (os.O_CREAT | os.O_WRONLY | os.O_RDWR):
            raise PermissionError("read only here")
        return real_open(path, flags, *args, **kwargs)

    with announce_server():
        monkeypatch.setattr(os, "open", refuse_to_write)
        assert server_up() is True
    assert flags_used and all(not (flags & os.O_CREAT) for flags in flags_used)


def test_an_app_that_never_ran_here_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("TALKTOME_DATA_DIR", str(tmp_path / "never-created"))
    assert server_up() is False
