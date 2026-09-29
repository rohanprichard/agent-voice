"""The SSH path of the remote bridge, with a fake ssh that runs on this machine."""

import asyncio
import json
import os
import plistlib
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from talktome.remote import config as remote_config
from talktome.remote import protocol, service
from talktome.remote.connector import RemoteConnector
from talktome.remote.relay import RelayStore
from talktome.remote.tunnel import SSHTunnel, explain

FAKE_SSH = Path(__file__).with_name("fake_ssh.py")
TALKTOME = f"{sys.executable} -m talktome"


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie still answers kill 0. ps shows whether it is one.
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False).stdout
    return bool(state.strip()) and not state.strip().startswith("Z")


def wait_until(check, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return False


def listening(port):
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", port)) == 0


def children(pid):
    found = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True, check=False).stdout
    return [int(line) for line in found.split()]


@pytest.fixture
def fake_ssh(tmp_path):
    folder = tmp_path / "bin"
    folder.mkdir()
    script = folder / "ssh"
    script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_SSH}" "$@"\n')
    script.chmod(0o755)
    return script


@pytest.fixture
def server(tmp_path, fake_ssh):
    """Two data folders, and a fake ssh that runs commands as the server."""
    server_dir = tmp_path / "server"
    env_file = tmp_path / "server-env.json"
    env_file.write_text(json.dumps({"TALKTOME_DATA_DIR": str(server_dir), "HOME": str(tmp_path / "server-home")}))
    laptop_dir = tmp_path / "laptop"
    env = {
        **os.environ,
        "PATH": f"{fake_ssh.parent}:{os.environ['PATH']}",
        "TALKTOME_DATA_DIR": str(laptop_dir),
        "FAKE_SSH_ENV": str(env_file),
        "FAKE_SSH_LOG": str(tmp_path / "ssh.log"),
    }
    return {"dir": server_dir, "laptop": laptop_dir, "env": env, "log": tmp_path / "ssh.log"}


def talktome(env, *args, **kwargs):
    return subprocess.run(
        [sys.executable, "-m", "talktome", *args], env=env, capture_output=True, text=True, timeout=60, check=False, **kwargs
    )


def laptop_config(server):
    return json.loads((server["laptop"] / remote_config.LAPTOP_FILE).read_text())


def test_remote_connect_pairs_the_laptop_without_showing_the_credential(server):
    port = free_port()
    result = talktome(
        server["env"], "remote-connect", "me@server", "--remote-command", TALKTOME, "--relay-port", str(port)
    )
    assert result.returncode == 0, result.stderr
    saved = laptop_config(server)
    assert saved["relay"] == f"ws://127.0.0.1:{port}/v1/relay"
    assert saved["ssh"] == {"target": "me@server", "port": None, "remote_port": port}
    assert saved["credential"].startswith("ttlaptop_")
    assert saved["credential"] not in result.stdout + result.stderr
    assert "Restart TalkToMe" in result.stderr
    assert "remote-up" in result.stderr

    agent = json.loads((server["dir"] / remote_config.AGENT_FILE).read_text())
    assert agent["pair"] == saved["pair"]
    assert agent["relay"] == f"ws://127.0.0.1:{port}/v1/relay"
    store = RelayStore(server["dir"] / "relay" / "relay.json")
    assert store.authenticate(saved["pair"], "laptop", saved["credential"])

    # The credential crossed only as ssh output, never as an argument.
    for line in server["log"].read_text().splitlines():
        assert saved["credential"] not in line


