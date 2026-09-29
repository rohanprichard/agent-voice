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
import subprocess
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

    monkeypatch.setattr(entry, "serve", refuse)
    assert entry.main() == 0
    assert ran == ["talktome"]
    # argparse reads this, so the command has to see its own arguments and not the
    # `-m talktome` that carried it there.
    assert sys.argv == ["talktome", "call", "--thread", "t"]


def test_a_module_name_is_not_taken_for_an_option(monkeypatch, entry):
    ran = []
    monkeypatch.setattr(sys, "argv", ["talktome-server", "-m", "talktome.mcp_server"])
    monkeypatch.setattr(runpy, "run_module", lambda name, **k: ran.append(name))
    monkeypatch.setattr(entry, "serve", lambda port: None)
    entry.main()
    assert ran == ["talktome.mcp_server"]


def test_no_arguments_still_starts_the_server(monkeypatch, entry):
    # The app spawns the binary with nothing at all, and that has to keep meaning
    # "serve".
    monkeypatch.setattr(sys, "argv", ["talktome-server"])
    monkeypatch.setenv("TALKTOME_PORT", "8799")
    started = []
    monkeypatch.setattr(entry, "serve", started.append)
    entry.main()
    assert started == [8799]


def test_a_long_option_is_not_mistaken_for_a_module(monkeypatch, entry):
    monkeypatch.setattr(sys, "argv", ["talktome-server", "--selftest"])
    printed = []
    monkeypatch.setattr(entry, "selftest", lambda: printed.append(True))
    monkeypatch.setattr(entry, "serve", lambda port: None)
    entry.main()
    assert printed == [True]


def test_a_command_does_not_load_the_server(tmp_path):
    # Each `talktome call` runs through `-m`. Loading uvicorn and the app first
    # made every command wait for a server it never starts.
    (tmp_path / "probe.py").write_text(
        "import sys\nprint('uvicorn' in sys.modules, 'talktome.app' in sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, str(SERVER), "-m", "probe"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={"PYTHONPATH": str(tmp_path)},
        check=True,
    )
    assert result.stdout.strip() == "False False"
