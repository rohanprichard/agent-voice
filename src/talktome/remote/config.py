"""Private remote configuration for both ends of the bridge.

The agent server keeps the pairing code; the laptop keeps its own credential.
They are different files with different roles, and neither file is ever printed
whole. A network relay URL must be ``wss``; plain ``ws`` is allowed only on
loopback for development.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from ..config import data_dir
from . import credentials
from .private import (
    PrivateFileError,
    atomic_write_json,
    check_private_file,
    read_json,
)

AGENT_FILE = "remote-agent.json"
LAPTOP_FILE = "remote-laptop.json"
CONFIG_VERSION = 1
MAX_URL = 512
MAX_LABEL = 120
DEFAULT_RELAY_PATH = "/v1/relay"


class RemoteConfigError(ValueError):
    """A remote configuration that must not be used as written."""


def is_loopback_host(host: str) -> bool:
    """Whether a host is loopback, by address rather than by prefix.

    A string check such as ``startswith("127.")`` also matches
    ``127.attacker.example``. ``ipaddress`` parses the real address and asks the
    standard library whether it is loopback.
    """
    if not isinstance(host, str):
        return False
    normalized = host.strip()
    if normalized.startswith("[") and normalized.endswith("]"):
        normalized = normalized[1:-1]
    if normalized.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def websocket_url(value: str) -> str:
    """Validate a relay URL and fill in the relay route when no path is given."""
    if not isinstance(value, str) or not value.strip():
        raise RemoteConfigError("Enter the relay WebSocket URL.")
    value = value.strip()
    if len(value) > MAX_URL:
        raise RemoteConfigError("The relay URL is too long.")
    parsed = urlsplit(value)
    if parsed.scheme not in {"ws", "wss"}:
        raise RemoteConfigError("Use a ws:// or wss:// relay URL.")
    if not parsed.hostname:
        raise RemoteConfigError("The relay URL has no host.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise RemoteConfigError("The relay URL has an invalid port.") from exc
    if port is not None and not 1 <= port <= 65535:
        raise RemoteConfigError("The relay URL has an invalid port.")
    if parsed.username or parsed.password:
        raise RemoteConfigError("The relay URL cannot contain credentials.")
    if parsed.query or parsed.fragment:
        raise RemoteConfigError("The relay URL cannot contain a query or fragment.")
    if parsed.scheme == "ws" and not is_loopback_host(parsed.hostname):
        raise RemoteConfigError("Use wss:// for a network relay. ws:// is loopback only.")
    path = parsed.path if parsed.path not in {"", "/"} else DEFAULT_RELAY_PATH
    return f"{parsed.scheme}://{parsed.netloc}{path}"


# A user@host or an ssh config alias. It must not start with "-", so ssh
# never reads it as an option.
SSH_TARGET = re.compile(r"^(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9_][A-Za-z0-9._-]*$")


def _port(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise RemoteConfigError(f"Use a {name} from 1 to 65535.")
    return value


def ssh_settings(target, remote_port, ssh_port=None) -> dict:
    """Check the SSH tunnel settings for a laptop that reaches a loopback relay."""
    if not isinstance(target, str) or not SSH_TARGET.match(target.strip()):
        raise RemoteConfigError("Enter the SSH target as user@host.")
    return {
        "target": target.strip(),
        "port": None if ssh_port is None else _port(ssh_port, "SSH port"),
        "remote_port": _port(remote_port, "remote relay port"),
    }


def _label(value) -> str:
    if not isinstance(value, str):
        raise RemoteConfigError("Enter a label as text.")
    value = value.strip()
    if len(value) > MAX_LABEL:
        raise RemoteConfigError(f"Use a label of at most {MAX_LABEL} characters.")
    return value


def agent_config_path() -> Path:
    return data_dir() / AGENT_FILE


def laptop_config_path() -> Path:
    return data_dir() / LAPTOP_FILE


def save_agent_config(relay: str, pair: str, code: str, label: str = "") -> dict:
    """Store the agent server's pairing code with mode ``0600``."""
    if not credentials.valid_pair_id(pair):
        raise RemoteConfigError("Enter a valid pair identifier.")
    if not credentials.valid_credential(code, credentials.AGENT_PREFIX):
        raise RemoteConfigError("The pairing code is not an agent code.")
    document = {
        "version": CONFIG_VERSION,
        "role": credentials.AGENT_ROLE,
        "relay": websocket_url(relay),
        "pair": pair,
        "code": code,
        "label": _label(label),
    }
    atomic_write_json(agent_config_path(), document)
    return {key: value for key, value in document.items() if key != "code"}