def test_remote_connect_refuses_a_configured_server_and_replace_revokes_the_old_pair(server):
    port = str(free_port())
    first = talktome(server["env"], "remote-connect", "me@server", "--remote-command", TALKTOME, "--relay-port", port)
    assert first.returncode == 0, first.stderr
    old = laptop_config(server)

    again = talktome(server["env"], "remote-connect", "me@server", "--remote-command", TALKTOME, "--relay-port", port)
    assert again.returncode == 1
    assert "--replace" in again.stderr
    assert f"relay-revoke --pair {old['pair']}" in again.stderr
    assert laptop_config(server) == old

    replaced = talktome(
        server["env"], "remote-connect", "me@server", "--remote-command", TALKTOME, "--relay-port", port, "--replace"
    )
    assert replaced.returncode == 0, replaced.stderr
    new = laptop_config(server)
    assert new["pair"] != old["pair"]
    store = RelayStore(server["dir"] / "relay" / "relay.json")
    assert not store.authenticate(old["pair"], "laptop", old["credential"])
    assert store.authenticate(new["pair"], "laptop", new["credential"])
    assert new["credential"] not in replaced.stdout + replaced.stderr


def test_remote_connect_explains_a_missing_talktome(server):
    result = talktome(server["env"], "remote-connect", "me@server", "--remote-command", "/nonexistent/talktome")
    assert result.returncode == 1
    assert "--remote-command" in result.stderr
    assert not (server["laptop"] / remote_config.LAPTOP_FILE).exists()


def test_remote_connect_refuses_an_option_as_target(server):
    result = talktome(server["env"], "remote-connect", "-oProxyCommand=evil")
    assert result.returncode != 0
    assert not server["log"].exists()


def test_remote_remove_revokes_the_pair(tmp_path):
    env = {**os.environ, "TALKTOME_DATA_DIR": str(tmp_path / "server")}
    assert talktome(env, "remote-init", "--json", "--relay-port", str(free_port())).returncode == 0
    pair = json.loads((tmp_path / "server" / remote_config.AGENT_FILE).read_text())["pair"]
    removed = talktome(env, "remote-remove")
    assert json.loads(removed.stdout) == {"removed": True, "pair": pair, "revoked": True}
    assert RelayStore(tmp_path / "server" / "relay" / "relay.json").revoked(pair)


def test_remote_init_puts_the_port_in_the_relay_url(tmp_path):
    env = {**os.environ, "TALKTOME_DATA_DIR": str(tmp_path / "server")}
    result = talktome(env, "remote-init", "--relay", "ws://localhost", "--relay-port", "8771", "--ssh-host", "me@box")
    assert result.returncode == 0, result.stderr
    agent = json.loads((tmp_path / "server" / remote_config.AGENT_FILE).read_text())
    assert agent["relay"] == "ws://127.0.0.1:8771/v1/relay"
    assert "--relay ws://127.0.0.1:8771/v1/relay" in result.stdout
    assert "--ssh-host me@box" in result.stdout


def test_remote_init_refuses_an_ipv6_loopback_relay(tmp_path):
    env = {**os.environ, "TALKTOME_DATA_DIR": str(tmp_path / "server")}
    result = talktome(env, "remote-init", "--relay", "ws://[::1]:8771")
    assert result.returncode == 1
    assert "127.0.0.1" in result.stderr
    assert not (tmp_path / "server" / remote_config.AGENT_FILE).exists()


def test_remote_init_names_the_relay_step_for_wss(tmp_path):
    env = {**os.environ, "TALKTOME_DATA_DIR": str(tmp_path / "server")}
    result = talktome(env, "remote-init", "--relay", "wss://relay.example.com")
    assert result.returncode == 0, result.stderr
    assert "talktome relay-serve" in result.stdout
    assert "talktome remote-daemon" in result.stdout
    assert "--ssh-host" not in result.stdout


def test_connector_setup_can_save_an_ssh_target(tmp_path):
    pair = RelayStore(tmp_path / "relay.json").create_pair()
    env = {**os.environ, "TALKTOME_DATA_DIR": str(tmp_path / "laptop")}
    result = talktome(
        env, "connector-setup", "--relay", "ws://127.0.0.1:8772", "--pair", pair["pair"],
        "--ssh-host", "me@box", "--ssh-port", "2222", "--credential-stdin",
        input=pair["laptop_credential"],
    )
    assert result.returncode == 0, result.stderr
    saved = json.loads((tmp_path / "laptop" / remote_config.LAPTOP_FILE).read_text())
    assert saved["ssh"] == {"target": "me@box", "port": 2222, "remote_port": 8772}


