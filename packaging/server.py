"""Entry point for the frozen server.

PyInstaller freezes a script rather than a console entry point, so this exists to
be that script. It builds the application directly instead of naming the factory
for uvicorn to import, because a frozen build has no importable package tree for
uvicorn to walk at runtime.
"""

import multiprocessing
import os
import sys


def selftest():
    """Report what the frozen build can actually do.

    A frozen app differs from a checkout in ways that only appear at runtime: a data
    file that was never collected, a framework that will not load, a package left
    behind. Asking the binary directly is the only way to tell which, and the
    alternative is inferring it from a message written for a user.
    """
    import json
    import traceback

    report = {}
    try:
        import keyring

        backend = keyring.get_keyring()
        report["keyring_backend"] = f"{type(backend).__module__}.{type(backend).__name__}"
    except Exception as exc:  # noqa: BLE001 - a self-test reports, it never raises.
        report["keyring_backend"] = f"{type(exc).__name__}: {exc}"

    try:
        from ctypes.util import find_library

        report["find_library"] = {
            name: repr(find_library(name)) for name in ("Security", "CoreServices", "Foundation")
        }
    except Exception as exc:  # noqa: BLE001 - a self-test reports, it never raises.
        report["find_library"] = f"{type(exc).__name__}: {exc}"

    try:
        from keyring.backends.macOS import api

        report["macos_api"] = f"imported, Security handle {api._sec!r}"
    except Exception as exc:  # noqa: BLE001 - a self-test reports, it never raises.
        report["macos_api"] = f"{type(exc).__name__}: {exc}"

    try:
        import keyring

        keyring.set_password("talktome-selftest", "probe", "x")
        keyring.delete_password("talktome-selftest", "probe")
        report["keyring_write"] = "ok"
    except Exception as exc:  # noqa: BLE001 - a self-test reports, it never raises.
        report["keyring_write"] = f"{type(exc).__name__}: {exc}"
        report["keyring_trace"] = traceback.format_exc()[-700:]

    # The way in for an agent's command, which is the one part of this build that
    # only exists at runtime. A module left out of the freeze, or a folder that
    # cannot be written, breaks every call while every test still passes — so the
    # binary is asked directly rather than inferred to be fine. Where the request
    # landed is reported too: the fallback exists because a sandbox refuses the
    # app's own folder, and which one was used is the first thing worth knowing.
    try:
        from talktome import inbox

        request = inbox.ask("selftest", {"probe": True})
        inbox.answer(request, result={"ok": True})
        reply = inbox.reply_for(request)
        inbox.collect(request)
        report["inbox"] = "ok" if reply and reply.get("result") == {"ok": True} else reply
        report["inbox_place"] = str(request.place)
    except Exception as exc:  # noqa: BLE001 - a self-test reports, it never raises.
        report["inbox"] = f"{type(exc).__name__}: {exc}"

    try:
        from talktome import inbox

        report["inbox_fallback"] = "ok" if inbox.prepare(inbox.shared()) else "not writable"
    except Exception as exc:  # noqa: BLE001 - a self-test reports, it never raises.
        report["inbox_fallback"] = f"{type(exc).__name__}: {exc}"

    # The command decides whether to start an app by reading this lock, so a build
    # where it cannot be taken would start a second copy on every call.
    try:
        from talktome.config import announce_server, server_up

        with announce_server():
            held = server_up()
        report["presence"] = "ok" if held and not server_up() else f"held={held}"
    except Exception as exc:  # noqa: BLE001 - a self-test reports, it never raises.
        report["presence"] = f"{type(exc).__name__}: {exc}"

    # The binary is also the `talktome` command, and that half is easy to lose:
    # nothing the server imports reaches `talktome.cli`, so PyInstaller left it out
    # of the archive and every call started another server instead. Asked here, so
    # the next time it goes missing the bundle says so rather than the user.
    try:
        import importlib.util

        report["command"] = (
            "ok" if importlib.util.find_spec("talktome.cli") else "talktome.cli is missing"
        )
    except Exception as exc:  # noqa: BLE001 - a self-test reports, it never raises.
        report["command"] = f"{type(exc).__name__}: {exc}"

    print(json.dumps(report, indent=2))


def main():
    # tqdm makes a multiprocessing lock during a model download, and that starts the
    # resource tracker as this binary with `-c`. Without this, the tracker ran as a
    # second server and failed on the presence lock.
    multiprocessing.freeze_support()
    if "--selftest" in sys.argv:
        return selftest()
    argv = sys.argv[1:]
    # This one binary does two jobs. It is the server the app runs, and — because a
    # bundle has no interpreter inside it to `-m talktome` with — it is also the
    # `talktome` command an agent runs. `-m` is honoured here rather than given a
    # flag of its own so the installed shim reads exactly as it does in a checkout.
    #
    # Getting this wrong was silent and total: the first build of this bundle left
    # `talktome.cli` out of the archive entirely, so `talktome call` ran `main()`
    # below instead, started a second server on a port the app already held, and the
    # user read "address already in use" for a call that was never attempted.
    if len(argv) >= 2 and argv[0] == "-m":
        import runpy

        sys.argv = [argv[1], *argv[2:]]
        runpy.run_module(argv[1], run_name="__main__")
        return 0
    serve(int(os.environ.get("TALKTOME_PORT", "8765")))


def serve(port):
    # Imported here, not at the top: every `talktome call` runs this binary with
    # `-m`, and loading the server for it made each command slow.
    import uvicorn

    from talktome.app import create_app
    from talktome.config import announce_server

    # Held for as long as this process is listening, so the `talktome` command can
    # tell the app is up without asking the network — which, inside an agent's
    # sandbox, tells it nothing and costs it a second copy on a taken port.
    with announce_server():
        uvicorn.run(create_app(), host="127.0.0.1", port=port, access_log=False)


if __name__ == "__main__":
    sys.exit(main())
