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

**Facts (read-for-specifics, vision item 1, 2026-10-28).** A read may carry ``facts`` — ``{subject, predicate,
object, quote}``, at most :data:`MAX_FACTS` — the specific things the page states about a thing Cicada already has a
page for (the tool an article reviews, the program a page announces). Each quote joins the episode as one more page
line, and each fact becomes a claim on ITS subject's page (``agentic_write.write_claim``, observer ``agent``) whose
evidence is that line's span (``page``: the page's words as the agent reported them, G118), with the read link as an
untrusted where-to-check source for that fact, linked to the saved-link page (``entity:``). A fact is left out, and
counted, when its subject has no page (a read never makes one), is a person (their facts come from their own words,
``cicada_record_profile`` or ruling 44's public test), or is a happening (``progress`` writes those).

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
MAX_FACTS = 8
MAX_FACT_SUBJECT = 200
MAX_FACT_PREDICATE = 60
MAX_FACT_OBJECT = 300
#: A fact read off a page is the page's claim as an agent reported it — below the read's own ``describes`` (0.7).
FACT_CONFIDENCE = 0.6
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


def _facts(raw) -> tuple[list[dict], int]:
    """``facts`` as ``{subject, predicate, object, quote}`` one-line strings, capped, in the order given, and how many
    were left out (one missing a field, or past :data:`MAX_FACTS`). Scrubbed by the caller."""
    kept: list[dict] = []
    dropped = 0
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            dropped += 1
            continue
        fact = {
            "subject": _one_line(item.get("subject"))[:MAX_FACT_SUBJECT].strip(),
            "predicate": _one_line(item.get("predicate"))[:MAX_FACT_PREDICATE].strip(),
            "object": _one_line(item.get("object"))[:MAX_FACT_OBJECT].strip(),
            "quote": _one_line(item.get("quote")).lstrip("> ").strip()[:MAX_QUOTE_CHARS].rstrip(),
        }
        if not all(fact.values()) or len(kept) >= MAX_FACTS:
            dropped += 1
            continue
        kept.append(fact)
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
    episode_id = episode_ids.create_episode(episodes_dir, frontmatter, body)
    return episode_id, True


def _apply_title(memory_path: Path, target: Target, title: str) -> bool:
    """A page saved without a fetch is titled from its URL ("Post by @<user>" for
    an X post; before 2026-10-22, its bare status id). The agent saw the real title: it replaces the slug, and ONLY
    the slug — a title the person, the reader or a provider gave is never
    overwritten. Both places that hold it move together (the index's ``title``
    is what the Feed lists)."""
    idx = media_ingestor.load_url_index(memory_path)
    entry = idx.get(media_ingestor.url_hash(target.url))
    if not isinstance(entry, dict) or not entry.get("title") \
            or not media_ingestor.is_placeholder_title(target.url, entry.get("title")):
        return False
    slug = str(entry["title"])
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
    facts=None,
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
    fact_items, facts_dropped = _facts(facts)
    for fact in fact_items:
        for key in fact:
            fact[key], n = episode_scrub.scrub(fact[key])
            scrubbed += n
    fact_items = [f for f in fact_items if all(f.values())]
    clean_title = None
    if title:
        clean_title, n = episode_scrub.scrub(_one_line(title))
        scrubbed += n
        clean_title = clean_title[:MAX_TITLE_CHARS].strip() or None
    episode_scrub.record("mcp", scrubbed, bank=memory_path.name)

    host = reading_hosts.display_host(reading_hosts.host_of(target.url)) or "page"
    label = author if author and author != "agent" else "an agent"
    # A fact's quote is one more line of the page's words; one the excerpts already hold is not written twice.
    quotes += [q for q in dict.fromkeys(f["quote"] for f in fact_items) if q not in quotes]
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
    written, skipped = _write_facts(
        memory_path, target, fact_items, text=text, episode_id=episode_id, author=author, session_id=session_id,
        origin=origin, recorded_ts=recorded_ts, today=today)
    for entry in written:
        if entry["path"] not in paths:
            paths.append(entry["path"])
    if facts_dropped:
        skipped["malformed"] = skipped.get("malformed", 0) + facts_dropped
    return {"entity_id": target.entity_id, "episode_id": episode_id, "claim_id": result.get("claim_id"),
            "evidence": result.get("evidence") or [], "excerpts": len(quotes), "dropped": dropped,
            "summary_clipped": clipped, "described": described, "closed_claim": closed,
            "retitled": retitled, "paths": paths, "facts": written, "facts_skipped": skipped}


def _write_facts(memory_path: Path, target: Target, facts: list[dict], *, text: str, episode_id: str, author: str,
                 session_id, origin: str, recorded_ts, today) -> tuple[list[dict], dict[str, int]]:
    """Each fact as a claim on its subject's page (see the module docstring). Returns ``(written, skipped)``:
    ``[{entity_id, claim_id, path, source}]`` and ``{reason: count}``. Never raises on a normal input; never makes a
    page."""
    from api.services import fact_sources
    from api.services.id_utils import resolve_entity_file, sanitize_id

    written: list[dict] = []
    skipped: dict[str, int] = {}

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    remote = str(origin or "").startswith(fact_sources.REMOTE_PREFIX)
    for fact in facts:
        page = resolve_entity_file(memory_path, fact["subject"])
        if page is None:
            skip("no_page")
            continue
        try:
            kind = str((markdown_parser.parse(page).frontmatter or {}).get("type") or "")
        except Exception:  # noqa: BLE001 — an unreadable page takes no fact
            skip("no_page")
            continue
        if kind == "person":
            skip("person")
            continue
        cite = {"episode": episode_id, "quote": fact["quote"]}
        at = text.find("\n> " + fact["quote"])
        if at >= 0:
            cite["window"] = [at + 1, at + 3 + len(fact["quote"])]
        result = agentic_write.write_claim(
            memory_path, page.stem, fact["predicate"], fact["object"], observer="agent",
            confidence=FACT_CONFIDENCE, context="general", source_episode=episode_id, evidence=[cite],
            session_id=session_id, origin=origin, authored_by=author, forbid_owner_observer=True,
            recorded_ts=recorded_ts, today=today,
        )
        action = result.get("action")
        if action in ("error", "ambiguous_subject", "corrupt_claims_block") or not result.get("entity_id"):
            skip("event" if "happening or a milestone" in str(result.get("error") or "") else "refused")
            continue
        entity_id = str(result["entity_id"])
        source = None
        if entity_id != target.entity_id:
            # Where to check this fact: the page the agent read, the agent's own (untrusted until the person takes it),
            # linked to the saved link's page. A removed or full key drops the source, never the claim (G61 S3-a).
            try:
                added = fact_sources.add_source(
                    memory_path, entity_id, target.url, kind=fact_sources.KIND_URL,
                    predicate=sanitize_id(fact["predicate"]) or None, added_by=author or "agent",
                    origin=origin if remote else None, entity=target.entity_id, via_agent=True)
                source = added.get("ref") if added else None
            except fact_sources.InvalidSource:
                source = None
        written.append({"entity_id": entity_id, "claim_id": result.get("claim_id"),
                        "path": result.get("path") or f"entities/{entity_id}.md", "source": source})
    return written, skipped
