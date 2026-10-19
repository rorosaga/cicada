"""ask_memory — auditable natural-language synthesis over the knowledge graph.

The flagship, thesis-novel retrieval surface (decision D3 = BOTH in
``docs/goals/memory-evolution.md``): an answer that **cites its sources** and
**admits what it does not know**. Unlike an opaque RAG substrate, every claim is
traceable back to the markdown entity that grounded it (entity-level citations
now; line-level git-blame citations are a documented follow-up), and thin
evidence produces an explicit *gap* ("I don't have information about X") rather
than a confident hallucination.

The service is dependency-injected for hermetic testing:

- ``retrieve_fn(query, top_k) -> list[hit]`` — defaults to
  :meth:`SqliteVecIndexer.search_entities`. Each hit follows the indexer's
  contract: ``{"score", "text", "metadata": {entity_id, entity_name, type,
  status, confidence, file_path}}``.
- ``llm_fn(prompt) -> str`` — defaults to a litellm JSON-mode call per
  :class:`api.config.Settings`. Returns the model's raw string, which the
  service parses as JSON.

No real embedding/LLM/network calls happen unless the defaults are used, so unit
tests inject both.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from loguru import logger

from api.config import Settings
from api.services import ask_sources, json_parse, markdown_parser, section_provenance, text_fold
from api.services.claims import current_day, is_current, is_event, is_record, parse_claims, stated_end, strip_claims_block

RetrieveFn = Callable[[str, int], list[dict]]
LlmFn = Callable[[str], str]

# Body excerpt length carried into each citation (enough to audit the claim,
# short enough not to dump the whole page into the response).
_SNIPPET_CHARS = 280

# What one retrieved page may put in front of the model (owner, 2026-10-14). The claims and the prose used to share
# ONE 3,000-character budget, claims first: on a hub page (the owner's: ~178 KB, 6,008 claims) the claims took all
# of it and the prose got `body[:remaining]` — one character, the summary "truncated at 'R'" — and the page's other
# names were never sent at all, so "what is the owner's full name?" was answered "only a first name is recorded"
# while eleven aliases held it. Each part now has its own budget, and the header always carries the page's names.
# 2026-10-17 (G148, LoCoMo conv-26): the prose budget was 2,400 characters taken a blank-line paragraph at a time, so a
# page's whole ``## Key Facts`` list was ONE paragraph clipped to 600 characters and the fact a question named — the
# reason for a choice, a count said later — sat past the cut on a page that held it. A page is now read item by item
# (an article paragraph, a key fact, a history line, as ``section_provenance.scan`` cuts it), the items that share
# the question's words chosen first, each dated by the conversations it came from.
_CLAIMS_CHARS = 3000
_PROSE_CHARS = 4800
_LEAD_CHARS = 700
_PARAGRAPH_CHARS = 600
#: The page sections Ask reads as background, in page order. The summary is in the header; open questions are what
#: memory does NOT know, and a stale one beside a newer claim was read as the answer (conv-26: "not stated").
_PROSE_SECTIONS = ("article", "key_facts", "history", "links")
_SECTION_LABELS = {"article": "Article", "key_facts": "Key Facts", "history": "History", "links": "Links"}
_ALIASES_CHARS = 800
_SUMMARY_CHARS = 600
#: Pages after the first three get half of each budget: they are context, not the answer.
_FULL_BUDGET_PAGES = 3
# People linked to a retrieved page (owner, 2026-10-14): "who is helping on <project>?" missed the people recorded on
# the project's page and on a page that links to it — the context never followed a link.
_MAX_LINKED_PEOPLE = 8
_LINK_LINES = 2
_LINK_LINE_CHARS = 240
_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
# The person asking about themselves, the way an agent relays it (G169's forms, plus the possessives a question uses).
_SELF_PHRASES = ("the owner", "the user", "the person", "owner s", "user s", "my", "me", "myself", "mine", "i")
#: A citation names at most this many of its page's conversations: the ones this answer was grounded in (2026-10-18:
#: the owner page's citation listed several hundred ids, every conversation that ever touched the page).
MAX_CITED_EPISODES = 5

ASK_SYSTEM_PROMPT = """You answer questions using ONLY the retrieved memory context below. \
This is a personal knowledge graph; the context is the ONLY source of truth you may use. \
Do NOT use outside knowledge and do NOT invent facts.

You are given ENTITIES with individually labeled claims and legacy body text.

Rules:
1. Ground every claim in the provided entities. If the context does not contain \
the answer, say so plainly — never guess.
2. List the entity ids you actually used in ``used_entities`` (only ids that appear \
in the context).
3. Populate ``gaps`` with explicit, honest statements of what you could NOT answer \
or what is missing from memory (e.g. "No information about the database choice"). \
If you are confident and the context fully answers the question, ``gaps`` may be empty.
4. ``confidence`` is 0.0–1.0 reflecting how well the retrieved context supports your \
answer. Thin or tangential evidence => low confidence and a populated ``gaps`` list.
5. If the context is irrelevant to the question, set a low confidence, give an \
answer that admits you don't know, and explain the gap.
6. Each structured claim carries its validity. Closed claims are history, NEVER \
current beliefs: use closed beliefs only for questions about the past, explicitly state \
their dates and distinguish superseded or withdrawn assertions from facts. \
For current beliefs use only claims with current=true. If only history \
supports a value, report that the current value is unknown. A dated event \
may ground recent progress when labeled with its day, never a continuing state. Unversioned prose \
is background; structured claim validity takes precedence over it.
7. ``also called`` lists other names of the SAME entity — a full name or another spelling \
is often among them. LINKED PEOPLE are people whose pages link to a retrieved entity or that \
it links to; their ``linked`` lines say how. Use them to answer who is involved, and cite them \
by their entity_id.
8. WHAT WAS SAID quotes the conversations the entities cite, word for word, each line dated and \
naming who spoke. Use it for detail the entities leave out and to check them, and cite the entity \
whose claims or lines led there. Only the person's own words are the person's statements: words \
of the assistant or of another person are theirs — say whose they are when you rely on them.
9. Background lines marked ``said <day>``, claims (``valid_from``) and every quote carry the day they \
were said. When two give different values of something that changes (a count, a time, a price, a \
record, a status, a plan), the one said on the later day is the current value and the earlier one \
is history — say which is newer. A quote is not newer for being quoted: a quote from an earlier day \
never overrides a current claim or a line said later. When an undated line and a dated quote \
disagree, give both with what you know of their days instead of choosing. Work out a relative time \
("last week", "next month") against the day it was said, not today.
10. A block COMPUTED FROM THE RECORD NOW (the WATCH HISTORY) was counted from the stored record when \
this question was asked, and the record runs only through the last day it names: it is current \
through that day and says nothing about later days. It outranks one kind of statement only: an \
earlier statement about this memory system itself — that something was not yet imported, read, \
processed or counted — which is about the system's state when it was said; where the block shows \
the record, never repeat such a statement as current. The person's own words are never overridden \
by it: what they say about days after the record's last day is newer than the record; use it for \
those days and say where the record ends.
11. OTHER CONVERSATIONS are lines found by searching every conversation for the question's words; no \
entity cites them. They are the person's record word for word, with rule 8's speakers and rule 9's \
days, but a shared word does not make a line about the question's subject: use a line only when it \
plainly speaks of what the question asks (the same person, thing and event), say the day it was \
said, and list its conversation id in ``used_conversations``. Lines that only share words are not an \
answer; when nothing else answers, say what memory lacks as usual.

