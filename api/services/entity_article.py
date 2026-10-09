"""Entity pages as articles (G194; owner 2026-10-09: "check how gbrain works … they do markdowns and i always see them
as way longer. So we dont constraint the agents … but keep a history (git)").

A page has two halves. **Above the line** — the ``## Summary`` lead and the ``## Article`` sections — is compiled
prose, rewritten freely each time the page gains material, at the length the material gives it. **Below the line** —
``## Key Facts``, ``## History``, ``## Links``, ``## Open Questions``, ``## Related`` and the claims fence — is the
record: unioned deterministically, never shortened by the writer. The line is conceptual, not a ``---`` in the file:
a rule right after a paragraph is a setext heading, and every parser of the page already splits on ``## ``.

    ## Summary
    The lead: what it is, what it is to the owner, where it stands as of a date. One paragraph, no length cap.

    ## Article
    ### <a title that fits the page>
    Paragraphs with [[links]] inside the sentences.

    ## Key Facts / ## History / … (the record)

The writer (:func:`prompt`, Stage 3, behind ``page_articles_enabled``) is given the record as numbered inputs — facts,
dated History lines, what this update's conversations said, the page's earlier prose, current claims, open questions
— and returns JSON: the lead and the sections, each paragraph listing the inputs it was written from. Code then holds
the rails (:func:`parse`): a paragraph that cites no input it shares a word with is the model's own knowledge, not the
person's experience (G121), and is dropped; so is one with a relative time word (G194: written as of its own date) or
"the user" (G169); a ``[[link]]`` to no page is unwrapped. A lead that fails these rejects the whole article (the
page keeps today's merge). Provenance is per paragraph (G118): each kept paragraph carries the evidence rows of the
inputs it validly cites, under the paragraph's exact text guard (`section_provenance`), so a line is still one click
from where it came from and an edit unlinks it rather than recertifying it.

What the prose leaves out is never lost: every fact stays in Key Facts, every dated line in History, every claim in
its fence. The two kinds of prose that were not yet record — this update's incoming summary and, on a page's first
article, its old Summary — have each sentence the article does not visibly carry kept as a Key Fact
(:func:`retained`). The writer's own earlier lead and paragraphs are rewritten freely; git keeps every version.

The frontmatter ``article`` stamp (:func:`stamp`) hashes the lead and the Article as written. When they no longer
match (:func:`edited`), someone edited them: the page is the person's from then on (`entity_body.has_human_prose`),
additive-only, and the writer leaves it alone.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date

from api.services import claims, entity_body, evidence, fact_policy, section_provenance, source_dates

SECTION = "Article"
FIELD = "article"            # frontmatter stamp
STAMP_VERSION = 1
PROMPT_VERSION = 1
MIN_CONVERSATIONS = 2        # a page resting on one conversation is a stub: it keeps today's merge, no call
MAX_EVIDENCE_PER_ITEM = 16   # rows recorded per paragraph (spans first); the inputs keep all of theirs

_RELATIVE = re.compile(r"\b(?:currently|now|nowadays|recently|lately|soon|these days|this (?:week|month|year)|"
                       r"right now|at the moment|at present)\b", re.I)
_THE_USER = re.compile(r"\bthe user(?:'s|’s)?\b", re.I)
_WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_BLOCK_START = re.compile(r"^\s*(?:#|[-*+]\s|>|\d+\.\s|```|~~~|\|)")
_TERMINAL = re.compile(r"""[.!?…]["'”’)\]]*$""")

# Sections a page of each type usually wants (owner: "a project, a person, a tool and a place want different
# sections"). Suggestions: the writer uses the ones the material fills, renames or adds one when the page needs it.
SUGGESTED_SECTIONS = {
    "person": ["Who they are", "With {owner}", "Work and projects together", "Where things stand"],
    "project": ["What it is", "{owner}'s part in it", "How it works", "How it developed", "Where it stands"],
    "company": ["What it is", "Connection to {owner}", "People", "Where things stand"],
    "tool": ["What it is", "How {owner} uses it", "Setup", "Problems and decisions"],
    "concept": ["What it is", "Why it matters to {owner}", "Where it comes up"],
    "location": ["The place", "{owner}'s connection to it", "Visits and plans"],
    "skill": ["What it is", "How {owner} practises it", "Progress"],
    "directory": ["What it holds", "How {owner} uses it"],
    "media": ["What it is", "Why {owner} saved it"],
    "deadline": ["What is due", "Where it stands"],
}

