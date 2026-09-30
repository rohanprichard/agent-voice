import os
import sys
from pathlib import Path


def data_dir(env=os.environ) -> Path:
    """Where the server keeps its socket and settings. TALKTOME_DIR changes it."""
    configured = env.get("TALKTOME_DIR")
    if configured:
        return Path(configured)
    home = Path(env.get("HOME") or Path.home())
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "talktome-server"
    base = env.get("XDG_CONFIG_HOME")
    return (Path(base) if base else home / ".config") / "talktome-server"


def socket_path(env=os.environ) -> Path:
    return data_dir(env) / "server.sock"