def save_laptop_config(
    relay: str, pair: str, credential: str, label: str = "", ssh: dict | None = None
) -> dict:
    """Store the laptop credential with mode ``0600``.

    With ``ssh``, the connector opens its own tunnel to a relay that binds
    loopback on the server, so the relay URL must be loopback too.
    """
    if not credentials.valid_pair_id(pair):
        raise RemoteConfigError("Enter a valid pair identifier.")
    if not credentials.valid_credential(credential, credentials.LAPTOP_PREFIX):
        raise RemoteConfigError("The laptop credential is not a laptop code.")
    document = {
        "version": CONFIG_VERSION,
        "role": credentials.LAPTOP_ROLE,
        "relay": websocket_url(relay),
        "pair": pair,
        "credential": credential,
        "label": _label(label),
    }
    if ssh is not None:
        document["ssh"] = _checked_ssh(ssh, document["relay"])
    atomic_write_json(laptop_config_path(), document)
    return {key: value for key, value in document.items() if key != "credential"}


def load_agent_config() -> dict | None:
    return _load(
        agent_config_path(),
        "code",
        credentials.AGENT_PREFIX,
        credentials.AGENT_ROLE,
    )


def load_laptop_config() -> dict | None:
    return _load(
        laptop_config_path(),
        "credential",
        credentials.LAPTOP_PREFIX,
        credentials.LAPTOP_ROLE,
    )


def _checked_ssh(ssh, relay: str) -> dict:
    if not isinstance(ssh, dict):
        raise RemoteConfigError("The SSH settings are not valid.")
    if not relay.startswith("ws://") or not is_loopback_host(urlsplit(relay).hostname or ""):
        raise RemoteConfigError("An SSH tunnel needs a ws:// loopback relay URL.")
    return ssh_settings(ssh.get("target"), ssh.get("remote_port"), ssh.get("port"))


def _load(path: Path, secret_key: str, prefix: str, expected_role: str) -> dict | None:
    if not path.is_file():
        return None
    try:
        check_private_file(path)
    except PrivateFileError as exc:
        raise RemoteConfigError(str(exc)) from exc
    document = read_json(path)
    if not isinstance(document, dict):
        raise RemoteConfigError(f"{path.name} is not a valid configuration file.")
    if document.get("version") != CONFIG_VERSION:
        raise RemoteConfigError(f"{path.name} uses an unsupported configuration version.")
    if document.get("role") != expected_role:
        raise RemoteConfigError(f"{path.name} is not a {expected_role} configuration.")
    relay = websocket_url(str(document.get("relay") or ""))
    pair = document.get("pair")
    secret = document.get(secret_key)
    if not credentials.valid_pair_id(pair):
        raise RemoteConfigError(f"{path.name} has an invalid pair identifier.")
    if not credentials.valid_credential(secret, prefix):
        raise RemoteConfigError(f"{path.name} has an invalid credential.")
    loaded = {
        "version": document.get("version", CONFIG_VERSION),
        "role": document.get("role"),
        "relay": relay,
        "pair": pair,
        secret_key: secret,
        "label": str(document.get("label") or ""),
    }
    if document.get("ssh") is not None:
        loaded["ssh"] = _checked_ssh(document["ssh"], relay)
    return loaded


def remove_agent_config() -> bool:
    return _remove(agent_config_path())


def remove_laptop_config() -> bool:
    return _remove(laptop_config_path())


def _remove(path: Path) -> bool:
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise RemoteConfigError(f"Could not remove {path.name}: {exc}") from exc
    return True


def describe(config: dict | None) -> dict:
    """A configuration summary safe to print. Never includes a credential."""
    if not config:
        return {"configured": False}
    summary = {
        "configured": True,
        "role": config.get("role"),
        "relay": config.get("relay"),
        "pair": config.get("pair"),
        "label": config.get("label") or "",
    }
    if config.get("ssh"):
        summary["ssh"] = config["ssh"]
    return summary


def json_text(document) -> str:
    return json.dumps(document, indent=2, sort_keys=True)


# Keep the environment override discoverable from one place. The remote inbox
# and daemon both honor it, so a sandbox with no writable user data directory
# can still point the pair at a private temporary folder.
def data_root() -> Path:
    override = os.environ.get("TALKTOME_REMOTE_DIR")
    return Path(override).expanduser() if override else data_dir()