PROMPT = """You are writing a page of a personal wiki: an article about one thing as it figures in one person's life.

Write from the INPUT only. Every input has an id. The record (facts, dated history, claims) stays on the page below
your article whatever you write, so the article is for reading: connected sentences, not a list.

WHAT TO RETURN — JSON only:
{"summary": {"text": "...", "from": ["f0", "h2"]},
 "sections": [{"title": "...", "paragraphs": [{"text": "...", "from": ["f3", "c1"]}]}]}

THE LEAD ("summary"): one paragraph that says what it is, what it is to OWNER (built it, uses it, works with them,
is deciding about it) and where it stands as of the latest dated input, naming that month and year.

THE SECTIONS: prose paragraphs under short plain titles. SUGGESTED_SECTIONS fit this kind of page; use the ones the
material fills, in a sensible order, rename one or add another when the page needs it, and leave out any the inputs
do not fill. Length follows the material: write everything the inputs support and nothing they do not. Many inputs
make a long article; a handful make a lead and perhaps one short section. Never pad, never repeat a sentence.

RULES
- "from" lists the ids of the inputs that sentence-by-sentence support the paragraph. A paragraph with no supporting
  input is not written. Never add background from your own knowledge: what the thing is in general belongs only as
  far as the inputs say it.
- Link other pages inside the sentences with [[Name]], using only names from LINKABLE, each the first time it comes
  up in a section.
- Dates: write as of when things were said, never as of today. Anything said more than 90 days before TODAY names its
  month and year ("In February 2025, ..."). Plans, intentions and states of mind always name when they were stated.
  When inputs disagree, the later dated one is where things stand and the earlier one is how they were. Never write
  "currently", "now", "recently", "soon", "these days" or "this week".
- earlier inputs are the page's previous prose: unverified background to rewrite freely, not to copy.
- Name the owner as OWNER, never "the user". No markdown inside paragraphs except [[links]], **bold** and `code`;
  no bullet lists, no headings, no tables.
"""


# --------------------------------------------------------------------------- the stamp


def _halves(sections: dict) -> tuple[str, str]:
    return (str(sections.get("Summary") or "").strip(), str(sections.get(SECTION) or "").strip())


def _stamp_hash(sections: dict) -> str:
    lead, article = _halves(sections)
    return evidence.body_hash(lead + "\n\x00\n" + article)


def stamp(frontmatter: dict, sections: dict, *, written: str | None = None) -> None:
    """Record that the page's Summary and Article are the writer's, as they stand in ``sections``."""
    frontmatter[FIELD] = {"v": STAMP_VERSION, "hash": _stamp_hash(sections),
                          "written": written or date.today().isoformat()}


def stamped(frontmatter: dict, sections: dict) -> bool:
    """The lead and the Article (which may be empty: a lead-only article) are exactly what the writer last wrote."""
    raw = (frontmatter or {}).get(FIELD)
    if not _halves(sections or {})[0] or not isinstance(raw, dict) or raw.get("v") != STAMP_VERSION:
        return False
    return raw.get("hash") == _stamp_hash(sections)


def edited(frontmatter: dict, sections: dict) -> bool:
    """An Article the writer did not leave as it is: a hand-written one, or a machine one edited since."""
    return bool(_halves(sections or {})[1]) and not stamped(frontmatter, sections)


