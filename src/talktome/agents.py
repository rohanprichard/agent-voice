"""Install the TalkToMe skill and the `talktome` command for an agent to use.

The skill teaches an agent that `talktome call` exists, and the command is what
it runs. The two install together, because either one alone installs nothing.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path


def same_python(configured, expected) -> bool:
    """Compare interpreter paths, which can be spelled differently.

    `python` and `python3` inside one virtual environment are the same
    interpreter even though the strings differ. Comparing the text reported an
    installed command as absent.
    """
    if not isinstance(configured, str) or not expected:
        return False
    try:
        return Path(configured).resolve() == Path(expected).resolve()
    except OSError:
        return False


SKILL_DIR = "talktome"


def skill_source() -> Path:
    """Find the skill in the frozen app, Python package, or repository."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        bundled = Path(frozen_root) / "skills" / SKILL_DIR / "SKILL.md"
        if bundled.is_file():
            return bundled
    packaged = Path(__file__).resolve().parent / "skills" / SKILL_DIR / "SKILL.md"
    if packaged.is_file():
        return packaged
    return Path(__file__).resolve().parents[2] / "skills" / SKILL_DIR / "SKILL.md"


def skill_target(home: Path) -> Path:
    return home / ".codex" / "skills" / SKILL_DIR / "SKILL.md"


def skill_targets(home: Path) -> dict[str, Path]:
    """Find skill targets for Codex and existing host profiles."""
    targets = {"codex": skill_target(home)}
    hermes_home = Path(os.environ.get("HERMES_HOME") or home / ".hermes").expanduser()
    if hermes_home.is_dir():
        targets["hermes"] = hermes_home / "skills" / SKILL_DIR / "SKILL.md"
    openclaw_home = Path(os.environ.get("OPENCLAW_STATE_DIR") or home / ".openclaw").expanduser()
    if openclaw_home.is_dir():
        targets["openclaw"] = openclaw_home / "skills" / SKILL_DIR / "SKILL.md"
    claude_home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude").expanduser()
    if claude_home.is_dir():
        targets["claude"] = claude_home / "skills" / SKILL_DIR / "SKILL.md"
    return targets


def _skill_current(target: Path) -> bool:
    try:
        return target.read_text(encoding="utf-8") == skill_source().read_text(encoding="utf-8")
    except OSError:
        return False


def skill_installed(home: Path) -> bool:
    """Whether the installed copy is the current one, not merely present.

    Comparing the text means an edited skill is offered again rather than sitting
    stale, which is the failure that matters: an agent following outdated
    instructions is worse than one with none.
    """
    return all(_skill_current(target) for target in skill_targets(home).values())


# Where a command can live and still be found by whatever shell an agent runs in.
# The first one that is on PATH and writable wins.
COMMAND_DIRS = ("~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin")

# The folder the desktop app can write into after an administrator prompt. On a
# Mac without Homebrew it is on PATH through /etc/paths but belongs to root.
SYSTEM_COMMAND_DIR = "/usr/local/bin"


APP_ID = "com.rohanprichard.talktome"
SERVER_IN_APP = "Contents/Resources/talktome-server/talktome-server"
APP_FOLDERS = ("/Applications/TalkToMe.app", "$HOME/Applications/TalkToMe.app")


# A login shell can take seconds, so its answer is kept for a short time. The
# time is short so that a folder the user adds to PATH is found without a restart.
LOGIN_PATH_TTL = 60
_LOGIN_PATH: dict[tuple[str, str], tuple[float, str]] = {}