Return ONLY a JSON object with exactly these keys:
{
  "answer": "natural-language answer grounded in the context",
  "confidence": 0.0,
  "used_entities": ["entity-id", "..."],
  "used_conversations": ["ep_... id of an OTHER CONVERSATIONS line you used", "..."],
  "gaps": ["explicit gap statement", "..."]
}"""


def _snippet(body: str, limit: int = _SNIPPET_CHARS) -> str:
    text = " ".join((body or "").split())
    return (text[:limit] + "…") if len(text) > limit else text


def _wants_history(query: str) -> bool:
    """Conservative, engine-free intent: default to current beliefs.

    Explicit past/change language or an as-of date also permits labeled history.
    No interpretation here ever converts a closed claim back into a current one.
    """
    return bool(re.search(
        r"\b(history|historical|past|previously|previous|earlier|formerly|former|before|"
        r"used to|as of|back then|changed?|happened|was|were|did|had|"
        r"yesterday|last (?:week|month|year)|in \d{4})\b",
        query, re.IGNORECASE,
    ))


def _claim_context(claim, all_claims) -> dict:
    """``all_claims`` is the page's claims, as a list or (on a hub page, where a scan per claim was quadratic —
    ~1.7 s for 6,008 claims) an ``{id: claim}`` map."""
    current = is_current(claim)
    validity = "current" if current else "history"
    if isinstance(all_claims, dict):
        successor = all_claims.get(claim.superseded_by) if claim.superseded_by else None
    else:
        successor = next((c for c in all_claims if c.id == claim.superseded_by), None) if claim.superseded_by else None
    if not current:
        if successor is not None and is_record(successor):
            validity += "; withdrawn"
        elif claim.superseded_by:
            validity += f"; superseded by {claim.superseded_by}"
        elif claim.valid_to or stated_end(claim):
            validity += f"; until {claim.valid_to or stated_end(claim)}"
        else:
            validity += f"; not yet current (from {claim.valid_from})"
    out = {
        "id": claim.id, "current": current, "validity": validity,
        "valid_from": claim.valid_from, "valid_to": claim.valid_to,
        "expected_end": stated_end(claim), "superseded_by": claim.superseded_by,
        "observer": claim.observer, "context": claim.context,
        "source_trust": claim.source_trust,
    }
    if is_event(claim):
        out.update(event_day=claim.valid_from, event_status=claim.status)
    # Clip TEXT only. The validity envelope always survives intact.
    out["text"] = _snippet(claim.text, limit=320)
    return out


def _history_query(query: str) -> str:
    """Question/temporal words are instructions, not words the old claim must contain."""
    from api.services import text_fold
    stop = set("what which who where how when did was were had does do is are the a an "
               "this that use used to as of in on now current currently previously previous "
               "earlier formerly former before history historical past changed change "
               "happened last week month year yesterday".split())
    query = re.sub(r"\b\d{4}(?:-\d{2}-\d{2})?\b", "", query)
    return " ".join(t for t in text_fold.query_tokens(query) if t not in stop)


def _load_entity(memory_path: Path, entity_id: str) -> dict | None:
    """Read an entity's markdown to back a citation. Returns None if missing."""
    filepath = memory_path / "entities" / f"{entity_id}.md"
    if not filepath.exists():
        return None
    try:
        parsed = markdown_parser.parse(filepath)
    except Exception:
        return None
    fm = parsed.frontmatter or {}
    if fm.get("status") == "dropped":
        return None
    return {
        "entity_id": entity_id,
        "entity_name": str(fm.get("name", entity_id.replace("-", " ").title())),
        "file_path": str(filepath),
        "snippet": _snippet(parsed.body),
        "source_episodes": list(fm.get("source_episodes", []) or []),
        "type": str(fm.get("type", "concept") or "concept"),
        "body": parsed.body or "",
        "aliases": [str(a).strip() for a in (fm.get("aliases") or []) if str(a or "").strip()],
        "summary": _page_summary(fm, parsed.body or ""),
        "frontmatter": fm,
        "related": [str(r).strip() for r in (fm.get("related") or []) if str(r or "").strip()],
        "owner": fm.get("owner") is True,
    }


def _page_summary(fm: dict, body: str) -> str:
    """The page's one-paragraph lead: the frontmatter ``summary`` when a writer kept one, else ``## Summary``."""
    summary = str(fm.get("summary") or "").strip()
    if summary:
        return summary
    from api.services import entity_body

    try:
        return str(entity_body.parse_sections(strip_claims_block(body)).get("Summary") or "").strip()
    except Exception:  # noqa: BLE001 — a page without sections has no lead to add
        return ""


def _coerce_str_list(value) -> list[str]:
    """Normalize an LLM field that should be a list of strings.

    Guards against the common JSON-mode slip where the model returns a bare
    string (``"gaps": "no info"``) instead of a list — iterating that directly
    would shred it into one entry per character. A bare string becomes a
    one-element list; non-string scalars are coerced; non-iterables are dropped.
    """
    if value is None:
        return []
    if isinstance(value, str):
        v = value.strip()
        return [v] if v else []
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            s = str(item).strip()
            if s:
                out.append(s)
        return out
    # Some other scalar (number/bool) — treat as a single value.
    s = str(value).strip()
    return [s] if s else []


def _substring_match(memory_path: Path, query: str, top_k: int) -> list[dict]:
    """Disk-backed substring fallback for a cold/empty vector index.

    Mirrors the graceful-degrade pattern in ``routers/search.py``: when the
    vector index returns nothing on a populated graph (fresh install before the
    index is built), fall back to a name/tag/body substring scan so ``ask`` can
    still ground an answer instead of falsely claiming ignorance. Returns hits in
    the ``search_entities`` shape so the rest of the pipeline is unchanged.
    """
    q = (query or "").lower().strip()
    entities_dir = memory_path / "entities"
    if not q or not entities_dir.exists():
        return []
    scored: list[tuple[int, dict]] = []
    for filepath in sorted(entities_dir.glob("*.md")):
        try:
            parsed = markdown_parser.parse(filepath)
        except Exception:
            continue
        fm = parsed.frontmatter or {}
        name = str(fm.get("name", filepath.stem.replace("-", " "))).lower()
        tags = [str(t).lower() for t in (fm.get("tags", []) or [])]
        relevance = 0
        if q in name:
            relevance += 10
        if any(q in t for t in tags):
            relevance += 5
        body = strip_claims_block(parsed.body or "")
        relevant_claims = [c for c in parse_claims(parsed.body or "")
                           if not is_record(c) and (_wants_history(query) or is_current(c) or (is_event(c) and not c.superseded_by))]
        if q in (body + "\n" + "\n".join(c.text for c in relevant_claims)).lower():
            relevance += 2
        if relevance <= 0:
            continue
        scored.append(
            (
                relevance,
                {
                    "score": float(relevance),
                    "text": parsed.body or "",
                    "metadata": {
                        "entity_id": filepath.stem,
                        "entity_name": str(fm.get("name", filepath.stem)),
                        "type": str(fm.get("type", "concept") or "concept"),
                        "status": str(fm.get("status", "active") or "active"),
                        "confidence": float(fm.get("confidence", 0.5) or 0.0),
                        "file_path": str(filepath),
                    },
                },
            )
        )
    scored.sort(key=lambda x: -x[0])
    return [hit for _, hit in scored[:top_k]]


