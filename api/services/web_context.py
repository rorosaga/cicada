"""Light web context for public pages, kept current (G121; owner ruling 44, 2026-10-27, amends rulings 27 and 40).

The owner, 2026-10-27: "looking up public figures not only them but companies, programs, anything really i think
internet can add a lot of useful context, but depends on the request. Can start small or be bigger, memory should
always state why it is/was/will be relevant to me and also be up to date."

**Who may be looked up — the public test** (:func:`local_verdict`, then :func:`wikidata_verdict`; err private):

* Never the owner, a project, a skill, a directory, a saved item (``media``: ruling 30's saves are indexed, never read
  by a model) or a name that is not a public proper name (``org_sites.proper_name``), carries a person's or a project's
  name, or that the page says is the person's own.
* A **person** is public only when ALL of these hold, and private otherwise:
  1. locally, with nothing sent: a full name (two words or more, not relation-shaped, not a role-only page); no
     acquaintance with the owner on the record — a relation, or a prose sentence naming the owner or "the user", that
     says they know each other: met, talked or messaged, friend, family, partner, colleague or classmate, a contact,
     invited by, interviewed by, taught or supervised (``_ACQUAINTANCE``); being inspired by, reading, watching,
     quoting, citing, following or admiring their public work is not acquaintance; no conversation from a personal
     channel (Messages, a LinkedIn import); and a public cue on the page — a public role (founder, author, researcher
     …) or public work (a talk, a tweet, a book, a video, a role at a company);
  2. then, and only then, Wikidata: exactly ONE item whose label or alias IS the name, that is a human (P31 = Q5),
     with an encyclopedia article (a Wikipedia sitelink). Zero or several → private.
  A name that fails step 1 never reaches any service — not Wikidata, not the search.
* A **company, tool or place** is public on the local test alone (ruling 27's public things). A **concept** also needs
  step 2's shape: exactly one non-human Wikidata item with an encyclopedia article (a concept is often the person's
  own idea).

**What a lookup writes** (:func:`apply`): cited, dated world-tier claims (observer ``agent``, ``source_trust:
external``, ``origin: web-context``), their citations in one ``web-check`` episode (a ``page``-kind span each; never
the page's ``sources:``, never a tracked source — ruling 27's shape), and one record under ``inbox/settled/ctx-<n>.md``
so the person can take it back from "Settled by a check" (:func:`undo`). The newest cited value replaces an older open
world fact of the same predicate (closed, ``superseded_by`` — history kept on the page and in git); a fact that cites
the person's own words about their own life is never closed or contradicted (``protected``; what they said about a
public thing's world fact is replaced like any dated world fact, history kept); a value the person took back is never
written again (the memo's ``undone``).

**Depth follows use** (:func:`depth_for`): a passing page gets a line (≤ 2 facts, one search); one the person comes back
to gets more (≤ 4, two searches); one with a commitment — applied to, attending, registered, a deadline — gets dates
and deadlines (≤ 8, three searches, the extra two the name plus "dates" / "deadline"). Every search must be one of the
pinned queries word for word (``web_lookup.queries_ok``'s rule), or nothing is written.

**Re-checks** (:func:`plan`): world facts are a dated cache. A page never looked up, or holding world facts no lookup
wrote (model knowledge), is due first, most-used first. A page looked up before is due again after its most volatile
predicate's base interval (a role, a price, a deadline: 30 days; a headquarters, a description: 180; a founding date:
never) divided by ``1 + log2(1 + use)``. A page with no conversation in 180 days is re-checked only when someone asks
(:func:`deeper`). Use is the record's own count — conversations, stated relations, a mention in the last 30 days; the
telemetry ledger's reads are not used (CLAUDE.md: nothing learned from the ledger is auto-applied).

**Gates.** The Sleep tail is behind ``CICADA_ALLOW_CONNECTOR_FETCH`` and ``web_context_per_run`` (default 6 lookups a
run, 0 = off) and :data:`WIKIDATA_BUDGET` public-test lookups a run; the person's click (:func:`deeper`) is not gated
by the connector switch (a click never is). Engine: a plan's own web search only — a metered key is never spent here
(``metered_only``, said in words), a scheduled run needs ruling 4b's switch. Wikidata through ``org_sites.wikidata_get``
(``net_guard``, 4 s, ≤ 512 KB, no cookies, a block never retried). Telemetry: ids and enums only
(``web_settle.record_event``). The memo lives outside every bank: page ids, days, enums and hashes.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger

from api.services import bank_index, page_relevance, promotion, text_fold, web_settle

STAGE = "web_context"
ORIGIN = "web-context"
RECORD_PREFIX = "ctx-"
DEFAULT_PER_RUN = 6
WIKIDATA_BUDGET = 20
WIKIDATA_RETRY_DAYS = 90
TIMEOUT_S = 150.0
MAX_VALUE_CHARS = 120
QUIET_DAYS = 180
#: Use at which a page gets more than a line: e.g. two conversations, one of them in the last 30 days.
STANDARD_USE = 4

#: Types a lookup may ever be about. ``media`` is a save (ruling 30); ``project``/``skill``/``directory``/``deadline``
#: are the person's own.
SCOPE_TYPES = frozenset({"person", "company", "tool", "location", "concept"})
#: Personal channels: a conversation from one of these makes a person someone the owner knows.
PERSONAL_SOURCES = frozenset({"imessage", "messages", "email", "gmail", "whatsapp", "contacts", "linkedin"})
#: Acquaintance on the record (coordinator rule 2026-10-27): a relation, or a sentence naming the owner, that says the
#: two know each other — met, talked or messaged, friend, family, partner, colleague or classmate, a contact, invited
#: by, interviewed by, a shared chat, taught or supervised. Being inspired by, reading, watching, quoting, citing,
#: following, admiring or wanting to work at their company is NOT one: that is consuming public work. Applied to a
#: relation's label (hyphens read as spaces) and to each prose sentence that names the owner.
_ACQUAINTANCE = re.compile(
    r"\b(?:met|meet|meets|meeting|talked|talks? (?:with|to)|spoke|speaks? (?:with|to)|chatted|chats? with|"
    r"messag\w*|texted|texts?|e-?mailed|e-?mails? (?:with|to|from)|called|phoned|dm(?:s|ed)?|whatsapp\w*|"
    r"friends?|friendship|befriended|family|brother|sister|mother|father|dad|mom|mum|son|daughter|cousin|uncle|aunt|"
    r"wife|husband|partner|girlfriend|boyfriend|dating|dated (?:him|her)|ex-\w+|"
    r"colleagues?|co-?workers?|teammates?|same team|classmates?|same class|class(?:es)? (?:with|of|taught)|"
    r"roommates?|flatmates?|neighbou?rs?|"
    r"contacts?|contacted|connected|connection|reached out|reach out|outreach|introduc\w*|approach(?:ed|ing)? (?:him|her|them)|(?:person|one) to approach|"
    r"invited by|invited (?:him|her|them)|invitation (?:from|to)|interviewed by|interviewed with|interview invitation|"
    r"interview(?:ed|ing)? (?:him|her|them)|shares? a chat|group chat|"
    r"taught|teaches|teacher|professor of|supervis\w*|advis(?:or|er|es|ed)|mentor\w*|thesis (?:director|tutor)|"
    r"boss|manager of|reports to|works? with|worked with|working with|collaborat\w*|co-?authored|alongside|"
    r"hired|recruit\w*|referred|referral|offered|forwarded|knows|known personally)\b",
    re.IGNORECASE)
PUBLIC_ROLE = re.compile(
    r"\b(?:founder|co-?founder|ceo|cto|chief executive|president|prime minister|minister|senator|congress(?:wo)?man|"
    r"politician|author|writer|novelist|journalist|researcher|scientist|physicist|mathematician|economist|"
    r"philosopher|historian|professor|investor|venture capitalist|entrepreneur|youtuber|podcaster|streamer|"
    r"influencer|actor|actress|filmmaker|film director|musician|singer|rapper|composer|artist|athlete|footballer|"
    r"tennis player|chess player|grandmaster|astronaut|nobel|known for|public figure|blogger|commentator|"
    r"fundador|cofundador|autor|escritor|investigador|cantante|presidente|periodista|"
    # Public work on the page counts as a cue too (a talk, a tweet, a book, a video, a role at a company): the
    # encyclopedia match below still has to hold.
    r"talks?|keynote|lectures?|tweets?|tweeted|posts? on x|book|books|video|videos|youtube channel|podcast|"
    r"interview with|paper|papers|essay|blog|newsletter|substack|engineer at|works at|worked at|joined)\b",
    re.IGNORECASE)
#: Words an owner alias may carry that name nobody ("the user", an address's "gmail", a school's "edu").
_NOT_A_NAME = frozenset({"the", "user", "person", "owner", "speaker", "student", "com", "edu", "org", "net", "gmail",
                         "mail", "email", "outlook", "icloud", "hotmail", "yahoo", "me", "you"})
_SPEAKER = re.compile(r"\b(?:the (?:user|person|owner|speaker)|you|your)\b", re.IGNORECASE)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_COMMITMENT = re.compile(r"appl|attend|regist|enrol|interview|admit|accept|offer|deadline|cohort|fellowship|"
                         r"scholarship|hackathon|conference|program|visit|trip|travel|ticket|booked", re.IGNORECASE)

#: The world-tier predicates a lookup may write, and how fast each goes stale.
VOLATILITY = {
    "works-at": "volatile", "role": "volatile", "led-by": "volatile", "status": "volatile",
    "latest-version": "volatile", "pricing": "volatile", "owned-by": "volatile", "deadline": "volatile",
    "starts": "volatile", "ends": "volatile", "application-opens": "volatile", "edition": "volatile",
    "takes-place-in": "volatile",
    "description": "slow", "headquartered-in": "slow", "industry": "slow", "known-for": "slow",
    "located-in": "slow", "made-by": "slow", "license": "slow", "part-of": "slow",
    "founded": "fixed",
}
BASE_DAYS = {"volatile": 30, "slow": 180}
_BY_TYPE = {
    "person": ("description", "works-at", "role", "known-for"),
    "company": ("description", "headquartered-in", "founded", "led-by", "industry", "status", "owned-by"),
    "tool": ("description", "made-by", "latest-version", "license", "pricing", "status"),
    "location": ("description", "located-in", "known-for"),
    "concept": ("description", "part-of", "known-for"),
}
_DEEP_EXTRA = ("deadline", "starts", "ends", "application-opens", "edition", "takes-place-in")
DEPTHS = {"line": (2, ()), "standard": (4, ()), "deep": (8, ("dates", "deadline"))}
#: What each predicate means, for the model.
_MEANING = {
    "description": "what it is, in one short phrase", "works-at": "the organisation the person works at now",
    "role": "their current role or title", "known-for": "what it is best known for",
    "headquartered-in": "city/country of its headquarters", "founded": "the year it was founded",
    "led-by": "who leads it now (a public figure's name only)", "industry": "its industry",
    "status": "active, acquired by <x>, defunct …", "owned-by": "its parent organisation now",
    "made-by": "who makes it", "latest-version": "its latest version", "license": "its licence",
    "pricing": "its current price or plan", "located-in": "the country (and region) it is in",
    "part-of": "what it is part of", "deadline": "the next application or registration deadline, as a date",
    "starts": "the next edition's start date", "ends": "the next edition's end date",
    "application-opens": "when applications open, as a date", "edition": "the next edition's name or year",
    "takes-place-in": "where the next edition takes place",
}
REASON_WORDS = {
    "off": "Light context is off (web_context_per_run is 0).",
    "gate": "Light context is off: Sleep may not fetch on its own (CICADA_ALLOW_CONNECTOR_FETCH).",
    "nothing": "No public page is due for light context.",
    "metered_only": "Light context runs only on a plan's own web search; the only engine here is a metered key, so "
                    "it was skipped and nothing was spent.",
    "scheduled_plan": "Light context skipped: scheduled runs may not use the plan (Settings switch).",
    "no_search_tool": "Light context skipped: this engine has no web search.",
    "no_engine": "Light context skipped: no engine is set up.",
}


# ---------------------------------------------------------------------------------------------------- the memo


def _memo_path(memory_path: Path) -> Path:
    from api.services.auth import cicada_home

    return cicada_home() / "web_context" / f"{Path(memory_path).name}.json"


def load_memo(memory_path: Path) -> dict:
    try:
        raw = json.loads(_memo_path(memory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    for key in ("pages", "wd", "undone"):
        if not isinstance(raw.get(key), dict):
            raw[key] = {}
    return raw


def save_memo(memory_path: Path, memo: dict) -> None:
    path = _memo_path(memory_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(memo, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.debug(f"web context memo not saved: {type(exc).__name__}")


ENDED_MARK = "ended:"


def value_hash(predicate: str, value: str) -> str:
    """A taken-back value, remembered without its words."""
    return hashlib.sha256(f"{predicate}\x00{text_fold.fold(value)}".encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------------------------------- the page


@dataclass
class Page:
    entity_id: str
    name: str
    type: str
    fm: dict
    body: str
    claims: list
    relevance: page_relevance.Relevance
    use: int = 0
    depth: str = "line"
    last_mentioned: str = ""
    world: list = field(default_factory=list)       # open world-tier claims on the page
    owner_id: str | None = None
    owner_words: frozenset = frozenset()            # the owner's name words (3+ letters): "about their own life"


def _cites_the_person(claim) -> bool:
    from api.services.claims import is_persons_words

    if str(getattr(claim, "source_trust", "") or "") == "user_stated" or is_persons_words(claim):
        return True
    for ev in getattr(claim, "evidence", None) or []:
        start = getattr(ev, "start", None)
        if getattr(ev, "kind", None) in promotion.PERSON_KINDS and isinstance(start, int) and start >= 0:
            return True
    return False


def _is_protected(claim, page: "Page | None" = None) -> bool:
    """The person's own words about their own life: never closed or contradicted by a lookup (ruling 44). A claim
    that cites their words AND is about them — its object is the owner's page, its text names the owner, or its
    predicate's truth lives in the person (``locus: person``). What the person said about a public thing's world
    fact (a public figure's employer, a tool's version) is a dated world fact like any other: the newest dated,
    cited evidence replaces it, closed with its history kept and undoable (ruling 26's rule for a re-check)."""
    if not _cites_the_person(claim):
        return False
    if page is None:
        return True   # no page to judge by: err on the person's side
    if page.owner_id and str(getattr(claim, "object", "") or "") == page.owner_id:
        return True
    if page.owner_words and set(text_fold.words(str(getattr(claim, "text", "") or ""))) & page.owner_words:
        return True
    return _locus(str(getattr(claim, "predicate", "") or "")) == "person"


_LOCUS_FN: list = []


def _locus(predicate: str) -> str:
    """The seed vocabulary's ``locus`` for a predicate, read once per process."""
    if not _LOCUS_FN:
        from api.services import predicates

        _LOCUS_FN.append(predicates.build_locus_fn(None))
    return _LOCUS_FN[0](predicate)


def world_claims(claims: list, *, today: date | None = None) -> list:
    from api.services.claims import is_current, is_event

    preds = set(VOLATILITY) | set(web_settle.PUBLIC_PREDICATES)
    return [c for c in claims if str(c.predicate or "").lower() in preds and not is_event(c)
            and is_current(c, now=today)]


def depth_for(rel: page_relevance.Relevance, use: int) -> str:
    if any(r.tense in ("is", "will_be") and _COMMITMENT.search(r.text) for r in rel.relations):
        return "deep"
    return "standard" if use >= STANDARD_USE else "line"


def load_page(memory_path: Path, entity_id: str, *, today: date | None = None) -> Page | None:
    from api.services import markdown_parser
    from api.services.claims import parse_claims

    today = today or date.today()
    path = Path(memory_path) / "entities" / f"{entity_id}.md"
    try:
        parsed = markdown_parser.parse(path)
        claims = parse_claims(parsed.body)
    except Exception:  # noqa: BLE001 — an unreadable page is no candidate
        return None
    fm = parsed.frontmatter
    rel = page_relevance.for_page(memory_path, entity_id, today=today, fm=fm, body=parsed.body)
    recent = bool(rel.last_mentioned) and rel.last_mentioned >= (today - timedelta(days=30)).isoformat()
    use = rel.conversations + 2 * sum(1 for r in rel.relations if r.tense in ("is", "will_be")) + (2 if recent else 0)
    owner_id = page_relevance._owner_id(memory_path)
    owner_name = page_relevance.page_names(memory_path).get(owner_id or "", "")
    return Page(entity_id=entity_id, name=" ".join(str(fm.get("name") or entity_id).split()),
                owner_id=owner_id, owner_words=frozenset(w for w in text_fold.words(owner_name) if len(w) >= 3),
                type=str(fm.get("type") or "").strip().lower(), fm=fm, body=parsed.body, claims=claims,
                relevance=rel, use=use, depth=depth_for(rel, use), last_mentioned=rel.last_mentioned,
                world=world_claims(claims, today=today))


# ---------------------------------------------------------------------------------------------------- public test


@dataclass
class Verdict:
    public: bool | None          # None: passed the local test, Wikidata still to ask
    reason: str


def _prose(body: str) -> str:
    from api.services.claims import strip_claims_block

    return strip_claims_block(body or "")


def _owner_mentions(text: str, owner_names: frozenset[str], subject: str = "") -> list[str]:
    """Sentences of ``text`` that name the owner (or speak of "the user"/"you") — each one a possible relation. A word
    the subject's own name shares with the owner's (a common surname) is not a mention of the owner."""
    own = set(text_fold.words(subject))
    names = {n for n in owner_names if " " not in n and len(n) >= 3 and n.isalpha() and n not in _NOT_A_NAME
             and n not in text_fold.SUBJECT_STOPWORDS} - own
    out = []
    for sentence in _SENTENCE.split(text or ""):
        words = set(text_fold.words(sentence))
        if (words & names) or _SPEAKER.search(sentence):
            out.append(sentence)
    return out


def _personal_channel(memory_path: Path, fm: dict) -> bool:
    for ep in fm.get("source_episodes") or []:
        entry = bank_index.file(Path(memory_path), "episodes", f"{ep}.md")
        if entry is not None and str((entry.frontmatter or {}).get("source") or "").lower() in PERSONAL_SOURCES:
            return True
    return False


def local_verdict(memory_path: Path, page: Page, facts: web_settle.BankFacts) -> Verdict:
    """The test that runs with nothing sent. ``public=None`` means: only Wikidata may still say public."""
    from api.services import org_sites

    fm = page.fm
    if fm.get("owner") is True:
        return Verdict(False, "owner")
    if page.type not in SCOPE_TYPES:
        return Verdict(False, "type")
    if fm.get("unnamed") or fm.get("owner_roles"):
        return Verdict(False, "relation_only")
    name = page.name
    if not org_sites.proper_name(name):
        return Verdict(False, "name_shape")
    folded = text_fold.fold(name)
    owner_id = facts.owner_id
    if page.type != "person":
        if folded in facts.project_names:
            return Verdict(False, "project")
        others = facts.person_names | facts.pending_person_names
        if web_settle._names_a_person(name, frozenset(others)) or web_settle._names_a_person(name, facts.owner_names):
            return Verdict(False, "person_name")
        if org_sites._OWN_THING.search(" ".join([str(fm.get("description") or ""), str(fm.get("summary") or "")])):
            return Verdict(False, "own_thing")
        _, by_object = page_relevance.owner_index(memory_path)
        own = re.compile(r"(?:^|-)(?:founded|co-?founded|cofounded|created|built|owns|develops|developed|maintains|"
                         r"runs|works-on|building)(?:-|$)")
        if any(own.search(str(c.predicate or "").lower()) for c in by_object.get(page.entity_id, [])):
            return Verdict(False, "own_thing")
        if page.type == "concept":
            return Verdict(None, "needs_encyclopedia")
        return Verdict(True, "public_thing")
    # A person.
    words = [w for w in name.split() if w[:1].isalpha()]
    if len(words) < 2:
        return Verdict(False, "single_name")
    if web_settle.relation_shaped(name):
        return Verdict(False, "relation")
    if folded in facts.owner_names:
        return Verdict(False, "owner")
    _, by_object = page_relevance.owner_index(memory_path)
    def knows(predicate) -> bool:
        return bool(_ACQUAINTANCE.search(str(predicate or "").replace("-", " ").replace("_", " ")))

    if any(knows(c.predicate) for c in by_object.get(page.entity_id, [])):
        return Verdict(False, "personal_relation")
    if owner_id and any(c.object_kind == "node" and c.object == owner_id and knows(c.predicate) for c in page.claims):
        return Verdict(False, "personal_relation")
    for sentence in _owner_mentions(_prose(page.body), facts.owner_names, page.name):
        if _ACQUAINTANCE.search(sentence):
            return Verdict(False, "owner_in_prose")
    if _personal_channel(memory_path, fm):
        return Verdict(False, "personal_channel")
    cues = " ".join([_prose(page.body), " ".join(str(t) for t in fm.get("tags") or []),
                     " ".join(str(c.text or "") for c in page.claims)])
    if not PUBLIC_ROLE.search(cues):
        return Verdict(False, "no_public_cue")
    return Verdict(None, "needs_encyclopedia")


JsonGet = Callable[[dict], Awaitable[dict | None]]


def _has_article(entity: dict) -> bool:
    links = (entity or {}).get("sitelinks") or {}
    return any(k.endswith("wiki") and k not in {"commonswiki", "specieswiki", "wikidatawiki", "metawiki",
                                                "mediawikiwiki", "sourceswiki"} for k in links)


async def wikidata_verdict(page: Page, get: JsonGet) -> Verdict:
    """Step 2: exactly one Wikidata item that IS this name, of the right kind (a human for a person, not a human
    otherwise), with an encyclopedia article. Only the page's name is sent."""
    from api.services import org_sites

    want_human = page.type == "person"
    data = await get({"action": "wbsearchentities", "search": page.name, "language": "en", "uselang": "en",
                      "type": "item", "limit": org_sites.SEARCH_LIMIT})
    if data is None or not isinstance(data.get("search"), list):
        # An error body (rate limit, maxlag) is no answer: never read, or cached, as "no such person".
        return Verdict(False, "lookup_failed")
    target = text_fold.fold(page.name)
    hits = [h for h in data.get("search") or [] if isinstance(h, dict) and h.get("id")
            and (text_fold.fold(str(h.get("label") or "")) == target
                 or text_fold.fold(str((h.get("match") or {}).get("text") or "")) == target)]
    kind: list[str] = []
    for hit in hits:
        p31 = await get({"action": "wbgetclaims", "entity": hit["id"], "property": "P31"})
        if p31 is None or "claims" not in p31:   # a failed request is no answer: never read as "not a human"
            return Verdict(False, "lookup_failed")
        classes = org_sites._claim_values(p31, "P31")
        if (org_sites.HUMAN in classes) == want_human:
            kind.append(hit["id"])
    if not kind:
        return Verdict(False, "no_encyclopedia")
    if len(kind) > 1:
        return Verdict(False, "ambiguous")
    ent = await get({"action": "wbgetentities", "ids": kind[0], "props": "sitelinks"})
    if ent is None or "entities" not in ent:
        return Verdict(False, "lookup_failed")
    entity = ((ent or {}).get("entities") or {}).get(kind[0]) or {}
    if not _has_article(entity):
        return Verdict(False, "no_article")
    return Verdict(True, "encyclopedia_match")


async def verdict(memory_path: Path, page: Page, facts: web_settle.BankFacts, memo: dict, *, get: JsonGet | None,
                  today: date, budget: list[int] | None = None) -> Verdict:
    """The full test, Wikidata's answer cached outside every bank for :data:`WIKIDATA_RETRY_DAYS`. ``get=None`` (no
    network) or a spent ``budget`` leaves a page that still needs Wikidata private for now (``wikidata_pending``)."""
    v = local_verdict(memory_path, page, facts)
    if v.public is not None:
        return v
    cached = memo["wd"].get(page.entity_id) or {}
    if cached.get("at", "") >= (today - timedelta(days=WIKIDATA_RETRY_DAYS)).isoformat() and cached.get("v"):
        return Verdict(cached["v"] == "encyclopedia_match", str(cached["v"]))
    if get is None or (budget is not None and budget[0] <= 0):
        return Verdict(False, "wikidata_pending")
    if budget is not None:
        budget[0] -= 1
    w = await wikidata_verdict(page, get)
    if w.reason != "lookup_failed":
        memo["wd"][page.entity_id] = {"v": w.reason, "at": today.isoformat()}
    return w


# ---------------------------------------------------------------------------------------------------- the schedule


def interval_days(page: Page) -> float | None:
    """Days until this page's world facts are due again; None: never on a schedule (fixed facts only)."""
    preds = {str(c.predicate or "").lower() for c in page.world} or set(_BY_TYPE.get(page.type, ()))
    bases = [BASE_DAYS[VOLATILITY[p]] for p in preds if VOLATILITY.get(p) in BASE_DAYS]
    if not bases:
        return None
    return min(bases) / (1.0 + math.log2(1 + max(0, page.use)))


def due(page: Page, memo: dict, today: date) -> tuple[bool, str, float]:
    """``(due, why, priority)`` — ``why`` in new | unchecked | recheck | fresh | on_read | fixed; higher priority first."""
    entry = memo["pages"].get(page.entity_id) or {}
    at = str(entry.get("at") or "")
    if not at:
        unchecked = any(str(c.origin or "") != ORIGIN for c in page.world)
        return True, ("unchecked" if unchecked else "new"), 1000.0 + page.use
    if not page.last_mentioned or page.last_mentioned < (today - timedelta(days=QUIET_DAYS)).isoformat():
        return False, "on_read", 0.0
    days = interval_days(page)
    if days is None:
        return False, "fixed", 0.0
    try:
        age = (today - date.fromisoformat(at)).days
    except ValueError:
        age = 10 ** 4
    if age < days:
        return False, "fresh", 0.0
    return True, "recheck", age / days


def candidates(memory_path: Path, *, today: date, skip: frozenset[str] = frozenset()) -> list[Page]:
    """Live pages of a scope type with at least one conversation, read from the warm frontmatter cache first."""
    from api.services import quiet_pages

    out: list[Page] = []
    for f in bank_index.files(Path(memory_path), "entities"):
        fm = f.frontmatter or {}
        if str(fm.get("type") or "").lower() not in SCOPE_TYPES or fm.get("owner") is True:
            continue
        if str(fm.get("status") or "active") in ("archived", "dropped") or f"entities/{f.stem}.md" in skip:
            continue
        if f.stem.endswith(".claims") or quiet_pages.page_is_quiet(Path(memory_path), f.stem):
            continue
        page = load_page(memory_path, f.stem, today=today)
        if page is not None and page.relevance.conversations > 0:
            out.append(page)
    return out


@dataclass
class Planned:
    page: Page
    why: str
    priority: float
    verdict: Verdict


async def plan(memory_path: Path, *, cap: int, today: date, memo: dict, get: JsonGet | None,
               facts: web_settle.BankFacts | None = None, skip: frozenset[str] = frozenset(),
               wikidata_budget: int = WIKIDATA_BUDGET, pages: list[Page] | None = None) -> list[Planned]:
    """The next ``cap`` lookups: due pages, highest priority first, each passing the public test. Writes only the
    memo's Wikidata cache (outside every bank)."""
    facts = facts or web_settle.bank_facts(memory_path)
    pool = pages if pages is not None else candidates(memory_path, today=today, skip=skip)
    ranked = []
    for page in pool:
        ok, why, prio = due(page, memo, today)
        if ok:
            ranked.append((prio, page, why))
    ranked.sort(key=lambda r: (-r[0], r[1].entity_id))
    budget = [wikidata_budget]
    out: list[Planned] = []
    for prio, page, why in ranked:
        if len(out) >= cap:
            break
        v = await verdict(memory_path, page, facts, memo, get=get, today=today, budget=budget)
        if v.public:
            out.append(Planned(page, why, prio, v))
    return out


# ---------------------------------------------------------------------------------------------------- the lookup


def allowed_predicates(page: Page, depth: str) -> list[str]:
    preds = list(_BY_TYPE.get(page.type, ("description",)))
    if depth == "deep" and page.type != "person":
        preds += [p for p in _DEEP_EXTRA if p not in preds]
    return preds


def queries_for(page: Page, depth: str) -> list[str]:
    """The pinned queries: the name (plus at most one generic category word from Cicada's own description, never for a
    person or a place), and for a deep lookup the name plus "dates" / "deadline". Nothing else ever leaves the machine."""
    base = page.name
    # A place is searched by its name alone (dry run 2026-10-27: a country's description gave "startup", and the
    # search found its startup scene instead of the place).
    if page.type not in ("person", "location"):
        desc = web_settle.description_for(page.fm, page.fm, page.body)
        cat = web_settle._category(desc, type_question=False, labels=[], name=page.name)
        if cat:
            base = f"{page.name} {cat[0]}"
    extra = DEPTHS[depth][1] if page.type != "person" else ()
    return [base] + [f"{page.name} {w}" for w in extra]


SYSTEM_PROMPT = (
    "You look up current public facts about ONE public subject on the web. Use the web search tool only with the "
    "queries you are given, word for word, each at most once; never search for anything else. You may be given the "
    "person's own notes about the subject: they are only for telling which result is the subject the person meant "
    "(one name can belong to several things); never search for their words and never answer from them. You may also be "
    "given facts already on file: say what the results say NOW, whether it matches them or not.\n"
    "Report only facts the results state, each with the link of the result that states it and that result's words "
    "as the search showed them (at most 240 characters). For each fact give \"as_of\": the date the result gives "
    "for it (YYYY, YYYY-MM or YYYY-MM-DD), or \"\" when it gives none. Prefer the most recent result; for a role, an "
    "employer, a price or a version give the current one. Never write a relative date (\"next month\"). Never name a "
    "private person. Use only the predicates listed. A value is at most 12 words.\n"
    "When a fact on file is no longer true and the results name nothing in its place, give it with its value on file and "
    "\"ended\": true (a person who left an organisation and joined none the results name). Never write that something "
    "ended as a value.\n"
    "Answer {\"sure\": false, \"facts\": []} when the results are about different things sharing the name and the "
    "notes do not say which, or when they say nothing about the subject.\n"
    "Reply with one JSON object and nothing else: {\"sure\": true, \"facts\": [{\"predicate\": <one listed>, "
    "\"value\": <short>, \"as_of\": <date or \"\">, \"url\": <link>, \"quote\": <the result's words>}]}."
)


def build_messages(page: Page, depth: str, facts: web_settle.BankFacts) -> list[dict]:
    limit = DEPTHS[depth][0]
    keep = web_settle.subject_words(page.name)
    lines = [f"Subject: {page.name}", "Search queries (use only these, word for word):"]
    lines += [f"  {q}" for q in queries_for(page, depth)]
    desc = web_settle.description_for(page.fm, page.fm, page.body)
    if desc:
        lines.append("The person's own notes about this subject (only for telling which result is the one meant):")
        lines.append("  " + web_settle.clean_context_line(desc, facts, keep=keep))
    if page.world:
        lines.append("Facts on file — for each, give the same predicate with what the results say NOW: the same value "
                 "when it is still true, the new value when it changed (a person who left an organisation: where "
                 "they work now):")
        for c in page.world[:8]:
            lines.append("  " + web_settle.clean_context_line(f"{c.predicate}: {c.object}", facts, keep=keep))
    lines.append(f"Predicates you may use (at most {limit} facts in all):")
    lines += [f"  {p}: {_MEANING.get(p, p)}" for p in allowed_predicates(page, depth)]
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "\n".join(lines)}]


