"""Hard questions drafted from your own bank, for ``answer_eval`` (G148).

    api/.venv/bin/python -m benchmarks.hard_questions --bank <bank dir> --limit 40            # draft
    # open benchmarks/answer_eval.hard.review.local.md, tick "- [x] accept" on the ones that hold up
    api/.venv/bin/python -m benchmarks.hard_questions --accept                                 # keep the ticked ones
    api/.venv/bin/python -m benchmarks.answer_eval --bank <bank dir> \\
        --questions benchmarks/answer_eval.hard.accepted.local.yaml

The hand-written eval is mostly single-conversation recall. This samples the shapes it lacks from the bank's own
claims, evidence spans and pages — deterministically, by ``--seed`` — and asks the plan to draft ONE question per
sample in ``answer_eval``'s YAML shape:

- ``update`` — a claim a later claim superseded with a value that cannot hold beside it (``exclusive_update``): the
  later value is expected, the one the later evidence replaces forbidden;
- ``temporal`` — one subject in two conversations far apart, in one context, each dated when said (never a save or
  a bulk import's day): what changed, what came first;
- ``multi-hop`` — a link from one page to another, each side with its own evidence: the answer needs both;
- ``count`` — a subject in 3+ conversations: list or count what those conversations said;
- ``event`` — two or more dated happenings on one page: their order, or the time between them;
- ``abstention`` — a plausible question about a sampled subject whose answer is in none of the evidence shown;
  the drafter must say why, and the item is ``abstain: true``;
- ``es`` — about a quarter of the samples (seeded) are drafted in Spanish, on top of their own kind.

**Privacy and the bank.** The bank is only read: pages through ``markdown_parser.parse``, conversations through
``evidence.source_document``; nothing is written into it and ``--out``/``--review`` may not point inside it. The
questions go to the YAML and the evidence each was drafted from goes to the review sheet — both gitignored
(``benchmarks/*.local.*``) and written 0600. The terminal shows ids, kinds and counts only. Each draft is one plan
call (``claude -p`` through Cicada's plan engine, ``--model`` sonnet by default); ``--dry-run`` samples and writes
the sheet with no call. A rerun keeps every question already in the YAML for the same sample (``--fresh`` redrafts).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import random
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "benchmarks" / "answer_eval.hard.local.yaml"
DEFAULT_REVIEW = REPO / "benchmarks" / "answer_eval.hard.review.local.md"
DEFAULT_ACCEPTED = REPO / "benchmarks" / "answer_eval.hard.accepted.local.yaml"

KINDS = ("update", "temporal", "multi-hop", "count", "event", "abstention")
TAGS = frozenset({*KINDS, "es"})
#: One cycle of the default mix (20 slots): a kind with no candidates gives its slot to the next kind that has one.
MIX = ("update", "temporal", "multi-hop", "count", "abstention", "update", "temporal", "multi-hop", "event",
       "abstention", "update", "temporal", "multi-hop", "count", "abstention", "update", "temporal", "multi-hop",
       "count", "event")
SPANISH_SHARE = 0.25
MIN_GAP_DAYS = 14
SNIPPET_CHARS = 520
MAX_SNIPPETS = 6
MAX_CLAIMS = 14
SKIP_SUBJECT_TYPES = frozenset({"media"})
#: A day on which one origin wrote more than this many episodes is an import or a sync, not that many moments: its
#: date is when Cicada took them in, so it never anchors a temporal or event question. A live session's own capture
#: (a ``session_id`` and no saved link) is dated by the session and never counted.
BULK_DAY = 25
#: Where something saved comes from (a bookmark, a saved post, a pasted link, a feed item, an open-tab snapshot): its
#: date is the save's or the sync's, not a moment the person talked something over (mirrors ``inbox_tend``'s set).
SAVE_ORIGINS = frozenset({"bookmark", "saved-link", "media", "rss", "pdf", "ingest", "url", "video", "youtube",
                          "instagram", "linkedin", "safari-tab", "chrome-tab-group", "tab-group"})
SAVE_SUFFIXES = ("-bookmark", "-bookmarks", "-saved", "-likes", "-playlist", "-tab", "-tabs", "-tab-group")
#: Words too common to tie a question to a sentence, and the words that say a question asks for a number, a version
#: or a date (English and Spanish).
_STOP = frozenset("""about after again also been before being could does doing done from have here into just like
made make more most much only other over same since some still than that their them then there these they this those
through under very want were what when where which while whom whose will with would your mine
algo como cual cuál cuales cuando cuándo desde donde dónde esta este esto estos fue han hasta hay las los más mis
muy para pero por qué que quien quién sobre son tan tengo tenía tiene una uno unos ya""".split())
_ASKS = {
    "version": re.compile(r"\b(version|versión|release|upgrade[ds]?|actualic\w*)\b", re.I),
    "number": re.compile(r"\b(how (many|much|long|often|far|big)|cu[aá]nt[oa]s?|price|cost|costs|precio|cuesta|"
                         r"number|n[uú]mero|percent|porcentaje|size|tama[nñ]o|budget|presupuesto)\b", re.I),
    "date": re.compile(r"\b(when|cu[aá]ndo|what (date|day|year|month)|which (date|day|year|month)|qu[eé] (d[ií]a|"
                       r"fecha|año|mes)|fecha|deadline)\b", re.I),
}
_VALUES = {
    "version": re.compile(r"\bv?\d+(?:\.\d+)+\b|\bv\d+\b", re.I),
    "number": re.compile(r"\d"),
    "date": re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b(19|20)\d{2}\b|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|"
                       r"dec|january|february|march|april|june|july|august|september|october|november|december|enero|"
                       r"febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre|monday|"
                       r"tuesday|wednesday|thursday|friday|saturday|sunday|yesterday|tomorrow|ayer|mañana)\b", re.I),
}
_PLACEHOLDER = re.compile(r"""^[\s.…?¿!¡\-_"'`<>]*$""")