def _obsolete(rows: list) -> list:
    return [c for c in rows if not is_record(c) and not is_event(c) and not is_current(c)]


def _repeats(sentence: str, obsolete: list) -> bool:
    """Does ``sentence`` repeat a closed claim's text or its literal value?"""
    return any((c.text and c.text.casefold() in sentence.casefold()) or
               (c.object_kind == "literal" and c.object and
                re.search(r"(?<!\w)" + re.escape(c.object) + r"(?!\w)", sentence, re.IGNORECASE))
               for c in obsolete)


def _background(body: str, rows: list, *, include_history: bool) -> str:
    """Keep useful prose, excluding sentences that repeat an obsolete literal."""
    prose = strip_claims_block(body)
    if include_history:
        return prose
    obsolete = _obsolete(rows)
    sentences = re.split(r"(?<=[.!?])\s+|\n", prose)
    return "\n".join(s for s in sentences if not _repeats(s, obsolete))


def _retrieved_entities(memory_path: Path, hits: list[dict], *, include_history: bool = False,
                        query: str = "") -> list[dict]:
    """Map retrieval hits to loaded entity records, de-duped, order preserved."""
    out: list[dict] = []
    seen: set[str] = set()
    for hit in hits:
        meta = hit.get("metadata", {}) or {}
        eid = meta.get("entity_id")
        if not eid or eid in seen:
            continue
        seen.add(eid)
        loaded = _load_entity(memory_path, eid)
        if loaded is None:
            # Indexed text has no trustworthy current validity after deletion.
            continue
        page_claims = parse_claims(loaded["body"])
        eligible = [c for c in page_claims if not is_record(c) and (include_history or is_current(c) or (is_event(c) and not c.superseded_by))]
        terms = _focus(text_fold.subject_terms(query), [loaded])
        eligible.sort(key=lambda c: -len(terms & text_fold.subject_terms(f"{c.text} {c.predicate} {c.object}")))
        if include_history:
            current = [c for c in eligible if is_current(c)]
            history = [c for c in eligible if not is_current(c)]
            # Reserve representation for both sides of a change before the
            # prompt budget is applied; a large current list cannot hide history.
            eligible = [c for pair in zip(history, current) for c in pair] + history[len(current):] + current[len(history):]
        by_id = {c.id: c for c in page_claims}
        loaded["claims"] = [_claim_context(c, by_id) for c in eligible]
        loaded["claim_rows"] = eligible
        loaded["obsolete"] = [] if include_history else _obsolete(page_claims)
        loaded["claim_hit"] = meta.get("claim_id")
        loaded["context_body"] = _background(loaded["body"], page_claims, include_history=include_history)
        if not eligible and not loaded["context_body"].strip():
            continue
        loaded["snippet"] = _snippet("\n".join(
            [f"{c['validity']}: {c['text']}" for c in loaded["claims"]] or [loaded["context_body"]]))
        loaded["score"] = float(hit.get("score", 0.0) or 0.0)
        # Carry claim provenance from a claim-first hit so the citation can point
        # at claim_id + valid-window + observer (M5e). Absent for entity-only hits.
        cited = next((c for c in eligible if c.id == meta.get("claim_id")), None)
        if cited is not None:
            context = _claim_context(cited, by_id)
            loaded["snippet"] = _snippet(f"{context['validity']}: {context['text']}")
            loaded["claim_provenance"] = {
                "claim_id": cited.id, "observer": cited.observer, "context": cited.context,
                "valid_from": cited.valid_from, "valid_to": cited.valid_to,
                "superseded_by": cited.superseded_by, "source_trust": cited.source_trust,
            }
        out.append(loaded)
    return out


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def _prose_context(prose: str, summary: str, terms: set[str], budget: int) -> str:
    """What of a page's prose fits ``budget``: its lead, then the paragraphs that share the most words with the
    question, in page order. The summary is already in the header, so it is not repeated."""
    if budget <= 0 or not (prose or "").strip():
        return ""
    if summary and summary in prose:
        prose = prose.replace(summary, "", 1)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", prose) if p.strip()]
    paragraphs = [p for p in paragraphs if not re.fullmatch(r"#+\s.*", p)]
    if not paragraphs:
        return ""
    chosen: dict[int, str] = {0: _clip(paragraphs[0], min(_LEAD_CHARS, budget))}
    used = len(chosen[0])
    scored = sorted(((len(terms & text_fold.subject_terms(p)), i) for i, p in enumerate(paragraphs) if i),
                    key=lambda row: (-row[0], row[1]))
    for score, i in scored:
        if score <= 0 or used >= budget:
            break
        text = _clip(paragraphs[i], min(_PARAGRAPH_CHARS, budget - used))
        if len(text) < 40:
            break
        chosen[i] = text
        used += len(text) + 2
    return "\n…\n".join(chosen[i] for i in sorted(chosen))


def _header_lines(ent: dict, scale: float) -> list[str]:
    lines = [f"### entity_id: {ent['entity_id']}", f"name: {ent['entity_name']}",
             f"type: {ent.get('type', 'concept')}"]
    if ent.get("owner"):
        lines.append("this is the page of the person this memory belongs to")
    aliases = [a for a in ent.get("aliases") or [] if a != ent["entity_name"]]
    if aliases:
        lines.append("also called: " + _clip("; ".join(aliases), int(_ALIASES_CHARS * scale)))
    if ent.get("summary"):
        lines.append("summary: " + _clip(ent["summary"], int(_SUMMARY_CHARS * scale)))
    return lines


def _focus(terms: set[str], entities: list[dict]) -> set[str]:
    """The question's words less the retrieved pages' own names: "Caroline" is on every line of Caroline's page and
    in every turn addressed to her, so it ranks nothing. A question made only of names keeps them."""
    names: set[str] = set()
    for ent in entities:
        for name in (ent.get("entity_name"), ent.get("entity_id", "").replace("-", " "), *(ent.get("aliases") or [])):
            names |= text_fold.subject_terms(str(name or ""))
    return (terms - names) or terms


def _said_days(rows) -> str:
    """``said 2023-08-11, 2023-09-30`` — the days of the conversations a page line came from (its provenance rows),
    the latest two; empty when the line cites none."""
    days = sorted({d for d in (ask_sources.episode_day(getattr(ev, "episode", "")) for ev in rows or []) if d})
    return ("said " + ", ".join(days[-2:])) if days else ""


