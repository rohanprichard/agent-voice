"""The versioned JSON envelope two bridge peers exchange.

Only four operations exist, and each carries a typed payload. Frames are
bounded, request identifiers are bounded, and a response always names the
request it answers, so two peers can multiplex without a shared clock or a
shared session.
"""

from __future__ import annotations

import json
import secrets
import time

from . import PROTOCOL_VERSION

# A frame larger than this is refused before it is parsed. The largest legal
# payload is a reply of 16,000 characters, which fits with room to spare.
MAX_FRAME_BYTES = 64 * 1024
MAX_ID = 128

# A request ID carries the millisecond it was made. The laptop journal uses that
# stamp to refuse an old ID even after its claim was pruned, so retention cannot
# turn an expired request into a new operation. The prefix keeps the format
# explicit and lets both ends reject anything that is not one.
REQUEST_ID_PREFIX = "req1_"
REQUEST_ID_TOKEN_BYTES = 12
MAX_REQUEST_STAMP_DIGITS = 15
MAX_PAIR = 128
MAX_THREAD = 200
MAX_TEXT = 16000
MAX_GREETING = 2000
MAX_NAME = 120
MAX_ITEM_ID = 128
MAX_LISTEN_TIMEOUT = 25
MAX_AFTER = 2**31

OPS = frozenset({"call", "listen", "reply", "end"})
MUTATING_OPS = frozenset({"call", "reply", "end"})
AGENTS = frozenset({"codex", "claude", "hermes", "openclaw", "generic"})

FRAME_HELLO = "hello"
FRAME_WELCOME = "welcome"
FRAME_REQUEST = "req"
FRAME_RESPONSE = "res"
FRAME_EVENT = "event"
FRAME_PING = "ping"
FRAME_PONG = "pong"
FRAME_ERROR = "error"
FRAME_REVOKED = "revoked"
FRAME_PEER = "peer"

FRAME_TYPES = frozenset(
    {
        FRAME_HELLO,
        FRAME_WELCOME,
        FRAME_REQUEST,
        FRAME_RESPONSE,
        FRAME_EVENT,
        FRAME_PING,
        FRAME_PONG,
        FRAME_ERROR,
        FRAME_REVOKED,
        FRAME_PEER,
    }
)

ERR_VERSION = "unsupported_version"
ERR_INVALID = "invalid_request"
ERR_OCCUPIED = "occupied_role"
ERR_UNAVAILABLE = "unavailable_peer"
ERR_UNAUTHORIZED = "unauthorized"
ERR_REVOKED = "revoked"
ERR_UNKNOWN_DELIVERY = "unknown_delivery"
ERR_NOT_CONNECTED = "not_connected"
ERR_TOO_MANY = "too_many_requests"
ERR_FRAME = "frame_too_large"
ERR_INTERNAL = "internal_error"

# The relay closes a revoked pair with this code. A client that sees it stops
# reconnecting and ends its own call.
CLOSE_REVOKED = 4403


class ProtocolError(ValueError):
    """An envelope or payload that must not be forwarded or acted on."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def pack(frame: dict) -> str:
    """Serialize one frame, refusing anything oversized or untyped."""
    if not isinstance(frame, dict):
        raise ProtocolError(ERR_INVALID, "Send a frame object.")
    if frame.get("v") != PROTOCOL_VERSION:
        raise ProtocolError(ERR_VERSION, "This bridge speaks protocol version 1.")
    if frame.get("type") not in FRAME_TYPES:
        raise ProtocolError(ERR_INVALID, "Send a known frame type.")
    encoded = json.dumps(frame, separators=(",", ":"), sort_keys=True)
    if len(encoded.encode("utf-8")) > MAX_FRAME_BYTES:
        raise ProtocolError(ERR_FRAME, "The frame is too large.")
    return encoded


def unpack(raw) -> dict:
    """Parse one frame, refusing another version or an unknown type."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    if not isinstance(raw, str):
        raise ProtocolError(ERR_INVALID, "Send a text frame.")
    if len(raw.encode("utf-8")) > MAX_FRAME_BYTES:
        raise ProtocolError(ERR_FRAME, "The frame is too large.")
    try:
        frame = json.loads(raw)
    except ValueError as exc:
        raise ProtocolError(ERR_INVALID, "The frame is not valid JSON.") from exc
    if not isinstance(frame, dict):
        raise ProtocolError(ERR_INVALID, "Send a frame object.")
    if frame.get("v") != PROTOCOL_VERSION:
        raise ProtocolError(ERR_VERSION, "This bridge speaks protocol version 1.")
    if frame.get("type") not in FRAME_TYPES:
        raise ProtocolError(ERR_INVALID, "Send a known frame type.")
    return frame


