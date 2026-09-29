import contextlib
import os
import secrets
from pathlib import Path

from platformdirs import user_data_path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows, where this app is not shipped.
    fcntl = None


def data_dir() -> Path:
    path = Path(os.environ.get("TALKTOME_DATA_DIR", user_data_path("talktome", appauthor=False)))
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def get_token() -> str:
    if token := os.environ.get("TALKTOME_TOKEN"):
        return token
    path = data_dir() / "token"
    try:
        with open(path, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as file:
            file.write(secrets.token_urlsafe(32))
    except FileExistsError:
        pass
    return path.read_text().strip()


def base_url() -> str:
    return os.environ.get("TALKTOME_URL", "http://127.0.0.1:8765").rstrip("/")


def lock_path() -> Path:
    """The file a listening server holds a lock on."""
    return data_dir() / "server.lock"


def _create_lock():
    """Open the lock file for the server, creating it private.

    Only ever empty — it exists to be held, not to be read — but it is created
    with the mode of the token rather than the mode of the umask, because the two
    sit in the same folder and should look the same to anyone who goes looking.
    """
    descriptor = os.open(lock_path(), os.O_CREAT | os.O_RDWR, 0o600)
    return os.fdopen(descriptor, "r+")


@contextlib.contextmanager
def announce_server():
    """Hold a lock for as long as a server is listening.

    A command has to know whether the app is up before deciding to start it, and
    the only way it had to ask was the network. A sandboxed command gets no answer
    from an app that is plainly running, so it started a second copy, which found
    the port taken and reported that instead — a symptom reported as the cause.

    A lock is not a connection. The kernel drops it when the process dies, so
    unlike a recorded process id it cannot go stale, and it cannot be inherited by
    an unrelated process that happens to reuse the number.
    """
    handle = _create_lock()
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield lock_path()
    finally:
        handle.close()


def server_up() -> bool:
    """Whether a server process is alive, asked without touching the network.

    Opened for reading and nothing else. An agent's command runs in a sandbox that
    lets it read the app's folder and not write it, so asking with `O_CREAT` — which
    is how the server takes the lock in the first place — failed on a running app
    and reported it closed, which is the same wrong answer this check exists to
    stop giving. `flock` does not care how the descriptor was opened, and a shared
    lock is refused by the exclusive one the server holds.

    False when the platform has no ``fcntl``, or when the file is not there, which
    leaves the caller with the health check it had before rather than a claim it
    cannot support.
    """
    if fcntl is None:
        return False
    descriptor = None
    try:
        descriptor = os.open(lock_path(), os.O_RDONLY)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError:
        return False
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return False
