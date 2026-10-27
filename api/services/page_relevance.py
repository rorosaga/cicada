"""Why a page matters to the person: was, is or will be (G121's personal tier; owner ruling 44, 2026-10-27).

The owner, 2026-10-27: "memory should always state why it is/was/will be relevant to me and also be up to date."

**Derived on read, never stored.** The line is computed from what the record already holds every time a page is read,
so it is current the moment the record changes (a closed claim turns "is" into "was" with nothing to rewrite) and it
can never be invented: no model writes it.

What counts, in order:

1. **A stated relation to the person** — a claim between the owner's page and this one (on either page, the owner's
   ledger included), or a claim on this page that cites the person's own words (``user`` / ``speaker`` evidence,
   ``promotion.PERSON_KINDS``). Its tense is read from the claim: closed (``valid_to``, or an elapsed stated end) is
   **was**; starting later, or a plan/intent predicate, is **will be**; otherwise **is**. A sink predicate
   (``relates-to``) is no relation.
2. **No stated relation** — said plainly, with what the record does show: how many conversations it came up in and
   when last, or that only an import or Cicada's own reading put it here. Never padded.

The owner's own page reads "This is you." A page with no claims and no conversations says that too.
"""
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from api.services import bank_index, promotion, quiet_pages

#: Relations that say nothing about the person ("X relates to Y"): never a reason on their own.
SINK_PREDICATES = frozenset({"relates-to", "related-to", "mentioned", "mentions", "mentioned-in", "associated-with"})
#: A predicate that looks forward: the relation is about to matter.
_FUTURE = re.compile(r"(?:^|-)(?:plan|plans|planning|planned|will|wants?|wanting|intends?|considering|consider|"
                     r"may|might|would|applying|upcoming|hopes?|aims?|going)(?:-|$)")
MAX_RELATIONS = 2
MAX_TEXT = 160
OWNER_LINE = "This is you."
_EP_DATE = re.compile(r"^ep_(\d{4}-\d{2}-\d{2})_")


@dataclass
class Relation:
    tense: str          # was | is | will_be
    text: str
    claim_id: str
    since: str = ""     # the day it was said or started
    until: str = ""     # the day it ended (was only)


@dataclass
class Relevance:
    tense: str                       # self | is | will_be | was | none
    line: str
    relations: list[Relation] = field(default_factory=list)
    conversations: int = 0
    last_mentioned: str = ""

    def to_dict(self) -> dict:
        return {"tense": self.tense, "line": self.line, "conversations": self.conversations,
                "last_mentioned": self.last_mentioned,
                "basis": [{"claim_id": r.claim_id, "tense": r.tense} for r in self.relations]}


# ---- the owner's side, cached per owner-page stamp ---------------------------------------------------------------

_owner_cache: dict[str, tuple[tuple, str, dict[str, list]]] = {}
_owner_lock = threading.Lock()


def _stamp(path: Path) -> tuple:
    out = []
    for p in (path, path.with_name(path.stem + ".claims.jsonl")):
        try:
            st = os.stat(p)
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


def owner_index(memory_path: Path) -> tuple[str | None, dict[str, list]]:
    """``(owner page id, {entity id: [owner claims whose object is that page]})`` — read once per owner-page stamp."""
    from api.services import markdown_parser
    from api.services.claims import parse_claims

    memory_path = Path(memory_path)
    owner_id = _owner_id(memory_path)
    if owner_id is None:
        return None, {}
    path = memory_path / "entities" / f"{owner_id}.md"
    stamp = _stamp(path)
    key = str(memory_path)
    with _owner_lock:
        hit = _owner_cache.get(key)
        if hit and hit[0] == stamp and hit[1] == owner_id:
            return owner_id, hit[2]
    by_object: dict[str, list] = {}
    try:
        claims = parse_claims(markdown_parser.parse(path).body)
    except Exception:  # noqa: BLE001 — an unreadable owner page reads as one with no relations
        claims = []
    for c in claims:
        if c.subject == owner_id and c.object_kind == "node" and c.object and c.object != owner_id:
            by_object.setdefault(c.object, []).append(c)
    with _owner_lock:
        _owner_cache[key] = (stamp, owner_id, by_object)
    return owner_id, by_object


_names_cache: dict[str, tuple[tuple, dict[str, str], str | None]] = {}


def page_names(memory_path: Path) -> dict[str, str]:
    """Page id -> name, read once per state of ``entities/`` (a claim with no text is phrased with them)."""
    return _bank_meta(memory_path)[0]


def _owner_id(memory_path: Path) -> str | None:
    return _bank_meta(memory_path)[1]


def _bank_meta(memory_path: Path) -> tuple[dict[str, str], str | None]:
    memory_path = Path(memory_path)
    try:
        stamp = bank_index.dir_stamp(memory_path, "entities")
    except Exception:  # noqa: BLE001
        stamp = None
    key = str(memory_path)
    hit = _names_cache.get(key)
    if hit is not None and stamp is not None and hit[0] == stamp:
        return hit[1], hit[2]
    names: dict[str, str] = {}
    owner: str | None = None
    try:
        for f in sorted(bank_index.files(memory_path, "entities"), key=lambda f: f.stem):
            fm = f.frontmatter or {}
            if fm.get("name"):
                names[f.stem] = str(fm["name"])
            if owner is None and fm.get("owner") is True:
                owner = f.stem
    except Exception:  # noqa: BLE001
        pass
    _names_cache[key] = (stamp, names, owner)
    return names, owner


# ---- tense ---------------------------------------------------------------------------------------------------------


def _day(raw) -> str:
    text = str(raw or "")[:10]
    return text if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) else ""


