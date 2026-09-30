"""What an agent read on a page, kept as provenance (G166, spec §8.4, the ``watch_record`` sibling).

Cicada never opens a browser and never holds a session. A person's own agent —
a local harness with a browser tool, or a remote connection that can drive one —
reads a page in the person's signed-in session and brings back what it saw. This module records that, and
nothing about HOW it read: the tool is self-reported (``via``), the harness
label is the connection's, and neither is ever shown as proof.

A successful read writes:

* one **read episode** — ``assistant: <summary>`` (the agent's own words), then
  ``attachment [<host>]: as <harness> read it`` and one ``> <quote>`` line per
  excerpt. The ``attachment [..]:`` marker is what makes ``evidence._marker``
  answer ``page`` for the quotes (text an agent REPORTED from the page, never
  the person's words), while the summary stays ``assistant``. The episode is
  ``processed: true`` / ``processed_by: agent`` (Sleep never extracts from it
  raw) and carries no ``evidence_kind`` (a declared ``assistant`` would relabel
  every span, ``evidence.kind_for``). Unlike ``watch_record``'s, which is
  ``processed: false``;
* one **``describes`` claim** on the saved-link media page through
  ``agentic_write.write_claim``, whose spans are the summary line (``assistant``)
  and each excerpt's line (``page``), each located inside its OWN line so a quote
  the summary repeats still cites the page. A **re-read** with a different
  summary closes the previous read's claim (``valid_to`` + ``superseded_by``): the
  vocabulary has no cardinality for ``describes``, so two would otherwise coexist;
* the page's ``## Description`` — only when it has no substantive one of its own
  (the page's words and the reader's win over an agent's);
* a **stamp** ``read: {by: agent, tier: agent, at, v, via, harness, claim}`` on the
  page, and ``enrichment_attempted: true`` so Sleep's in-cycle link pass does not
  write a second ``describes`` claim from the description this just filled.
  ``fetch_status`` is never touched: it says what Cicada's own fetch did.

Cicada cannot check an agent's excerpts against the page (it never has the
page), so it does not pretend to: the label everywhere is "as <harness> read
it". Provenance never blocks memory — an excerpt that cannot be located becomes
``reasoning``, and the claim is still written.

This module NEVER mints a page: an agent cannot fabricate one. The caller
resolves an existing saved link (``watch_record.resolve``, through the dedup
index every saver writes) and hands it in.

Caps (as ``watch_record``): the summary is one line of at most 1,500 characters,
folded so no line of it can pose as a turn marker; at most 12 excerpts of 240;
the title, when the agent gives one, at most 200. Everything is scrubbed
(R-N3) before it is hashed or written.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime
from pathlib import Path

from api.services import (
    agentic_write, bank_index, episode_ids, episode_scrub, markdown_parser, media_ingestor, reading_hosts,
)
from api.services import evidence as evidence_mod
from api.services.claims import MalformedClaimsBlockError, parse_claims, write_claims
from api.services.watch_record import Target, resolve  # noqa: F401 — re-exported: one resolver for both

MAX_SUMMARY_CHARS = 1500
MAX_EXCERPTS = 12
MAX_QUOTE_CHARS = 240
MAX_TITLE_CHARS = 200
PREDICATE = "describes"
ORIGIN = "agent/read"
SOURCE = "page-read"
STAMP_V = 1
MARKER = "attachment"


def _one_line(text) -> str:
    """Whitespace folded to single spaces: a summary or quote with a newline could
    open a line that reads as a turn marker (``user: …``) and turn the page's words
    into the person's."""
    return " ".join(str(text or "").split())


def _excerpts(raw) -> tuple[list[str], int]:
    """Quotes in the order given, capped, and how many were left out (an empty or
    unreadable one is dropped and counted, never guessed)."""
    kept: list[str] = []
    dropped = 0
    for item in raw if isinstance(raw, list) else []:
        quote = item.get("quote") if isinstance(item, dict) else (item if isinstance(item, str) else None)
        text = _one_line(quote).lstrip("> ").strip()[:MAX_QUOTE_CHARS].rstrip()
        if not text:
            dropped += 1
            continue
        if len(kept) >= MAX_EXCERPTS:
            dropped += 1
            continue
        kept.append(text)
    return kept, dropped