def carry_stamp(frontmatter: dict, old_body: str, new_body: str) -> None:
    """Another machine writer changed the prose mechanically (a renamed page's ``[[links]]``): keep the stamp valid
    when it was valid before, so the page does not read as hand-edited. An edited page stays edited."""
    old = entity_body.parse_sections(claims.strip_claims_block(old_body or ""))
    if stamped(frontmatter, old):
        written = (frontmatter.get(FIELD) or {}).get("written")
        stamp(frontmatter, entity_body.parse_sections(claims.strip_claims_block(new_body or "")), written=written)


def eligible(frontmatter: dict, change_sources) -> bool:
    """Gets an article: rests on at least :data:`MIN_CONVERSATIONS` conversations once this update lands."""
    sources = {str(e) for e in (frontmatter or {}).get("source_episodes") or [] if e}
    sources |= {str(e) for e in change_sources or [] if e}
    return len(sources) >= MIN_CONVERSATIONS


# --------------------------------------------------------------------------- the record half


def record_sections(prose_body: str, entity_type: str, new_fields: dict) -> dict:
    """The page's record after this update — Key Facts, History, Links, Open Questions (and Related as it is), each
    unioned with the extraction's by the same deterministic merge every writer uses — without the lead or Article."""
    sections = entity_body.upgrade_legacy_to_v2(prose_body, entity_type)
    sections.pop("Summary", None)
    sections.pop(SECTION, None)
    fields = {k: v for k, v in (new_fields or {}).items() if k not in ("summary", "description")}
    return entity_body.merge_sections_fallback(sections, {**fields, "summary": ""})


# --------------------------------------------------------------------------- inputs


@dataclass
class Source:
    id: str
    kind: str             # fact | history | said | earlier | claim | question | link
    text: str
    said_on: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    retain: bool = False  # orientation text that is not yet record: kept as a Key Fact unless the article carries it


@dataclass
class Inputs:
    sources: list[Source]
    data: dict

    def by_id(self) -> dict[str, Source]:
        return {s.id: s for s in self.sources}


def _ev_dicts(evs) -> list[dict]:
    out = []
    for ev in evs or []:
        row = ev.to_dict() if hasattr(ev, "to_dict") else dict(ev)
        if row not in out:
            out.append(row)
    return out


def _days(evs) -> list[str]:
    days = {source_dates.parse_day(row.get("episode")) for row in evs}
    return sorted(d.isoformat() for d in days if d)


def _records(entity: dict, fields=("summary", "description", "key_facts")) -> dict[str, list[dict]]:
    """The extraction's transient G118 inputs, by exact text."""
    out: dict[str, list[dict]] = {}
    for record in (entity or {}).get(section_provenance.INPUTS) or []:
        if record.get("field") in fields:
            rows = out.setdefault(str(record.get("text") or "").strip(), [])
            rows += [ev for ev in record.get("evidence") or [] if ev not in rows]
    return out


