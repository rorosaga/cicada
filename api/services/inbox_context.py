"""G115 Phase 1 / G97 — the cause behind an inbox item, resolved at read.

Every inbox item already points at the conversation that raised it: a
clarification carries ``source_episode``, a conflict's option claims carry
``source_episodes``, and the subject page carries ``source_episodes``. Until
this module that link stopped at the API boundary — ``_item_from_file`` mapped
eighteen keys and never read it — so the app could not show "you were talking
about X in <that conversation>", which is what the owner asked for (G97).

Three rules, all from the G115 ruling:

* **Engine-free and bounded.** Reads go through ``bank_index`` (frontmatter
  cached per file, bodies read lazily) and an entity's claims block is parsed
  at most once per :class:`InboxContext`. G97 measured 43/49 live items reaching
  an episode in ~100 ms with zero LLM, git or vector calls; the budget test in
  ``test_inbox_context.py`` keeps it there.
* **Spans, not copies.** The excerpt is computed from the episode body on every
  read and the mention offsets are recomputed with it — nothing is written back
  and nothing reaches the ledger. A rewritten episode changes what the card
  shows instead of highlighting the wrong words (the G118 rail).
* **Served, never hidden.** When no tier resolves, the card carries the literal
  ``[ no source recorded ]`` so the person sees that provenance is missing
  rather than a card that quietly lost its context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from api.services import bank_index, inbox_questions
from api.services.id_utils import sanitize_id

NO_SOURCE = "[ no source recorded ]"
EXCERPT_RADIUS = 240
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


@dataclass
class Excerpt:
    excerpt: str
    mention_offsets: list[list[int]] = field(default_factory=list)
    start: int | None = None
    end: int | None = None


@dataclass
class Cause:
    tier: str = "none"
    episode_id: str | None = None
    timestamp: str | None = None
    conversation_id: str | None = None
    harness: str | None = None
    origin: str | None = None
    conversation_title: str | None = None
    excerpt: str = NO_SOURCE
    mention_offsets: list[list[int]] = field(default_factory=list)
    start: int | None = None
    end: int | None = None
    span_kind: str = "derived"

    def to_wire(self) -> dict:
        return {
            "episode_id": self.episode_id, "timestamp": self.timestamp,
            "conversation_id": self.conversation_id, "harness": self.harness, "origin": self.origin,
            "conversation_title": self.conversation_title, "excerpt": self.excerpt,
            "mention_offsets": [list(p) for p in self.mention_offsets],
            "start": self.start, "end": self.end, "tier": self.tier, "span_kind": self.span_kind,
        }


def locate_mention(text: str, name: str, entity_id: str) -> tuple[int, int] | None:
    """First occurrence of the entity in ``text`` (case-insensitive).

    Tries the display name, then the id with hyphens as spaces and as-is, then
    any name token of ≥ 4 chars — a person is usually mentioned by surname, a
    project by one word of its name. ``None`` when nothing matches; the caller
    then excerpts the head of the body with no offsets rather than faking one.
    """
    low = (text or "").lower()
    candidates = [name or "", (entity_id or "").replace("-", " "), entity_id or ""]
    candidates += [t for t in _TOKEN_RE.findall(name or "") if len(t) >= 4]
    for cand in candidates:
        c = cand.strip().lower()
        if not c:
            continue
        i = low.find(c)
        if i >= 0:
            return (i, i + len(c))
    return None


def excerpt_around(text: str, span: tuple[int, int] | None, *, radius: int = EXCERPT_RADIUS) -> Excerpt:
    """±``radius`` chars around ``span``, cut on word boundaries, offsets rebased.

    The window never starts or ends mid-word: the start advances to the next
    whitespace when it would split one, the end retreats likewise. Offsets in
    the result index the EXCERPT; ``start``/``end`` are the window's absolute
    offsets so a viewer can hand them to ``GET /episodes/{id}/span`` — which is
    only true if they are kept in step with the trimming, so every return path
    slices ``text[start:end]`` rather than ``.strip()``-ing a copy.
    """
    text = text or ""
    if not text:
        return Excerpt(excerpt="")
    if span is None:
        end = min(len(text), 2 * radius)
        if end < len(text):
            cut = text.rfind(" ", 0, end)
            end = cut if cut > 0 else end
        start = 0
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        return Excerpt(excerpt=text[start:end], start=start, end=end)
    m_start, m_end = span
    start = max(0, m_start - radius)
    end = min(len(text), m_end + radius)
    if start > 0 and not text[start - 1].isspace():
        nxt = text.find(" ", start, m_start)
        if nxt >= 0:
            start = nxt + 1
    if end < len(text) and not text[end].isspace():
        prev = text.rfind(" ", m_end, end)
        if prev >= 0:
            end = prev
    window = text[start:end]
    lead = len(window) - len(window.lstrip())
    trail = len(window) - len(window.rstrip())
    start += lead
    end -= trail
    excerpt = text[start:end]
    return Excerpt(excerpt=excerpt, mention_offsets=[[m_start - start, m_end - start]], start=start, end=end)


class InboxContext:
    """Per-``load_inbox`` read cache: episode + entity frontmatter via
    ``bank_index`` (one scandir each, parses only what changed since the last
    call) and entity claim blocks parsed at most once per context."""

    def __init__(self, memory_path: Path, *, today: str):
        self.memory_path = Path(memory_path)
        self.today = today
        self._episodes: dict[str, bank_index.IndexedFile] | None = None
        self._entities: dict[str, bank_index.IndexedFile] | None = None
        self._claims: dict[str, list] = {}
        self._bodies: dict[str, str] = {}

    # ---------- indices ----------

    def episode(self, ep_id: str | None):
        if not ep_id:
            return None
        if self._episodes is None:
            self._episodes = {f.stem: f for f in bank_index.files(self.memory_path, "episodes")}
        return self._episodes.get(str(ep_id))

    def entity(self, entity_id: str | None):
        """The subject page, by stem then by ``sanitize_id`` of the stem.

        ``load_inbox``'s own ``_subject_gone`` gate resolves through
        ``id_utils.resolve_entity_file``, which is tolerant (exact slug →
        sanitized → case-insensitive stem scan). This index is an exact dict
        lookup, so without the sanitized fallback an item whose ``entity_id``
        is a display name would pass the gate and then silently lose its
        entity tier and its ``entity_type``. The case-insensitive scan is
        deliberately NOT mirrored: it is O(files) per miss, and a miss here
        degrades to ``[ no source recorded ]``, never to a wrong card.
        """
        if not entity_id:
            return None
        if self._entities is None:
            pages = bank_index.files(self.memory_path, "entities")
            self._entities = {f.stem: f for f in pages}
            for f in pages:
                self._entities.setdefault(sanitize_id(f.stem), f)
        key = str(entity_id)
        return self._entities.get(key) or self._entities.get(sanitize_id(key))

    def entity_type(self, entity_id: str | None) -> str | None:
        page = self.entity(entity_id)
        if page is None:
            return None
        value = page.frontmatter.get("type")
        return str(value) if value else None

    def entity_last_referenced(self, entity_id: str | None) -> str | None:
        page = self.entity(entity_id)
        if page is None:
            return None
        value = page.frontmatter.get("last_referenced")
        return str(value) if value else None

    def claims(self, entity_id: str | None) -> list:
        """The subject's claims, parsed once. Unparseable → ``[]`` (a corrupt
        claims block must not hide the card; the resolve path is where it
        refuses loudly)."""
        if not entity_id:
            return []
        if entity_id not in self._claims:
            page = self.entity(entity_id)
            parsed: list = []
            if page is not None:
                try:
                    from api.services.claims import parse_claims

                    parsed = parse_claims(page.body())
                except Exception:
                    parsed = []
            self._claims[entity_id] = parsed
        return self._claims[entity_id]

    def _body(self, ep) -> str:
        if ep.stem not in self._bodies:
            try:
                self._bodies[ep.stem] = ep.body()
            except Exception:
                self._bodies[ep.stem] = ""
        return self._bodies[ep.stem]

    # ---------- cause ----------

    def cause_for(self, fm: dict, options: list[dict]) -> Cause:
        """The three tiers of G97, first hit wins (R1)."""
        # G129 slice 2: a `removal` item was raised by a browser sync, not a
        # conversation — none of the three episode-anchored tiers below apply
        # (there is no episode to excerpt). The item carries its own real
        # provenance directly (`synced_at`, `browser`); serve THAT as tier
        # "item" instead of falling through to `[ no source recorded ]`, which
        # would be honest but would throw away provenance the item actually
        # has.
        if str(fm.get("kind", "") or "") == "removal":
            at = _opt(fm.get("synced_at"))
            if at is None:
                return Cause()
            browser = _opt(fm.get("browser")) or _opt(fm.get("channel")) or "a browser"
            url = _opt(fm.get("url"))
            excerpt = f"Removed from {browser}" + (f" — {url}" if url else "")
            return Cause(tier="item", timestamp=at, origin=_opt(fm.get("channel")), excerpt=excerpt)
        entity_id = str(fm.get("entity_id", "") or "")
        name = str(fm.get("entity_name", "") or "")
        # Ordered + deduped: the item's own `claim_id` is normally ALSO one of
        # the options' (it is the claim Sleep proposed), and a duplicate would
        # push the same episode into `candidates` twice.
        claim_ids: list[str] = []
        for cid in [o.get("claim_id") for o in options] + [fm.get("claim_id")]:
            cid = str(cid or "").strip()
            if cid and cid not in claim_ids:
                claim_ids.append(cid)

        candidates: list[tuple[str, str | None, object]] = []
        item_ep = str(fm.get("source_episode", "") or "").strip()
        if item_ep:
            candidates.append(("item", item_ep, None))
        by_id = {c.id: c for c in self.claims(entity_id)} if claim_ids else {}
        option_claims = [by_id[c] for c in claim_ids if c in by_id]
        option_claims.sort(key=lambda c: str(c.recorded_at or c.valid_from or ""), reverse=True)
        for claim in option_claims:
            eps = list(claim.source_episodes or [])
            if eps:
                candidates.append(("claim", eps[-1], claim))
        page = self.entity(entity_id)
        if page is not None:
            eps = list(page.frontmatter.get("source_episodes") or [])
            if eps:
                candidates.append(("entity", str(eps[-1]), None))

        for tier, ep_id, claim in candidates:
            ep = self.episode(ep_id)
            if ep is None:
                continue
            body = self._body(ep)
            span, span_kind = None, "derived"
            if claim is not None:
                span = _asserted_span(claim, ep_id, body)
                if span is not None:
                    span_kind = "asserted"
            if span is None:
                span = locate_mention(body, name, entity_id)
            ex = excerpt_around(body, span)
            efm = ep.frontmatter
            return Cause(
                tier=tier, episode_id=ep.stem,
                timestamp=_opt(efm.get("timestamp")),
                conversation_id=_opt(efm.get("session_id")) or _opt(efm.get("source_id")),
                harness=_opt(efm.get("harness")), origin=_opt(efm.get("origin")) or _opt(efm.get("source")),
                conversation_title=_opt(efm.get("title")),
                excerpt=ex.excerpt, mention_offsets=ex.mention_offsets, start=ex.start, end=ex.end,
                span_kind=span_kind,
            )
        return Cause()


def _asserted_span(claim, ep_id: str, body: str) -> tuple[int, int] | None:
    """A G118 evidence span on the claim, into THIS episode, and not stale."""
    from api.services import evidence as ev

    for e in getattr(claim, "evidence", None) or []:
        if not getattr(e, "is_span", lambda: False)() or e.episode != ep_id:
            continue
        if e.hash and e.hash != ev.body_hash(body):
            continue
        if 0 <= e.start < e.end <= len(body):
            return (e.start, e.end)
    return None


def _opt(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def cause_line(cause: Cause | dict | None, today: str) -> str:
    """One line for a terminal/agent: ``“…excerpt…” — from "Title" · harness · age``.

    Shared by the MCP renderer and the docs so the two surfaces never phrase
    provenance differently. Tier ``none`` is the literal ``[ no source recorded ]``.
    """
    if cause is None:
        return NO_SOURCE
    c = cause if isinstance(cause, dict) else cause.to_wire()
    if c.get("tier", "none") == "none":
        return NO_SOURCE
    excerpt = re.sub(r"\s+", " ", str(c.get("excerpt") or "")).strip()
    if len(excerpt) > 200:
        excerpt = excerpt[:199].rstrip() + "…"
    where = [f'from "{c["conversation_title"]}"' if c.get("conversation_title") else f"from {c.get('episode_id')}"]
    if c.get("harness") or c.get("origin"):
        where.append(str(c.get("harness") or c.get("origin")))
    age = inbox_questions.humanize_age(c.get("timestamp"), today)
    if age != "unknown":
        where.append(age)
    return f"“{excerpt}” — " + " · ".join(where)