def test_an_ssh_target_needs_a_loopback_relay(tmp_path):
    pair = RelayStore(tmp_path / "relay.json").create_pair()
    with pytest.raises(remote_config.RemoteConfigError):
        remote_config.save_laptop_config(
            "wss://relay.example.com", pair["pair"], pair["laptop_credential"],
            ssh={"target": "me@box", "remote_port": 8766},
        )
    with pytest.raises(remote_config.RemoteConfigError):
        remote_config.ssh_settings("-oProxyCommand=x", 8766)
    loaded_without = remote_config.save_laptop_config(
        "wss://relay.example.com", pair["pair"], pair["laptop_credential"]
    )
    assert "ssh" not in loaded_without
    assert "ssh" not in remote_config.load_laptop_config()


def test_thread_ids_allow_openclaw_session_keys():
    for key in (
        "agent:main:whatsapp:direct:+15551234567",
        "agent:main:whatsapp:group:123@g.us",
        "agent:main:matrix:channel:!room:example.org",
    ):
        assert protocol._thread(key) == key
    for bad in ("has space", "tab\there", "bell\x07", "x" * (protocol.MAX_THREAD + 1)):
        with pytest.raises(protocol.ProtocolError):
            protocol._thread(bad)


async def echo_server():
    async def echo(reader, writer):
        while data := await reader.read(1024):
            writer.write(data)
            await writer.drain()
        writer.close()

    return await asyncio.start_server(echo, "127.0.0.1", 0)


async def through(port, text=b"hello"):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(text)
    await writer.drain()
    answer = await asyncio.wait_for(reader.read(len(text)), 5)
    writer.close()
    return answer


def ssh_pids(log):
    if not log.exists():
        return []
    return [json.loads(line)["pid"] for line in log.read_text().splitlines()]


