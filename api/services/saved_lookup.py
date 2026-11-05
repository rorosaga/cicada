"""What the lean pass keeps findable (ruling 62, owner 2026-11-04): "enough info so that it can come up in a relevant
conversation and an agent can look further into it."

A saved item no model has read holds a title, a link, a site, a date and, when one is already on the page, its own
description. This module finds those by words, engine-free, for the three doors an agent reads memory through: recall,
Ask and the hook's implicit note. Each hit is a line an agent can act on: follow the link, ask the person about it.
Rarity decides, as in the hook's topic leg: a word most saved items hold finds nothing, so a message sharing "guide" with
a title brings nothing up, and two rare words carrying most of the message's rare weight do.

A hit is the page's words: a line here is never the person's, and being found changes nothing. No read path wakes a save
(``saved_mentions``). The query is never logged.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from api.services import bank_index, history_index, search_index, text_fold

LIVE_STATUSES = frozenset({"active", "decaying"})
#: The message's own subject words read, from its end (the question closes a message).
MAX_TERMS = 16
#: Rows counted per word for its rarity: past this the word is common in any bank that has it.
DF_CAP = 1_000
#: A word held by more than this share of the saved items finds nothing…
COMMON_SHARE = 0.03
#: …never fewer than this: in a small bank no word is common.
COMMON_FLOOR = 5
#: The share of the message's rare weight a hit must carry: two incidental words of a long paste are not its subject.
MIN_COVER = 0.4
#: How much of a description the final check reads.
ABOUT_CHARS = 400
#: In an unasked note (two words or more): the share of a title's own subject words the message must say. The body of a
#: feed item can share words with anything; a title shared by half is what the link is about.
TITLE_COVER = 0.5
#: …and the share of the message's rare weight, higher than a lookup's: nobody asked. Measured on a worst case, 3,000
#: titles drawn from the same 70 technical words: two of four rare words in a coding message brought up a link at 0.4.
NOTE_COVER = 0.6
#: How much of a description rides on a line.
LINE_ABOUT_CHARS = 140
CANDIDATES = 60
#: The vector leg: how many pages it reads, and how far below its best a page may be and still be offered. Relative,
#: since every search model has its own scale (measured on the default: unrelated text sits about 0.04 below a real hit).
MEANING_K = 12
MEANING_GAP = 0.03


@dataclass(frozen=True)
class Hit:
    """One saved item a message's words found. ``page`` is its media page, or None for a tab group."""

    id: str
    title: str
    url: str | None
    site: str | None
    day: str | None
    about: str
    page: str | None
    episode: str | None
    read: bool


def subject_stems(text: str) -> list[str]:
    """The message's subject words, folded the way a title's are compared, from its end, distinct."""
    out: list[str] = []
    for w in reversed(list(text_fold.words(text or ""))):
        if len(w) < 3 or w in text_fold.SUBJECT_STOPWORDS or w.isdigit():
            continue
        s = text_fold.stem(w)
        if s not in out:
            out.append(s)
        if len(out) == MAX_TERMS:
            break
    return out


def _about(body: str) -> str:
    """A saved page's own description, when it holds one: its ``## Description``, never Cicada's one-line summary."""
    from api.services.link_enrichment import _extract_description_section

    return " ".join((_extract_description_section(body or "") or "").split())


def page_hit(memory_path: Path, ref: str) -> Hit | None:
    entry = bank_index.file(memory_path, "entities", f"{ref}.md")
    if entry is None:
        return None
    fm = entry.frontmatter or {}
    if str(fm.get("status") or "active") not in LIVE_STATUSES:
        return None
    media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
    episodes = [str(e).split("#", 1)[0] for e in (fm.get("source_episodes") or []) if str(e).startswith("ep_")]
    kinds = [history_index.kind(e.frontmatter) for e in
             (bank_index.file(memory_path, "episodes", f"{i}.md") for i in episodes[:4]) if e is not None]
    return Hit(
        id=ref, title=str(fm.get("name") or ref), url=str(media.get("url") or "") or None,
        site=str(media.get("site") or "") or None,
        day=str(fm.get("saved_at") or media.get("saved_at") or fm.get("created") or "")[:10] or None,
        about=_about(entry.body()), page=ref, episode=episodes[0] if episodes else None,
        read=not any(k in ("saved", "list") for k in kinds))


def _episode_hit(memory_path: Path, ref: str) -> Hit | None:
    entry = bank_index.file(memory_path, "episodes", f"{ref}.md")
    if entry is None:
        return None
    fm = entry.frontmatter or {}
    if not history_index.is_unread_save(fm) or fm.get("source_deleted_at"):
        return None
    return Hit(id=ref, title=str(fm.get("title") or ref), url=str(fm.get("url") or "") or None, site=None,
               day=str(fm.get("timestamp") or "")[:10] or None, about="", page=None, episode=ref, read=False)


def _weights(conn, stems: list[str], saved_docs: dict[int, str]) -> tuple[dict[str, float], dict[str, set[int]]]:
    """Each word's rarity over the saved items, and the documents holding it (a media page's title, aliases or
    description; a tab group's passages)."""
    bits = search_index.ROW_BITS
    n = max(1, int(conn.execute("SELECT count(*) FROM med").fetchone()[0]) + len(saved_docs))
    weights: dict[str, float] = {}
    rows: dict[str, set[int]] = {}
    for s in stems:
        found = {int(r) >> bits for (r,) in conn.execute(
            f"SELECT rowid FROM med WHERE med MATCH ? LIMIT {DF_CAP}", (f'{{title aliases body}} : "{s}"*',))}
        if saved_docs:
            found |= {d for (r,) in conn.execute(f"SELECT rowid FROM pas WHERE pas MATCH ? LIMIT {DF_CAP}", (f'"{s}"*',))
                      if (d := int(r) >> bits) in saved_docs}
        if not found or len(found) >= DF_CAP or len(found) > max(COMMON_FLOOR, COMMON_SHARE * n):
            continue
        weights[s] = math.log((n + 1) / (len(found) + 0.5))
        rows[s] = found
    return weights, rows


