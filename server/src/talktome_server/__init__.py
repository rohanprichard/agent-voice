"""The agent side of talktome voice calls.

The talktome app starts this server on each machine where coding agents run:
as a child process on the user's own computer, and over SSH on a server. The
app and the server talk in JSON lines over stdin and stdout. Agents, hooks,
and host plugins reach the server through a local socket.
"""

__version__ = "0.2.0"