def _page_lines(ent: dict, terms: set[str], budget: int) -> tuple[str, list]:
    """What of a page's prose fits ``budget``, item by item (``section_provenance.scan``): the article's lead, then
    the items sharing the most of the question's words, in page order under their section, each with the days it
    was said. Returns ``(text, pointers)`` — the pointers (``ask_sources.Pointer``) are where the chosen items came
    from, weighted by the question's words each shares (0 for none), for :mod:`ask_sources` and the citation. A page
    with no canonical section falls back to its paragraphs."""
    if budget <= 0:
        return "", []
    body = ent.get("body", "") or ""
    try:
        items = section_provenance.scan(body)
        provenance = section_provenance.matched(ent.get("frontmatter") or {}, body)
    except Exception:  # noqa: BLE001 — a page that does not scan is read as paragraphs
        items, provenance = {}, {}
    rows = []
    obsolete = ent.get("obsolete") or []
    for section in _PROSE_SECTIONS:
        for item in items.get(section, []):
            text = item.text.strip()
            if not text or (obsolete and _repeats(text, obsolete)):
                continue
            evs = (provenance.get(section, {}).get(item.key) or (None, []))[1]
            rows.append({"section": section, "text": text, "evidence": evs,
                         "score": len(terms & text_fold.subject_terms(text))})
    if not rows:
        return _prose_context(ent.get("context_body", ""), ent.get("summary", ""), terms, budget), []
    chosen: set[int] = set()
    used = 0
    lead = next((i for i, r in enumerate(rows) if r["section"] == "article"), None)
    if lead is not None:
        chosen.add(lead)
        used += min(len(rows[lead]["text"]), _LEAD_CHARS)
    else:
        # No article: the page's first items stand in for its lead, as the first paragraph always did.
        for i, row in enumerate(rows):
            if row["section"] != rows[0]["section"] or used + len(row["text"]) > _LEAD_CHARS:
                break
            chosen.add(i)
            used += len(row["text"]) + 24
    for i in sorted((i for i, r in enumerate(rows) if r["score"] > 0), key=lambda i: (-rows[i]["score"], i)):
        if used >= budget:
            break
        if i in chosen:
            continue
        chosen.add(i)
        used += min(len(rows[i]["text"]), _PARAGRAPH_CHARS) + 24
    lines: list[str] = []
    found: list = []
    section = None
    for i in sorted(chosen):
        row = rows[i]
        if row["section"] != section:
            section = row["section"]
            lines.append(f"{_SECTION_LABELS[section]}:")
        limit = _LEAD_CHARS if i == lead and row["score"] <= 0 else _PARAGRAPH_CHARS
        said = "" if section == "history" else _said_days(row["evidence"])
        lines.append(f"- {'[' + said + '] ' if said else ''}{_clip(row['text'], limit)}")
        # Every chosen item's conversations ground the page's citation; only the ones sharing the question's words
        # (weight > 0) lead to WHAT WAS SAID (``ask_sources.gather`` skips weight 0).
        found += ask_sources.pointers(row["evidence"], row["score"], text_fold.subject_terms(row["text"]))
    return "\n".join(lines), found


_ENVELOPE = frozenset({"id", "current", "validity", "valid_from", "valid_to", "text"})


def _ground(grounds: dict[str, int], pointed: list) -> None:
    for p in pointed:
        grounds[p.episode] = max(grounds.get(p.episode, 0), p.weight)


def _cited_episodes(ent: dict) -> tuple[list[str], int]:
    """``(episodes, more)`` for a page's citation: the conversations this answer was grounded in — the ones whose
    words reached the model first, then by the question's words the claim or line pointing there shares, newest first
    — at most :data:`MAX_CITED_EPISODES`; with nothing pointed (claims with no evidence, a linked person), the page's
    newest conversations. ``more`` counts the page's other conversations, for "+N more"."""
    every = [str(e) for e in dict.fromkeys(ent.get("source_episodes") or []) if str(e or "").strip()]
    grounds: dict[str, int] = ent.get("grounding") or {}
    spoken: set[str] = ent.get("spoken") or set()
    if grounds:
        order = sorted(sorted(grounds, reverse=True), key=lambda ep: (ep not in spoken, -grounds[ep]))
    else:
        order = sorted(every, reverse=True)
    shown = order[:MAX_CITED_EPISODES]
    return shown, len(set(every) | set(grounds)) - len(shown)


def _compact(claim: dict) -> dict:
    """A claim's context without its empty optional fields; the validity envelope always stays whole."""
    return {k: v for k, v in claim.items() if k in _ENVELOPE or (v is not None and v != "" and v != [])}


def _conversation_refs(excerpts: list) -> dict[str, dict]:
    """``{episode_id: {"title", "day"}}`` of the conversations the search leg showed, in the order first shown."""
    out: dict[str, dict] = {}
    for e in excerpts:
        out.setdefault(e.episode, {"title": e.title, "day": e.day})
    return out


def _build_prompt(query: str, entities: list[dict], *, memory_path: Path | None = None,
                  source_words: bool = False, owner_name: str | None = None,
                  searched: "ask_sources.Searched | None" = None, shown: dict | None = None) -> str:
    """The model's context. ``source_words`` adds WHAT WAS SAID (:mod:`ask_sources`): the conversations' own words
    behind the claims and lines shown, read from ``memory_path`` now — off for a caller without the person's
    verbatim words (a remote connector without ``sources``). ``searched`` (with ``source_words`` only) adds OTHER
    CONVERSATIONS: the turns of the conversations the question's own words find, past what the pages point at;
    ``shown`` receives ``{"conversations": {episode_id: {title, day}}}`` for them."""
    terms = _focus(text_fold.subject_terms(query), [e for e in entities if not e.get("linked_from")])
    blocks: list[str] = []
    people: list[dict] = []
    found: list = []
    for rank, ent in enumerate(entities):
        if ent.get("linked_from"):
            people.append(ent)
            continue
        scale = 1.0 if rank < _FULL_BUDGET_PAGES else 0.5
        claim_lines = []
        remaining = int(_CLAIMS_CHARS * scale)
        rows = ent.get("claim_rows") or []
        # The conversations behind what this page put in front of the model, by the question's words they share:
        # what its citation names (`_cited_episodes`), never every conversation that ever touched the page.
        grounds: dict[str, int] = {}
        for i, claim in enumerate(ent.get("claims", [])):
            line = "claim: " + json.dumps(_compact(claim), ensure_ascii=False)
            if len(line) > remaining:
                break
            claim_lines.append(line)
            remaining -= len(line) + 1
            if i < len(rows):
                row = rows[i]
                words = text_fold.subject_terms(f"{row.text} {row.predicate} {row.object}")
                weight = len(terms & words)
                pointed = ask_sources.pointers(row.evidence, weight, words)
                _ground(grounds, pointed)
                if weight:
                    found += pointed
        prose, pointed = _page_lines(ent, terms, int(_PROSE_CHARS * scale))
        _ground(grounds, pointed)
        found += [p for p in pointed if p.weight > 0]
        ent["grounding"] = grounds
        blocks.append(
            "\n".join(_header_lines(ent, scale))
            + ("\n" + "\n".join(claim_lines) if claim_lines else "")
            + (f"\nunversioned background — may be outdated; never contradict current=true claims:\n{prose}"
               if prose else "")
        )
    context = "\n\n".join(blocks)
    if people:
        context += "\n\nLINKED PEOPLE (pages linked to the entities above):\n\n" + "\n\n".join(
            "\n".join(_header_lines(p, 0.5) + [f"linked: {line}" for line in p.get("linked_lines", [])])
            for p in people)
    excerpts: list = []
    if source_words and memory_path is not None and found:
        try:
            excerpts = ask_sources.gather(memory_path, query, found, owner_name=owner_name, terms=terms)
            said = ask_sources.render(excerpts)
        except Exception as exc:  # noqa: BLE001 — the words are context; their absence never fails an answer
            logger.debug(f"ask source words skipped ({type(exc).__name__})")
            excerpts, said = [], ""
        spoken = {e.episode for e in excerpts}
        for ent in entities:
            ent["spoken"] = spoken & set(ent.get("grounding") or ())
        if said:
            context += ("\n\nWHAT WAS SAID (word for word, from the conversations the claims and lines above cite; "
                        "oldest first):\n" + said)
    if source_words and memory_path is not None and searched is not None and searched.episodes:
        try:
            more = ask_sources.gather_search(memory_path, query, searched, owner_name=owner_name,
                                             taken=ask_sources.shown_turns(excerpts))
        except Exception as exc:  # noqa: BLE001 — the words are context; their absence never fails an answer
            logger.debug(f"ask search leg skipped ({type(exc).__name__})")
            more = []
        if more:
            if shown is not None:
                shown["conversations"] = _conversation_refs(more)
            context += ("\n\nOTHER CONVERSATIONS (word for word, found by searching every conversation for the "
                        "question's words; no page above cites these lines, so they may be about something else; "
                        "each names its conversation's id; oldest first):\n"
                        + ask_sources.render(more, with_episode=True))
    return (
        f"QUESTION:\n{query}\n\n"
        f"CURRENT LOCAL DAY: {current_day().isoformat()}\n"
        f"RETRIEVED MEMORY CONTEXT ({len(entities)} entities):\n\n{context}"
    )


