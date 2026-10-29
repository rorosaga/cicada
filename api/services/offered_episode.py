"""An episode an old home offers back after a take-over, written by the new home (G132 phase 2, ruling 51a).

When a home is taken over while it is only away, what it ordered after the take-over point is set aside on its own
computer — never merged — and offered back as transactions (``home_move.reconcile``). Every episode in that range
arrives here as one ``POST /capture/offered``: the episode's own file, through this home's own writer, so every rail
holds as for any capture — the text scrubbed (``episode_scrub``), the id minted here at apply time under the id rule
(``episode_ids.create_episode``: the day of its own date, max + 1), ``processed: false`` so Sleep reads it, never into
a demo bank. It records where it came from (``offered_from``: the device id, ``offered_term``) and keeps its
timestamps (ruling 39: ``received_at`` is when Cicada first received it, so it is kept, never re-stamped).

It is applied once: an offer whose conversation is already here (the same ``session_id`` and ``source`` — one episode
per session, G104 — which the hooks may have captured again since they followed the new home), or whose words are
already here (a save that the old home's offered calls already made again), answers ``already`` and writes nothing.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

MAX_CHARS = 2_000_000
#: Writer-owned keys an offered episode never carries over: the new home mints and decides them.
_DROPPED = ("id", "processed", "processed_by", "processed_at", "device")


def _split(text: str) -> tuple[dict, str] | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    try:
        fm = yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(fm, dict):
        return None
    body = text[end + 4:]
    return fm, body[1:] if body.startswith("\n") else body


def _body_hash(body: str) -> str:
    return hashlib.sha256(body.strip().encode("utf-8")).hexdigest()


def _already(memory_path: Path, fm: dict, body: str) -> bool:
    from api.services import bank_index

    session, source = fm.get("session_id"), fm.get("source")
    wanted = _body_hash(body)
    for f in bank_index.files(memory_path, "episodes"):
        other = f.frontmatter
        if session and other.get("session_id") == session and other.get("source") == source:
            return True
        if other.get("offered_hash") == wanted:
            return True
    # The words themselves (a save the offered calls already made again here): only among recent episodes.
    for path in sorted((memory_path / "episodes").glob("ep_*.md"))[-400:]:
        parsed = _split(path.read_text(encoding="utf-8", errors="replace"))
        if parsed is not None and _body_hash(parsed[1]) == wanted:
            return True
    return False


def write(memory_path: Path, text: str, *, from_device: str | None, term: int | None) -> dict:
    """``{"status": "created" | "already" | "refused", "episodeId"?, "reason"?}``."""
    from api.services import episode_ids, episode_scrub

    if not isinstance(text, str) or len(text) > MAX_CHARS:
        return {"status": "refused", "reason": "too_large"}
    parsed = _split(text)
    if parsed is None:
        return {"status": "refused", "reason": "not_an_episode"}
    fm, body = parsed
    body, scrubbed = episode_scrub.scrub(body)
    if scrubbed:
        episode_scrub.record("offered_episode", scrubbed, bank=memory_path.name)
    episodes = memory_path / "episodes"
    with episode_ids.episode_lock(episodes):
        if _already(memory_path, fm, body):
            return {"status": "already"}
        keep = {k: v for k, v in fm.items() if k not in _DROPPED}
        stamp = str(keep.get("timestamp") or episode_ids.utc_now_iso())
        day = episode_ids.id_day(stamp)
        keep = {"id": episode_ids.next_episode_id(episodes, day), **keep, "processed": False,
                "offered_from": from_device, "offered_term": term, "offered_hash": _body_hash(body)}
        episode_id = episode_ids.create_episode(episodes, keep, body)
    from api.services import bank_index

    bank_index.invalidate(memory_path)
    return {"status": "created", "episodeId": episode_id}