_EP_DAY_RE = re.compile(r"^ep_(\d{4}-\d{2}-\d{2})_")
ACCEPT_RE = re.compile(r"^\s*-\s*\[[xX]\]\s*accept\s+(\S+)")


# ---------------------------------------------------------------------------------------------- reading the bank

@dataclass
class Conversation:
    id: str
    day: str
    title: str
    body: str
    moment: bool = True      # its day is when it was said: not a save, not one of a bulk import's day
    project_dir: str = ""


def _is_save(fm: dict) -> bool:
    """A saved thing, not a conversation: it carries the page's link, or came from a saving door."""
    if fm.get("url") or fm.get("media_entity_id"):
        return True
    for key in ("origin", "source"):
        value = str(fm.get(key) or "").strip().lower()
        if value and (value in SAVE_ORIGINS or value.endswith(SAVE_SUFFIXES)):
            return True
    from api.services import source_overview

    saved = {o for spec in source_overview.CATALOG if spec.id in source_overview.SAVED_SOURCES for o in spec.origins}
    return str(fm.get("origin") or "") in saved


def _repo_of(project_dir: str) -> str:
    """A working folder with any worktree tail cut off: two worktrees of one repo are one project."""
    d = str(project_dir or "").strip().rstrip("/")
    return re.sub(r"/(?:\.claude/|\.)?worktrees/[^/]+(?:/.*)?$", "", d)


@dataclass
class Page:
    id: str
    name: str
    type: str
    names: list[str]
    claims: list            # claims.Claim
    episodes: list[str]     # conversation ids that mention it, oldest first


@dataclass
class Sample:
    kind: str
    key: str                # stable across runs: the kind plus the claim/page/conversation ids it was drawn from
    page: str
    spanish: bool
    sources: list[str]
    claims: list[str]       # display lines for the drafter
    snippets: list[dict]    # {episode, day, title, text}
    extra: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"hq-{self.kind}-{hashlib.sha256(self.key.encode()).hexdigest()[:8]}"

    @property
    def tags(self) -> list[str]:
        return [self.kind, *(["es"] if self.spanish else [])]


class Bank:
    """A read-only view of one bank: its pages (owner page left out) and the conversations they cite."""

    def __init__(self, root: Path):
        from api.services import markdown_parser
        from api.services.claims import parse_claims

        self.root = root
        self._docs: dict[str, Conversation | None] = {}
        self.pages: dict[str, Page] = {}
        self.bulk = _bulk_days(root)
        for path in sorted((root / "entities").glob("*.md")):
            try:
                head = markdown_parser.parse(path, ledger=False)
            except Exception:  # noqa: BLE001 — an unreadable page is skipped, never fatal
                continue
            fm = head.frontmatter or {}
            if fm.get("owner") is True or str(fm.get("status") or "") in ("dropped",):
                continue
            try:
                parsed = markdown_parser.parse(path) if fm.get("claims_ledger") else head
                claims = parse_claims(parsed.body)
            except Exception:  # noqa: BLE001
                claims = []
            eid = path.stem
            name = str(fm.get("name") or eid)
            aliases = [str(a) for a in (fm.get("aliases") or []) if isinstance(a, (str, int))]
            names = sorted({n for n in [name, eid.replace("-", " "), *aliases] if len(str(n).strip()) >= 3},
                           key=lambda n: (-len(n), n))
            cited: set[str] = {str(e) for e in (fm.get("source_episodes") or []) if isinstance(e, str)}
            for c in claims:
                cited.update(str(e) for e in c.source_episodes or [])
                cited.update(ev.episode for ev in c.evidence or [] if ev.episode)
            episodes = sorted((e for e in cited if self.conversation(e) is not None),
                              key=lambda e: (self.conversation(e).day, e))
            self.pages[eid] = Page(eid, name, str(fm.get("type") or ""), names, claims, episodes)
        #: conversation id -> the project pages that cite it (what it was about, as Sleep resolved it)
        self.projects_of: dict[str, set[str]] = defaultdict(set)
        for page in self.pages.values():
            if page.type == "project":
                for e in page.episodes:
                    self.projects_of[e].add(page.id)

    def moment(self, doc_id: str) -> Conversation | None:
        """A conversation whose day is when it was said — never a save, never one of a bulk import's day."""
        conv = self.conversation(doc_id)
        return conv if conv is not None and conv.moment else None

    def same_context(self, a: str, b: str, page: Page) -> bool:
        """Do conversations ``a`` and ``b`` talk about the same ``page`` — not two things sharing its name? False when
        both are tied to project pages and share none (a project page is its own context), or both were captured in
        working folders of different repos."""
        if page.type != "project":
            pa, pb = self.projects_of.get(a) or set(), self.projects_of.get(b) or set()
            if pa and pb and not (pa & pb):
                return False
        ca, cb = self.conversation(a), self.conversation(b)
        da, db = _repo_of(ca.project_dir if ca else ""), _repo_of(cb.project_dir if cb else "")
        return not (da and db and da != db)

    def conversation(self, doc_id: str) -> Conversation | None:
        """A dated conversation by id, or ``None`` (not an episode, missing, untimed, or an indexed-only record)."""
        if doc_id in self._docs:
            return self._docs[doc_id]
        from api.services import episode_time, evidence, history_index

        conv = None
        if evidence.is_episode_id(doc_id):
            doc = evidence.source_document(self.root, doc_id)
            if doc is not None:
                fm, body = doc
                if episode_time.counts_as_activity(fm) and history_index.kind(fm) is None:
                    day = _said_on(fm.get("timestamp"), doc_id)
                    if _is_day(day):
                        conv = Conversation(doc_id, day, str(fm.get("title") or ""), body,
                                            moment=not _is_save(fm) and doc_id not in self.bulk,
                                            project_dir=str(fm.get("project_dir") or ""))
        self._docs[doc_id] = conv
        return conv