# --------------------------------------------------------------------------- #
# Linked people and the person's own page (owner, 2026-10-14)
# --------------------------------------------------------------------------- #


def _key(text: str) -> str:
    return " ".join(text_fold.words(text))


def _says(text: str, names: list[str]) -> bool:
    """Does ``text`` say one of ``names`` as whole words (folded)?"""
    folded = f" {_key(text)} "
    return any(name and f" {name} " in folded for name in names)


class _People:
    """The bank's person pages and its owner page, from the cached frontmatter scan (``bank_index``)."""

    def __init__(self, memory_path: Path):
        from api.services import bank_index

        self.memory_path = memory_path
        self.pages: dict[str, dict] = {}
        self.by_name: dict[str, str] = {}
        self.owner: str | None = None
        for f in bank_index.files(memory_path, "entities"):
            fm = f.frontmatter or {}
            if fm.get("owner") is True and self.owner is None:
                self.owner = f.stem
            if str(fm.get("type") or "") != "person" or str(fm.get("status") or "") in ("dropped", "archived"):
                continue
            self.pages[f.stem] = fm
            for name in (fm.get("name"), *(fm.get("aliases") or []), f.stem.replace("-", " ")):
                key = _key(str(name or ""))
                if len(key) >= 3:
                    self.by_name.setdefault(key, f.stem)

    def resolve(self, ref: str) -> str | None:
        ref = str(ref or "").strip()
        if ref in self.pages:
            return ref
        return self.by_name.get(_key(ref))

    def find_in(self, text: str) -> list[str]:
        """The person pages ``text`` names by a name or an alias, as whole words — by n-gram lookup, so a hub page's
        thousands of claims cost a dictionary probe per word, never a scan of every person per line."""
        if not self.by_name:
            return []
        if not hasattr(self, "_longest"):
            self._longest = max(len(k.split()) for k in self.by_name)
        words = text_fold.words(text)
        out: list[str] = []
        for i in range(len(words)):
            for n in range(min(self._longest, len(words) - i), 0, -1):
                pid = self.by_name.get(" ".join(words[i:i + n]))
                if pid and pid not in out:
                    out.append(pid)
                    break
        return out

    def names(self, person_id: str) -> list[str]:
        fm = self.pages.get(person_id) or {}
        out = [_key(str(n or "")) for n in (fm.get("name"), *(fm.get("aliases") or []), person_id.replace("-", " "))]
        return [n for n in dict.fromkeys(out) if len(n) >= 3]


def _mentions_owner(query: str) -> bool:
    folded = f" {_key(query)} "
    return any(f" {phrase} " in folded for phrase in _SELF_PHRASES)


def _pin_owner(hits: list[dict], query: str, people: "_People | None") -> list[dict]:
    """A question about the person themselves ("the owner's full name", "who helps me…") reads their page first,
    whatever the vectors ranked — a hub page's 6,000 claims make it a poor nearest neighbour for any one question."""
    if people is None or people.owner is None or not _mentions_owner(query):
        return hits
    if any((h.get("metadata") or {}).get("entity_id") == people.owner for h in hits):
        return hits
    pinned = {"score": 1.0, "text": "", "metadata": {"entity_id": people.owner, "entity_name": people.owner,
                                                     "type": "person", "status": "active", "file_path": ""}}
    return [pinned, *hits]


def _linked_people(memory_path: Path, entities: list[dict], query: str, people: "_People | None") -> list[dict]:
    """The people linked to the retrieved pages, at most :data:`_MAX_LINKED_PEOPLE`, each with the lines that link
    them: a claim or a wikilinked sentence on the page, its ``related`` list, and person pages whose own ``related``
    or claims name the page (a backlink). The owner's page is never a source (it links to everyone) and never a
    linked person (the question is about who ELSE). Ranked by the words the lines share with the question, then by
    where they were found — never by confidence."""
    if people is None or not people.pages:
        return []
    shown = {e["entity_id"] for e in entities}
    terms = text_fold.subject_terms(query)
    found: dict[str, dict] = {}

    def note(person_id: str | None, source: dict, line: str, order: int) -> None:
        if not person_id or person_id in shown or person_id == people.owner or person_id == source["entity_id"]:
            return
        row = found.setdefault(person_id, {"order": order, "lines": [], "from": source["entity_id"]})
        line = _clip(line, _LINK_LINE_CHARS)
        if line and line not in row["lines"] and len(row["lines"]) < _LINK_LINES:
            row["lines"].append(line)

    order = 0
    for ent in entities:
        if ent.get("owner") or ent["entity_id"] == people.owner:
            continue
        page_id, page_name = ent["entity_id"], ent["entity_name"]
        page_names = [n for n in {_key(page_name), _key(page_id.replace("-", " ")), *map(_key, ent.get("aliases") or [])}
                      if len(n) >= 3]
        try:
            rows = parse_claims(ent.get("body", ""))
        except Exception:  # noqa: BLE001 — an unreadable fence links nobody
            rows = []
        for claim in rows:
            if is_record(claim) or not (is_current(claim) or is_event(claim)):
                continue
            targets = [people.resolve(claim.object)] if claim.object_kind != "literal" else []
            for target in [t for t in targets if t] or people.find_in(claim.text):
                order += 1
                note(target, ent, f"{page_name}: {claim.text}", order)
        prose = strip_claims_block(ent.get("body", ""))
        for sentence in re.split(r"(?<=[.!?])\s+|\n", prose):
            plain = _WIKILINK.sub(lambda m: m.group(1), sentence)
            linked = [people.resolve(ref) for ref in _WIKILINK.findall(sentence)]
            for target in dict.fromkeys([t for t in linked if t] + people.find_in(plain)):
                order += 1
                note(target, ent, f"{page_name}: {plain}", order)
        for ref in ent.get("related") or []:
            order += 1
            note(people.resolve(ref), ent, f"{page_name} lists them as related", order)
        for person_id, fm in people.pages.items():
            related = [str(r or "") for r in (fm.get("related") or [])]
            if any(r == page_id or _key(r) in page_names for r in related):
                order += 1
                note(person_id, ent, f"their page lists {page_name} as related", order)

    for person_id, row in found.items():
        # The person's own page: what it says about the page that linked them (a claim naming it, else its lead).
        loaded = _load_entity(memory_path, person_id)
        row["loaded"] = loaded
        if loaded is None:
            continue
        source = next((e for e in entities if e["entity_id"] == row["from"]), None)
        source_names = [_key(source["entity_name"]), _key(source["entity_id"].replace("-", " "))] if source else []
        try:
            own = parse_claims(loaded["body"])
        except Exception:  # noqa: BLE001
            own = []
        for claim in own:
            if is_record(claim) or not is_current(claim):
                continue
            if (source and claim.object == source["entity_id"]) or _says(claim.text, source_names):
                line = _clip(f"{loaded['entity_name']}: {claim.text}", _LINK_LINE_CHARS)
                if line not in row["lines"]:
                    row["lines"].insert(0, line)
                break
        row["score"] = len(terms & text_fold.subject_terms(" ".join(row["lines"])))

    ranked = sorted(((pid, row) for pid, row in found.items() if row.get("loaded") is not None),
                    key=lambda item: (-item[1]["score"], item[1]["order"]))
    out = []
    for person_id, row in ranked[:_MAX_LINKED_PEOPLE]:
        loaded = dict(row["loaded"])
        loaded.update(linked_from=row["from"], linked_lines=row["lines"][:_LINK_LINES + 1], claims=[],
                      context_body="", snippet=_snippet(" ".join(row["lines"])), score=0.0)
        out.append(loaded)
    return out