def _write_episode(memory_path: Path, target: Target, body: str, session_fm: dict) -> tuple[str, bool]:
    """One episode per (page, body): a repeated call returns the same id.
    Returns ``(id, created)`` — ``created`` is False for an episode that was
    already there, which a failed record must never delete."""
    content_hash = hashlib.sha256(f"{target.entity_id}\x00{body}".encode("utf-8")).hexdigest()[:12]
    for f in bank_index.files(memory_path, "episodes"):
        if f.frontmatter.get("content_hash") == content_hash and f.frontmatter.get("source") == SOURCE:
            return f.stem, False
    episodes_dir = memory_path / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    episode_id = episode_ids.next_episode_id(episodes_dir, datetime.now().strftime("%Y-%m-%d"))
    frontmatter = {
        "id": episode_id,
        "timestamp": episode_ids.utc_now_iso(),
        "source": SOURCE,
        # G9's closed origin vocabulary: an agent's write through MCP.
        "origin": "mcp",
        "title": f"Read: {target.title}"[:120],
        # The agent's own report, already digested: Sleep never re-reads it raw.
        "processed": True,
        "processed_by": "agent",
        "content_hash": content_hash,
        "url": target.url,
        "media_entity_id": target.entity_id,
        **session_fm,
    }
    markdown_parser.write(episodes_dir / f"{episode_id}.md", frontmatter, body)
    return episode_id, True


def _apply_title(memory_path: Path, target: Target, title: str) -> bool:
    """A page saved without a fetch is titled by its URL's last segment (an X
    status id, say). The agent saw the real title: it replaces the slug, and ONLY
    the slug — a title the person, the reader or a provider gave is never
    overwritten. Both places that hold it move together (the index's ``title``
    is what the Feed lists)."""
    idx = media_ingestor.load_url_index(memory_path)
    entry = idx.get(media_ingestor.url_hash(target.url))
    slug = media_ingestor._fallback_title(target.url)
    if not isinstance(entry, dict) or str(entry.get("title") or "") != slug:
        return False
    entry["title"] = title
    media_ingestor.save_url_index(memory_path, idx)
    page = memory_path / "entities" / f"{target.entity_id}.md"
    parsed = markdown_parser.parse(page)
    if str(parsed.frontmatter.get("name") or "") == slug:
        parsed.frontmatter["name"] = title
        markdown_parser.write(page, parsed.frontmatter, parsed.body)
    return True


def _finish_page(memory_path: Path, target: Target, *, summary: str, min_len: int, via, harness: str,
                 claim_id: str | None, day: str) -> tuple[bool, str | None]:
    """Stamp the page, fill a thin description, and close the previous read's
    claim. One parse, one write. Returns ``(description written, closed claim id)``."""
    from api.services import link_enrichment

    page = memory_path / "entities" / f"{target.entity_id}.md"
    parsed = markdown_parser.parse(page)
    fm = parsed.frontmatter
    body = parsed.body
    previous = fm.get("read") if isinstance(fm.get("read"), dict) else {}
    previous_claim = str(previous.get("claim") or "") or None
    described = False
    current = link_enrichment._extract_description_section(body)
    if not link_enrichment._is_substantive(link_enrichment._claim_description(current, min_len), min_len):
        body = link_enrichment._upsert_description(body, summary[: media_ingestor.DESCRIPTION_LIMIT])
        described = True
    closed = None
    if previous_claim and claim_id and previous_claim != claim_id:
        try:
            claims = parse_claims(body, strict=True)
        except MalformedClaimsBlockError:
            claims = None
        if claims is not None:
            old = next((c for c in claims if c.id == previous_claim and c.valid_to is None), None)
            if old is not None:
                old.valid_to = day
                old.superseded_by = claim_id
                body = write_claims(body, claims)
                closed = previous_claim
    stamp = {"by": "agent", "tier": "agent", "at": episode_ids.utc_now_iso(), "v": STAMP_V}
    clean_via = _via(via)
    if clean_via:
        stamp["via"] = clean_via
    if harness:
        stamp["harness"] = harness
    if claim_id:
        stamp["claim"] = claim_id
    fm["read"] = stamp
    fm["enrichment_attempted"] = True
    markdown_parser.write(page, fm, body)
    return described, closed


def _via(via) -> str | None:
    from api.services import reading_asks

    return reading_asks.clean_via(via)