def _bulk_days(root: Path) -> frozenset[str]:
    """Episode ids written on a day their origin wrote more than ``BULK_DAY`` of: an import or a sync."""
    from api.services import bank_index

    per: dict[tuple[str, str], list[set[str]]] = defaultdict(list)
    try:
        files = bank_index.files(root, "episodes")
    except OSError:
        return frozenset()
    for f in files:
        fm = f.frontmatter or {}
        if fm.get("session_id") and not _is_save(fm):
            continue   # a live session's own capture is dated by the session
        eid = str(fm.get("id") or f.stem)
        day = _said_on(fm.get("timestamp"), eid)
        per[(str(fm.get("origin") or fm.get("source") or ""), day)].append({eid, f.stem})
    return frozenset(e for files_ in per.values() if len(files_) > BULK_DAY for ids in files_ for e in ids)


def _said_on(stamp, episode_id: str) -> str:
    """The day a conversation was said, in the person's zone (ruling 34): its ``timestamp`` read locally, else the day
    in its id — never a UTC stamp's first ten characters."""
    from api.services import ask_sources

    said = ask_sources.local_day(stamp) if stamp else None
    if said is not None:
        return said.isoformat()
    m = _EP_DAY_RE.match(episode_id or "")
    return m.group(1) if m else ""


def _is_day(s: str) -> bool:
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def _days_between(a: str, b: str) -> int:
    return abs((date.fromisoformat(b) - date.fromisoformat(a)).days)


# ---------------------------------------------------------------------------------------------- evidence snippets