@dataclass
class Fact:
    predicate: str
    value: str
    as_of: str
    url: str
    quote: str
    #: The value on file is no longer true and the results name no replacement: close it, write nothing new.
    ended: bool = False


#: A value that only says something ended ("Left X in 2024", "former CEO") is no value: it must come as ``ended``.
_ENDED_VALUE = re.compile(r"^\s*(?:left|no longer|former(?:ly)?|ex-|previously|stepped down|departed)\b", re.IGNORECASE)
_AS_OF = re.compile(r"^\d{4}(?:-\d{2}(?:-\d{2})?)?$")


def parse_facts(page: Page, depth: str, text: str, facts: web_settle.BankFacts) -> tuple[list[Fact], str]:
    """``(facts, reason)`` — reason ``ok`` or why nothing usable came back. A value naming a private person of the
    bank, a missing citation or a predicate not offered drops that fact."""
    from api.services.json_parse import parse_json_object

    try:
        data = parse_json_object(text)
    except Exception:  # noqa: BLE001
        data = None
    if not isinstance(data, dict):
        return [], "unreadable"
    if data.get("sure") is not True:
        return [], "unsure"
    allowed = set(allowed_predicates(page, depth))
    private = frozenset(n for n in facts.person_names | facts.pending_person_names
                        if text_fold.fold(n) not in {text_fold.fold(page.name)})
    out: list[Fact] = []
    for row in data.get("facts") or []:
        if not isinstance(row, dict):
            continue
        pred = str(row.get("predicate") or "").strip().lower()
        value = " ".join(str(row.get("value") or "").split())[:MAX_VALUE_CHARS]
        url, quote = str(row.get("url") or "").strip(), web_settle.clean_quote(row.get("quote"))
        as_of = str(row.get("as_of") or "").strip()
        if pred not in allowed or not value or not quote or not url.lower().startswith(("http://", "https://")):
            continue
        if web_settle._names_a_person(value, private) or web_settle._names_a_person(value, facts.owner_names):
            continue
        try:
            web_settle.check_ref(url, "public")   # a walled or refused page is never cited
        except web_settle.NotSettleable:
            continue
        ended = row.get("ended") is True
        on_file = {text_fold.fold(str(c.object or "")) for c in page.world if str(c.predicate or "").lower() == pred}
        if ended and text_fold.fold(value) not in on_file:
            continue   # an end is said only of a value on file
        if not ended and _ENDED_VALUE.search(value):
            continue
        out.append(Fact(pred, value, as_of if _AS_OF.match(as_of) else "", url, quote, ended))
        if len(out) >= DEPTHS[depth][0]:
            break
    return out, ("ok" if out else "no_facts")


