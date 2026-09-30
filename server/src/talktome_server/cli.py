"""talktome-server: the agent side of talktome voice calls.

With no command, it serves the talktome app on stdin and stdout. The app runs
it on this computer, and over SSH on a server.
"""

import argparse
import asyncio
import json
import logging
import sys

from . import __version__, hook, paths, plugins
from .api import Client, NotRunning


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="talktome-server", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("serve", help="serve the talktome app on stdin and stdout (the default)")
    commands.add_parser("status", help="show whether a server is running on this machine")
    commands.add_parser("mcp", help="serve the call tools over MCP on stdio")
    commands.add_parser("permission-mcp", help="Claude Code's permission tool during a call (internal)")
    hook_cmd = commands.add_parser("hook", help="run one Claude Code or Codex hook (internal)")
    hook_cmd.add_argument("host", nargs="?", default="claude")
    plugin = commands.add_parser("plugin", help="add the talktome plugin to an agent host")
    plugin.add_argument("action", choices=["install", "remove", "status"])
    plugin.add_argument("--host", required=True, choices=plugins.HOSTS)
    detect = commands.add_parser("hosts", help="list the agent hosts on this machine, as JSON")
    detect.set_defaults(json=True)
    commands.add_parser("version", help="print the version")
    args = parser.parse_args(argv)

    if args.command in (None, "serve"):
        serve()
    elif args.command == "status":
        try:
            s = Client(paths.socket_path()).request("GET", "/v1/status", timeout=3)
            print(f"Running as {s['name']}, version {s['version']}.")
        except NotRunning as exc:
            print(exc)
    elif args.command == "mcp":
        from .mcp_tools import call_tools

        call_tools().run("stdio")
    elif args.command == "permission-mcp":
        from .mcp_tools import permission_tool

        permission_tool().run("stdio")
    elif args.command == "hook":
        hook.run(args.host)
    elif args.command == "plugin":
        installer = plugins.Installer()
        action = {"install": installer.install, "remove": installer.remove, "status": installer.status}[args.action]
        try:
            print(json.dumps(action(args.host), indent=2))
        except plugins.PluginError as exc:
            print(f"talktome-server: {exc}", file=sys.stderr)
            sys.exit(1)
    elif args.command == "hosts":
        print(json.dumps(plugins.Installer().detect(), indent=2))
    elif args.command == "version":
        print(__version__)


def serve() -> None:
    from .link import stdio_link
    from .server import serve as run

    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="talktome-server: %(message)s")

    async def main():
        await run(await stdio_link())

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
