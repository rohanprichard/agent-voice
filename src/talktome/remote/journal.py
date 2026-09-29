"""A bounded private command journal for the laptop side of the bridge.

A mutating request is claimed before it touches the app. A retry with the same
identifier and the same payload gets the original result instead of a second
ring or a second spoken message. A retry with a different payload fails. A
claim that survived a restart is marked unknown and is never run again on its
own, because the bridge cannot know whether the earlier delivery happened.

A request ID carries the time it was made. An ID older than the acceptance
window is refused even when no claim for it remains, so pruning retention can
never turn an expired request into a new operation. Claims are scoped to the
pair that owns them, so two pairs sharing a laptop cannot collide. The journal
is bounded: once it is full, a new claim is refused rather than evicting a live
one. An unreadable or corrupt journal fails closed instead of starting empty.

The journal stores identifiers, a payload hash, a small result, and timing. It
does not store transcript text.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from . import protocol
from .private import PrivateFileError, atomic_write_json, read_private_json

logger = logging.getLogger(__name__)

JOURNAL_VERSION = 1

# The acceptance window. A request ID older than this is refused before any
# lookup, so a pruned entry cannot quietly become a new operation. It is also
# the retention, so every unexpired claim is still present.
JOURNAL_TTL = 24 * 60 * 60

# A little future skew tolerates a laptop clock that is slightly ahead without
# accepting a forged far-future stamp.
MAX_CLOCK_SKEW = 300

# Refuse new claims past this many live entries instead of evicting one.
MAX_JOURNAL = 2048
MAX_RESULT_BYTES = 8 * 1024
MAX_JOURNAL_BYTES = 4 * 1024 * 1024

STATE_CLAIMED = "claimed"
STATE_DONE = "done"
STATE_UNKNOWN = "unknown"

STATES = frozenset({STATE_CLAIMED, STATE_DONE, STATE_UNKNOWN})


class JournalError(ValueError):
    """A journal problem the caller must report rather than ignore."""


class JournalConflict(JournalError):
    """The same request ID arrived with a different payload."""


class JournalPending(JournalError):
    """The same request ID is already in flight."""


class JournalUnknown(JournalError):
    """The delivery of this request is unknown. Do not resend it."""


class JournalExpired(JournalError):
    """The request ID is outside the acceptance window."""


class JournalFull(JournalError):
    """The journal has no room for another unexpired claim."""


@dataclass
class Claim:
    state: str
    result: dict | None = None


class CommandJournal:
    def __init__(
        self,
        path: Path,
        pair: str,
        *,
        ttl: int = JOURNAL_TTL,
        limit: int = MAX_JOURNAL,
    ):
        if not isinstance(pair, str) or not pair:
            raise JournalError("The command journal needs a pair identifier.")
        self.path = Path(path)
        self.pair = pair
        self.ttl = ttl
        self.limit = limit
        self.entries: dict[str, dict] = {}
        self.dirty = False
        self.load()

    def _key(self, request_id: str) -> str:
        return f"{self.pair}:{request_id}"

    def load(self) -> None:
        """Read the journal, refusing to start empty when a file is present.

        A missing journal is a first run and starts empty. A present but
        unreadable, oversized, or malformed journal is a corrupt one: silently
        forgetting it would let an already-run request run a second time.
        """
        if not self.path.exists():
            self.entries = {}
            return
        try:
            document = read_private_json(self.path, max_bytes=MAX_JOURNAL_BYTES)
        except PrivateFileError as exc:
            raise JournalError(f"The command journal could not be read: {exc}") from exc
        if not isinstance(document, dict) or document.get("version") != JOURNAL_VERSION:
            raise JournalError("The command journal has an unsupported format.")
        entries = document.get("entries")
        if not isinstance(entries, dict):
            raise JournalError("The command journal has no entries.")
        loaded = {}
        for key, entry in entries.items():
            if not isinstance(key, str) or not isinstance(entry, dict):
                raise JournalError("The command journal has a malformed entry.")
            state = entry.get("state")
            if state not in STATES:
                raise JournalError("The command journal has an unknown entry state.")
            if state == STATE_CLAIMED:
                # A claim from a previous process has unknown delivery.
                state = STATE_UNKNOWN
            loaded[key] = {
                "op": str(entry.get("op") or ""),
                "hash": str(entry.get("hash") or ""),
                "state": state,
                "time": float(entry.get("time") or 0),
                "result": entry.get("result") if isinstance(entry.get("result"), dict) else None,
                "error": str(entry.get("error") or "") or None,
            }
        self.entries = loaded

    def save(self) -> None:
        document = {
            "version": JOURNAL_VERSION,
            "entries": self.entries,
        }
        atomic_write_json(self.path, document)
        self.dirty = False

    @staticmethod
    def payload_hash(op: str, payload: dict) -> str:
        canonical = json.dumps(
            {"op": op, "payload": payload}, separators=(",", ":"), sort_keys=True
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _prune(self, now: float) -> None:
        # Only expired claims leave. An unexpired claim is never evicted, so the
        # cache cannot forget a mutation that a retry may still name.
        cutoff = now - self.ttl
        expired = [key for key, entry in self.entries.items() if entry["time"] < cutoff]
        for key in expired:
            self.entries.pop(key, None)
        if expired:
            self.dirty = True

    def _age(self, request_id: str, now: float) -> float:
        millis = protocol.request_id_millis(request_id)
        if millis is None:
            raise JournalError("Use a request ID made by this bridge.")
        return now - millis / 1000.0

    def claim(self, request_id: str, op: str, payload: dict) -> Claim:
        """Name the mutation before it happens, or explain why it must not run."""
        now = time.time()
        age = self._age(request_id, now)
        if age > self.ttl:
            raise JournalExpired(
                "This request ID is older than the acceptance window. Start a new operation."
            )
        if age < -MAX_CLOCK_SKEW:
            raise JournalError("This request ID is dated in the future.")
        self._prune(now)
        digest = self.payload_hash(op, payload)
        key = self._key(request_id)
        entry = self.entries.get(key)
        if entry is not None:
            if entry["hash"] != digest or entry["op"] != op:
                raise JournalConflict("This request ID has a different payload.")
            if entry["state"] == STATE_DONE:
                return Claim(STATE_DONE, entry["result"])
            if entry["state"] == STATE_CLAIMED:
                raise JournalPending("This request is already in progress.")
            raise JournalUnknown(
                "The delivery of this request is unknown. Do not resend it."
            )
        if len(self.entries) >= self.limit:
            raise JournalFull(
                "The command journal is full. Wait for old requests to expire."
            )
        self.entries[key] = {
            "op": op,
            "hash": digest,
            "state": STATE_CLAIMED,
            "time": now,
            "result": None,
            "error": None,
        }
        self.save()
        return Claim(STATE_CLAIMED)

    def complete(self, request_id: str, result: dict) -> None:
        entry = self.entries.get(self._key(request_id))
        if entry is None or entry["state"] != STATE_CLAIMED:
            return
        entry["state"] = STATE_DONE
        entry["result"] = _bounded_result(result)
        entry["error"] = None
        entry["time"] = time.time()
        self.save()

    def fail_unknown(self, request_id: str, error: str = "") -> None:
        """A claim that raised or lost its connection must never run again."""
        entry = self.entries.get(self._key(request_id))
        if entry is None or entry["state"] == STATE_DONE:
            return
        entry["state"] = STATE_UNKNOWN
        entry["result"] = None
        entry["error"] = str(error or "")[:400] or None
        entry["time"] = time.time()
        self.save()

    def mark_pending_unknown(self) -> None:
        """On a disconnect, every in-flight claim becomes unknown delivery."""
        changed = False
        for entry in self.entries.values():
            if entry["state"] == STATE_CLAIMED:
                entry["state"] = STATE_UNKNOWN
                entry["error"] = "The connection closed before the result arrived."
                changed = True
        if changed:
            self.save()


def _bounded_result(result) -> dict:
    if not isinstance(result, dict):
        return {}
    try:
        encoded = json.dumps(result, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError):
        return {}
    if len(encoded.encode("utf-8")) > MAX_RESULT_BYTES:
        return {"ok": True, "cached": True}
    return result