def _window(text: str, start: int, end: int, chars: int = SNIPPET_CHARS) -> str:
    """About ``chars`` of text around the span, snapped outward to whole lines where they fit, else to words."""
    end = max(end, start)
    pad = max(0, (chars - (end - start)) // 2)
    lo, hi = max(0, start - pad), min(len(text), end + pad)
    if hi - lo < chars:  # near an edge: give the room to the other side
        lo, hi = max(0, min(lo, hi - chars)), min(len(text), max(hi, lo + chars))
    line_lo = text.rfind("\n", 0, lo) + 1
    if lo - line_lo < 120:
        lo = line_lo
    elif (sp := text.find(" ", lo, start)) >= 0:
        lo = sp + 1
    line_hi = text.find("\n", hi)
    line_hi = len(text) if line_hi < 0 else line_hi
    if line_hi - hi < 120:
        hi = line_hi
    elif (sp := text.rfind(" ", end, hi)) >= 0:
        hi = sp
    out = text[lo:hi].strip()
    return ("… " if lo > 0 else "") + out + (" …" if hi < len(text) else "")


def snippet(bank: Bank, page: Page, episode: str, claim_ids: set[str] | None = None) -> dict | None:
    """What ``episode`` says about ``page``: a claim's evidence span there, else the first mention of a name, else
    the conversation's opening."""
    conv = bank.conversation(episode)
    if conv is None:
        return None
    text = conv.body
    for c in page.claims:
        if claim_ids is not None and c.id not in claim_ids:
            continue
        for ev in c.evidence or []:
            if ev.episode == episode and ev.is_span() and ev.end <= len(text):
                return {"episode": episode, "day": conv.day, "title": conv.title,
                        "text": _window(text, ev.start, ev.end)}
    low = text.lower()
    for name in page.names:
        at = low.find(name.lower())
        if at >= 0:
            return {"episode": episode, "day": conv.day, "title": conv.title,
                    "text": _window(text, at, at + len(name))}
    return {"episode": episode, "day": conv.day, "title": conv.title, "text": _window(text, 0, 0)}


def _claim_line(c) -> str:
    when = f"from {c.valid_from}" if c.valid_from else ""
    if c.valid_to:
        when += f" until {c.valid_to}"
    if getattr(c, "status", None):
        when += f" ({c.status})"
    state = "closed" if c.valid_to or c.superseded_by else "current"
    return f"[{state}{', ' + when.strip() if when.strip() else ''}] {c.text}".strip()


def _claim_days(c, bank: Bank) -> list[str]:
    days = [bank.conversation(e).day for e in (c.source_episodes or []) if bank.conversation(e)]
    return sorted(days)


def _claim_episodes(c, bank: Bank) -> list[str]:
    eps = {*(c.source_episodes or []), *(ev.episode for ev in c.evidence or [] if ev.episode)}
    return sorted((e for e in eps if bank.conversation(e)), key=lambda e: (bank.conversation(e).day, e))


def _claims_for(page: Page, limit: int = MAX_CLAIMS) -> list[str]:
    from api.services.claims import is_record

    lines = [_claim_line(c) for c in page.claims if (c.text or "").strip() and not is_record(c)]
    return lines[:limit]


# ---------------------------------------------------------------------------------------------- samplers

def _subjects(bank: Bank):
    """Pages a question can be about: a saved link or video (``media``) is a thing kept, not a subject talked over."""
    return (p for p in bank.pages.values() if p.type not in SKIP_SUBJECT_TYPES)


def _distinct(snips) -> list[dict]:
    seen, out = set(), []
    for s in snips:
        if s and (s["episode"], s["text"]) not in seen:
            seen.add((s["episode"], s["text"]))
            out.append(s)
    return out


def _value_words(value: str) -> set[str]:
    return {w for w in re.findall(r"[^\W_]+(?:[-.][^\W_]+)*", (value or "").lower()) if w not in _STOP
            and w not in ("a", "an", "the", "of", "in", "at", "on", "de", "la", "el", "en", "y", "and")}


def _shown_value(bank: Bank, c) -> str:
    target = bank.pages.get(c.object or "") if c.object_kind == "node" else None
    return target.name if target else str(c.object or "")


def _linked(bank: Bank, a: str, b: str) -> bool:
    """Does either page carry a claim pointing at the other (a venue in a city, a VM on a host)?"""
    pa, pb = bank.pages.get(a), bank.pages.get(b)
    return bool((pa and any(c.object == b for c in pa.claims)) or (pb and any(c.object == a for c in pb.claims)))


def exclusive_update(bank: Bank, page: Page, old, new) -> str | None:
    """Why ``old`` → ``new`` is no fair knowledge update (both could hold at once), or ``None`` when the later value
    really replaces the earlier one: the same predicate, two values that share no word and neither of which contains
    or links the other, and — on a predicate the vocabulary calls a set — later evidence that names the earlier value
    ("moved from X to Y"). Precision over recall: a dropped sample costs nothing, a wrong forbid costs a reviewer."""
    from api.services import predicates

    if not old.predicate or predicates._slugify_predicate(old.predicate) != predicates._slugify_predicate(new.predicate):
        return "different predicates"
    a, b = _shown_value(bank, old).strip(), _shown_value(bank, new).strip()
    la, lb = a.lower(), b.lower()
    if not a or not b or la == lb:
        return "no second value"
    if la in lb or lb in la:
        return "one value contains the other"
    if _value_words(a) & _value_words(b):
        return "the values share a word (a facet, not a replacement)"
    if old.object_kind == "node" and new.object_kind == "node" and _linked(bank, old.object, new.object):
        return "the values' pages link each other"
    if predicates.cardinality(bank.root, old.predicate) == "multi":
        names = {la, str(old.object or "").lower()}
        target = bank.pages.get(old.object or "")
        names |= {n.lower() for n in (target.names if target else [])}
        later = " ".join(sn["text"].lower() for e in _claim_episodes(new, bank)
                         if (sn := snippet(bank, page, e, {new.id})))
        if not any(n and n in later for n in names):
            return "a set-valued predicate whose later evidence never names the earlier value"
    if not any(bank.same_context(x, y, page) for x in _claim_episodes(old, bank) for y in _claim_episodes(new, bank)):
        return "the two claims come from different contexts"
    return None


def _update_candidates(bank: Bank) -> list[Sample]:
    from api.services.claims import is_record

    out = []
    for page in _subjects(bank):
        by_id = {c.id: c for c in page.claims}
        for old in page.claims:
            new = by_id.get(old.superseded_by or "")
            if (new is None or new.valid_to or new.superseded_by or not (old.text and new.text)
                    or is_record(old) or is_record(new)):  # a withdrawal is no new value
                continue
            old_eps = _claim_episodes(old, bank)
            eps = old_eps + [e for e in _claim_episodes(new, bank) if e not in old_eps]
            if not eps or exclusive_update(bank, page, old, new):
                continue
            snips = _distinct(snippet(bank, page, e, {old.id, new.id}) for e in eps[:MAX_SNIPPETS])
            out.append(Sample("update", f"update:{page.id}:{old.id}:{new.id}", page.id, False, eps, [
                f"EARLIER (superseded): {_claim_line(old)}", f"LATER (current): {_claim_line(new)}"], snips,
                {"stale": old.text}))
    return out


def _cited_moments(bank: Bank, page: Page) -> list[str]:
    """The page's conversations that a claim on it cites (Sleep tied a belief there to this page, not just a name
    string), dated when said: no save, no bulk import's day. Oldest first."""
    cited = {e for c in page.claims for e in _claim_episodes(c, bank)}
    return [e for e in page.episodes if e in cited and bank.moment(e)]


def _temporal_candidates(bank: Bank) -> list[Sample]:
    out = []
    for page in _subjects(bank):
        eps = _cited_moments(bank, page)
        if len(eps) < 2:
            continue
        first = eps[0]
        day0 = bank.conversation(first).day
        last = next((e for e in reversed(eps[1:]) if _days_between(day0, bank.conversation(e).day) >= MIN_GAP_DAYS
                     and bank.same_context(first, e, page)), None)
        if last is None:
            continue
        gap = _days_between(day0, bank.conversation(last).day)
        snips = _distinct(snippet(bank, page, e) for e in (first, last))
        out.append(Sample("temporal", f"temporal:{page.id}:{first}:{last}", page.id, False, [first, last],
                          _claims_for(page), snips, {"gap_days": gap}))
    return out


def _multi_hop_candidates(bank: Bank) -> list[Sample]:
    out = []
    for page in _subjects(bank):
        for c in page.claims:
            target = bank.pages.get(c.object or "") if c.object_kind == "node" else None
            if target is None or target.id == page.id or c.valid_to or not c.text:
                continue
            eps_a = _claim_episodes(c, bank)
            # The second hop must come from a conversation the first did not: the answer needs both.
            onward = [(d, [e for e in _claim_episodes(d, bank) if e not in eps_a]) for d in target.claims
                      if not d.valid_to and d.text and d.object != page.id]
            onward = [(d, eps) for d, eps in onward if eps]
            if not eps_a or not onward:
                continue
            d, eps_b = onward[0]
            sa = snippet(bank, page, eps_a[0], {c.id})
            sb = snippet(bank, target, eps_b[0], {d.id})
            sources = [eps_a[0], eps_b[0]]
            out.append(Sample("multi-hop", f"multi-hop:{page.id}:{c.id}:{target.id}:{d.id}", page.id, False, sources,
                              [f"HOP 1 ({page.name}): {_claim_line(c)}", f"HOP 2 ({target.name}): {_claim_line(d)}"],
                              _distinct((sa, sb)), {"bridge": target.id}))
            break  # one bridge per page keeps the pool diverse
    return out


def _count_candidates(bank: Bank) -> list[Sample]:
    out = []
    for page in _subjects(bank):
        if len(page.episodes) < 3:
            continue
        eps = page.episodes[:MAX_SNIPPETS]
        snips = _distinct(snippet(bank, page, e) for e in eps)
        out.append(Sample("count", f"count:{page.id}:{len(page.episodes)}", page.id, False, eps, _claims_for(page),
                          snips, {"conversations": len(page.episodes), "shown": len(eps)}))
    return out


def _event_candidates(bank: Bank) -> list[Sample]:
    from api.services.claims import is_event

    out = []
    for page in _subjects(bank):
        # A happening dated only by a save or an import's day is dated by the sync, not by when it happened.
        events = sorted((c for c in page.claims if is_event(c) and c.valid_from and c.text
                         and any(bank.moment(e) for e in _claim_episodes(c, bank))),
                        key=lambda c: (str(c.valid_from), c.id))
        if len({str(c.valid_from)[:10] for c in events}) < 2:
            continue
        events = events[:MAX_CLAIMS]
        eps = list(dict.fromkeys(e for c in events for e in _claim_episodes(c, bank)))
        snips = _distinct(snippet(bank, page, e, {c.id for c in events}) for e in eps[:MAX_SNIPPETS])
        out.append(Sample("event", f"event:{page.id}:{','.join(c.id for c in events)}", page.id, False, eps,
                          [_claim_line(c) for c in events], snips))
    return out


def _abstention_candidates(bank: Bank) -> list[Sample]:
    out = []
    for page in _subjects(bank):
        if len(page.episodes) < 2 or not page.claims:
            continue
        eps = page.episodes[:MAX_SNIPPETS]
        snips = _distinct(snippet(bank, page, e) for e in eps)
        out.append(Sample("abstention", f"abstention:{page.id}", page.id, False, eps, _claims_for(page), snips))
    return out


SAMPLERS: dict[str, Callable[[Bank], list[Sample]]] = {
    "update": _update_candidates, "temporal": _temporal_candidates, "multi-hop": _multi_hop_candidates,
    "count": _count_candidates, "event": _event_candidates, "abstention": _abstention_candidates,
}


def draw(bank: Bank, limit: int, seed: int, kinds: tuple[str, ...] = KINDS) -> list[Sample]:
    """``limit`` samples, the same ones for the same bank and seed: each kind's pool shuffled by its own seeded
    generator, filled slot by slot from ``MIX``, one sample per page."""
    pools: dict[str, list[Sample]] = {}
    for kind in kinds:
        pool = sorted(SAMPLERS[kind](bank), key=lambda s: s.key)
        random.Random(f"{seed}:{kind}").shuffle(pool)
        pools[kind] = pool
    lang = random.Random(f"{seed}:es")
    mix = [k for k in MIX if k in kinds] or list(kinds)
    used_pages: set[str] = set()
    out: list[Sample] = []
    slot = 0
    while len(out) < limit and any(pools.values()):
        order = [mix[(slot + i) % len(mix)] for i in range(len(mix))]
        slot += 1
        for kind in order:
            pool = pools.get(kind) or []
            while pool and pool[0].page in used_pages:
                pool.pop(0)
            if pool:
                s = pool.pop(0)
                used_pages.add(s.page)
                s.spanish = lang.random() < SPANISH_SHARE
                out.append(s)
                break
    return out


# ---------------------------------------------------------------------------------------------- drafting

DRAFT_SYSTEM = """You write evaluation questions for a personal memory system that answers questions about one \
person's own life from their past conversations. You see evidence drawn from that person's memory. Write ONE question \
the person could plausibly ask their memory, answerable (or, when told, deliberately NOT answerable) from the evidence \
shown and from nothing else. Address the person as "I"/"my" in the question. Expected facts are short, checkable \
statements a right answer must contain; never add a fact the evidence does not state. `forbid` holds only facts the evidence shows are stale or wrong (an earlier value that changed); never invent distractors — leave it empty otherwise. Every claim and every snippet shown counts as known, including ones about other things: a question any of them answers, or lets one infer, is answerable. Return ONLY JSON."""

KIND_BRIEFS = {
    "update": "KNOWLEDGE UPDATE. The LATER claim is recorded as replacing the EARLIER one. First check the evidence: "
              "is the earlier value really no longer true — does the later evidence say it changed, or name a value "
              "for the same slot that cannot hold alongside it? If both could be true at once (a venue and the city "
              "it is in; a tool and the machine it runs on; two facets of one thing; an offer at one place and waiting "
              "on another), return skip. Otherwise ask for the current value without hinting that it changed. "
              "`expect` holds the later value in the evidence's own terms — never a conclusion it does not state "
              "(\"is waiting on B\" is not \"works at B\"); `forbid` holds ONLY the earlier value the later evidence "
              "replaces, stated as a fact (e.g. \"X is <earlier value>\").",
    "temporal": "TEMPORAL. The same subject came up in two conversations {gap_days} days apart (each dated by when it "
                "was said). Ask something whose answer needs both moments: what changed between them, what came first, "
                "or how long between them. If the two snippets are plainly about different things that share a name "
                "(two files, two projects, two people), return skip. `expect` names what each conversation "
                "said, in its own terms, with its timing where it matters — call it a change only when the later "
                "conversation says so (a venue then its city, or two facets of one thing, is no change).",
    "multi-hop": "MULTI-HOP. HOP 1 links the subject to a second page; HOP 2 is a fact about that second page. Ask a "
                 "question about the subject whose answer needs HOP 2 without naming the second page in the question "
                 "(e.g. \"what does the tool my <project> runs on cost?\"). `expect` holds the HOP 2 fact and names "
                 "the bridge.",
    "count": "COUNT / LIST. The subject came up in {conversations} conversations; you see {shown}. Ask for a list or a "
             "count of discrete things the shown conversations state about it (options considered, places, steps, "
             "people) — never \"how many conversations\". `expect` lists each item.",
    "event": "EVENTS. These are dated happenings on one page. Ask about their order, or what happened before/after "
             "one of them, or the time between two. `expect` states the order or dates.",
    "abstention": "ABSTENTION TRAP. Ask a plausible, specific question about this subject whose answer appears in NONE "
                  "of the evidence or claims shown (something a person might expect memory to know, e.g. a date, a "
                  "price, a name, a reason that was never said). EVERY claim and snippet shown counts — read them all, the ones "
                  "about other things too: if any states the answer or lets one infer it (a version, a number, a date, "
                  "a name said elsewhere), pick another question or skip. Set \"abstain\": true, leave `expect` empty, "
                  "and in `why` say what is missing and why the evidence does not answer it. Do not ask about "
                  "something the evidence touches on indirectly.",
}

DRAFT_TEMPLATE = """{brief}

SUBJECT: {name} ({type})

CLAIMS ON RECORD:
{claims}

EVIDENCE FROM CONVERSATIONS:
{snippets}

LANGUAGE: {language}

If the evidence cannot support a fair question of this kind, return {{"skip": true, "why": "<one sentence>"}}.
Otherwise return exactly:
{{"question": "...", "expect": ["..."], "forbid": ["..."], "abstain": false, "why": "one sentence: what the \
question tests and which evidence answers it (or, for an abstention, what is absent)", "skip": false}}"""


def draft_prompt(sample: Sample, bank: Bank) -> str:
    page = bank.pages[sample.page]
    brief = KIND_BRIEFS[sample.kind].format(**{"gap_days": "", "conversations": "", "shown": "", **sample.extra})
    snips = "\n\n".join(f"[{s['episode']} · {s['day']} · {s['title']}]\n{s['text']}" for s in sample.snippets)
    language = ("Write the question in natural Spanish (as a Spanish speaker would ask it); expected and forbidden "
                "facts may be in Spanish too." if sample.spanish else "Write the question in English.")
    return DRAFT_TEMPLATE.format(brief=brief, name=page.name, type=page.type or "thing",
                                 claims="\n".join(f"- {c}" for c in sample.claims) or "(none)",
                                 snippets=snips or "(none)", language=language)


def _meaningful(text: str) -> bool:
    """Real words, not an echo of the template's ``"..."`` or an empty string."""
    return not _PLACEHOLDER.match(text or "") and sum(ch.isalnum() for ch in text) >= 2


def _strs(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    return [str(v).strip() for v in (value or []) if _meaningful(str(v).strip())][:6]


def usable_question(question: str) -> bool:
    """A question of at least three words that is not the template's placeholder."""
    q = (question or "").strip()
    return _meaningful(q) and len(re.findall(r"[^\W\d_]{2,}", q)) >= 3 and len(q) <= 400


def _sentences(text: str) -> list[str]:
    return [t for t in re.split(r"(?<=[.!?])\s+|\n+", text or "") if t.strip()]


def abstention_leak(question: str, sample: Sample, subject_names=()) -> str | None:
    """Why a shown claim or snippet already answers an abstention question, or ``None``. A cheap string check: the
    question asks for a version, a number or a date, and some shown sentence holds one of that kind beside a word of
    the question (the subject's own names left out — every snippet carries them)."""
    asked = [kind for kind, cue in _ASKS.items() if cue.search(question or "")]
    if not asked:
        return None
    skip = {w for n in subject_names for w in re.findall(r"[^\W\d_]{4,}", str(n).lower())}
    words = {w for w in re.findall(r"[^\W\d_]{4,}", (question or "").lower())
             if w not in _STOP and w not in skip and not any(c.search(w) for c in _ASKS.values())}
    if not words:
        return None
    shown = [*sample.claims, *(sn.get("text") or "" for sn in sample.snippets)]
    for text in shown:
        for sentence in _sentences(text):
            low = sentence.lower()
            if not any(re.search(rf"\b{re.escape(w)}", low) for w in words):
                continue
            for kind in asked:
                if _VALUES[kind].search(sentence):
                    return f"abstention answerable from a shown snippet (a {kind} beside the question's words)"
    return None


def to_item(sample: Sample, reply: dict | None, subject_names=()) -> tuple[dict | None, str | None]:
    """The YAML item for a draft, or ``(None, reason)`` when it is skipped or unusable."""
    if not isinstance(reply, dict):
        return None, "unparseable reply"
    if reply.get("skip") is True:
        return None, "drafter skipped: " + str(reply.get("why") or "")[:200]
    question = str(reply.get("question") or "").strip()
    if not usable_question(question):
        return None, "empty draft: no usable question"
    abstain = sample.kind == "abstention"
    expect = [] if abstain else _strs(reply.get("expect"))
    forbid = _strs(reply.get("forbid"))
    why = str(reply.get("why") or "").strip()[:400]
    if abstain and not _meaningful(why):
        return None, "abstention without a reason"
    if not abstain and not expect:
        return None, "no expected facts"
    if sample.kind == "update" and not forbid:
        # The drafter was told to forbid only a value the later evidence replaces: an update it would not forbid
        # anything on is one it judged both-true, never filled in from the stale claim.
        return None, "update with nothing the later evidence replaces"
    if abstain and (leak := abstention_leak(question, sample, subject_names)):
        return None, leak
    item = {"id": sample.id, "question": question, "expect": expect, "forbid": forbid, "abstain": abstain,
            "tags": sample.tags, "sources": list(sample.sources), "why": why, "sample": sample.key}
    return item, None


def _kept_ok(item: dict) -> bool:
    """A draft kept from an earlier run still stands (one written before the empty-draft check may not)."""
    return usable_question(str(item.get("question") or "")) and (bool(item.get("abstain")) or bool(item.get("expect")))


def _empty(content: str, parsed) -> bool:
    """The engine returned nothing: no text, or an object with neither a question nor a skip."""
    if not (content or "").strip():
        return True
    return isinstance(parsed, dict) and not parsed.get("skip") and not str(parsed.get("question") or "").strip() \
        and not parsed.get("expect")


# ---------------------------------------------------------------------------------------------- files

def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, 0o600)


def write_yaml(path: Path, items: list[dict]) -> None:
    import yaml

    head = ("# Drafted by benchmarks/hard_questions.py from your own bank — gitignored, never commit it.\n"
            "# Review each one in the review sheet before use; `--accept` keeps the ticked ones.\n")
    _write_private(path, head + yaml.safe_dump({"questions": items}, allow_unicode=True, sort_keys=False, width=110))


def _quote(text: str) -> str:
    return "\n".join("> " + line for line in (text or "").splitlines()) or "> (empty)"


def write_review(path: Path, samples: list[Sample], items: dict[str, dict], skipped: dict[str, str],
                 yaml_path: Path) -> None:
    lines = ["# Hard questions — review sheet (local, gitignored)", "",
             f"Questions: `{yaml_path.name}`. Tick `- [x] accept <id>` on each question that is fair and whose "
             "expected facts the evidence below really states (for an abstention: really does not state), then run "
             "`python -m benchmarks.hard_questions --accept`. Edit a question's wording in the YAML if it only needs "
             "a fix.", ""]
    for s in samples:
        item = items.get(s.id)
        lines.append(f"## {s.id} · {s.kind}{' · es' if s.spanish else ''}")
        lines.append("")
        if item:
            lines += [f"- [ ] accept {s.id}", "", f"**Q:** {item['question']}", ""]
            if item["abstain"]:
                lines.append("**Should abstain.**")
            for f in item["expect"]:
                lines.append(f"- expect: {f}")
            for f in item["forbid"]:
                lines.append(f"- forbid: {f}")
            if item.get("why"):
                lines += ["", f"_Why:_ {item['why']}"]
        elif s.id in skipped:
            lines.append(f"_Not drafted — {skipped[s.id]}_")
        else:
            lines.append("_Sample only (dry run)._")
        lines += ["", f"Sources: {', '.join(s.sources)}", "", "Claims shown:"]
        lines += [f"- {c}" for c in s.claims] or ["- (none)"]
        lines += ["", "Evidence shown:", ""]
        for sn in s.snippets:
            lines += [f"`{sn['episode']}` · {sn['day']} · {sn['title']}", "", _quote(sn["text"]), ""]
        lines.append("")
    _write_private(path, "\n".join(lines))


def _load_items(path: Path) -> list[dict]:
    import yaml

    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [q for q in data.get("questions") or [] if isinstance(q, dict) and q.get("id")]


def accept(yaml_path: Path, review_path: Path, accepted_path: Path) -> int:
    ticked = {m.group(1) for line in review_path.read_text(encoding="utf-8").splitlines()
              if (m := ACCEPT_RE.match(line))}
    items = [q for q in _load_items(yaml_path) if q["id"] in ticked]
    write_yaml(accepted_path, items)
    print(f"accepted {len(items)} of {len(_load_items(yaml_path))} → {accepted_path}")
    return 0


# ---------------------------------------------------------------------------------------------- main

def plan_llm(model: str):
    from api.config import get_settings
    from api.services import providers

    settings = get_settings().model_copy(update={"llm_mode": "agent", "agent_model": model})
    return providers.resolve_llm_fn(settings, stage="judge", is_async=False)


def run(bank_dir: Path, *, limit: int, seed: int, out: Path, review: Path, dry_run: bool, fresh: bool,
        kinds: tuple[str, ...], llm=None, model: str = "sonnet") -> dict:
    from api.services import json_parse

    bank = Bank(bank_dir)
    samples = draw(bank, limit, seed, kinds)
    kept = {} if fresh else {q.get("sample"): q for q in _load_items(out) if _kept_ok(q)}
    items: dict[str, dict] = {}
    skipped: dict[str, str] = {}
    calls = retries = 0
    for s in samples:
        if dry_run:
            continue
        if s.key in kept:
            items[s.id] = kept[s.key]
            continue
        if llm is None:
            llm = plan_llm(model)
        messages = [{"role": "system", "content": DRAFT_SYSTEM}, {"role": "user", "content": draft_prompt(s, bank)}]
        parsed, failed = None, None
        for attempt in range(2):   # once more only when the engine returned nothing
            calls += 1
            retries += attempt
            try:
                reply = llm(messages=messages, response_format={"type": "json_object"})
                content, failed = reply.choices[0].message.content or "", None
            except Exception as exc:  # noqa: BLE001 — one failed draft is reported, never fatal
                content, failed = "", f"draft failed: {type(exc).__name__}"
                break
            try:
                parsed = json_parse.parse_json_object(content)
            except Exception:  # noqa: BLE001 — to_item reports it
                parsed = None
            if not _empty(content, parsed):
                break
        if failed:
            skipped[s.id] = failed
        elif _empty(content, parsed):
            skipped[s.id] = "empty draft: the engine returned nothing twice"
        else:
            item, why = to_item(s, parsed, bank.pages[s.page].names)
            if item:
                items[s.id] = item
            else:
                skipped[s.id] = why or "skipped"
        print(f"{s.id:24} {s.kind:10} {'es' if s.spanish else '  '}  "
              f"{'drafted' if s.id in items else 'skipped'}", flush=True)
    if not dry_run:
        write_yaml(out, [items[s.id] for s in samples if s.id in items])
    write_review(review, samples, items, skipped, out)
    by_kind: dict[str, int] = defaultdict(int)
    for s in samples:
        by_kind[s.kind] += 1
    return {"samples": len(samples), "by_kind": dict(by_kind), "spanish": sum(s.spanish for s in samples),
            "drafted": len(items), "skipped": len(skipped), "plan_calls": calls, "retries": retries}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bank", type=Path, help="the bank folder to read (named explicitly, never guessed)")
    ap.add_argument("--limit", type=int, default=30, help="how many samples (one plan call each)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--kinds", nargs="*", choices=KINDS, help="only these kinds (default: all)")
    ap.add_argument("--model", default="sonnet", help="the plan model that drafts")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    ap.add_argument("--accepted", type=Path, default=DEFAULT_ACCEPTED)
    ap.add_argument("--dry-run", action="store_true", help="sample and write the review sheet; no plan call")
    ap.add_argument("--fresh", action="store_true", help="redraft samples already in --out")
    ap.add_argument("--accept", action="store_true", help="write --accepted from the ticked items in --review")
    a = ap.parse_args(argv)

    os.environ.setdefault("CICADA_TELEMETRY", "off")   # a measurement, not the person's use
    os.environ.setdefault("CICADA_CAPTURE", "off")
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    if a.accept:
        return accept(a.out, a.review, a.accepted)
    if a.bank is None:
        ap.error("--bank is required (or --accept)")
    bank = a.bank.expanduser().resolve()
    if not (bank / "entities").is_dir():
        print(f"no entities/ under {bank} — --bank takes a bank folder", file=sys.stderr)
        return 2
    for p in (a.out, a.review):
        rp = p.expanduser().resolve()
        if rp == bank or bank in rp.parents:
            print("--out and --review must be outside the bank", file=sys.stderr)
            return 2
    summary = run(bank, limit=max(0, a.limit), seed=a.seed, out=a.out, review=a.review, dry_run=a.dry_run,
                  fresh=a.fresh, kinds=tuple(a.kinds or KINDS), model=a.model)
    kinds = " · ".join(f"{k} {n}" for k, n in sorted(summary["by_kind"].items()))
    print(f"\n{summary['samples']} samples ({kinds}; {summary['spanish']} in Spanish) · {summary['drafted']} drafted · "
          f"{summary['skipped']} skipped · {summary['plan_calls']} plan calls ({summary['retries']} retries)")
    if not a.dry_run:
        print(f"questions: {a.out}")
    print(f"review sheet: {a.review}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