def build(*, name: str, entity_type: str, frontmatter: dict, original_body: str, record: dict,
          incoming: dict, today: str, update_days: list[str], owner: str | None = None,
          linkable=()) -> Inputs:
    """The writer's numbered inputs and the prompt's data. ``original_body`` is the page as read (claims included),
    ``record`` its record half after this update (:func:`record_sections`), ``incoming`` the extraction's fields."""
    prose = claims.strip_claims_block(original_body or "")
    page = entity_body.parse_sections(prose)
    matched = section_provenance.matched(frontmatter or {}, original_body or "")
    scanned = section_provenance.scan(original_body or "")

    def page_rows(section: str, text: str) -> list[dict]:
        item = section_provenance._item(text, ())
        proof = matched.get(section, {}).get(item.key)
        return _ev_dicts(proof[1]) if proof and proof[0] == item.text_hash else []

    incoming_rows = _records(incoming)
    sources: list[Source] = []

    def add(prefix: str, kind: str, text: str, rows: list[dict], said_on=None, retain=False) -> None:
        text = " ".join(str(text or "").split()) if kind != "fact" else str(text or "").strip()
        if not text:
            return
        count = sum(1 for s in sources if s.id[0] == prefix)
        sources.append(Source(f"{prefix}{count}", kind, text, said_on if said_on is not None else _days(rows),
                              rows, retain))

    first_article = not str(page.get(SECTION) or "").strip()
    old_lead = str(page.get("Summary") or "").strip()
    lead_item = next(iter(scanned.get("summary", [])), None)
    lead_rows = page_rows("summary", lead_item.text) if lead_item else []
    for sentence in entity_body._summary_sentences(old_lead):
        add("p", "earlier", sentence, lead_rows, retain=first_article)
    for item in scanned.get("article", []):
        add("p", "earlier", item.text, page_rows("article", item.text))

    said = str(incoming.get("summary") or incoming.get("description") or "").strip()
    said_rows = incoming_rows.get(said, [])
    for sentence in entity_body._summary_sentences(said):
        add("s", "said", sentence, said_rows, said_on=list(update_days), retain=True)

    for fact in entity_body._bullet_lines(record.get("Key Facts", "")):
        rows = page_rows("key_facts", fact) or list(incoming_rows.get(fact.strip(), []))
        add("f", "fact", fact, rows, said_on=_days(rows) or (list(update_days) if fact.strip() in incoming_rows
                                                                else []))
    for line in entity_body._bullet_lines(record.get("History", "")):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})", line.strip())
        add("h", "history", line, page_rows("history", line), said_on=[m.group(1)] if m else None)
    for line in entity_body._bullet_lines(record.get("Open Questions", "")):
        add("q", "question", line, page_rows("open_questions", line))
    for line in entity_body._bullet_lines(record.get("Links", "")):
        add("l", "link", line, [])

    now = source_dates.parse_day(today) or date.today()
    try:
        current = [c for c in claims.parse_claims(original_body or "")
                   if claims.is_current(c, now=now) and not claims.is_record(c)]
    except Exception:  # noqa: BLE001 - a fence that cannot be read costs the claims as inputs, never the article
        current = []
    for claim in current:
        rows = _ev_dicts(claim.evidence)
        add("c", "claim", claim.text, rows, said_on=[claim.valid_from] if claim.valid_from else _days(rows))

    owner_name = owner or "the person whose wiki this is"
    suggested = [t.format(owner=owner_name) for t in SUGGESTED_SECTIONS.get(entity_type, ["What it is",
                                                                                           "Where it stands"])]
    links = sorted({str(n) for n in linkable if n and str(n).strip() and str(n).lower() != name.lower()})
    data = {
        "TODAY": today, "OWNER": owner_name, "NAME": name, "TYPE": entity_type,
        "PAGE_FIRST_MENTIONED": str((frontmatter or {}).get("created") or "unknown")[:10],
        "THIS_UPDATE_SAID_ON": list(update_days) or ["unknown"],
        "SUGGESTED_SECTIONS": suggested, "LINKABLE": links,
        "INPUT": [{"id": s.id, "kind": s.kind, "text": s.text, **({"said_on": s.said_on} if s.said_on else {})}
                  for s in sources],
    }
    return Inputs(sources, data)


def prompt(inputs: Inputs, *, max_chars: int) -> str | None:
    """The writer's prompt, or ``None`` when it is over ``max_chars`` (never clipped: the latest dated input could be
    the part cut). The page then keeps the deterministic merge."""
    text = (PROMPT.replace("OWNER", inputs.data["OWNER"]) + "\nDATA:\n"
            + json.dumps(inputs.data, ensure_ascii=False, indent=0))
    return text if len(text) <= max_chars else None


# --------------------------------------------------------------------------- the answer


@dataclass
class Paragraph:
    text: str
    cites: list[str]
    evidence: list[dict]


@dataclass
class Written:
    lead: Paragraph
    sections: list[tuple[str, list[Paragraph]]]
    dropped: dict[str, int]

    def paragraphs(self) -> list[Paragraph]:
        return [self.lead] + [p for _t, ps in self.sections for p in ps]

    def markdown(self) -> str:
        return "\n\n".join(f"### {title}\n\n" + "\n\n".join(p.text for p in paras) for title, paras in self.sections)


