"""The talktome plugin's command for each Claude Code or Codex hook. It reads
the hook's input on stdin and prints the hook output both hosts understand. A
hook must never get in the way, so every failure is silent."""

import json
import os
import sys

from . import paths
from .api import Client
from .sessions import RUNNER_ENV

HOOK_TIMEOUT = 590


def run(host: str, stdin=sys.stdin, stdout=sys.stdout) -> None:
    if os.environ.get(RUNNER_ENV):
        return  # a call's own claude -p run is not an open session
    try:
        given = json.load(stdin)
    except ValueError:
        return
    if not isinstance(given, dict) or not given.get("session_id"):
        return
    event = given.get("hook_event_name", "")
    body = {
        "host": host,
        "event": event,
        "session_id": given["session_id"],
        "cwd": given.get("cwd", ""),
        "stop_hook_active": bool(given.get("stop_hook_active")),
        "last_assistant_message": given.get("last_assistant_message", ""),
        "tool_name": given.get("tool_name", ""),
        "tool_input": given.get("tool_input"),
    }
    try:
        result = Client(paths.socket_path()).request("POST", "/v1/hook", body, HOOK_TIMEOUT)
    except Exception:  # noqa: BLE001 - the server may not be running
        return
    out = None
    if result.get("permission"):
        decision = {"behavior": result["permission"]}
        if result.get("message"):
            decision["message"] = result["message"]
        out = {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": decision}}
    elif result.get("block"):
        out = {"decision": "block", "reason": result["block"]}
    elif result.get("context"):
        out = {"hookSpecificOutput": {"hookEventName": event, "additionalContext": result["context"]}}
    if out:
        json.dump(out, stdout)
        stdout.write("\n")
