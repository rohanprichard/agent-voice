"""Connect a remote agent bridge to the laptop voice pipeline.

The local file inbox stays exactly as it was.
This package adds a second, clearly separate path: two outbound WebSocket
connections meet at a relay, and only bounded protocol frames cross it. The
microphone, speech models, and call controls never leave the laptop.

The package is deliberately importable without speech models or macOS
frameworks, because the remote daemon runs on the agent's server.
"""

# The only protocol version this release speaks. A peer with another version is
# refused with an explicit error rather than guessed at.
PROTOCOL_VERSION = 1

# The relay's one WebSocket route. Kept here so every side agrees without
# repeating the string.
RELAY_PATH = "/v1/relay"