def tense_of(claim, today: date) -> str:
    from api.services.claims import read_valid_to

    end = read_valid_to(claim)
    if end and end <= today.isoformat():
        return "was"
    began = _day(getattr(claim, "valid_from", None))
    if began and began > today.isoformat():
        return "will_be"
    if _FUTURE.search(str(getattr(claim, "predicate", "") or "").lower()):
        return "will_be"
    return "is"


def _text(claim, names: dict[str, str]) -> str:
    from api.services import predicates

    text = " ".join(str(getattr(claim, "text", "") or "").split())
    if not text:
        subj = names.get(claim.subject, claim.subject)
        obj = names.get(claim.object, claim.object) if claim.object_kind == "node" else claim.object
        text = predicates.predicate_phrase(claim.predicate, subj, obj)
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1].rstrip() + "…"


def _cites_person(claim) -> bool:
    for ev in getattr(claim, "evidence", None) or []:
        start = getattr(ev, "start", None)
        if getattr(ev, "kind", None) in promotion.PERSON_KINDS and isinstance(start, int) and start >= 0:
            return True
    return False


def relations(memory_path: Path, entity_id: str, page_claims: list, *, today: date | None = None,
              names: dict[str, str] | None = None) -> list[Relation]:
    """Every stated relation between the person and this page, newest-relevant first (is, will be, was)."""
    today = today or date.today()
    owner_id, by_object = owner_index(memory_path)
    names = names or {}
    seen: set[str] = set()
    out: list[Relation] = []
    pool = list(by_object.get(entity_id, [])) if owner_id else []
    for c in page_claims:
        if owner_id and c.object_kind == "node" and c.object == owner_id:
            pool.append(c)
        elif _cites_person(c):
            pool.append(c)
    for c in pool:
        if c.id in seen or str(c.predicate or "").lower() in SINK_PREDICATES or getattr(c, "recovered_by", None):
            continue
        seen.add(c.id)
        t = tense_of(c, today)
        out.append(Relation(tense=t, text=_text(c, names), claim_id=c.id,
                            since=_day(c.valid_from) or _day(c.recorded_at),
                            until=_day(getattr(c, "valid_to", None)) if t == "was" else ""))
    rank = {"is": 0, "will_be": 1, "was": 2}
    # Within a tense, the most recent first.
    out.sort(key=lambda r: (rank[r.tense], -int(r.since.replace("-", "") or 0)))
    return out


# ---- mentions ------------------------------------------------------------------------------------------------------


def conversations(memory_path: Path, fm: dict) -> tuple[int, str, int]:
    """``(conversations it came up in, the last one's day, imports/checks only)`` from the page's own episodes."""
    convo, last, other = 0, "", 0
    for ep in fm.get("source_episodes") or []:
        ep = str(ep)
        entry = bank_index.file(Path(memory_path), "episodes", f"{ep}.md")
        kind = quiet_pages.episode_kind(entry.frontmatter if entry is not None else None)
        if kind is None and _EP_DATE.match(ep):
            kind = quiet_pages.CONVERSATION   # an id that no longer resolves still names the day it was said
        if kind == quiet_pages.CONVERSATION:
            convo += 1
            m = _EP_DATE.match(ep)
            if m and m.group(1) > last:
                last = m.group(1)
        elif kind is not None:
            other += 1
    return convo, last, other


# ---- the line ------------------------------------------------------------------------------------------------------


def _relation_clause(r: Relation) -> str:
    if r.tense == "was":
        return f"{r.text}" + (f" (until {r.until})" if r.until else "")
    if r.since:
        return f"{r.text} (since {r.since})" if r.tense == "is" else f"{r.text} (said {r.since})"
    return r.text


def compose(fm: dict, rels: list[Relation], convo: int, last: str, other: int) -> Relevance:
    if fm.get("owner") is True:
        return Relevance("self", OWNER_LINE)
    if rels:
        top = rels[0]
        head = {"is": "Why it matters to you", "will_be": "Why it will matter to you",
                "was": "Why it mattered to you"}[top.tense]
        shown = [top] + [r for r in rels[1:MAX_RELATIONS] if r.tense != top.tense or top.tense == "is"][:1]
        line = f"{head}: " + "; ".join(_relation_clause(r) for r in shown) + "."
        return Relevance(top.tense, line, shown, convo, last)
    if convo:
        word = "conversation" if convo == 1 else "conversations"
        line = (f"No personal relation on the record: it came up in {convo} {word}"
                + (f", last on {last}" if last else "") + ".")
    elif other:
        line = "No personal relation on the record: only a save, an import or Cicada's own reading put it here."
    else:
        line = "No personal relation on the record."
    return Relevance("none", line, [], convo, last)


def for_page(memory_path: Path, entity_id: str, *, today: date | None = None, fm: dict | None = None,
             body: str | None = None) -> Relevance:
    """The page's "why it matters to you" — never raises (an unreadable page reads as one with no relation)."""
    from api.services import markdown_parser
    from api.services.claims import parse_claims

    memory_path = Path(memory_path)
    try:
        if fm is None or body is None:
            parsed = markdown_parser.parse(memory_path / "entities" / f"{entity_id}.md")
            fm, body = parsed.frontmatter, parsed.body
        claims = parse_claims(body or "")
    except Exception:  # noqa: BLE001
        return Relevance("none", "No personal relation on the record.")
    if fm.get("owner") is True:
        return Relevance("self", OWNER_LINE)
    rels = relations(memory_path, entity_id, claims, today=today, names=page_names(memory_path))
    convo, last, other = conversations(memory_path, fm)
    return compose(fm, rels, convo, last, other)