async def wait_for(check, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        await asyncio.sleep(0.05)
    return False


async def test_tunnel_starts_restarts_after_ssh_exits_and_stops(tmp_path, fake_ssh, monkeypatch):
    log = tmp_path / "ssh.log"
    monkeypatch.setenv("FAKE_SSH_LOG", str(log))
    monkeypatch.setattr("talktome.remote.tunnel.MIN_BACKOFF", 0.1)
    relay = await echo_server()
    remote_port = relay.sockets[0].getsockname()[1]
    tunnel = SSHTunnel("me@server", remote_port, free_port(), ssh=str(fake_ssh))
    task = asyncio.create_task(tunnel.run())
    try:
        await asyncio.wait_for(tunnel.ready.wait(), 10)
        assert tunnel.status()["state"] == "up"
        assert await through(tunnel.local_port) == b"hello"
        argv = json.loads(log.read_text().splitlines()[0])["argv"]
        for option in ("BatchMode=yes", "ExitOnForwardFailure=yes", "ServerAliveInterval=15", "ServerAliveCountMax=3"):
            assert option in argv
        assert f"127.0.0.1:{tunnel.local_port}:127.0.0.1:{remote_port}" in argv

        # ssh exits, as after a laptop sleep. The tunnel starts it again.
        first = ssh_pids(log)[0]
        os.kill(first, signal.SIGKILL)
        assert await wait_for(lambda: len(ssh_pids(log)) == 2)
        await asyncio.wait_for(tunnel.ready.wait(), 10)
        assert tunnel.starts == 2
        assert await through(tunnel.local_port) == b"hello"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        relay.close()
    assert tunnel.status()["state"] == "stopped"
    assert await wait_for(lambda: not any(alive(pid) for pid in ssh_pids(log)))


async def test_tunnel_moves_to_a_free_port_when_its_port_is_busy(tmp_path, fake_ssh):
    relay = await echo_server()
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen()
    wanted = busy.getsockname()[1]
    tunnel = SSHTunnel("me@server", relay.sockets[0].getsockname()[1], wanted, ssh=str(fake_ssh))
    task = asyncio.create_task(tunnel.run())
    try:
        await asyncio.wait_for(tunnel.ready.wait(), 10)
        assert tunnel.local_port != wanted
        assert await through(tunnel.local_port) == b"hello"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        relay.close()
        busy.close()


async def test_tunnel_reports_a_key_failure(tmp_path, fake_ssh, monkeypatch):
    monkeypatch.setenv("FAKE_SSH_FAIL", "auth")
    tunnel = SSHTunnel("me@server", free_port(), free_port(), ssh=str(fake_ssh))
    task = asyncio.create_task(tunnel.run())
    try:
        assert await wait_for(lambda: tunnel.error is not None)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert "could not log in to me@server with a key" in tunnel.error
    assert "ssh me@server" in tunnel.error


def test_explain_names_the_host_key_problem():
    assert "accept the key" in explain("me@box", ["Host key verification failed."])
    assert "stopped: ssh: connect to host box port 22: Connection refused" in explain(
        "me@box", ["ssh: connect to host box port 22: Connection refused"]
    )


class NoManaged:
    adapter = None
    ring = None


async def test_connector_opens_the_tunnel_first_and_reports_it(tmp_path, fake_ssh, monkeypatch):
    monkeypatch.setenv("FAKE_SSH_FAIL", "auth")
    pair = RelayStore(tmp_path / "relay.json").create_pair()
    config = {
        "pair": pair["pair"],
        "relay": "ws://127.0.0.1:8770/v1/relay",
        "credential": pair["laptop_credential"],
        "ssh": {"target": "me@server", "port": None, "remote_port": 8770},
    }
    connector = RemoteConnector(NoManaged(), config, journal_path=tmp_path / "journal.json")
    connector.tunnel.ssh = str(fake_ssh)
    task = asyncio.create_task(connector.run())
    try:
        assert await wait_for(lambda: connector.tunnel.error is not None)
        status = connector.status()
        assert status["connection"] == "waiting for tunnel"
        assert "could not log in" in status["tunnel"]["error"]
        assert pair["laptop_credential"] not in json.dumps(status)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert connector.tunnel.status()["state"] == "stopped"


TUNNEL_CHILD = """
import asyncio, sys
from talktome.remote.tunnel import SSHTunnel

async def main():
    tunnel = SSHTunnel("me@server", int(sys.argv[2]), int(sys.argv[3]), ssh=sys.argv[1])
    asyncio.create_task(tunnel.run())
    await tunnel.ready.wait()
    print("ready", flush=True)
    await asyncio.sleep(3600)

asyncio.run(main())
"""


def test_a_killed_app_leaves_no_ssh_behind(tmp_path, fake_ssh):
    log = tmp_path / "ssh.log"
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    env = {**os.environ, "FAKE_SSH_LOG": str(log)}
    app = subprocess.Popen(
        [sys.executable, "-c", TUNNEL_CHILD, str(fake_ssh), str(listener.getsockname()[1]), str(free_port())],
        env=env, stdout=subprocess.PIPE, text=True,
    )
    try:
        assert app.stdout.readline().strip() == "ready"
        pid = ssh_pids(log)[0]
        assert alive(pid)
        # SIGKILL runs no cleanup at all. The watchdog sees its pipe close.
        app.kill()
        app.wait()
        assert wait_until(lambda: not alive(pid))
    finally:
        if app.poll() is None:
            app.kill()
        listener.close()


def remote_up(tmp_path):
    env = {**os.environ, "TALKTOME_DATA_DIR": str(tmp_path / "server")}
    port = free_port()
    assert talktome(env, "remote-init", "--json", "--relay-port", str(port)).returncode == 0
    process = subprocess.Popen(
        [sys.executable, "-m", "talktome", "remote-up"], env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    assert wait_until(lambda: children(process.pid)), "remote-up started no relay"
    relay = children(process.pid)[0]
    assert wait_until(lambda: listening(port))
    # remote-up checks its relay once after 1.5 s, before it watches it.
    time.sleep(2)
    return process, relay


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGHUP])
def test_remote_up_stops_its_relay_when_it_is_signalled(tmp_path, signum):
    process, relay = remote_up(tmp_path)
    try:
        process.send_signal(signum)
        assert process.wait(15) == 0
        assert wait_until(lambda: not alive(relay))
    finally:
        if process.poll() is None:
            process.kill()