def queries_ok(searched: list[str], allowed: list[str]) -> bool:
    from api.services.web_lookup import _norm

    pinned = {_norm(q) for q in allowed}
    return 0 < len(searched) <= len(allowed) + 1 and all(_norm(q) in pinned for q in searched)


@dataclass
class Looked:
    page: Page
    depth: str
    facts: list[Fact]
    reason: str
    model: str | None = None


async def look_up(fn: Callable[..., Any], page: Page, depth: str, facts: web_settle.BankFacts) -> Looked:
    """One engine call; an answer counts only when every search was a pinned query. Writes nothing."""
    from api.services import web_lookup

    try:
        resp = await asyncio.to_thread(fn, messages=build_messages(page, depth, facts), web_search=True,
                                       timeout=TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001
        from api.services import engine_errors

        logger.info(f"web context: a lookup failed ({type(exc).__name__})")
        limit = isinstance(exc, (engine_errors.EngineThrottled, engine_errors.EngineExhausted,
                                 engine_errors.EngineOverage))
        return Looked(page, depth, [], "plan_limit" if limit else "engine_error")
    model = web_lookup._model_of(resp)
    if not queries_ok(web_lookup.searched_queries(resp), queries_for(page, depth)):
        return Looked(page, depth, [], "query_strayed", model)
    found, reason = parse_facts(page, depth, web_lookup._content(resp), facts)
    return Looked(page, depth, found, reason, model)


# ---------------------------------------------------------------------------------------------------- the write


@dataclass
class Change:
    predicate: str
    value: str
    action: str                 # add | replace | confirm | protected | undone
    old: list[str] = field(default_factory=list)
    url: str = ""


def diff(page: Page, found: list[Fact], undone: set[str]) -> list[Change]:
    """What writing ``found`` would do to the page — the dry run's answer, and :func:`apply`'s plan."""
    out: list[Change] = []
    by_pred: dict[str, list[Fact]] = {}
    for f in found:
        by_pred.setdefault(f.predicate, []).append(f)
    for pred, rows in by_pred.items():
        open_same = [c for c in page.world if str(c.predicate or "").lower() == pred]
        values = {text_fold.fold(r.value) for r in rows if not r.ended}
        for r in rows:
            if r.ended:
                if value_hash(pred, ENDED_MARK + r.value) in undone:
                    out.append(Change(pred, r.value, "undone", url=r.url))
                    continue
                ending = [c for c in open_same if text_fold.fold(str(c.object or "")) == text_fold.fold(r.value)]
                if any(_is_protected(c, page) for c in ending):
                    out.append(Change(pred, r.value, "protected", [r.value], url=r.url))
                elif ending:
                    out.append(Change(pred, r.value, "end", [r.value], url=r.url))
                continue
            if value_hash(pred, r.value) in undone:
                out.append(Change(pred, r.value, "undone", url=r.url))
                continue
            if any(text_fold.fold(str(c.object or "")) == text_fold.fold(r.value) for c in open_same):
                out.append(Change(pred, r.value, "confirm", url=r.url))
                continue
            stale = [c for c in open_same if text_fold.fold(str(c.object or "")) not in values]
            if any(_is_protected(c, page) for c in stale):
                out.append(Change(pred, r.value, "protected", [str(c.object) for c in stale if _is_protected(c, page)],
                                  url=r.url))
                continue
            out.append(Change(pred, r.value, "replace" if stale else "add", [str(c.object) for c in stale],
                              url=r.url))
    return out


@dataclass
class Written:
    record_id: str
    paths: list[str]
    lines: list[str]
    changes: list[Change]


def _next_record_id(memory_path: Path) -> str:
    settled = Path(memory_path) / "inbox" / web_settle.SETTLED_DIR
    nums = [int(m.group(1)) for p in settled.glob(f"{RECORD_PREFIX}*.md")
            if (m := re.fullmatch(rf"{RECORD_PREFIX}(\d+)", p.stem))]
    return f"{RECORD_PREFIX}{(max(nums) + 1) if nums else 1:03d}"


def _write_episode(memory_path: Path, page: Page, rows: list[Fact], checker: str, origin: str) -> str:
    from api.services import episode_ids
    from api.services.web_settle import check_ref

    body = [f"assistant: Looked up {page.name} on the web.", ""]
    for r in rows:
        try:
            ref, host = check_ref(r.url, "public")
        except web_settle.NotSettleable:
            continue
        body += [f"attachment [{host}]: as {checker} read it at {ref}", f"> {r.quote}", ""]
    # Every writer scrubs (CLAUDE.md): a quoted page could carry a token or a one-time code.
    from api.services import episode_scrub

    text = episode_scrub.scrub_body("\n".join(body).rstrip() + "\n", writer="web-context",
                                    bank=Path(memory_path).name)
    episodes_dir = Path(memory_path) / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    fm = {
        "id": episode_ids.next_episode_id(episodes_dir, date.today().isoformat()),
        "timestamp": episode_ids.utc_now_iso(),
        "source": web_settle.SOURCE,
        "origin": origin,
        "check_kind": "context",
        "title": f"Web context: {page.name}"[:120],
        "processed": True,
        "processed_by": "agent",
        "content_hash": hashlib.sha256(f"{page.entity_id}\x00{text}".encode("utf-8")).hexdigest()[:12],
        "entity_id": page.entity_id,
    }
    return episode_ids.create_episode(episodes_dir, fm, text)


def apply(memory_path: Path, page: Page, found: list[Fact], *, checker: str, origin: str = "sleep",
          engine: str | None = None, undone: set[str] | None = None) -> Written | None:
    """Write one lookup's facts. The caller holds the bank (Sleep's window, or admission + page lock) and commits
    ``paths``. None when nothing changes (every fact confirmed, protected or taken back)."""
    from api.services import markdown_parser, predicates
    from api.services.claims import Claim, MalformedClaimsBlockError, parse_claims, write_claims

    memory_path = Path(memory_path)
    entity_path = memory_path / "entities" / f"{page.entity_id}.md"
    parsed = markdown_parser.parse(entity_path)
    try:
        claims = parse_claims(parsed.body, strict=True)
    except MalformedClaimsBlockError:
        return None
    page.claims, page.world = claims, world_claims(claims)
    changes = diff(page, found, undone or set())
    to_write = [c for c in changes if c.action in ("add", "replace", "end")]
    if not to_write:
        return None
    rows = [f for f in found if any(c.predicate == f.predicate and c.value == f.value for c in to_write)]
    ending = [f for f in rows if f.ended]
    rows = [f for f in rows if not f.ended]
    label = checker if checker and checker != "agent" else "an agent"
    episode_id = _write_episode(memory_path, page, rows + ending, label, origin)
    from api.services.web_settle import _evidence_for

    today = date.today().isoformat()
    new_claims: list = []
    closed: list[dict] = []
    world_ids = {id(w) for w in page.world}
    for f in rows:
        pred = f.predicate   # this feature's own closed vocabulary: never folded into another label
        digest = hashlib.sha1(f"{page.entity_id}\x00{pred}\x00{f.value}\x00ctx\x00{today}".encode()).hexdigest()[:8]
        cid = f"clm_{today}_ctx_{digest}"
        if any(x.id == cid for x in claims + new_claims):
            continue
        valid_from = f.as_of if len(f.as_of) == 10 else today
        new = Claim(id=cid, text=predicates.predicate_phrase(pred, page.name, f.value), subject=page.entity_id,
                    predicate=pred, object=f.value, object_kind="literal", observer="agent", source_trust="external",
                    origin=ORIGIN, authored_by=checker or "agent", confidence=0.8, valid_from=valid_from,
                    recorded_at=today, evidence=list(_evidence_for(memory_path, episode_id, f.quote)))
        values = {text_fold.fold(r.value) for r in rows if r.predicate == f.predicate}
        for old in claims:
            if (str(old.predicate or "").lower() == f.predicate and id(old) in world_ids and not _is_protected(old, page)
                    and text_fold.fold(str(old.object or "")) not in values and old.valid_to is None):
                before = old.to_dict()
                old.valid_to = today
                old.superseded_by = cid
                closed.append({"id": old.id, "before": json.dumps(before, sort_keys=True),
                               "after": json.dumps(old.to_dict(), sort_keys=True)})
        new_claims.append(new)
    ended: list[list[str]] = []
    for f in ending:
        end_day = f.as_of if len(f.as_of) == 10 and f.as_of <= today else today
        for old in claims:
            if (str(old.predicate or "").lower() == f.predicate and id(old) in world_ids and old.valid_to is None
                    and not _is_protected(old, page)
                    and text_fold.fold(str(old.object or "")) == text_fold.fold(f.value)):
                before = old.to_dict()
                # Never closed before it began: a claim recorded after the end the source dates keeps its own start.
                began = str(old.valid_from or "")[:10]
                old.valid_to = end_day if not began or end_day >= began else began
                closed.append({"id": old.id, "before": json.dumps(before, sort_keys=True),
                               "after": json.dumps(old.to_dict(), sort_keys=True)})
                ended.append([f.predicate, f.value])
    if not new_claims and not ended:
        (memory_path / "episodes" / f"{episode_id}.md").unlink(missing_ok=True)
        return None
    markdown_parser.write(entity_path, parsed.frontmatter, write_claims(parsed.body, claims + new_claims))
    record_id = _next_record_id(memory_path)
    settled_dir = memory_path / "inbox" / web_settle.SETTLED_DIR
    settled_dir.mkdir(parents=True, exist_ok=True)
    first = (rows + ending)[0]
    try:
        ref, host = web_settle.check_ref(first.url, "public")
    except web_settle.NotSettleable:
        ref, host = first.url, ""
    record = {
        "at": _now_iso(), "by": checker or "agent", "by_kind": "sleep" if origin == "sleep" else "person",
        "scope": "public", "group": "check", "ref": ref, "host": host, "quote": first.quote,
        "answer": "; ".join([f"{c.predicate}: {c.object}" for c in new_claims]
                            + [f"{p_}: {v} (no longer)" for p_, v in ended]),
        "predicate": new_claims[0].predicate if new_claims else ended[0][0],
        "entity_id": page.entity_id, "entity_name": page.name, "claim_id": new_claims[0].id if new_claims else "",
        "claim_ids": [c.id for c in new_claims], "episode": episode_id, "held": False, "closed": closed,
        "ended": ended,
        **({"engine": engine} if engine else {}),
    }
    markdown_parser.write(settled_dir / f"{record_id}.md",
                          {"kind": "context", "question": f"What is current about {page.name}?",
                           "entity_id": page.entity_id, "entity_name": page.name, "settled": record}, "")
    bank_index.invalidate(memory_path)
    trigger = "sleep/web-context" if origin == "sleep" else "person/web-context"
    paths = [f"episodes/{episode_id}.md", f"entities/{page.entity_id}.md",
             f"inbox/{web_settle.SETTLED_DIR}/{record_id}.md"]
    lines = [f"episodes/{episode_id}.md: created (source: web-context, trigger: {trigger})",
             f"entities/{page.entity_id}.md: updated (source: {episode_id}, trigger: {trigger})",
             f"inbox/{web_settle.SETTLED_DIR}/{record_id}.md: created (source: {episode_id}, trigger: {trigger})"]
    return Written(record_id, paths, lines, changes)


def is_record_id(item_id: str) -> bool:
    return bool(re.fullmatch(rf"{RECORD_PREFIX}\d{{3,}}", item_id or ""))


def undo(memory_path: Path, record_id: str) -> tuple[list[str], list[str]]:
    """Take back one lookup: its claims withdrawn, what it closed reopened (only a claim still as it left it), the
    record removed, and each value remembered so no lookup writes it again. ``web_settle.NotSettleable`` when there is
    no such record. The episode stays: it is what the lookup read."""
    from api.services import markdown_parser
    from api.services.claims import Claim, MalformedClaimsBlockError, parse_claims, write_claims

    memory_path = Path(memory_path)
    if not is_record_id(record_id):
        raise web_settle.NotSettleable("No such settled check.")
    rec_path = memory_path / "inbox" / web_settle.SETTLED_DIR / f"{record_id}.md"
    if not rec_path.exists():
        raise web_settle.NotSettleable("No such settled check.")
    rec = markdown_parser.parse(rec_path).frontmatter.get("settled")
    if not isinstance(rec, dict):
        raise web_settle.NotSettleable("No such settled check.")
    entity_id = str(rec.get("entity_id") or "")
    claim_ids = {str(x) for x in rec.get("claim_ids") or [] if x}
    paths: list[str] = []
    lines: list[str] = []
    entity_path = memory_path / "entities" / f"{entity_id}.md"
    taken: list[tuple[str, str]] = []
    if entity_path.exists():
        page = markdown_parser.parse(entity_path)
        try:
            claims = parse_claims(page.body, strict=True)
        except MalformedClaimsBlockError as exc:
            raise web_settle.NotSettleable("The page's claims could not be read; nothing was changed.") from exc
        taken = [(str(c.predicate), str(c.object)) for c in claims if c.id in claim_ids]
        kept = [c for c in claims if c.id not in claim_ids]
        changed = len(kept) != len(claims)
        closed = {str(r.get("id")): r for r in rec.get("closed") or [] if isinstance(r, dict)}
        for i, c in enumerate(kept):
            row = closed.get(c.id)
            if row and json.dumps(c.to_dict(), sort_keys=True) == row.get("after"):
                kept[i] = Claim.from_dict(json.loads(row["before"]))
                changed = True
        if changed:
            markdown_parser.write(entity_path, page.frontmatter, write_claims(page.body, kept))
            paths.append(f"entities/{entity_id}.md")
            lines.append(f"entities/{entity_id}.md: updated (source: {record_id}, trigger: inbox/web-context/undone)")
    taken += [(str(p_), ENDED_MARK + str(v)) for p_, v in (rec.get("ended") or []) if p_ and v]
    rec_path.unlink()
    bank_index.invalidate(memory_path)
    paths.append(f"inbox/{web_settle.SETTLED_DIR}/{record_id}.md")
    lines.append(f"inbox/{web_settle.SETTLED_DIR}/{record_id}.md: removed (trigger: inbox/web-context/undone)")
    if taken:
        memo = load_memo(memory_path)
        undone = set(memo["undone"].get(entity_id) or [])
        undone |= {value_hash(p, v) for p, v in taken}
        memo["undone"][entity_id] = sorted(undone)
        save_memo(memory_path, memo)
    return paths, lines


# ---------------------------------------------------------------------------------------------------- engine


async def engine_for(settings, *, user_triggered: bool) -> tuple[Any, str | None, str]:
    """A plan's own web search, or nothing: a metered key is never spent here (``metered_only``)."""
    from api.services import web_lookup

    resolved, label, why = await web_lookup.engine_for(settings, user_triggered=user_triggered)
    if why == "plan":
        return resolved, label, why
    mode = str(getattr(settings, "llm_mode", "") or "").strip().lower()
    if why in ("metered", "search_unreported") or (why == "no_search_tool" and mode == "byok"):
        return None, label, "metered_only"
    return None, label, why


def _llm_fn(resolved, *, sink=None):
    from api.services import providers

    return providers.resolve_llm_fn(resolved, stage=STAGE, is_async=False, sink=sink)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------------------------------- Sleep's tail


@dataclass
class Report:
    looked_up: int = 0
    written: int = 0
    wikidata: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    paths: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    engine: str | None = None
    models: list[str] = field(default_factory=list)
    reason: str | None = None
    before: dict[str, bytes | None] = field(default_factory=dict)
    settled_items: list[str] = field(default_factory=list)   # web_lookup.restore's memo hook: never used here

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1

    @property
    def words(self) -> str:
        return REASON_WORDS.get(self.reason or "", "")


def _snapshot(memory_path: Path, report: Report, rels: list[str]) -> None:
    for rel in rels:
        if rel not in report.before:
            p = Path(memory_path) / rel
            try:
                report.before[rel] = p.read_bytes() if p.is_file() else None
            except OSError:
                report.before[rel] = None


async def run_tail(memory_path: Path, settings, *, user_triggered: bool, llm_fn: Callable[..., Any] | None = None,
                   engine: tuple[Any, str | None, str] | None = None, get: JsonGet | None = None,
                   today: date | None = None, skip: frozenset[str] = frozenset(),
                   report: Report | None = None) -> Report:
    """Look up this run's due public pages and write what changed. Never raises; the caller commits
    ``report.paths`` (and on a failed commit calls ``web_lookup.restore(memory_path, report)``)."""
    from api.services import org_sites
    from api.services.connectors.base import network_allowed

    report = report if report is not None else Report()
    memory_path = Path(memory_path)
    today = today or date.today()
    cap = int(getattr(settings, "web_context_per_run", DEFAULT_PER_RUN) or 0)
    if cap <= 0:
        report.reason = "off"
        return report
    if not network_allowed():
        report.reason = "gate"
        return report
    resolved, label, why = engine if engine is not None else await engine_for(settings, user_triggered=user_triggered)
    report.engine = label
    if resolved is None:
        # Decided before any page is read or any name leaves: no engine that may search, nothing is sent anywhere.
        report.reason = why
        return report
    memo = load_memo(memory_path)
    facts = web_settle.bank_facts(memory_path)
    counted: list[int] = [0]

    async def _get(params: dict) -> dict | None:
        counted[0] += 1
        return await (get or org_sites.wikidata_get)(params)

    todo = await plan(memory_path, cap=cap, today=today, memo=memo, get=_get, facts=facts, skip=skip)
    report.wikidata = counted[0]
    if not todo:
        save_memo(memory_path, memo)
        report.reason = "nothing"
        return report
    fn = llm_fn or _llm_fn(resolved)
    for item in todo:
        page = item.page
        looked = await look_up(fn, page, page.depth, facts)
        report.looked_up += 1
        if looked.model and looked.model not in report.models:
            report.models.append(looked.model)
        if looked.reason == "plan_limit":
            report.skip("plan_limit")
            break   # a plan limit is a pause: the rest waits for the next run
        if looked.reason == "engine_error":
            report.skip("engine_error")
            continue
        memo["pages"][page.entity_id] = {"at": today.isoformat(), "outcome": looked.reason, "depth": page.depth}
        if not looked.facts:
            report.skip(looked.reason)
            web_settle.record_event(memory_path, action="context_skip", item_id="", entity_id=page.entity_id,
                                    by_kind="sleep", reason=looked.reason, engine=label)
            continue
        by = looked.model or label or "agent"
        _snapshot(memory_path, report, [f"entities/{page.entity_id}.md", f"entities/{page.entity_id}.claims.jsonl"])
        try:
            done = await asyncio.to_thread(apply, memory_path, page, looked.facts, checker=by, origin="sleep",
                                           engine=label, undone=set(memo["undone"].get(page.entity_id) or []))
        except Exception as exc:  # noqa: BLE001 — one page never stops the rest
            logger.warning(f"web context: a page was not written ({type(exc).__name__})")
            report.skip("write_failed")
            continue
        if done is None:
            report.skip("unchanged")
            continue
        for rel in done.paths:
            report.before.setdefault(rel, None)
        report.written += 1
        report.paths += [p for p in done.paths if p not in report.paths]
        report.lines += done.lines
        web_settle.record_event(memory_path, action="context", item_id=done.record_id, entity_id=page.entity_id,
                                by_kind="sleep", engine=label)
    save_memo(memory_path, memo)
    return report


# ---------------------------------------------------------------------------------------------------- on request


async def deeper(memory_path: Path, settings, entity_id: str, *, llm_fn: Callable[..., Any] | None = None,
                 engine: tuple[Any, str | None, str] | None = None, get: JsonGet | None = None,
                 commit: bool = True) -> dict:
    """The person's click (or their agent through the API): a deep lookup on this one page, now — the same public test,
    pinned queries, citations, protection and undo; no schedule and no per-run budget; not behind the connector switch
    (a click never is). Returns counts and enums, plus the written record's id."""
    from api.services import git_service, org_sites, page_lock, write_admission

    memory_path = Path(memory_path)
    page = load_page(memory_path, entity_id)
    if page is None:
        return {"status": "not_found"}
    memo = load_memo(memory_path)
    facts = web_settle.bank_facts(memory_path)
    v = await verdict(memory_path, page, facts, memo, get=get or org_sites.wikidata_get, today=date.today())
    save_memo(memory_path, memo)
    if not v.public:
        return {"status": "private", "reason": v.reason}
    resolved, label, why = engine if engine is not None else await engine_for(settings, user_triggered=True)
    if resolved is None:
        return {"status": "skipped", "reason": why, "words": REASON_WORDS.get(why, "")}
    looked = await look_up(llm_fn or _llm_fn(resolved), page, "deep", facts)
    memo = load_memo(memory_path)
    if looked.reason not in ("engine_error", "plan_limit"):
        memo["pages"][entity_id] = {"at": date.today().isoformat(), "outcome": looked.reason, "depth": "deep"}
        save_memo(memory_path, memo)
    if not looked.facts:
        return {"status": "nothing", "reason": looked.reason}
    by = looked.model or label or "agent"
    undone = set(memo["undone"].get(entity_id) or [])

    def work() -> Written | None:
        with page_lock.page_lock(memory_path):
            before = git_service.snapshot_dirty_sync(memory_path) if commit else None
            done = apply(memory_path, page, looked.facts, checker=by, origin="person", engine=label, undone=undone)
            if done is not None and commit:
                web_settle.commit_sync(memory_path, web_settle.commit_message("Web context", done.lines,
                                                                              authors=[by], engine=label),
                                       done.paths, before=before)
            return done

    from api.services.sleep_refusal import SleepWriting

    done = await write_admission.run_admitted(memory_path, lambda: asyncio.to_thread(work),
                                              refuse=lambda: SleepWriting("Sleep is running; try again after it."))
    if done is None:
        return {"status": "unchanged", "facts": len(looked.facts)}
    web_settle.record_event(memory_path, action="context", item_id=done.record_id, entity_id=entity_id,
                            by_kind="person", engine=label)
    return {"status": "written", "record_id": done.record_id,
            "changes": {a: sum(1 for c in done.changes if c.action == a)
                        for a in ("add", "replace", "confirm", "protected", "undone")}}


# ---------------------------------------------------------------------------------------------------- the dry run


async def dry_run(memory_path: Path, settings, *, limit: int, today: date | None = None,
                  llm_fn: Callable[..., Any] | None = None, engine: tuple[Any, str | None, str] | None = None,
                  get: JsonGet | None = None, wikidata_budget: int = 200, sample: int = 30) -> dict:
    """Measure on a bank copy, writing nothing to the bank (the memo is a scratch copy: never saved). Returns the full
    rows for the person's own eyes — every person page with its verdict, what each lookup would change and the
    "why it matters to you" lines for a sample — plus counts."""
    from api.services import org_sites

    memory_path = Path(memory_path)
    today = today or date.today()
    memo = load_memo(memory_path)
    facts = web_settle.bank_facts(memory_path)
    counted = [0]

    async def _get(params: dict) -> dict | None:
        counted[0] += 1
        return await (get or org_sites.wikidata_get)(params)

    out: dict[str, Any] = {"people": [], "verdicts": {}, "lookups": [], "relevance": [], "counts": {}}
    budget = [wikidata_budget]
    persons = [f.stem for f in bank_index.files(memory_path, "entities")
               if str((f.frontmatter or {}).get("type") or "").lower() == "person"]
    for eid in sorted(persons):
        page = load_page(memory_path, eid, today=today)
        if page is None:
            continue
        v = await verdict(memory_path, page, facts, memo, get=_get, today=today, budget=budget)
        out["people"].append({"id": eid, "name": page.name, "public": bool(v.public), "reason": v.reason,
                              "status": str(page.fm.get("status") or "")})
    pages = candidates(memory_path, today=today)
    for page in pages:
        v = await verdict(memory_path, page, facts, memo, get=_get, today=today, budget=budget)
        key = f"{page.type}:{'public' if v.public else 'private'}:{v.reason}"
        out["verdicts"][key] = out["verdicts"].get(key, 0) + 1
    todo = await plan(memory_path, cap=limit, today=today, memo=memo, get=_get, facts=facts, pages=pages,
                      wikidata_budget=budget[0])
    out["counts"]["wikidata_requests"] = counted[0]
    out["counts"]["candidates"] = len(pages)
    out["counts"]["due"] = sum(1 for p in pages if due(p, memo, today)[0])
    out["counts"]["depth"] = {d: sum(1 for t in todo if t.page.depth == d) for d in DEPTHS}
    resolved, label, why = engine if engine is not None else await engine_for(settings, user_triggered=True)
    out["engine"] = label
    if resolved is None:
        out["reason"] = why
    else:
        fn = llm_fn or _llm_fn(resolved, sink=lambda _e: None)
        for item in todo:
            looked = await look_up(fn, item.page, item.page.depth, facts)
            changes = diff(item.page, looked.facts, set(memo["undone"].get(item.page.entity_id) or []))
            out["lookups"].append({
                "id": item.page.entity_id, "name": item.page.name, "type": item.page.type, "why": item.why,
                "depth": item.page.depth, "use": item.page.use, "verdict": item.verdict.reason,
                "queries": queries_for(item.page, item.page.depth), "reason": looked.reason, "model": looked.model,
                "changes": [{"predicate": c.predicate, "value": c.value, "action": c.action, "old": c.old,
                             "url": c.url} for c in changes]})
            if looked.reason == "plan_limit":
                break
    out["counts"]["looked_up"] = len(out["lookups"])
    # "Why it matters to you": before (what the page's own prose says about the person) and after, for a sample.
    import random

    rng = random.Random(44)
    pool = [p for p in pages]
    for page in rng.sample(pool, min(sample, len(pool))):
        out["relevance"].append({"id": page.entity_id, "name": page.name, "type": page.type,
                                 "before": _before_line(page, facts), "after": page.relevance.line})
    return out


def _before_line(page: Page, facts: web_settle.BankFacts) -> str:
    """The first sentence of the page's prose that speaks of the person — what it said about relevance before."""
    for sentence in _owner_mentions(_prose(page.body), facts.owner_names, page.name):
        s = " ".join(sentence.split()).lstrip("#- ").strip()
        if s:
            return s[:220]
    return ""
