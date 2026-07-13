"""Device-aware local file/folder references (backlog G27).

An entity's markdown body can point at a file or folder that lives on a
particular *device* (this laptop, that old desktop, ...) rather than inside
the memory graph itself — e.g. "the PDF is at ``~/Documents/thesis.pdf``".
Memory itself is portable (it's a git repo you can clone anywhere), but a
local-file reference is only meaningful on the machine it was created on.
This module answers three questions:

1. What machine are we currently running on? -> :func:`current_device_id`
2. Given a ``(path, device)`` pair recorded in an entity, does that path
   still exist *right now*? -> :func:`resolve_local_ref`
3. Which local-file references does a given entity body mention?
   -> :func:`extract_local_refs`

No function in this module ever reads file *contents* — only
``Path.exists()`` / ``Path.is_dir()`` (a `stat(2)` call). That's a deliberate
security boundary: this is a "does it still exist" oracle, not a file server.

Reference syntax
-----------------
Two minimal, greppable forms are recognized inside an entity body:

1. Wikilink-style embed, with an optional device tag::

       ![[file:/absolute/path|device:<device-id>]]
       ![[file:/absolute/path]]                      # device omitted -> None

   ``device:<device-id>`` records which machine's filesystem the path is
   valid on. When omitted, the reference is assumed to belong to whichever
   device the entity was authored on (unknown to this parser — the caller
   decides how to treat a ``None`` device, e.g. "assume current machine").

   Example::

       ![[file:/Users/alice/Documents/thesis.pdf|device:alices-mbp]]

2. A plain markdown link to a ``file://`` URL (no device component — by
   definition a bare ``file://`` URL is host-less here, so ``device`` is
   always ``None`` for this form)::

       [Thesis PDF](file:///Users/alice/Documents/thesis.pdf)

Both forms are matched independently; a body may contain any mix of them.
"""

from __future__ import annotations

import platform
import re
import socket
from pathlib import Path
from typing import Any

# ![[file:/abs/path]]  or  ![[file:/abs/path|device:some-id]]
_WIKILINK_RE = re.compile(
    r"!\[\[file:(?P<path>[^|\]]+?)(?:\|device:(?P<device>[^\]]+))?\]\]"
)

# [label](file:///abs/path)
_MD_LINK_RE = re.compile(r"\[[^\]]*\]\(file://(?P<path>[^\s)]+)\)")


def current_device_id() -> str:
    """Return a stable identifier for "this machine".

    Uses ``socket.gethostname()`` — the machine's configured hostname. It's
    stable across reboots and process restarts, requires no extra permissions
    or persisted state (unlike, say, generating and storing a random UUID on
    first run), and is something a user actually recognizes ("rodrigos-mbp"
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


def resolve_local_ref(path: str, device: str | None = None) -> dict[str, Any]:
    """Check whether a recorded local-file reference is still valid *here*.

    Args:
        path: the filesystem path as recorded (may use ``~``).
        device: the device id the reference was recorded on, or ``None`` if
            unknown/unspecified (treated as "assume current device").

    Returns:
        A dict with keys ``path``, ``device``, ``exists``, ``is_dir``,
        ``status``, ``resolved_path``:

        - If ``device`` is given and differs from :func:`current_device_id`,
          the path belongs to a different machine we have no filesystem
          access to. We deliberately do NOT stat it (that would be checking
          the wrong machine's namespace and could produce a false
          "missing"/coincidental "present" for an unrelated file at the same
          path on *this* machine). ``status`` is ``"other_device"``,
          ``exists`` is ``False``, ``resolved_path`` is ``None``.
        - Otherwise (``device`` is ``None`` or matches the current device) we
          stat the path on this machine: ``status`` is ``"present"`` when it
          exists, else ``"moved_or_missing"``.
    """
    resolved_device = (device or "").strip() or None
    current = current_device_id()

    if resolved_device is not None and resolved_device != current:
        return {
            "path": path,
            "device": resolved_device,
            "exists": False,
            "is_dir": False,
            "status": "other_device",
            "resolved_path": None,
        }

    p = Path(path).expanduser()
    exists = p.exists()
    is_dir = p.is_dir() if exists else False

    return {
        "path": path,
        "device": resolved_device or current,
        "exists": exists,
        "is_dir": is_dir,
        "status": "present" if exists else "moved_or_missing",
        "resolved_path": str(p) if exists else None,
    }


def extract_local_refs(body: str) -> list[dict[str, str | None]]:
    """Find local-file references in an entity markdown body.

    Recognizes both syntaxes documented in the module docstring. Returns a
    list of ``{"path": str, "device": str | None}`` dicts in the order they
    appear in the body. Does not touch the filesystem — pure text parsing.
    """
    refs: list[dict[str, str | None]] = []

    for match in _WIKILINK_RE.finditer(body):
        raw_path = match.group("path").strip()
        raw_device = match.group("device")
        device = raw_device.strip() if raw_device else None
        refs.append({"path": raw_path, "device": device or None})

    for match in _MD_LINK_RE.finditer(body):
        raw_path = match.group("path").strip()
        refs.append({"path": "/" + raw_path.lstrip("/"), "device": None})

    return refs