def _owner_name(memory_path: Path, entities: list[dict], people: "_People | None") -> str | None:
    """The name of the person this memory belongs to, for labelling their own words; ``None`` when the bank has no
    owner page."""
    for ent in entities:
        if ent.get("owner"):
            return ent["entity_name"]
    owner = people.owner if people is not None else None
    loaded = _load_entity(memory_path, owner) if owner else None
    return loaded["entity_name"] if loaded else None


def _clamp_confidence(value, default: float) -> float:
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, conf))


def _watch_history_lines(memory_path: Path, query: str) -> list[str]:
    """The watch-history lines a question about watching is answered from; ``[]`` for any other question or on any
    failure (the record is context, its absence never fails an answer)."""
    try:
        from api.services import watch_history

        if not watch_history.is_about_watching(query, memory_path):
            return []
        return watch_history.lookup(memory_path, query)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"ask watch history skipped ({type(exc).__name__})")
        return []


def _gap_response(query: str) -> dict:
    """The honest-ignorance answer when nothing relevant was retrieved."""
    return {
        "answer": (
            f"I don't have information in memory to answer that. Nothing in the "
            f"knowledge graph matches \"{query}\"."
        ),
        "confidence": 0.05,
        "citations": [],
        "gaps": [
            f"No entities in memory relate to: {query}",
        ],
        "used_entities": [],
        "conversations": [],
    }