def find(memory_path: Path, text: str, *, k: int = 3, min_shared: int = 2,
         exclude: frozenset[str] = frozenset(), episodes: bool = False, reader=None) -> list[Hit]:
    """At most ``k`` saved items the words of ``text`` are about, best first. ``min_shared``: rare words a hit must share
    (recall's lookup takes one, the hook's unasked note two). ``exclude``: ids already shown. ``episodes``: also tab groups,
    which hold no page and whose words are the person's tabs: only for a caller with the source scope. Never raises."""
    try:
        stems = subject_stems(text)
        if len(stems) < min_shared:
            return []
        memory_path = Path(memory_path)
        if reader is not None:
            return _find(memory_path, reader, stems, k, min_shared, exclude, episodes)
        if search_index.ensure_fresh(memory_path) not in ("ready", "stale"):
            return []
        with search_index.Reader(memory_path) as own:
            return _find(memory_path, own, stems, k, min_shared, exclude, episodes)
    except Exception as exc:  # noqa: BLE001 — a leg fewer, never a failed read
        logger.debug(f"saved lookup skipped ({type(exc).__name__})")
        return []


def _find(memory_path: Path, reader, stems: list[str], k: int, min_shared: int, exclude: frozenset[str],
          episodes: bool) -> list[Hit]:
    conn = reader.conn
    saved_docs: dict[int, str] = {}
    if episodes:
        for doc_id, ref, meta in conn.execute(
                """SELECT id, ref, meta FROM docs WHERE kind = 'episode' AND meta LIKE '%"saved_no_page": true%'"""):
            saved_docs[int(doc_id)] = str(ref)
    weights, rows = _weights(conn, stems, saved_docs)
    if len(weights) < min_shared:
        return []
    total = sum(weights.values())
    score: dict[int, float] = {}
    held: dict[int, int] = {}
    for s, found in rows.items():
        for d in found:
            score[d] = score.get(d, 0.0) + weights[s]
            held[d] = held.get(d, 0) + 1
    order = sorted((d for d in score if held[d] >= min_shared and score[d] >= MIN_COVER * total),
                   key=lambda d: (-score[d], -d))[:CANDIDATES]
    docs = reader.docs(order)
    out: list[Hit] = []
    for d in order:
        doc = docs.get(d)
        if doc is None or doc.ref in exclude:
            continue
        if doc.kind == "media" and str(doc.meta.get("status") or "active") in LIVE_STATUSES:
            hit = page_hit(memory_path, doc.ref)
        elif d in saved_docs:
            hit = _episode_hit(memory_path, doc.ref)
        else:
            hit = None
        if hit is None or hit.page in exclude or hit.episode in exclude:
            continue
        # The rule again on the words a line shows, never on a prefix alone: "port" is not "portfolio".
        own = text_fold.subject_terms(f"{hit.title} {hit.about[:ABOUT_CHARS]}")
        shared = [s for s in weights if s in own]
        if hit.page is not None and (len(shared) < min_shared or sum(weights[s] for s in shared) < MIN_COVER * total):
            continue
        if hit.page is not None and min_shared > 1:
            title = text_fold.subject_terms(hit.title)
            if title and len(title & set(shared)) < TITLE_COVER * len(title):
                continue
            if sum(weights[s] for s in shared) < NOTE_COVER * total:
                continue
        out.append(hit)
        if len(out) == k:
            break
    return out


def by_meaning(memory_path: Path, text: str, *, k: int = 2, exclude: frozenset[str] = frozenset()) -> list[Hit]:
    """Saved pages the stored vectors put near ``text``, for a caller that can judge them (Ask's model reads the header
    saying so). Words leg first: this only adds. One query embedding; never loads a model it does not have. Never raises."""
    if k <= 0:
        return []
    try:
        from api.services.vector_index import SqliteVecIndexer

        rows = SqliteVecIndexer(Path(memory_path)).search_entities(text, top_k=MEANING_K)
    except Exception as exc:  # noqa: BLE001 — a leg fewer
        logger.debug(f"saved meaning leg skipped ({type(exc).__name__})")
        return []
    best = max((float(r.get("score") or 0.0) for r in rows), default=0.0)
    media = [r for r in rows if str((r.get("metadata") or {}).get("type") or "") == "media"
             and float(r.get("score") or 0.0) >= best - MEANING_GAP]
    out: list[Hit] = []
    for row in media:
        ref = str((row.get("metadata") or {}).get("entity_id") or "")
        if not ref or ref in exclude:
            continue
        hit = page_hit(Path(memory_path), ref)
        if hit is not None:
            out.append(hit)
        if len(out) == k:
            break
    return out


def line(hit: Hit) -> str:
    """One hit as an agent reads it: what it is, where it came from, how to look further."""
    bits = ", ".join(b for b in (hit.site, f"saved {hit.day}" if hit.day else None) if b)
    head = f"- {hit.title}" + (f" ({bits})" if bits else "")
    if hit.url:
        head += f" {hit.url}"
    head += f" — `{hit.page or hit.episode}`"
    if hit.about:
        about = hit.about if len(hit.about) <= LINE_ABOUT_CHARS else hit.about[:LINE_ABOUT_CHARS - 1].rstrip() + "…"
        head += f": {about}"
    return head


__all__ = ["Hit", "by_meaning", "find", "line", "page_hit", "subject_stems"]
