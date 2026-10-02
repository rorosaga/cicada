"""The video watch record (G140 Q-R8, G22, R5 §5.7): what an agent saw in a
saved video, kept as provenance — spans, not copies.

Cicada never watches, downloads or transcribes a video; the Track V rail ("a
stream is never derived") holds. A person's agent may watch one with its own
tools, on its own machine, with its own keys. This module records what it
brings back:

* one **watch episode** — ``assistant: <summary>``, then one
  ``video [m:ss]: <quote>`` line per cited excerpt, in time order. The
  ``video`` marker is what makes ``evidence.speaker_kind`` answer ``media``
  (Q-R9), so a creator's words are never read as the person's (R5 §2
  defect 3);
* one **``describes`` claim** on the media page, written through
  ``agentic_write.write_claim`` (one reconcile path), whose evidence is the
  summary span (``assistant``) and each excerpt's span (``media``) — each
  located inside its own line, so a quote the summary repeats still cites
  the video;
* **chapters**, only when the page has none (a description's own win);
* **how it was read** (G162): ``watch_basis`` (``transcript`` | ``frames`` |
  ``both``) and ``watch_engine`` (a closed set) on the episode's frontmatter —
  the agent's own word, never verified, so the app says "an agent recorded
  that it watched", never "Cicada watched" (R-VU2). An unknown value is
  dropped and the record is still written; and the video's length, kept on
  the page only when it has none.

Caps (Q-R8): the summary is one line of at most 1,500 characters — folded,
so no line of it can pose as a turn marker; at most 12 excerpts of 240, each
at most ``MAX_T_S`` into the video; at most 50 chapters. A transcript does not
fit and is never asked for (R5 D3).
"Watched" is derived, never stored: a ``describes`` claim with a ``media`` span.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from api.services import (
    agentic_write, bank_index, episode_ids, episode_scrub, markdown_parser, media_ingestor, video_chapters,
    video_state,
)
from api.services import evidence as evidence_mod

MAX_SUMMARY_CHARS = 1500
MAX_EXCERPTS = 12
MAX_QUOTE_CHARS = 240
MAX_CHAPTERS = 50
# A day of video. Past it a stamp needs a three-digit hour, which the
# `video [h:mm:ss]:` marker does not read (Q-R9), and the quote would land in
# the summary's turn. So a later time is dropped, never written.
MAX_T_S = 24 * 3600
PREDICATE = "describes"
ORIGIN = "agent/watch"
SOURCE = "video-watch"
MARKER = "video"


@dataclass
class Target:
    """The saved media page a watch is recorded on — resolved, never minted
    here: a watch describes a video Cicada already holds (Q-R8)."""

    entity_id: str
    title: str
    url: str


def _one_line(text) -> str:
    """Whitespace folded to single spaces. A summary or quote with a newline
    could open a line that reads as a turn marker (``user: …``) and turn the
    video's words into the person's — the defect this record exists to end."""
    return " ".join(str(text or "").split())


def resolve(memory_path: Path, url: str) -> Target | None:
    """The saved media page for ``url``, through the dedup index every saver
    writes (``url_hash``) — a video saved from the app, a bookmark import or
    ``cicada_save_url`` resolves alike. ``None`` when not saved."""
    entry = media_ingestor.load_url_index(Path(memory_path)).get(media_ingestor.url_hash(url))
    if not entry or not entry.get("media_entity_id"):
        return None
    entity_id = str(entry["media_entity_id"])
    if not (Path(memory_path) / "entities" / f"{entity_id}.md").exists():
        return None
    return Target(entity_id=entity_id, title=str(entry.get("title") or entity_id), url=url)


def _excerpts(raw) -> tuple[list[tuple[int, str]], int]:
    """``[(seconds, quote)]`` in time order, capped, and how many were left out.

    An unreadable, empty or past-``MAX_T_S`` entry is dropped and counted, so
    the reply can say so (Q-R8) — an agent's malformed excerpt never fails
    the watch, and a guessed time is never written."""
    kept: list[tuple[int, str]] = []
    dropped = 0
    items = raw if isinstance(raw, list) else []
    for item in items:
        t = video_chapters.seconds(item.get("t")) if isinstance(item, dict) else None
        quote = _one_line(item.get("quote"))[:MAX_QUOTE_CHARS].rstrip() if isinstance(item, dict) else ""
        if t is None or t > MAX_T_S or not quote:
            dropped += 1
            continue
        kept.append((t, quote))
    kept.sort(key=lambda e: e[0])
    if len(kept) > MAX_EXCERPTS:
        dropped += len(kept) - MAX_EXCERPTS
        kept = kept[:MAX_EXCERPTS]
    return kept, dropped


def _chapters(raw) -> list[dict]:
    """An agent's chapters as ``[{t, title}]`` (the ``media.chapters`` shape
    ``video_chapters.parse`` writes), capped and sorted; malformed rows are
    skipped rather than guessed at (Q-R12's "absent beats a guess")."""
    out = []
    items = raw if isinstance(raw, list) else []
    for item in items[:MAX_CHAPTERS]:
        if not isinstance(item, dict):
            continue
        t = video_chapters.seconds(item.get("t"))
        title = _one_line(item.get("title"))[: video_chapters.TITLE_LIMIT]
        if t is not None and t <= MAX_T_S and title:
            out.append({"t": t, "title": title})
    return sorted(out, key=lambda c: c["t"])


def _union_basis(old, new: str | None) -> str | None:
    """The basis a repeated record leaves on the episode (§4.2): ``transcript`` +
    ``frames`` is ``both``, and a stated basis replaces an unstated one. A
    repeat that states none changes nothing — it never downgrades."""
    if new is None:
        return None
    facts = (video_state.basis_facts({"watch_basis": old}) - {"U"}) | video_state.basis_facts({"watch_basis": new})
    return video_state.basis_from_facts(facts)


def _write_episode(memory_path: Path, target: Target, body: str, session_fm: dict,
                   *, basis: str | None = None, engine: str | None = None,
                   at: str | None = None) -> tuple[str, bool]:
    """One episode per (page, body): a repeated call returns the same id, read
    back through ``bank_index``'s frontmatter cache — the same rule as
    ``media_ingestor.write_note_episode`` (Q-R10). Ids and timestamps go
    through ``episode_ids`` (G114). Returns ``(id, existed)``.

    A repeat with a new ``basis`` or ``engine`` merges them into the existing
    episode's frontmatter **in place** (G162 A2): the union of the bases, the
    newest stated engine; ``content_hash`` and ``processed`` are untouched, so
    Sleep does not re-read it and no second episode is minted."""
    content_hash = hashlib.sha256(f"{target.entity_id}\x00{body}".encode("utf-8")).hexdigest()[:12]
    for f in bank_index.files(memory_path, "episodes"):
        if f.frontmatter.get("content_hash") == content_hash:
            _merge_how(f.path, basis, engine)
            return f.stem, True
    episodes_dir = memory_path / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    episode_id = episode_ids.next_episode_id(episodes_dir, (at or "")[:10] or datetime.now().strftime("%Y-%m-%d"))
    frontmatter = {
        "id": episode_id,
        "timestamp": at or episode_ids.utc_now_iso(),
        "source": SOURCE,
        # G9's closed origin vocabulary: an agent's write through MCP.
        "origin": "mcp",
        "title": f"Watched: {target.title}"[:120],
        "processed": False,
        "content_hash": content_hash,
        "url": target.url,
        "media_entity_id": target.entity_id,
        **session_fm,
    }
    if basis:
        frontmatter["watch_basis"] = basis
    if engine:
        frontmatter["watch_engine"] = engine
    markdown_parser.write(episodes_dir / f"{episode_id}.md", frontmatter, body)
    return episode_id, False


def _merge_how(path: Path, basis: str | None, engine: str | None) -> bool | None:
    """Merge a repeat's basis/engine into the existing episode file. ``True``
    when the file changed, ``False`` when nothing new was stated, ``None`` for
    a repeat that stated neither (nothing read or written)."""
    if not basis and not engine:
        return None
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    before = (fm.get("watch_basis"), fm.get("watch_engine"))
    if basis:
        union = _union_basis(fm.get("watch_basis"), basis)
        if union:
            fm["watch_basis"] = union
    if engine:
        fm["watch_engine"] = engine
    if (fm.get("watch_basis"), fm.get("watch_engine")) == before:
        return False
    markdown_parser.write(path, fm, parsed.body)
    return True


def _store_chapters(memory_path: Path, entity_id: str, chapters: list[dict]) -> bool:
    """Q-R8: an agent's chapters fill ``media.chapters`` only when it is empty."""
    path = memory_path / "entities" / f"{entity_id}.md"
    parsed = markdown_parser.parse(path)
    media = parsed.frontmatter.get("media")
    if not isinstance(media, dict) or media.get("chapters"):
        return False
    media["chapters"] = chapters
    markdown_parser.write(path, parsed.frontmatter, parsed.body)
    return True


def _duration(raw) -> int | None:
    """The video's length in whole seconds, or ``None`` when unreadable, zero or
    past a day (the same ceiling as a quote's time)."""
    if raw is None or isinstance(raw, bool):
        return None
    seconds = video_chapters.seconds(raw)
    return seconds if seconds and 0 < seconds <= MAX_T_S else None


def _store_duration(memory_path: Path, entity_id: str, seconds: int) -> bool:
    """G162: an agent-reported length fills ``media.duration_s`` only when the
    page has none — the same shape as ``_store_chapters``. A provider's own
    figure (Vimeo, Loom) is never overwritten by an agent's."""
    path = memory_path / "entities" / f"{entity_id}.md"
    parsed = markdown_parser.parse(path)
    media = parsed.frontmatter.get("media")
    if not isinstance(media, dict):
        return False
    existing = media.get("duration_s")
    if isinstance(existing, int) and not isinstance(existing, bool) and existing > 0:
        return False
    media["duration_s"] = seconds
    markdown_parser.write(path, parsed.frontmatter, parsed.body)
    return True


def record(
    memory_path: Path,
    target: Target,
    *,
    summary: str,
    excerpts=None,
    chapters=None,
    session_frontmatter: dict | None = None,
    author: str = "agent",
    session_id: str | None = None,
    origin: str = ORIGIN,
    recorded_ts: str | None = None,
    basis=None,
    engine=None,
    duration=None,
    clock: str | None = None,
) -> dict:
    """Write the watch episode and the ``describes`` claim. Never raises on a
    normal input; returns ``{error}`` or the ids, counts and ``paths`` to commit.

    ``basis``, ``engine`` and ``duration`` (G162) are the agent's own account of
    how it read the video. An unrecognised ``basis`` or ``engine``, or an
    unreadable ``duration``, is dropped (and reported in the result) — the
    record is still written: provenance never blocks memory."""
    memory_path = Path(memory_path)
    basis_given = basis not in (None, "")
    engine_given = engine not in (None, "")
    clean_basis = video_state.clean_basis(basis)
    clean_engine = video_state.clean_engine(engine)
    seconds = _duration(duration)
    # R-N3 / R-LS6: one scrub for every episode writer — the summary and each
    # quote are scrubbed before the body is built, so neither the episode nor
    # the `describes` claim (whose object is the summary) holds a secret.
    summary, scrubbed = episode_scrub.scrub(_one_line(summary))
    if not summary:
        return {"error": "a summary is required — say what the video covers; nothing was recorded"}
    clipped = len(summary) > MAX_SUMMARY_CHARS
    summary = summary[:MAX_SUMMARY_CHARS].rstrip()
    kept, dropped = _excerpts(excerpts)
    cleaned: list[tuple[int, str]] = []
    for t, quote in kept:
        quote, n = episode_scrub.scrub(quote)
        scrubbed += n
        cleaned.append((t, quote))
    kept = cleaned
    episode_scrub.record("mcp", scrubbed, bank=memory_path.name)
    video_lines = [f"{MARKER} [{video_chapters.stamp(t)}]: {quote}" for t, quote in kept]
    body = "\n".join([f"assistant: {summary}", *([""] + video_lines if video_lines else [])])
    episode_id, existed = _write_episode(memory_path, target, body, session_frontmatter or {},
                                         basis=clean_basis, engine=clean_engine, at=clock)
    text = evidence_mod.source_text(memory_path, episode_id) or body
    # Each quote is located inside its OWN line's window: a quote the summary
    # repeats would otherwise land on the `assistant:` line first and cite the
    # agent's words as the video's (and the summary span stays on line one).
    summary_line = f"assistant: {summary}"
    first = {"episode": episode_id, "quote": summary[: evidence_mod.MAX_QUOTE_CHARS]}
    at = text.find(summary_line)
    if at >= 0:
        first["window"] = [at, at + len(summary_line)]
    cites: list[dict] = [first]
    for line, (_, quote) in zip(video_lines, kept):
        item = {"episode": episode_id, "quote": quote}
        # Anchored at a line start, so a summary that happens to contain the
        # whole `video [m:ss]: …` text can never capture the window.
        at = text.find("\n" + line)
        if at >= 0:
            item["window"] = [at + 1, at + 1 + len(line)]
        cites.append(item)
    result = agentic_write.write_claim(
        memory_path, target.entity_id, PREDICATE, summary, observer="agent", confidence=0.75,
        context="general", source_episode=episode_id, object_kind="literal",
        text=f"{target.title}: {summary}", session_id=session_id, origin=origin, evidence=cites,
        authored_by=author, recorded_ts=recorded_ts,
        today=datetime.fromisoformat(clock).date() if clock else None,
    )
    paths = [f"episodes/{episode_id}.md"]
    if result.get("action") in ("error", "ambiguous_subject", "corrupt_claims_block"):
        return {"error": result.get("error") or result.get("action"), "episode_id": episode_id, "paths": paths}
    wanted = _chapters(chapters)
    chapters_stored = _store_chapters(memory_path, target.entity_id, wanted) if wanted else None
    duration_stored = _store_duration(memory_path, target.entity_id, seconds) if seconds else None
    paths.append(result.get("path") or f"entities/{target.entity_id}.md")
    return {"entity_id": target.entity_id, "episode_id": episode_id, "claim_id": result.get("claim_id"),
            "evidence": result.get("evidence") or [], "excerpts": len(kept), "dropped": dropped,
            "summary_clipped": clipped, "chapters": chapters_stored, "paths": paths,
            "basis": clean_basis, "engine": clean_engine, "existed": existed,
            "basis_dropped": basis_given and clean_basis is None,
            "engine_dropped": engine_given and clean_engine is None,
            "duration_dropped": duration not in (None, "") and seconds is None,
            "duration": duration_stored}