def _default_llm_fn(settings: Settings | None = None) -> LlmFn:
    """Production LLM call: litellm JSON-mode per Settings, via the provider
    seam. ``settings`` (R-E23): the router passes the copy
    ``engine_select.resolve_settings`` returned, so Ask runs on the engine
    chosen in Settings → Engines; ``None`` keeps the env resolution MCP's
    ``cicada_ask`` still uses this round (Track R adopts this seam when it
    moves the tool bodies into ``mcp_tools``)."""
    import litellm

    from api.config import get_settings
    from api.services.providers import resolve_llm_fn

    settings = settings or get_settings()
    llm_fn = resolve_llm_fn(settings, model=settings.litellm_model, completion=litellm.completion, stage="ask")

    def _call(prompt: str) -> str:
        response = llm_fn(
            messages=[
                {"role": "system", "content": ASK_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content or ""

    return _call


def _default_retrieve_fn(memory_path: Path) -> RetrieveFn:
    """The default retrieve seam — **claim-first** with an entity fallback (M5e)."""
    return build_claim_first_retrieve_fn(memory_path)


def build_claim_first_retrieve_fn(memory_path, *, embed_fn=None) -> RetrieveFn:
    """Claim-first retrieval that degrades to entity search on un-consolidated banks.

    Strategy (D2 "Retrieval / /ask", reduced to what the ask pipeline consumes):

    1. **KNN over the derived ``claims`` index** (``search_claims`` — only
       currently-valid, non-superseded claims). Each claim hit is mapped back to
       its **subject entity** so the rest of the ask pipeline (citations, prompt
       building) is unchanged; the claim's provenance (``claim_id``, ``observer``,
       ``context``, ``valid_from``, ``source_trust``) rides along in the hit
       metadata so a citation can point at the claim + its valid-window + observer.
    2. **1-hop graph expansion:** the claim's ``object`` (when it is a node) is
       added as a low-weight neighbour subject so relational depth is retrievable.
    3. **Entity fallback:** when the bank has **no claims yet** (legacy /
       un-consolidated), fall back to ``search_entities`` so ``/ask`` never
       regresses on a graph that was indexed before M5 consolidation.

    ``embed_fn`` is injected by hermetic tests; ``None`` resolves the production
    embedder inside the indexer.
    """
    from api.services.id_utils import resolve_entity_file
    from api.services.vector_index import SqliteVecIndexer

    memory_path = Path(memory_path)
    indexer = SqliteVecIndexer(memory_path, embed_fn=embed_fn)

    def _subject_to_entity_id(subject: str) -> str | None:
        page = resolve_entity_file(memory_path, subject)
        return page.stem if page is not None else None

    def _claim_hit_to_entity_hit(hit: dict) -> dict | None:
        meta = hit.get("metadata", {}) or {}
        subject = str(meta.get("subject", "") or "")
        entity_id = _subject_to_entity_id(subject) or subject
        if not entity_id:
            return None
        return {
            "score": float(hit.get("score", 0.0) or 0.0),
            "text": hit.get("text", "") or "",
            "metadata": {
                "entity_id": entity_id,
                "entity_name": entity_id.replace("-", " ").title(),
                "type": "concept",
                "status": "active",
                "confidence": float(meta.get("confidence", 0.5) or 0.5),
                "file_path": str(meta.get("file_path", "")),
                # claim provenance carried into the citation (M5e contract):
                "claim_id": meta.get("claim_id"),
                "observer": meta.get("observer"),
                "context": meta.get("context"),
                "valid_from": meta.get("valid_from"),
                "valid_to": meta.get("valid_to"),
                "superseded_by": meta.get("superseded_by"),
                "source_trust": meta.get("source_trust"),
                "predicate": meta.get("predicate"),
                "object": meta.get("object"),
            },
        }

    def _retrieve(query: str, top_k: int) -> list[dict]:
        try:
            claim_hits = indexer.search_claims(query, top_k=top_k) or []
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"claim search failed, falling back to entities: {exc}")
            claim_hits = []

        if _wants_history(query):
            from api.services import search_index, search_service
            try:
                state = search_index.ensure_fresh(memory_path)
                if state == "building":
                    search_index.ensure_fresh(memory_path, wait=True)
                history = search_service.search(memory_path, _history_query(query), kinds=("claim",),
                                                mode="prefix", per_kind=top_k)
                claim_hits = [{"score": h.score, "text": h.name,
                               "metadata": {"claim_id": h.id, "subject": h.subject_id,
                                            "valid_from": h.valid_from, "valid_to": h.valid_to,
                                            "superseded_by": h.superseded_by}}
                              for h in history.results] + claim_hits
            except Exception as exc:
                logger.debug(f"ask history index unavailable ({type(exc).__name__})")

        if not claim_hits:
            # No claims in this bank (un-consolidated) — graceful entity fallback.
            return indexer.search_entities(query, top_k=top_k)

        # Map claim hits → subject-entity hits, preserving order + de-duping by
        # entity (keep the strongest-scoring claim per subject).
        out: list[dict] = []
        seen: set[str] = set()
        neighbours: list[str] = []
        for hit in claim_hits:
            mapped = _claim_hit_to_entity_hit(hit)
            if mapped is None:
                continue
            eid = mapped["metadata"]["entity_id"]
            if eid not in seen:
                seen.add(eid)
                out.append(mapped)
            # 1-hop expansion: the claim's object node becomes a neighbour subject.
            obj = str(hit.get("metadata", {}).get("object", "") or "")
            if obj and obj not in neighbours:
                neighbours.append(obj)

        # Add object-neighbours (1-hop) as low-weight grounding if room remains.
        for obj in neighbours:
            if len(out) >= top_k:
                break
            eid = _subject_to_entity_id(obj)
            if not eid or eid in seen:
                continue
            seen.add(eid)
            out.append({
                "score": 0.1,
                "text": "",
                "metadata": {
                    "entity_id": eid,
                    "entity_name": eid.replace("-", " ").title(),
                    "type": "concept",
                    "status": "active",
                    "confidence": 0.5,
                    "file_path": "",
                },
            })

        return out[:top_k]

    return _retrieve


def answer_query(
    memory_path,
    query: str,
    top_k: int = 6,
    *,
    retrieve_fn: RetrieveFn | None = None,
    llm_fn: LlmFn | None = None,
    no_engine: bool | None = None,
    source_words: bool = True,
    search_fn: Callable[[Path, str], "ask_sources.Searched"] | None = None,
) -> dict:
    """Synthesize an auditable, gap-aware answer grounded only in retrieved memory.

    ``no_engine``: the engine the caller resolved would call an API model with no key
    (``engine_readiness.key_missing``); ``None`` asks the environment's settings when no ``llm_fn`` is given.

    ``source_words``: put the conversations' own words behind the shown claims and lines in front of the model
    (:mod:`ask_sources`, read now, never stored). ``False`` for a caller that may not see the person's verbatim
    words — a remote connector without the ``sources`` scope (G135 R-R22).

    ``search_fn(memory_path, query)``: the conversations the question's words find (default
    :func:`ask_sources.search`, the derived indexes only); their matching turns reach the model as OTHER
    CONVERSATIONS, past what the pages point at — with ``source_words`` only. Injected by hermetic tests.

    Returns a dict with: ``answer``, ``confidence`` (0..1 float), ``citations``
    (entity-level, each ``{entity_id, entity_name, file_path, snippet,
    source_episodes, source_episodes_more}`` — the conversations this answer was grounded in, at most
    :data:`MAX_CITED_EPISODES`, and how many more the page has), ``gaps`` (explicit list of what could not be answered),
    ``used_entities`` (the retrieved ids), and ``conversations`` (``{episode_id, title, day}`` of the OTHER
    CONVERSATIONS the answer used).
    """
    memory_path = Path(memory_path)
    query = (query or "").strip()

    # Empty/whitespace query: nothing to ground on — short-circuit before
    # spending a retrieval + LLM round-trip on garbage.
    if not query:
        return _gap_response(query)

    retrieve = retrieve_fn or _default_retrieve_fn(memory_path)
    try:
        hits = retrieve(query, top_k) or []
    except Exception as exc:  # noqa: BLE001 — retrieval must never crash the answer
        logger.warning(f"ask retrieval failed: {exc}")
        hits = []
    try:
        people = _People(memory_path)
    except Exception as exc:  # noqa: BLE001 — links are context; their absence never fails an answer
        logger.debug(f"ask people scan unavailable ({type(exc).__name__})")
        people = None
    hits = _pin_owner(hits, query, people)

    include_history = _wants_history(query)
    entities = _retrieved_entities(memory_path, hits, include_history=include_history, query=query)

    # Cold-index degrade: the vector index found nothing, but entities may exist
    # on disk (fresh install before the index is built). Fall back to a
    # substring scan so we don't falsely claim ignorance on a populated graph —
    # same graceful pattern as routers/search.py.
    if not entities:
        fallback_hits = _substring_match(memory_path, query, top_k)
        entities = _retrieved_entities(memory_path, fallback_hits, include_history=include_history, query=query)

    # Owner ruling 2026-10-18: watch history is a record to look up. A question about watching reads it here,
    # engine-free (`watch_history.lookup`) — the lines are what the platform recorded, never the person's words,
    # and go to the model only for a caller that may see the record's own text (`source_words`).
    watched = _watch_history_lines(memory_path, query) if source_words else []

    # 2026-10-19: the conversations the question's own words find. Ask is page-first, and a conversation's words
    # reached the model only through a shown page's evidence or provenance — when Sleep left the detail off the page,
    # or the page holding it was not retrieved, it never arrived although episode search ranked that conversation in
    # its top five (the owner's eval: 16 of 25 misses; their words reached the prompt for 5). Verbatim words, so
    # only for a caller that may see them (`source_words`, R-R22).
    searched = None
    if source_words:
        try:
            searched = (search_fn or ask_sources.search)(memory_path, query)
        except Exception as exc:  # noqa: BLE001 — the leg is context; its absence never fails an answer
            logger.debug(f"ask search leg skipped ({type(exc).__name__})")

    # Honest-gap fast path: nothing to ground on => do NOT call the LLM, do NOT
    # hallucinate. This is the key auditable-synthesis behaviour.
    if not entities and not watched and not (searched and searched.episodes):
        return _gap_response(query)

    if entities:
        try:
            entities = entities + _linked_people(memory_path, entities, query, people)
        except Exception as exc:  # noqa: BLE001 — links are context; their absence never fails an answer
            logger.debug(f"ask linked people skipped ({type(exc).__name__})")

    retrieved_ids = [e["entity_id"] for e in entities]
    shown: dict = {}
    prompt = _build_prompt(query, entities, memory_path=memory_path, source_words=source_words,
                           owner_name=_owner_name(memory_path, entities, people) if source_words else None,
                           searched=searched, shown=shown)
    conversations: dict[str, dict] = shown.get("conversations") or {}
    if not entities and not watched and not conversations:
        # The words found nothing a turn holds: still nothing to ground on.
        return _gap_response(query)
    if watched:
        from datetime import datetime

        # 2026-10-18: an agent's note from earlier the same day ("the history has not been read yet") outranked the
        # record it was about. The block says when it was computed, so rule 9's "later wins" and rule 10 apply.
        # Review of #341: an export is a snapshot that ends on its last watched day — the person's own later words
        # ("I've been watching <channel> daily this month") are newer than it and are never overridden.
        from api.services import watch_history

        now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
        try:
            last = watch_history.last_day(memory_path)
        except Exception:  # noqa: BLE001 — the header names the end when it can
            last = None
        through = (f"the record runs through {last.isoformat()} and is current only through that day — the "
                   f"person's own words about later days are newer than it" if last else
                   "the record is current only through its last watched day")
        prompt += (f"\n\nWATCH HISTORY — COMPUTED FROM THE RECORD NOW ({now}, when this question was asked; "
                   f"{through}). What was watched, as the platform recorded it: a record, not the person's words "
                   "and not an entity. A line naming an episode in brackets is one watched day or a month's "
                   "summary; a range's table is counted from the watched days. Answer questions about watching "
                   "from it and say the days or the range. It outranks only an earlier statement about the system "
                   "itself: never repeat that the history was not yet imported, read or counted:\n"
                   + "\n".join(watched))

    from api.services import engine_readiness

    if no_engine is None and llm_fn is None:
        from api.config import get_settings

        no_engine = engine_readiness.key_missing(get_settings())
    if no_engine:
        # Owner decision 2 (2026-10-16): with no engine here, say so — never a keyless call that fails into "could
        # not synthesize". The pages it found are still named.
        names = _found_names(entities, watched, conversations)
        return {
            "answer": f"{engine_readiness.ASK_NO_ENGINE} Relevant pages: {names}.",
            "confidence": 0.0,
            "citations": _citations_for(entities, retrieved_ids),
            "gaps": ["No engine to answer with on this machine."],
            "used_entities": retrieved_ids,
            "conversations": _conversation_list(conversations, list(conversations)),
        }
    llm = llm_fn or _default_llm_fn()
    parsed: dict | None = None
    try:
        raw = llm(prompt)
        parsed = json_parse.parse_json_object(raw)
        if not isinstance(parsed, dict):
            parsed = None
    except Exception as exc:  # noqa: BLE001 — malformed reply must degrade, not 500
        logger.warning(f"ask synthesis parse failed: {exc}")
        parsed = None

    if parsed is None:
        # Degrade to an honest low-confidence answer over the retrieved entities
        # rather than inventing content from a broken model reply.
        names = _found_names(entities, watched, conversations)
        return {
            "answer": (
                "I retrieved related memory but could not synthesize a reliable "
                f"answer. Relevant entities: {names}."
            ),
            "confidence": 0.15,
            "citations": _citations_for(entities, retrieved_ids),
            "gaps": ["Could not synthesize a grounded answer from the retrieved context."],
            "used_entities": retrieved_ids,
            "conversations": _conversation_list(conversations, list(conversations)),
        }

    answer = str(parsed.get("answer", "")).strip()
    # Coerce list-shaped fields defensively: a model may return a bare string,
    # which must not be iterated character-by-character into the flagship fields.
    gaps = _coerce_str_list(parsed.get("gaps"))
    cited_raw = _coerce_str_list(parsed.get("used_entities"))
    # The OTHER CONVERSATIONS the model says it used — only ids that were shown. Omitted: every one shown (the same
    # fallback as entities); an id put in used_entities instead is moved here, never read as an invented entity.
    named = _coerce_str_list(parsed.get("used_conversations")) if "used_conversations" in parsed else None
    used_conversations = [c for c in (named if named is not None else list(conversations)) if c in conversations]
    used_conversations += [c for c in cited_raw if c in conversations and c not in used_conversations]
    if watched or conversations:
        # A watch-history line names its day's episode, an OTHER CONVERSATIONS line its conversation: an id taken
        # from one is not an invented entity.
        cited_raw = [c for c in cited_raw if not c.startswith("ep_")]
    # Only entities that were actually retrieved may be cited — drop any id the
    # model invented (anti-hallucination guard on the citation set).
    used = [eid for eid in cited_raw if eid in retrieved_ids]
    # Distinguish "model omitted used_entities" (benign: fall back to retrieved)
    # from "model cited only hallucinated ids" (a grounding failure: do NOT
    # silently attribute the answer to entities the model said it did not use).
    model_named_sources = bool(cited_raw)
    all_cited_invalid = model_named_sources and not used

    # Default confidence is conservative; an empty answer is itself a gap.
    confidence = _clamp_confidence(parsed.get("confidence"), default=0.5)

    if all_cited_invalid:
        # The answer claims grounding in entities that were never retrieved.
        # Treat as an ungrounded gap rather than fabricating provenance.
        if not gaps:
            gaps = [
                "The answer could not be grounded in any retrieved entity "
                f"for: {query}"
            ]
        return {
            "answer": (
                "I don't have grounded information in memory to answer that "
                "reliably."
            ),
            "confidence": min(confidence, 0.15),
            "citations": [],
            "gaps": gaps,
            "used_entities": [],
            "conversations": [],
        }

    if not answer:
        answer = (
            "I don't have enough grounded information in memory to answer that."
        )
        if not gaps:
            gaps = [f"Memory did not yield a usable answer for: {query}"]
        confidence = min(confidence, 0.2)

    # used_entities reflects the model's actual selection where it named valid
    # sources; only when it omitted the field do we fall back to the retrieved
    # set. citations and used_entities therefore agree.
    cite_ids = used if used else retrieved_ids
    return {
        "answer": answer,
        "confidence": confidence,
        "citations": _citations_for(entities, cite_ids),
        "gaps": gaps,
        "used_entities": cite_ids,
        "conversations": _conversation_list(conversations, used_conversations),
    }


def _found_names(entities: list[dict], watched: list[str], conversations: dict[str, dict]) -> str:
    names = [e["entity_name"] for e in entities]
    if conversations:
        names.append(f"{len(conversations)} conversation(s)")
    return ", ".join(names) or ("the watch history" if watched else "nothing")


def _conversation_list(conversations: dict[str, dict], ids: list[str]) -> list[dict]:
    return [{"episode_id": ep, **conversations[ep]} for ep in ids if ep in conversations]


def _claim_evidence(body: str, claim_id: str) -> list[dict]:
    """G118 slice 2 (R-PB12): the spans behind a claim-first citation, read
    from the page itself — the source of truth — not from the claims index,
    whose metadata carries no evidence and is only as fresh as its last
    rebuild. ``body`` is the one ``_load_entity`` already read, so this is a
    ``parse_claims`` and no I/O. ``[]`` when the claim is gone or legacy."""
    for claim in parse_claims(body or ""):
        if claim.id == claim_id:
            return [e.to_dict() for e in claim.evidence]
    return []


def _citations_for(entities: list[dict], cite_ids: list[str]) -> list[dict]:
    """Assemble entity-level citations for the given ids, preserving order."""
    by_id = {e["entity_id"]: e for e in entities}
    citations: list[dict] = []
    seen: set[str] = set()
    for eid in cite_ids:
        ent = by_id.get(eid)
        if ent is None or eid in seen:
            continue
        seen.add(eid)
        episodes, more = _cited_episodes(ent)
        citation = {
            "entity_id": ent["entity_id"],
            "entity_name": ent["entity_name"],
            "file_path": ent["file_path"],
            "snippet": ent["snippet"],
            "source_episodes": episodes,
            "source_episodes_more": more,
        }
        # When the grounding came from a claim, the citation points at the claim
        # id + its valid-window + observer (M5e), not just the entity page.
        prov = ent.get("claim_provenance")
        if prov:
            citation["claim_provenance"] = prov
            claim_id = str(prov.get("claim_id") or "").strip()
            if claim_id:
                citation["claim_id"] = claim_id
                citation["evidence"] = _claim_evidence(ent.get("body", ""), claim_id)
        citations.append(citation)
    return citations
