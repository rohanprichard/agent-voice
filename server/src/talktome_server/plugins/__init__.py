"""Install the talktome plugins into agent hosts. The plugin files ship with
this package, so a plugin always matches its server."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from importlib import resources
from pathlib import Path

from .. import paths

HOSTS = ["claude", "codex", "hermes", "openclaw"]

# In a plugin file, this becomes the path of talktome-server, because a hook
# runs with no promise that the command is on PATH.
EXE_PLACEHOLDER = "{{talktome-server}}"

# Codex installs plugins from a marketplace, so the plugin comes in a local
# marketplace of its own.
CODEX_MARKETPLACE = "talktome"
CODEX_PLUGIN = "talktome@" + CODEX_MARKETPLACE
CODEX_HOOK_EVENTS = [
    "session_start",
    "user_prompt_submit",
    "post_tool_use",
    "stop",
    "session_end",
    "permission_request",
]
CODEX_LISTING = {
    "name": CODEX_MARKETPLACE,
    "interface": {"displayName": "talktome"},
    "plugins": [
        {
            "name": "talktome",
            "source": {"source": "local", "path": "./plugins/talktome"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Productivity",
        }
    ],
}

# Hermes reads a global display setting before a platform default, so a user
# with display.tool_progress: all would hear tool progress read aloud. Only the
# keys the user has not set are written.
HERMES_VOICE_DISPLAY = [
    ("tool_progress", "off"),
    ("show_reasoning", "false"),
    ("streaming", "false"),
    ("interim_assistant_messages", "true"),
    ("long_running_notifications", "false"),
    ("busy_ack_detail", "false"),
]

# Where people install agent commands. A shell over SSH often has none of them on PATH.
USER_BIN_DIRS = ["~/.local/bin", "~/.npm-global/bin", "~/.claude/local", "/opt/homebrew/bin", "/usr/local/bin"]


# The earlier talktome app put a skill that runs the `talktome` command in
# each host's skills folder. An agent that finds it tries that command, which
# no longer exists, so installing a plugin removes it.
OLD_SKILL_MARK = "through the local TalkToMe app"


class PluginError(Exception):
    pass


def find(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for folder in USER_BIN_DIRS:
        path = Path(os.path.expanduser(folder)) / name
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def run_host(name: str, *args: str) -> str:
    path = find(name)
    if not path:
        raise PluginError(f"the {name} command was not found")
    done = subprocess.run(
        [path, *args], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120, check=False
    )
    text = (done.stdout + done.stderr).strip()
    if done.returncode != 0:
        raise PluginError(f"{name} {' '.join(args)}: {text or done.returncode}")
    return text


def this_program() -> str:
    """The talktome-server that runs now, so the plugins match it."""
    running = sys.argv[0]
    if os.path.basename(running) == "talktome-server" and os.path.isfile(running):
        return os.path.realpath(running)
    return os.path.realpath(shutil.which("talktome-server") or find("talktome-server") or running)


class Installer:
    def __init__(self, home: Path | None = None, env=os.environ, run=run_host, exe: str | None = None, hook_trust=None):
        self.home = home or Path.home()
        self.env = env
        self.run = run
        self.exe = exe or this_program()
        self.hook_trust = hook_trust or codex_hook_trust

    def host_home(self, host: str) -> Path:
        env_name, folder = {
            "claude": ("CLAUDE_CONFIG_DIR", ".claude"),
            "codex": ("CODEX_HOME", ".codex"),
            "hermes": ("HERMES_HOME", ".hermes"),
            "openclaw": ("OPENCLAW_STATE_DIR", ".openclaw"),
        }[host]
        return Path(self.env.get(env_name) or self.home / folder)

    def target(self, host: str) -> Path:
        home = self.host_home(host)
        return {
            "claude": home / "skills" / "talktome",
            "codex": home / "talktome-plugins" / "plugins" / "talktome",
            "hermes": home / "plugins" / "talktome",
            "openclaw": home / "extensions" / "talktome",
        }[host]

    def detect(self) -> list[dict]:
        """The agent hosts on this machine, and the state of their plugins."""
        found = []
        for host in HOSTS:
            if find(host) or self.host_home(host).is_dir():
                found.append(self.status(host))
        return found

    def install(self, host: str) -> dict:
        # The plugins run this program by its path. uvx runs it from uv's cache,
        # which uv can clear, and the hooks would then point at nothing.
        if "/uv/archive-" in self.exe or "/uv/environments-" in self.exe:
            raise PluginError(
                "talktome-server runs from uv's cache here, which uv can delete. "
                "Install it first with: uv tool install talktome-server"
            )
        home = self.host_home(host)
        if not home.is_dir():
            raise PluginError(f"{host} is not set up for this user: {home} does not exist")
        paths.data_dir(self.env).mkdir(parents=True, exist_ok=True, mode=0o700)
        self._remove_old_skill(host)
        target = self.target(host)
        if host == "openclaw":
            return self._install_openclaw(target)
        if host == "codex":
            return self._install_codex(target)
        shutil.rmtree(target, ignore_errors=True)
        self._copy(host, target)
        if host == "claude":
            return {"host": host, "path": str(target), "next": "Start a new Claude Code session to load the plugin."}
        self.run("hermes", "plugins", "enable", "talktome")
        changed = self._hermes_display()
        return {
            "host": host,
            "path": str(target),
            "config": changed,
            "next": "Restart the Hermes gateway: hermes gateway restart",
        }

    def _remove_old_skill(self, host: str) -> None:
        skill = self.host_home(host) / "skills" / "talktome"
        try:
            old = OLD_SKILL_MARK in (skill / "SKILL.md").read_text(errors="replace")
        except OSError:
            return
        if old and not (skill / ".claude-plugin").exists():
            shutil.rmtree(skill, ignore_errors=True)

    def _hermes_display(self) -> list[str]:
        changed = []
        for key, value in HERMES_VOICE_DISPLAY:
            name = "display.platforms.talktome." + key
            try:
                self.run("hermes", "config", "get", name)
                continue
            except PluginError:
                pass
            self.run("hermes", "config", "set", name, value)
            changed.append(name)
        return changed

    def _install_codex(self, target: Path) -> dict:
        root = target.parent.parent
        self._remove_codex(root)
        self._copy("codex", target)
        listing = root / ".agents" / "plugins"
        listing.mkdir(parents=True, exist_ok=True)
        (listing / "marketplace.json").write_text(json.dumps(CODEX_LISTING, indent=2) + "\n")
        self.run("codex", "plugin", "marketplace", "add", str(root))
        self.run("codex", "plugin", "add", CODEX_PLUGIN)
        return {
            "host": "codex",
            "path": str(target),
            "next": "Codex runs plugin hooks only after you trust them. In a new Codex session, open /hooks "
            "and trust the talktome hooks.",
        }

    def _remove_codex(self, root: Path) -> None:
        for args in (("plugin", "remove", CODEX_PLUGIN), ("plugin", "marketplace", "remove", CODEX_MARKETPLACE)):
            try:
                self.run("codex", *args)
            except PluginError:
                pass
        shutil.rmtree(root, ignore_errors=True)

    # OpenClaw copies the plugin and records it in its own config, so OpenClaw
    # has to install and remove it. A folder deleted behind its back leaves a
    # config entry for a missing plugin, and OpenClaw then refuses to start.
    def _install_openclaw(self, target: Path) -> dict:
        self._remove_openclaw(target)
        with tempfile.TemporaryDirectory(prefix="talktome-openclaw-") as staging:
            source = Path(staging) / "talktome"
            self._copy("openclaw", source)
            self.run("openclaw", "plugins", "install", str(source))
        try:
            self.run("openclaw", "plugins", "enable", "talktome")
        except PluginError:
            pass
        return {
            "host": "openclaw",
            "path": str(target),
            "next": "Restart the OpenClaw gateway: openclaw gateway restart",
        }

    def _remove_openclaw(self, target: Path) -> None:
        if not target.exists():
            return
        try:
            self.run("openclaw", "plugins", "uninstall", "talktome", "--force")
        except PluginError as exc:
            if "not managed" not in str(exc):
                raise
        shutil.rmtree(target, ignore_errors=True)

    def remove(self, host: str) -> dict:
        target = self.target(host)
        if host == "openclaw":
            self._remove_openclaw(target)
        elif host == "codex":
            self._remove_codex(target.parent.parent)
        else:
            if host == "hermes":
                try:
                    self.run("hermes", "plugins", "disable", "talktome")
                except PluginError:
                    pass
            shutil.rmtree(target, ignore_errors=True)
        return {"host": host, "path": str(target)}

    def status(self, host: str) -> dict:
        """Whether the installed plugin is the one in this package."""
        target = self.target(host)
        status = {"host": host, "path": str(target), "installed": target.is_dir(), "current": False}
        if not target.is_dir():
            return status
        status["current"] = all(
            (target / name).is_file() and (target / name).read_bytes() == data for name, data in self._files(host)
        )
        if host == "codex":
            try:
                trust = self.hook_trust()
            except Exception:  # noqa: BLE001 - Codex may be missing or old
                trust = {}
            status["hooks_trusted"] = all(
                trust.get(f"{CODEX_PLUGIN}:plugin.json#hooks[0]:{event}:0:0") == "trusted"
                for event in CODEX_HOOK_EVENTS
            )
        return status

    def _files(self, host: str):
        root = resources.files(__package__) / host

        def walk(node, prefix=""):
            for child in node.iterdir():
                name = prefix + child.name
                if child.is_dir():
                    if child.name != "__pycache__":
                        yield from walk(child, name + "/")
                elif not child.name.endswith(".pyc"):
                    yield name, child.read_bytes().replace(EXE_PLACEHOLDER.encode(), self.exe.encode())

        yield from walk(root)

    def _copy(self, host: str, target: Path) -> None:
        for name, data in self._files(host):
            dest = target / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)


def codex_hook_trust() -> dict[str, str]:
    """Ask `codex app-server` for its hooks, and return the trust status of each by its key."""
    codex = find("codex")
    if not codex:
        return {}
    lines = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "talktome", "version": "1"}},
        },
        {"jsonrpc": "2.0", "method": "initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "hooks/list", "params": {"cwds": [str(Path.home())]}},
    ]
    proc = subprocess.Popen(
        [codex, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
    )
    timer = threading.Timer(20, proc.kill)
    timer.start()
    try:
        proc.stdin.write("".join(json.dumps(line) + "\n" for line in lines))
        proc.stdin.flush()
        for line in proc.stdout:
            try:
                reply = json.loads(line)
            except ValueError:
                continue
            if reply.get("id") == 2:
                return {
                    hook["key"]: hook.get("trustStatus", "")
                    for data in (reply.get("result") or {}).get("data", [])
                    for hook in data.get("hooks", [])
                }
        return {}
    finally:
        timer.cancel()
        proc.kill()
        proc.wait()
