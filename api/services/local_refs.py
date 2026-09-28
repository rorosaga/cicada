"""Which machine this is (backlog G27).

Memory is portable (a git repo you can clone anywhere), but a declared local
path — a watched folder, a ``repos:`` checkout — is only meaningful on the
machine it was recorded on. :func:`current_device_id` names "this machine" so
a declaration can say which device its path belongs to.

This module never touches the filesystem. The backend does not stat or list a
folder the person declared: the app reads the person's Mac (the ``~/Library``
rail), and the backend parses what it is sent.
"""

from __future__ import annotations

import platform
import socket


def current_device_id() -> str:
    """Return a stable identifier for "this machine".

    Uses ``socket.gethostname()`` — the machine's configured hostname. It's
    stable across reboots and process restarts, requires no extra permissions
    or persisted state (unlike, say, generating and storing a random UUID on
    first run), and is something a user actually recognizes ("alex-mbp"
    vs. an opaque UUID). Falls back to ``platform.node()`` (rarely different,
    but covers the edge case where ``gethostname()`` returns an empty string
    in some sandboxed/containerized environments), and finally to a fixed
    placeholder so this never raises.

    This is intentionally NOT a hardware UUID or MAC-derived id: Cicada only
    needs to answer "is this the same machine as before?", not guarantee
    global uniqueness across the internet.
    """
    host = (socket.gethostname() or "").strip()
    if host:
        return host
    node = (platform.node() or "").strip()
    if node:
        return node
    return "unknown-device"
