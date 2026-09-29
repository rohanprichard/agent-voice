"""A user service that keeps `talktome remote-up` running on the server.

Linux gets a systemd user unit and macOS gets a launchd agent. The service runs
this interpreter by absolute path, so it finds the same install that wrote it.
"""

from __future__ import annotations

import getpass
import os
import plistlib
import shlex
import subprocess
import sys
from pathlib import Path

UNIT_NAME = "talktome-remote.service"
LAUNCHD_LABEL = "com.rohanprichard.talktome.remote"
# The service must see the same private folders as the agent's commands.
PASSED_ENV = ("TALKTOME_DATA_DIR", "TALKTOME_REMOTE_DIR", "TALKTOME_RELAY_FILE")


class ServiceError(RuntimeError):
    pass


def service_command(relay_file: str | None = None) -> list[str]:
    command = [sys.executable, "-m", "talktome", "remote-up"]
    if relay_file:
        command += ["--relay-file", str(Path(relay_file).expanduser().resolve())]
    return command


def service_env(environ=os.environ) -> dict:
    return {key: environ[key] for key in PASSED_ENV if environ.get(key)}


def _systemd_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def systemd_unit(command: list[str], env: dict) -> str:
    lines = [
        "[Unit]",
        "Description=TalkToMe remote bridge (relay and daemon)",
        "After=network-online.target",
        "",
        "[Service]",
        "ExecStart=" + " ".join(_systemd_quote(part).replace("$", "$$") for part in command),
        *(f"Environment={_systemd_quote(f'{key}={value}')}" for key, value in sorted(env.items())),
        # remote-up exits 0 when the relay revokes its pair, and a later
        # remote-init --replace needs it to start again with the new pair.
        "Restart=always",
        "RestartSec=5",
        "",
        "[Install]",
        "WantedBy=default.target",
        "",
    ]
    return "\n".join(lines)


def launchd_plist(label: str, command: list[str], env: dict, log: Path) -> bytes:
    document = {
        "Label": label,
        "ProgramArguments": command,
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 5,
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
    }
    if env:
        document["EnvironmentVariables"] = env
    return plistlib.dumps(document)


def unit_path(home: Path) -> Path:
    return home / ".config" / "systemd" / "user" / UNIT_NAME


def plist_path(home: Path, label: str = LAUNCHD_LABEL) -> Path:
    return home / "Library" / "LaunchAgents" / f"{label}.plist"


def _run(run, command: list[str], check: bool = True):
    result = run(command, capture_output=True, text=True)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ServiceError(f"`{shlex.join(command)}` failed: {detail}")
    return result


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def install(
    command: list[str],
    env: dict,
    *,
    home: Path,
    log: Path,
    platform: str = sys.platform,
    label: str = LAUNCHD_LABEL,
    run=subprocess.run,
) -> list[str]:
    """Write and start the service. Return notes for the person."""
    if platform.startswith("linux"):
        _write(unit_path(home), systemd_unit(command, env).encode())
        _run(run, ["systemctl", "--user", "daemon-reload"])
        _run(run, ["systemctl", "--user", "enable", UNIT_NAME])
        # Restart, not start, so a second install picks up a new pair.
        _run(run, ["systemctl", "--user", "restart", UNIT_NAME])
        notes = [f"Installed and started {unit_path(home)}."]
        user = getpass.getuser()
        linger = _run(run, ["loginctl", "show-user", user, "--property=Linger"], check=False)
        if "Linger=yes" not in (linger.stdout or ""):
            notes.append(
                "User services stop when you log out. To keep this one running, "
                f"run: sudo loginctl enable-linger {user}"
            )
        return notes
    if platform == "darwin":
        path = plist_path(home, label)
        _write(path, launchd_plist(label, command, env, log))
        domain = f"gui/{os.getuid()}"
        _run(run, ["launchctl", "bootout", f"{domain}/{label}"], check=False)
        _run(run, ["launchctl", "bootstrap", domain, str(path)])
        return [
            f"Installed and started {path}.",
            "A launchd agent runs while you are logged in, and starts again at login.",
        ]
    raise ServiceError(f"remote-service supports Linux and macOS, not {platform}.")


def remove(*, home: Path, platform: str = sys.platform, label: str = LAUNCHD_LABEL, run=subprocess.run) -> bool:
    if platform.startswith("linux"):
        path = unit_path(home)
        _run(run, ["systemctl", "--user", "disable", "--now", UNIT_NAME], check=False)
        existed = path.exists()
        path.unlink(missing_ok=True)
        _run(run, ["systemctl", "--user", "daemon-reload"], check=False)
        return existed
    if platform == "darwin":
        path = plist_path(home, label)
        _run(run, ["launchctl", "bootout", f"gui/{os.getuid()}/{label}"], check=False)
        existed = path.exists()
        path.unlink(missing_ok=True)
        return existed
    raise ServiceError(f"remote-service supports Linux and macOS, not {platform}.")


def status(*, home: Path, platform: str = sys.platform, label: str = LAUNCHD_LABEL, run=subprocess.run) -> dict:
    if platform.startswith("linux"):
        path = unit_path(home)
        active = _run(run, ["systemctl", "--user", "is-active", UNIT_NAME], check=False)
        return {"file": str(path), "installed": path.exists(), "state": (active.stdout or "").strip() or "unknown"}
    if platform == "darwin":
        path = plist_path(home, label)
        result = _run(run, ["launchctl", "print", f"gui/{os.getuid()}/{label}"], check=False)
        state = "not loaded"
        if result.returncode == 0:
            state = "loaded"
            for line in (result.stdout or "").splitlines():
                if line.strip().startswith("state = "):
                    state = line.split("=", 1)[1].strip()
                    break
        return {"file": str(path), "installed": path.exists(), "state": state}
    raise ServiceError(f"remote-service supports Linux and macOS, not {platform}.")
