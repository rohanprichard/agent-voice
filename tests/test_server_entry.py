"""The frozen binary is two programs, and the second one is easy to lose.

The bundle has no interpreter inside it, so the same executable that serves the app
is also the `talktome` command an agent runs. Nothing the server imports reaches
`talktome.cli`, so PyInstaller left it out of the archive and `talktome call` ran the
server instead — starting a second copy on a port the app already held. The user
read "address already in use" for a call that was never attempted, and no test could
see it, because every test that runs the command runs it from the checkout.
"""

import importlib.util
import runpy
import sys
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parent.parent / "packaging" / "server.py"


@pytest.fixture
def entry():
    """Load the frozen entry point by path: it is a script, not a module."""
    spec = importlib.util.spec_from_file_location("talktome_server_entry", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_asking_for_a_module_runs_it_instead_of_starting_a_server(monkeypatch, entry):
    # `talktome call` reaches the binary as `-m talktome call`, which is exactly how
    # an interpreter would be asked. Treating it as "start a server" is the whole of
    # the bug.
    ran = []
    monkeypatch.setattr(sys, "argv", ["talktome-server", "-m", "talktome", "call", "--thread", "t"])
    monkeypatch.setattr(runpy, "run_module", lambda name, **k: ran.append(name))

    def refuse(*args, **kwargs):
        raise AssertionError("a request for the command must not start a server")

    monkeypatch.setattr(entry.uvicorn, "run", refuse)
    assert entry.main() == 0
    assert ran == ["talktome"]
    # argparse reads this, so the command has to see its own arguments and not the
    # `-m talktome` that carried it there.
    assert sys.argv == ["talktome", "call", "--thread", "t"]


def test_a_module_name_is_not_taken_for_an_option(monkeypatch, entry):
    ran = []
    monkeypatch.setattr(sys, "argv", ["talktome-server", "-m", "talktome.mcp_server"])
    monkeypatch.setattr(runpy, "run_module", lambda name, **k: ran.append(name))
    monkeypatch.setattr(entry.uvicorn, "run", lambda *a, **k: None)
    entry.main()
    assert ran == ["talktome.mcp_server"]


def test_no_arguments_still_starts_the_server(monkeypatch, entry):
    # The app spawns the binary with nothing at all, and that has to keep meaning
    # "serve".
    monkeypatch.setattr(sys, "argv", ["talktome-server"])
    monkeypatch.setenv("TALKTOME_PORT", "8799")
    started = []

    def run(app, **kwargs):
        started.append(kwargs["port"])

    monkeypatch.setattr(entry.uvicorn, "run", run)
    monkeypatch.setattr(entry, "create_app", lambda: object())
    entry.main()
    assert started == [8799]


def test_a_long_option_is_not_mistaken_for_a_module(monkeypatch, entry):
    monkeypatch.setattr(sys, "argv", ["talktome-server", "--selftest"])
    printed = []
    monkeypatch.setattr(entry, "selftest", lambda: printed.append(True))
    monkeypatch.setattr(entry.uvicorn, "run", lambda *a, **k: None)
    entry.main()
    assert printed == [True]