def record(
    memory_path: Path,
    target: Target,
    *,
    summary: str,
    excerpts=None,
    title=None,
    via=None,
    session_frontmatter: dict | None = None,
    author: str = "agent",
    session_id: str | None = None,
    origin: str = ORIGIN,
    recorded_ts: str | None = None,
    min_len: int = 120,
    today: date | None = None,
) -> dict:
    """Write the read episode, the ``describes`` claim, the description and the
    stamp. Never raises on a normal input; returns ``{error}`` or the ids, counts
    and ``paths`` to commit."""
    memory_path = Path(memory_path)
    summary, scrubbed = episode_scrub.scrub(_one_line(summary))
    if not summary:
        return {"error": "a summary is required for a read — say what the page says; nothing was recorded"}
    clipped = len(summary) > MAX_SUMMARY_CHARS
    summary = summary[:MAX_SUMMARY_CHARS].rstrip()
    kept, dropped = _excerpts(excerpts)
    quotes: list[str] = []
    for quote in kept:
        quote, n = episode_scrub.scrub(quote)
        scrubbed += n
        quotes.append(quote)
    clean_title = None
    if title:
        clean_title, n = episode_scrub.scrub(_one_line(title))
        scrubbed += n
        clean_title = clean_title[:MAX_TITLE_CHARS].strip() or None
    episode_scrub.record("mcp", scrubbed, bank=memory_path.name)

    host = reading_hosts.display_host(reading_hosts.host_of(target.url)) or "page"
    label = author if author and author != "agent" else "an agent"
    quote_lines = [f"> {q}" for q in quotes]
    head = f"{MARKER} [{host}]: as {label} read it"
    body = "\n".join([f"assistant: {summary}", *(["", head, *quote_lines] if quote_lines else [])])
    episode_id, created = _write_episode(memory_path, target, body, session_frontmatter or {})
    text = evidence_mod.source_text(memory_path, episode_id) or body
    # Each quote is located inside its OWN line's window: a quote the summary
    # repeats would otherwise land on the `assistant:` line and cite the agent's
    # words as the page's.
    summary_line = f"assistant: {summary}"
    first = {"episode": episode_id, "quote": summary[: evidence_mod.MAX_QUOTE_CHARS]}
    at = text.find(summary_line)
    if at >= 0:
        first["window"] = [at, at + len(summary_line)]
    cites: list[dict] = [first]
    for line, quote in zip(quote_lines, quotes):
        item = {"episode": episode_id, "quote": quote}
        at = text.find("\n" + line)
        if at >= 0:
            item["window"] = [at + 1, at + 1 + len(line)]
        cites.append(item)
    result = agentic_write.write_claim(
        memory_path, target.entity_id, PREDICATE, summary, observer="agent", confidence=0.7,
        context="general", source_episode=episode_id, object_kind="literal",
        text=f"{target.title}: {summary}", session_id=session_id, origin=origin, evidence=cites,
        authored_by=author, recorded_ts=recorded_ts, today=today,
    )
    paths = [f"episodes/{episode_id}.md"]
    if result.get("action") in ("error", "ambiguous_subject", "corrupt_claims_block"):
        if created:
            # Nothing cites this episode and nothing will commit it: left on disk, the next
            # `git add -A` writer would sweep it in under its own author (the G85-class smear).
            try:
                (memory_path / "episodes" / f"{episode_id}.md").unlink()
            except OSError:
                pass
            paths = []
        return {"error": result.get("error") or result.get("action"), "episode_id": episode_id, "paths": paths}
    day = (today or date.today()).isoformat()
    described, closed = _finish_page(
        memory_path, target, summary=summary, min_len=min_len, via=via, harness=author if author != "agent" else "",
        claim_id=result.get("claim_id"), day=day)
    retitled = _apply_title(memory_path, target, clean_title) if clean_title else False
    paths.append(result.get("path") or f"entities/{target.entity_id}.md")
    if retitled:
        paths.append("sources/url_index.json")
    return {"entity_id": target.entity_id, "episode_id": episode_id, "claim_id": result.get("claim_id"),
            "evidence": result.get("evidence") or [], "excerpts": len(quotes), "dropped": dropped,
            "summary_clipped": clipped, "described": described, "closed_claim": closed,
            "retitled": retitled, "paths": paths}