def _words(text: str, name_words) -> frozenset[str]:
    return fact_policy._profile(text)[0] - name_words


def _known(known) -> set[str]:
    return {str(k).strip().lower() for k in known or () if str(k).strip()}


def _unlink(text: str, known: set[str]) -> tuple[str, int]:
    count = 0

    def repl(m):
        nonlocal count
        if m.group(1).strip().lower() in known:
            return m.group(0)
        count += 1
        return m.group(2) or m.group(1)

    return _WIKILINK.sub(repl, text), count


def _clean(text) -> str | None:
    if not isinstance(text, str):
        return None
    text = text.strip()
    if not text or re.search(r"\n\s*\n", text) or "```" in text or _BLOCK_START.match(text):
        return None
    return " ".join(text.split())


def _evidence(cited: list[Source]) -> list[dict]:
    rows: list[dict] = []
    for source in cited:
        rows += [r for r in source.evidence if r not in rows]
    rows.sort(key=lambda r: r.get("kind") == "reasoning")  # spans first
    return rows[:MAX_EVIDENCE_PER_ITEM]


def _paragraph(raw, by_id: dict[str, Source], name_words, known: set[str], dropped: dict) -> Paragraph | None:
    if not isinstance(raw, dict):
        dropped["malformed"] = dropped.get("malformed", 0) + 1
        return None
    text = _clean(raw.get("text"))
    if text is None:
        dropped["malformed"] = dropped.get("malformed", 0) + 1
        return None
    if _RELATIVE.search(text):
        dropped["relative_time"] = dropped.get("relative_time", 0) + 1   # G194
        return None
    if _THE_USER.search(text):
        dropped["the_user"] = dropped.get("the_user", 0) + 1             # G169
        return None
    if not _TERMINAL.search(text):
        dropped["unfinished"] = dropped.get("unfinished", 0) + 1
        return None
    text, unlinked = _unlink(text, known)
    if unlinked:
        dropped["links_unwrapped"] = dropped.get("links_unwrapped", 0) + unlinked
    words = _words(text, name_words)
    cites, cited = [], []
    for ident in raw.get("from") or []:
        source = by_id.get(str(ident).strip()) if isinstance(ident, (str, int)) else None
        if source is None or source.id in cites:
            continue
        own = _words(source.text, name_words)
        if own and not own & words:
            continue   # cites an input it shares no word with: not where this paragraph came from
        cites.append(source.id)
        cited.append(source)
    if not cites:
        dropped["uncited"] = dropped.get("uncited", 0) + 1                # G121: not from the person's record
        return None
    return Paragraph(text, cites, _evidence(cited))


