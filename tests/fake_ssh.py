"""A stand-in for ssh that runs on this machine.

With a command, it runs the command locally, in the environment that
FAKE_SSH_ENV names, as if on the server. With -N and -L, it forwards the local
port to the remote port on 127.0.0.1, as the real tunnel does.

FAKE_SSH_LOG gets one JSON line per start. FAKE_SSH_FAIL=auth makes it fail
the way ssh does in BatchMode when no key works.
"""

import json
import os
import signal
import socket
import subprocess
import sys
import threading


def parse(argv):
    options = {"N": False, "L": None, "p": None, "o": []}
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--":
            index += 1
            break
        if not arg.startswith("-"):
            break
        flag = arg[1]
        if flag in "LpoiF":
            value = arg[2:] or argv[index + 1]
            index += 1 if arg[2:] else 2
            if flag == "o":
                options["o"].append(value)
            else:
                options[flag] = value
            continue
        if flag == "N":
            options["N"] = True
        index += 1
    return options, argv[index], " ".join(argv[index + 1 :])


def pipe(source, sink):
    try:
        while data := source.recv(65536):
            sink.sendall(data)
    except OSError:
        pass
    finally:
        for end in (source, sink):
            try:
                end.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def forward(spec):
    bind, local, host, remote = spec.split(":")
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((bind, int(local)))
    except OSError as exc:
        print(f"bind [{bind}]:{local}: {exc}", file=sys.stderr)
        print(f"channel_setup_fwd_listener_tcpip: cannot listen to port: {local}", file=sys.stderr)
        print("Could not request local forwarding.", file=sys.stderr)
        sys.exit(255)
    server.listen(16)
    while True:
        client, _ = server.accept()
        try:
            upstream = socket.create_connection((host, int(remote)), timeout=5)
        except OSError:
            print("channel 2: open failed: connect failed: Connection refused", file=sys.stderr)
            client.close()
            continue
        upstream.settimeout(None)
        threading.Thread(target=pipe, args=(client, upstream), daemon=True).start()
        threading.Thread(target=pipe, args=(upstream, client), daemon=True).start()


def main():
    options, target, command = parse(sys.argv[1:])
    log = os.environ.get("FAKE_SSH_LOG")
    if log:
        with open(log, "a") as file:
            file.write(json.dumps({"pid": os.getpid(), "argv": sys.argv[1:]}) + "\n")
    if os.environ.get("FAKE_SSH_FAIL") == "auth":
        print(f"{target}: Permission denied (publickey).", file=sys.stderr)
        return 255
    if options["N"]:
        signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
        forward(options["L"])
        return 0
    env = dict(os.environ)
    if os.environ.get("FAKE_SSH_ENV"):
        with open(os.environ["FAKE_SSH_ENV"]) as file:
            env.update(json.load(file))
    return subprocess.run(["/bin/sh", "-c", command], env=env, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
