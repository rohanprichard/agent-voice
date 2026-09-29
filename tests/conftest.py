"""Guards that keep a test run out of the user's own machine.

An earlier round of tests wrote real files into `~/.local/bin` and
`/opt/homebrew/bin`, and only a manual look noticed: `Path.expanduser()` ignores a
patched `Path.home`, so the redirect everyone assumed was in place was not there
at all. Everything the app treats as local state — the token, the inbox, the
server lock — now lives under `data_dir()`, so pointing that at a temporary folder
is the whole of the protection and it only has to be written once.
"""

import pytest

from talktome import agents, inbox


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    directory = tmp_path / "talktome"
    monkeypatch.setenv("TALKTOME_DATA_DIR", str(directory))
    return directory


@pytest.fixture(autouse=True)
def isolated_shared_inbox(tmp_path, monkeypatch):
    """The fallback half lives in `/tmp`, where a running app is watching.

    Without this a test would leave a real request in the real folder and ring
    whoever has TalkToMe open — which is the same way an earlier round of tests
    wrote a real `talktome` command into the user's own `~/.local/bin`.
    """
    shared = tmp_path / "shared" / "requests"
    monkeypatch.setattr(inbox, "shared", lambda: shared)
    return shared


@pytest.fixture(autouse=True)
def no_real_agent_homes(monkeypatch):
    """Skill targets read these before the home folder.

    An agent host exports its own, so a test run from inside Hermes would install
    and remove the skill in the real `~/.hermes` while the home was a temporary one.
    """
    for name in ("HERMES_HOME", "OPENCLAW_STATE_DIR", "CLAUDE_CONFIG_DIR"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def no_remembered_commands():
    """Nothing looks a command up twice across tests.

    `find_command` keeps what it found, and a real answer from one test would
    decide another test's question about where a command lives.
    """
    agents._FOUND.clear()
    yield
    agents._FOUND.clear()


@pytest.fixture(autouse=True)
def no_smart_turn_download(monkeypatch):
    """Each app start loads Smart Turn, which downloads 8.7 MB into a new data dir."""
    from talktome.smart_turn import SmartTurn

    def setup(self):
        self.state = {"status": "error", "error": "Smart Turn is off in tests."}

    monkeypatch.setattr(SmartTurn, "setup", setup)