def parse(raw, inputs: Inputs, *, name: str, aliases=(), known=()) -> Written | None:
    """The model's answer as a validated article, or ``None`` (the page keeps the deterministic merge). ``known``:
    the names, aliases and ids of the bank's pages, which a ``[[link]]`` must name."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return None
    if not isinstance(raw, dict):
        return None
    by_id = inputs.by_id()
    name_words = frozenset().union(*(fact_policy._profile(str(n))[0] for n in (name, *aliases) if n))
    known_names = _known(known) | _known([name, *aliases])
    dropped: dict[str, int] = {}
    lead = _paragraph(raw.get("summary"), by_id, name_words, known_names, dropped)
    if lead is None:
        return None
    sections: list[tuple[str, list[Paragraph]]] = []
    canonical = {t.lower() for t in entity_body.CANONICAL_SECTIONS} | {"description"}
    for section in raw.get("sections") or []:
        if not isinstance(section, dict):
            continue
        title = " ".join(str(section.get("title") or "").lstrip("# ").split())
        if (not title or len(title) > 80 or title.lower() in canonical or "[[" in title or "`" in title
                or _RELATIVE.search(title)):
            dropped["bad_title"] = dropped.get("bad_title", 0) + 1
            continue
        paras = [p for p in (_paragraph(r, by_id, name_words, known_names, dropped)
                             for r in section.get("paragraphs") or []) if p]
        if not paras:
            continue
        existing = next((ps for t, ps in sections if t.lower() == title.lower()), None)
        if existing is not None:
            existing.extend(paras)
        else:
            sections.append((title, paras))
    return Written(lead, sections, dropped)


def retained(inputs: Inputs, written: Written, *, name: str = "", aliases=()) -> list[str]:
    """The orientation sentences that are not yet record (this update's summary; a first article's old Summary) and
    that no kept paragraph visibly carries: they become Key Facts. Carried = cited by a paragraph that has most of
    its words (:func:`_carried`: three in five, at least two, and every name in it) and every number, negation and
    tense or status word it has (`fact_policy.compatible`, the orientation synthesis's floor). Anything less is kept:
    a duplicate in the record is cheaper than a lost sentence."""
    name_words = frozenset().union(*(fact_policy._profile(str(n))[0] for n in (name, *aliases) if n))
    citing: dict[str, list[str]] = {}
    for paragraph in written.paragraphs():
        for ident in paragraph.cites:
            citing.setdefault(ident, []).append(paragraph.text)
    out = []
    for source in inputs.sources:
        if not source.retain:
            continue
        carried = any(_carried(source.text, text, name_words) for text in citing.get(source.id, []))
        if not carried:
            out.append(source.text)
    return out


_NAME_TOKEN = re.compile(r"\[\[([^\]|]+)|(?<=\s)([A-Z][\w'’-]*)|([\w]+-[\w-]+)")


def _carried(sentence: str, paragraph: str, name_words) -> bool:
    """``paragraph`` says what ``sentence`` says, as far as words can tell: it shares at least three in five of the
    sentence's content words (at least two; one for a one-word sentence), every name the sentence uses (a
    ``[[link]]``, a capitalised word after the first, a hyphenated name) and nothing `fact_policy.compatible` forbids."""
    own = _words(sentence, name_words)
    theirs = _words(paragraph, name_words)
    need = max(min(2, len(own)), -(-3 * len(own) // 5))
    if len(own & theirs) < need or not fact_policy.compatible(sentence, paragraph):
        return False
    for m in _NAME_TOKEN.finditer(" " + sentence):
        token = next(g for g in m.groups() if g)
        if not _words(token, name_words) <= theirs:
            return False
    return True


def records(written: Written) -> list[dict]:
    """G118 inputs for the written prose: the lead as ``summary``, each paragraph as ``article``, with the evidence of
    the inputs it validly cites (`section_provenance.refresh` keeps them under each item's exact text guard)."""
    out = []
    if written.lead.evidence:
        out.append({"field": "summary", "text": written.lead.text, "evidence": list(written.lead.evidence)})
    for _title, paras in written.sections:
        for p in paras:
            if p.evidence:
                out.append({"field": "article", "text": p.text, "evidence": list(p.evidence)})
    return out


def payload(inputs: Inputs, written: Written, *, name: str = "", aliases=()) -> dict:
    """What Stage 3 hands Stage 5 on the change (``change["article"]``): plain data, decided once."""
    return {"lead": written.lead.text, "markdown": written.markdown(), "records": records(written),
            "retain": retained(inputs, written, name=name, aliases=aliases), "dropped": dict(written.dropped),
            "prompt_version": PROMPT_VERSION}


def compose(prose_body: str, entity_type: str, new_fields: dict, article: dict) -> dict:
    """Stage 5's page: the record half merged as Stage 3 saw it, then the written lead and Article, then the
    orientation sentences the article did not carry as Key Facts."""
    sections = record_sections(prose_body, entity_type, new_fields)
    sections["Summary"] = article["lead"]
    if article.get("markdown"):
        sections[SECTION] = article["markdown"]
    if article.get("retain"):
        sections["Key Facts"] = entity_body._merge_facts(sections.get("Key Facts", ""), list(article["retain"]))
    return sections