def login_path(run=subprocess.run) -> str:
    """What the user's own shell searches.

    A GUI-launched app inherits launchd's PATH, which is `/usr/bin:/bin:/usr/sbin:
    /sbin` and has none of the places a command like this belongs. The agent that
    will run the command has the user's *terminal* PATH, so the login shell is the
    only thing that can answer where the command will actually be found. The app's
    own environment reported that nowhere was suitable, which was true of the app
    and false of the machine.
    """
    shell = os.environ.get("SHELL") or "/bin/zsh"
    # Only the real runner is cached, so tests can inject their own. A failed
    # answer is never cached.
    key = (shell, os.environ.get("PATH", ""))
    cached = _LOGIN_PATH.get(key)
    if cached and run is subprocess.run and time.monotonic() - cached[0] < LOGIN_PATH_TTL:
        return cached[1]
    try:
        result = run(
            [shell, "-lic", "echo $PATH"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return os.environ.get("PATH", "")
    if result.returncode != 0:
        return os.environ.get("PATH", "")
    lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    if not lines:
        return os.environ.get("PATH", "")
    if run is subprocess.run:
        _LOGIN_PATH[key] = (time.monotonic(), lines[-1])
    return lines[-1]


# Commands already located, kept because finding one can cost a login shell. Only
# hits are kept: a miss is asked again each time, so installing Codex while the app
# is open is noticed rather than remembered as absent for the life of the process.
_FOUND: dict[str, str] = {}


def find_command(name: str, run=subprocess.run) -> str | None:
    """Where a command the *user* installed actually is.

    `shutil.which` searches this process's PATH, and a packaged app is started by
    Finder, so it inherits launchd's PATH — `/usr/bin:/bin:/usr/sbin:/sbin`, with
    none of the places a person installs things. The app therefore reported that
    Codex was "not installed" while the user sat looking at a Codex session, and
    refused every spoken message for a reason that was not true.

    The login shell is the only thing that knows where the user's commands are,
    and it is the same answer `install_command` already relies on to decide where
    the `talktome` command can go.
    """
    if name in _FOUND:
        return _FOUND[name]
    found = shutil.which(name) or shutil.which(name, path=login_path(run))
    if found:
        _FOUND[name] = found
    return found


def command_dirs(path_env: str) -> list[Path]:
    """Directories that are both on PATH and ours to write into."""
    on_path = [Path(entry).expanduser() for entry in path_env.split(":") if entry.strip()]
    wanted = [Path(pattern).expanduser() for pattern in COMMAND_DIRS]
    return [directory for directory in wanted if directory in on_path]


def writable(directory: Path) -> bool:
    """Whether a folder can be written, or made, without an administrator."""
    probe = directory
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return os.access(probe, os.W_OK)


def app_bundle(python: str) -> str | None:
    """The .app folder around a frozen server, or None for a checkout."""
    suffix = "/" + SERVER_IN_APP
    return python[: -len(suffix)] if python.endswith(suffix) else None


def temporary_copy(python: str, launcher: str | None = None) -> bool:
    """Whether this app runs from a place that goes away.

    A mounted disk image is gone after it is ejected. macOS runs an app opened
    from Downloads from a random, read-only copy that is gone after it quits.
    A checkout on an external disk is left alone, because only a developer has one.
    """
    if any("/AppTranslocation/" in (path or "") for path in (python, launcher)):
        return True
    return (app_bundle(python) or "").startswith("/Volumes/")


def command_script(python: str, launcher: str | None = None, apps=APP_FOLDERS) -> str:
    """The text of the `talktome` shim.

    A checkout points at its own interpreter. A packaged app is looked up each
    time the command runs, because a path written at install time breaks as soon
    as the user moves the app.
    """
    lines = ["#!/bin/sh", "# Written by TalkToMe so an agent can run `talktome call`."]
    if not app_bundle(python):
        if launcher:
            # So the command can open the app itself when it is closed. An agent
            # that can only reach the user while the app is already open is not
            # much of a reach, and only the app knows how it wants to be started.
            lines.append(f"export TALKTOME_LAUNCH={shlex.quote(launcher)}")
        # Quoted for the shell, so a path with `$`, `"`, or a space still runs.
        lines.append(f'exec {shlex.quote(python)} -m talktome "$@"')
        return "\n".join(lines) + "\n"
    folders = " ".join(f'"{folder}"' for folder in apps)
    lines += [
        "# It finds the app each time it runs, so it keeps working after the app moves.",
        f'server="{SERVER_IN_APP}"',
        "app=",
        f"for candidate in {folders}; do",
        '  if [ -x "$candidate/$server" ]; then app=$candidate; break; fi',
        "done",
        'if [ -z "$app" ]; then',
        f"  app=$(mdfind \"kMDItemCFBundleIdentifier == '{APP_ID}'\" 2>/dev/null |",
        "    grep -v -e /AppTranslocation/ -e '^/Volumes/' | while IFS= read -r candidate; do",
        '      if [ -x "$candidate/$server" ]; then echo "$candidate"; break; fi',
        "    done)",
        "fi",
        'if [ -z "$app" ]; then',
        '  echo "TalkToMe was not found. Move TalkToMe to the Applications folder, then try again." >&2',
        "  exit 1",
        "fi",
        'export TALKTOME_LAUNCH="open -g -a \\"$app\\""',
        'exec "$app/$server" -m talktome "$@"',
    ]
    return "\n".join(lines) + "\n"


def install_command(
    home: Path, python: str, path_env: str | None = None, launcher: str | None = None
) -> Path:
    """Put `talktome` where an agent's shell will find it.

    The skill tells an agent to run `talktome call`. Installing the skill without
    this leaves the instruction pointing at a command that is only in the app's own
    virtual environment, which no terminal has on its PATH: the two are one feature
    and installing either alone installs nothing.
    """
    if temporary_copy(python, launcher):
        raise ValueError("Move TalkToMe to Applications first, then install the command.")
    on_path = command_dirs(path_env if path_env is not None else login_path())
    script = command_script(python, launcher)
    directories = [directory for directory in on_path if writable(directory)]
    if not directories and Path(SYSTEM_COMMAND_DIR) in on_path:
        # The desktop app writes the same script there after an administrator
        # prompt. commandScript in desktop/install.cjs builds it.
        raise ValueError(
            f"Your shell only searches {SYSTEM_COMMAND_DIR}, and that folder needs an "
            "administrator. Choose Install for all users, or add this line to "
            '~/.zshrc and install again:\n    export PATH="$HOME/.local/bin:$PATH"'
        )
    if not directories:
        fallback = Path("~/.local/bin").expanduser()
        try:
            fallback.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError(f"There is nowhere to put the talktome command. {exc}") from None
        raise ValueError(
            "Your shell does not search ~/.local/bin, /opt/homebrew/bin, or "
            "/usr/local/bin, so the command has nowhere to go that your agent would "
            "find it. Add this line to ~/.zshrc, then install again:\n"
            '    export PATH="$HOME/.local/bin:$PATH"'
        )
    target = directories[0] / "talktome"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(script, encoding="utf-8")
        target.chmod(0o755)
    except OSError as exc:
        raise ValueError(f"The talktome command could not be written to {target}. {exc}") from None
    return target


def needs_admin(path_env: str | None = None) -> bool:
    """Whether the only folder on PATH for the command is the system one."""
    on_path = command_dirs(path_env if path_env is not None else login_path())
    return Path(SYSTEM_COMMAND_DIR) in on_path and not any(writable(d) for d in on_path)


# Marks a command as ours. `talktome` is a plausible name for someone else's tool,
# and that tool must not count as an installed TalkToMe command.
COMMAND_MARKER = "Written by TalkToMe"


def command_path(home: Path, path_env: str | None = None) -> Path | None:
    """The `talktome` command this app wrote, wherever it ended up."""
    for directory in command_dirs(path_env if path_env is not None else login_path()):
        candidate = directory / "talktome"
        if candidate.is_file():
            return candidate
    found = shutil.which("talktome")
    return Path(found) if found else None


def is_our_command(path: Path) -> bool:
    try:
        return COMMAND_MARKER in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def command_installed(home: Path, python: str, path_env: str | None = None) -> bool:
    """Whether a runnable `talktome` of ours is on PATH and points at this interpreter."""
    path = command_path(home, path_env)
    if not path or not is_our_command(path):
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if app_bundle(python):
        # Only the form that looks the app up counts. An older shim holds the
        # path of one copy of the app, and it breaks when that copy moves.
        return APP_ID in text and SERVER_IN_APP in text
    # The shim records an interpreter path, and the same interpreter is spelled
    # `python` or `python3` depending on how it was invoked, so the recorded path
    # is resolved rather than compared as text.
    for line in text.splitlines():
        if line.startswith("exec "):
            try:
                recorded = shlex.split(line)[1]
            except (ValueError, IndexError):
                return False
            return recorded == python or same_python(recorded, python)
    return False


def install_skill(home: Path) -> dict:
    source = skill_source()
    if not source.is_file():
        raise ValueError("This installation is missing the TalkToMe skill file.")
    for target in skill_targets(home).values():
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"The skill could not be written to {target}. {exc}") from None
    return skill_status(home)


def uninstall_skill(home: Path) -> dict:
    for target in skill_targets(home).values():
        try:
            target.unlink(missing_ok=True)
            target.parent.rmdir()
        except OSError:
            pass
    return skill_status(home)


def skill_status(home: Path) -> dict:
    python = sys.executable
    command = command_installed(home, python)
    return {
        "id": "skill",
        "name": "TalkToMe skill",
        "detected": True,
        # Installed means an agent can actually do what the skill says, which needs
        # the command as well as the instructions.
        "installed": skill_installed(home) and command,
        "skill": skill_installed(home),
        "command": command,
        # The desktop app offers Install for all users only when nothing else works.
        "admin_install": not command and needs_admin(),
        "path": str(skill_target(home)),
        "hosts": [
            {"id": host, "path": str(target), "skill": _skill_current(target)}
            for host, target in skill_targets(home).items()
        ],
    }


def install_skill_and_command(home: Path) -> dict:
    """Both halves of one step, so neither can be installed without the other."""
    install_skill(home)
    install_command(home, sys.executable, launcher=os.environ.get("TALKTOME_LAUNCH"))
    return skill_status(home)