def test_remote_up_stops_its_relay_on_an_interrupt_during_the_start_wait(tmp_path):
    env = {**os.environ, "TALKTOME_DATA_DIR": str(tmp_path / "server")}
    assert talktome(env, "remote-init", "--json", "--relay-port", str(free_port())).returncode == 0
    process = subprocess.Popen(
        [sys.executable, "-m", "talktome", "remote-up"], env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        assert wait_until(lambda: children(process.pid))
        relay = children(process.pid)[0]
        process.send_signal(signal.SIGINT)
        process.wait(15)
        assert wait_until(lambda: not alive(relay))
    finally:
        if process.poll() is None:
            process.kill()


def test_remote_up_starts_its_relay_again_when_it_dies(tmp_path):
    process, relay = remote_up(tmp_path)
    try:
        os.kill(relay, signal.SIGKILL)
        assert wait_until(lambda: [pid for pid in children(process.pid) if pid != relay and alive(pid)], 15)
    finally:
        process.terminate()
        process.wait(15)
    assert not [pid for pid in children(process.pid) if alive(pid)]


def test_systemd_unit_runs_this_python_and_keeps_the_environment():
    unit = service.systemd_unit(
        ["/opt/py 3/bin/python", "-m", "talktome", "remote-up"], {"TALKTOME_DATA_DIR": "/srv/tt"}
    )
    assert 'ExecStart="/opt/py 3/bin/python" "-m" "talktome" "remote-up"' in unit
    assert 'Environment="TALKTOME_DATA_DIR=/srv/tt"' in unit
    assert "Restart=always" in unit
    assert "WantedBy=default.target" in unit


def test_launchd_plist_runs_this_python_and_keeps_the_environment(tmp_path):
    document = plistlib.loads(
        service.launchd_plist("x.test", [sys.executable, "-m", "talktome", "remote-up"], {"A": "b"}, tmp_path / "log")
    )
    assert document["ProgramArguments"] == [sys.executable, "-m", "talktome", "remote-up"]
    assert document["KeepAlive"] is True
    assert document["RunAtLoad"] is True
    assert document["EnvironmentVariables"] == {"A": "b"}


def test_service_command_uses_the_absolute_interpreter():
    command = service.service_command()
    assert Path(command[0]).is_absolute()
    assert command[1:] == ["-m", "talktome", "remote-up"]


class Recorder:
    def __init__(self, outputs=None):
        self.calls = []
        self.outputs = outputs or {}

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        stdout = next((out for key, out in self.outputs.items() if key in command), "")
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


def test_linux_install_enables_the_unit_and_names_linger(tmp_path):
    run = Recorder({"loginctl": "Linger=no\n"})
    notes = service.install(["/py", "-m", "talktome", "remote-up"], {}, home=tmp_path, log=tmp_path / "log",
                            platform="linux", run=run)
    assert (tmp_path / ".config/systemd/user/talktome-remote.service").is_file()
    assert ["systemctl", "--user", "enable", "talktome-remote.service"] in run.calls
    assert ["systemctl", "--user", "restart", "talktome-remote.service"] in run.calls
    assert any("enable-linger" in note for note in notes)

    run = Recorder({"loginctl": "Linger=yes\n"})
    notes = service.install(["/py"], {}, home=tmp_path, log=tmp_path / "log", platform="linux", run=run)
    assert not any("enable-linger" in note for note in notes)

    assert service.remove(home=tmp_path, platform="linux", run=Recorder()) is True
    assert not (tmp_path / ".config/systemd/user/talktome-remote.service").exists()


def test_macos_install_bootstraps_the_agent(tmp_path):
    run = Recorder()
    service.install(["/py"], {}, home=tmp_path, log=tmp_path / "log", platform="darwin", label="x.test", run=run)
    path = tmp_path / "Library/LaunchAgents/x.test.plist"
    assert path.is_file()
    assert ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)] in run.calls
    assert service.remove(home=tmp_path, platform="darwin", label="x.test", run=run) is True
    assert not path.exists()
