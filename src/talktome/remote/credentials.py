"""Credentials and identifiers for the remote bridge.

The pairing code is a credential, not a short numeric code, and it never expires
on its own: it stays valid until the user revokes the pair. Every credential is
generated from at least 256 random bits and only ever stored as a hash.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

# 32 bytes is 256 bits. This is a floor, not a preference: `token_urlsafe` is
# asked for this many bytes and the pairing code inherits the guarantee.
CREDENTIAL_BYTES = 32

LAPTOP_PREFIX = "ttlaptop_"
AGENT_PREFIX = "ttagent_"
PAIR_PREFIX = "pair_"

MAX_CREDENTIAL = 256
MAX_PAIR_ID = 128

LAPTOP_ROLE = "laptop"
AGENT_ROLE = "agent"
ROLES = (LAPTOP_ROLE, AGENT_ROLE)


def _secret(prefix: str, nbytes: int = CREDENTIAL_BYTES) -> str:
    return prefix + secrets.token_urlsafe(nbytes)


def new_pair_id() -> str:
    """A public identifier for one pair. It is not a credential."""
    return PAIR_PREFIX + secrets.token_urlsafe(9)


def new_laptop_credential() -> str:
    """The credential that authorizes only the laptop role."""
    return _secret(LAPTOP_PREFIX)


def new_agent_credential() -> str:
    """The long-lived pairing code the user copies to the agent server.

    It authorizes only the agent role. It is deliberately a copyable text value
    rather than a short number, and it does not expire.
    """
    return _secret(AGENT_PREFIX)


def hash_credential(credential: str) -> str:
    return hashlib.sha256(credential.encode("utf-8")).hexdigest()


def verify_credential(credential, digest) -> bool:
    if not isinstance(credential, str) or not isinstance(digest, str):
        return False
    return hmac.compare_digest(hash_credential(credential), digest)


def valid_pair_id(value) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= MAX_PAIR_ID
        and value.startswith(PAIR_PREFIX)
        and all(character.isalnum() or character in "_-" for character in value)
    )


def valid_credential(value, prefix: str | None = None) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_CREDENTIAL:
        return False
    if any(character.isspace() for character in value):
        return False
    return prefix is None or value.startswith(prefix)
