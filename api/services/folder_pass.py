"""The folder pass and the catch-up of a browser list read (G245, ruling 78b): which folders to open after a list's All page,
and how far a read scrolls.

X keeps bookmark folders, Instagram collections and YouTube playlists, each on a page of its own, and the All page does not
say which folder a post is in. So one read of such a list is a *pass*: the All page, then up to :data:`FOLDERS_PER_PASS`
folders, the ones read longest ago first so a long list of folders is covered over several reads, never always the same
twelve. This module is the ordering and the privacy of its state alone; each list's own state file (``saved_lists``,
``youtube_lists``) keeps the stamps.

**Catching up.** The first read of a list goes deeper (:data:`FIRST_READ_SCREENS`) than a later one
(:data:`LATER_READ_SCREENS`), which stops at what the list already holds: :func:`known_ground` is how a record's reply knows it
has reached posts already in memory. Older items than the first read reaches still come only with the site's own export.

A folder's name is the person's own title, so machine state never keeps one: only a short hash of it and the time the
folder's page was last read. The names the agent sends with the All page are echoed back in the reply and kept nowhere.
"""
from __future__ import annotations

import hashlib

#: The folders one read opens after the All page, least recently read first.
FOLDERS_PER_PASS = 12
#: Stamps kept per list (a hash and a time each): the newest.
STAMPS_KEPT = 300
#: How far a read scrolls, in the words the agent gets: the first read of a list, a later one, and one folder's page.
FIRST_READ_SCREENS = 20
LATER_READ_SCREENS = 4
FOLDER_SCREENS = 5
#: A run of already-kept items in a row (the list is read newest first) is "known ground".
KNOWN_RUN = 3


def folder_hash(name) -> str:
    """A folder's name as machine state keeps it: a short hash, case and spacing folded, never the title itself."""
    return hashlib.sha256(" ".join(str(name or "").split()).casefold().encode("utf-8")).hexdigest()[:12]


def order(names: list[str], stamps) -> list[str]:
    """At most :data:`FOLDERS_PER_PASS` of ``names`` to open next: the folders never read first, in the order the site
    listed them, then the least recently read. ``stamps`` is ``{hash: iso time}`` (anything else reads as empty)."""
    stamps = stamps if isinstance(stamps, dict) else {}
    ranked = sorted(range(len(names)), key=lambda i: (str(stamps.get(folder_hash(names[i])) or ""), i))
    return [names[i] for i in ranked[:FOLDERS_PER_PASS]]


def stamped(stamps, name: str, moment: str) -> dict:
    """``stamps`` with ``name`` read at ``moment``, trimmed to the newest :data:`STAMPS_KEPT`."""
    out = dict(stamps) if isinstance(stamps, dict) else {}
    out[folder_hash(name)] = moment
    if len(out) > STAMPS_KEPT:
        out = dict(sorted(out.items(), key=lambda kv: str(kv[1]))[-STAMPS_KEPT:])
    return out


def known_ground(known: list[bool], run: int = KNOWN_RUN) -> bool:
    """Did a call reach items already kept: ``run`` of them in a row, or every row of a call shorter than that?"""
    if not known:
        return False
    if len(known) < run:
        return all(known)
    streak = 0
    for was in known:
        streak = streak + 1 if was else 0
        if streak >= run:
            return True
    return False