def _identifier(value, name, maximum=MAX_ID):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise ProtocolError(ERR_INVALID, f"Send a {name} of 1 to {maximum} characters.")
    if any(character.isspace() for character in value):
        raise ProtocolError(ERR_INVALID, f"The {name} cannot contain whitespace.")
    return value


def _thread(value):
    thread = _identifier(value, "connection ID", MAX_THREAD)
    # OpenClaw session keys carry +, @, and !, for example
    # agent:main:whatsapp:direct:+15551234567, so any printable text is allowed.
    if not thread.isprintable():
        raise ProtocolError(
            ERR_INVALID, "Use only printable characters with no spaces in the connection ID."
        )
    return thread


def _text(value, name, maximum):
    if not isinstance(value, str):
        raise ProtocolError(ERR_INVALID, f"Send {name} as text.")
    if len(value) > maximum:
        raise ProtocolError(ERR_INVALID, f"The {name} exceeds {maximum} characters.")
    return value


def _integer(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolError(ERR_INVALID, f"Send {name} as a whole number.")
    if not minimum <= value <= maximum:
        raise ProtocolError(ERR_INVALID, f"Use {name} from {minimum} to {maximum}.")
    return value


def _boolean(value, name):
    if not isinstance(value, bool):
        raise ProtocolError(ERR_INVALID, f"Send {name} as true or false.")
    return value


def make_request_id(now: float | None = None) -> str:
    """A fresh request ID that carries the time it was made."""
    millis = int((time.time() if now is None else now) * 1000)
    return f"{REQUEST_ID_PREFIX}{millis}_{secrets.token_hex(REQUEST_ID_TOKEN_BYTES)}"


def request_id_millis(value) -> int | None:
    """The millisecond stamp inside a request ID, or None if it is not one."""
    if not isinstance(value, str) or len(value) > MAX_ID:
        return None
    if not value.startswith(REQUEST_ID_PREFIX):
        return None
    rest = value[len(REQUEST_ID_PREFIX) :]
    stamp, separator, token = rest.partition("_")
    if separator != "_" or not stamp or not token:
        return None
    if len(stamp) > MAX_REQUEST_STAMP_DIGITS or not stamp.isdigit():
        return None
    if len(token) != REQUEST_ID_TOKEN_BYTES * 2:
        return None
    if any(character not in "0123456789abcdef" for character in token):
        return None
    return int(stamp)


def valid_request_id(value) -> bool:
    return request_id_millis(value) is not None


def make_request(op: str, payload: dict, pair: str, request_id: str) -> dict:
    return {
        "v": PROTOCOL_VERSION,
        "type": FRAME_REQUEST,
        "id": request_id,
        "pair": pair,
        "op": op,
        "payload": payload,
    }


def make_response(request_id: str, result: dict) -> dict:
    return {
        "v": PROTOCOL_VERSION,
        "type": FRAME_RESPONSE,
        "id": request_id,
        "ok": True,
        "result": result if isinstance(result, dict) else {},
    }


def make_error(request_id, code: str, message: str) -> dict:
    return {
        "v": PROTOCOL_VERSION,
        "type": FRAME_ERROR,
        "id": request_id,
        "code": code,
        "message": message,
    }


def make_hello(role: str, pair: str, credential: str) -> dict:
    return {
        "v": PROTOCOL_VERSION,
        "type": FRAME_HELLO,
        "role": role,
        "pair": pair,
        "credential": credential,
    }


def make_welcome(pair: str, role: str, peer: bool) -> dict:
    return {
        "v": PROTOCOL_VERSION,
        "type": FRAME_WELCOME,
        "pair": pair,
        "role": role,
        "peer": peer,
    }


def make_ping() -> dict:
    return {"v": PROTOCOL_VERSION, "type": FRAME_PING}


def make_pong() -> dict:
    return {"v": PROTOCOL_VERSION, "type": FRAME_PONG}


def make_revoked(reason: str) -> dict:
    return {"v": PROTOCOL_VERSION, "type": FRAME_REVOKED, "reason": reason}


def make_peer(pair: str, role: str, state: str) -> dict:
    return {"v": PROTOCOL_VERSION, "type": FRAME_PEER, "pair": pair, "role": role, "state": state}


def validate_request(frame: dict) -> tuple[str, dict]:
    """Check a request frame and hand back its operation and clean payload."""
    request_id = _identifier(frame.get("id"), "request ID")
    if not valid_request_id(request_id):
        raise ProtocolError(ERR_INVALID, "Send a timestamped request ID.")
    pair = frame.get("pair")
    if not isinstance(pair, str) or not 1 <= len(pair) <= MAX_PAIR:
        raise ProtocolError(ERR_INVALID, "Send a pair identifier.")
    op = frame.get("op")
    if op not in OPS:
        raise ProtocolError(ERR_INVALID, "Use call, listen, reply, or end.")
    payload = frame.get("payload")
    if not isinstance(payload, dict):
        raise ProtocolError(ERR_INVALID, "Send a payload object.")
    return request_id, validate_payload(op, payload)


def validate_payload(op: str, payload: dict) -> dict:
    """Validate one operation payload and return the fields worth forwarding.

    Unknown fields are ignored rather than refused, so a later version can add
    one without breaking this release. Every known field is bounded.
    """
    if op == "call":
        clean = {
            "thread": _thread(payload.get("thread")),
            "greeting": _text(payload.get("greeting") or "", "greeting", MAX_GREETING),
            "name": _text(payload.get("name") or "", "call name", MAX_NAME),
            "agent": payload.get("agent") or "generic",
            "wait": _boolean(payload.get("wait", True), "wait"),
        }
        if clean["agent"] not in AGENTS:
            raise ProtocolError(ERR_INVALID, "Use a supported agent or generic.")
        return clean
    if op == "listen":
        return {
            "thread": _thread(payload.get("thread")),
            "after": _integer(payload.get("after", 0), "after", 0, MAX_AFTER),
            "timeout": _timeout(payload.get("timeout", MAX_LISTEN_TIMEOUT)),
        }
    if op == "reply":
        return {
            "thread": _thread(payload.get("thread")),
            "call_id": _identifier(payload.get("call_id"), "call ID"),
            "turn_id": _identifier(payload.get("turn_id"), "turn ID"),
            "item_id": _identifier(payload.get("item_id"), "item ID", MAX_ITEM_ID),
            "text": _reply_text(payload.get("text")),
            "final": _boolean(payload.get("final", True), "final"),
        }
    if op == "end":
        return {}
    raise ProtocolError(ERR_INVALID, "Use call, listen, reply, or end.")


def _timeout(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError(ERR_INVALID, "Send timeout as seconds.")
    if not 0 <= value <= MAX_LISTEN_TIMEOUT:
        raise ProtocolError(ERR_INVALID, f"Use timeout from 0 to {MAX_LISTEN_TIMEOUT} seconds.")
    return float(value)


def _reply_text(value):
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError(ERR_INVALID, "Send reply text.")
    if len(value) > MAX_TEXT:
        raise ProtocolError(ERR_INVALID, f"The reply exceeds {MAX_TEXT} characters.")
    return value
