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

import functools
import platform
import re
import socket
import subprocess
import sys
from subprocess import run as _run_scutil  # bound at import: a test that stubs git's `subprocess.run` never reaches it

#: What a page writes for "my computer" that names no machine — an extractor's or
#: a hand edit's `device: Mac`. Read as this Mac, like no device at all: on a
#: second Mac the path is simply missing there, which says so.
GENERIC_DEVICE_NAMES = frozenset({"mac", "thismac", "mymac", "local", "localhost", "thismachine",
                                  "thiscomputer", "computer", "laptop"})


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


def fold_device(name: object) -> str:
    """A device name as compared: case-folded, a trailing ``.local`` dropped, letters
    and digits only — so ``macbot.local``, ``Macbot`` and ``MACBOT`` are one Mac, and
    ``Alex's MacBook Pro`` (the computer name) meets ``Alexs-MacBook-Pro`` (its local
    host name)."""
    text = str(name or "").strip().casefold()
    text = re.sub(r"\.local\.?$", "", text)
    return re.sub(r"[^0-9a-z]+", "", text)


@functools.lru_cache(maxsize=1)
def this_device_names() -> frozenset[str]:
    """Every name this Mac answers to, folded: the host name :func:`current_device_id`
    stamps, and on macOS the local host name and the computer name (``scutil``, a
    configuration read that needs no privacy grant). A page written under an older
    host name or with the friendly name still matches."""
    names = {current_device_id(), socket.gethostname() or "", platform.node() or ""}
    if sys.platform == "darwin":
        for key in ("LocalHostName", "ComputerName", "HostName"):
            try:
                out = _run_scutil(["scutil", "--get", key], capture_output=True, text=True, timeout=1, check=False)
            except (OSError, subprocess.SubprocessError):
                continue
            if out.returncode == 0:
                names.add(out.stdout.strip())
    return frozenset(f for f in (fold_device(n) for n in names) if f)


def is_this_device(device: object, this_device: str | None = None) -> bool:
    """Whether a declared ``device`` is this Mac — the one rule every reader uses.

    No device, or a word that names no machine (:data:`GENERIC_DEVICE_NAMES`), is
    this Mac. Otherwise the folded name must be one of :func:`this_device_names`.
    ``this_device`` pins the answer to one name (a test's fake host); pinned to
    :func:`current_device_id` it still accepts this Mac's other names."""
    folded = fold_device(device)
    if not folded or folded in GENERIC_DEVICE_NAMES:
        return True
    if this_device is None:
        return folded in this_device_names()
    pinned = fold_device(this_device)
    if folded == pinned:
        return True
    return pinned == fold_device(current_device_id()) and folded in this_device_names()


def same_device(a: object, b: object) -> bool:
    """Two stamped device names that are the same Mac once folded."""
    return fold_device(a) == fold_device(b)
