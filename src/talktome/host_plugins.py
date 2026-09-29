"""Install the TalkToMe plugin into an agent host.

A plugin makes a voice call part of the host itself. The host runs the listen
and reply loop, so the model only answers. The plugin files ship inside this
package, so the plugin and the talktome command stay at the same version.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .agents import find_command

PLUGINS = Path(__file__).resolve().parent / "plugins"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "node_modules")

# A global display setting outranks a platform default in Hermes, so a user with
# `display.tool_progress: all` would hear tool progress lines read aloud. A
# per-platform setting outranks both. Only keys the user has not set are written.
HERMES_VOICE_DISPLAY = {
    "tool_progress": "off",
    "show_reasoning": "false",
    "streaming": "false",
    "interim_assistant_messages": "true",
    "long_running_notifications": "false",
    "busy_ack_detail": "false",
}


def hermes_home(home: Path) -> Path:
    return Path(os.environ.get("HERMES_HOME") or home / ".hermes").expanduser()


def target(agent: str, home: Path) -> Path:
    if agent == "hermes":
        return hermes_home(home) / "plugins" / "talktome"
    raise ValueError(f"There is no TalkToMe plugin for {agent} yet.")


def _host_command(agent: str, run=subprocess.run, *args: str, check=True) -> str | None:
    binary = find_command(agent)
    if not binary:
        return None
    result = run([binary, *args], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    output = (result.stdout + result.stderr).strip()
    if result.returncode:
        if not check:
            return None
        raise ValueError(output or f"`{agent} {' '.join(args)}` failed.")
    return output


def _voice_display(run) -> list[str]:
    written = []
    for key, value in HERMES_VOICE_DISPLAY.items():
        name = f"display.platforms.talktome.{key}"
        if _host_command("hermes", run, "config", "get", name, check=False) is None:
            _host_command("hermes", run, "config", "set", name, value)
            written.append(name)
    return written


def install(agent: str, home: Path, run=subprocess.run) -> dict:
    source = PLUGINS / agent
    if not source.is_dir():
        raise ValueError(f"This install is missing the {agent} plugin.")
    home_dir = hermes_home(home)
    if not home_dir.is_dir():
        raise ValueError(f"{agent} is not set up for this user: {home_dir} does not exist.")
    destination = target(agent, home)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=IGNORE)
    enabled = _host_command(agent, run, "plugins", "enable", "talktome") is not None
    return {
        "agent": agent,
        "path": str(destination),
        "enabled": enabled,
        "config": _voice_display(run) if enabled else [],
        "next": "Restart the Hermes gateway: hermes gateway restart",
    }


def remove(agent: str, home: Path, run=subprocess.run) -> dict:
    destination = target(agent, home)
    if not destination.exists():
        return {"agent": agent, "path": str(destination), "removed": False}
    try:
        _host_command(agent, run, "plugins", "disable", "talktome")
    except ValueError:
        pass
    shutil.rmtree(destination)
    return {"agent": agent, "path": str(destination), "removed": True}


def status(agent: str, home: Path) -> dict:
    destination = target(agent, home)
    source = PLUGINS / agent
    installed = destination.is_dir()
    current = installed and all(
        (destination / path.relative_to(source)).is_file()
        and (destination / path.relative_to(source)).read_bytes() == path.read_bytes()
        for path in source.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    return {"agent": agent, "path": str(destination), "installed": installed, "current": current}
