"""An organisation's own website, found during consolidation (G61, G146; ruling 40, owner 2026-10-26).

The owner, 2026-10-26: "A lot of entity pages, like universities and stuff, don't have a picture … a university has a
website. Why wasn't this detected? When consolidated it should be part of a source that's used to update and from it
we also infer the picture if we are 100% sure."

Before this, a site reached a page only from Stage 1's optional ``website`` field when a page was CREATED (and only for
``company``/``tool``/``project``), or from the backfill's ``website`` claim / own-name ``## Links`` host
(``site_sources.candidates``). A page made before G61 S3-b, or one whose model left the field out, never got one; a
``location`` never could; and a domain the record plainly carries (an alias ``<org>.edu``, a bookmark on a subdomain)
was missed because the backfill matched only a host label of three letters or more equal to the page's name.

What this module adds, for organisations and public things only (:data:`SCOPE_TYPES` — never a person, never the
person's own project, never a name only the person uses, :func:`skip_reason`):

- **The record** (:func:`record_candidates`, no network): an origin whose site label is the page's name, an alias or
  its acronym, from the person's own line in a conversation the page rests on (that also names the page), or from the
  page's own text (an alias that is a domain, a ``## Links`` entry, a key fact, its ``website`` claim).
- **A structured public lookup** (:func:`lookup`): Wikidata's official website (P856) for exactly ONE item whose label
  or alias IS the page's name or alias, whose class (P31, up its P279 chain) agrees with the page's type, that is not a
  human, and whose country (P17) does not conflict with the countries the page names. A search engine's hit is never
  used. Only the page's name (and at most two proper-looking aliases) is sent.

A site is **trusted** (``verified`` with ``how`` and the sentence ``why``, :func:`trusted_entry`) only when, on top of
one of those, the site's own homepage names the entity in its title or site name (``link_enrichment.fetch_identity`` —
4 s, ≤ 512 KB, no cookies, ``net_guard``, a block never retried) — or, for the person's own located line whose link is
the page's own name, on their words alone (the D5 settle rule's shape). Anything short of that is a **proposal**
(``proposed: true``) that joins the one grouped "Confirm N links" review (``source_proposals``). A removal is
remembered (``sources_removed``) and never re-added; a page that already holds a trusted site is never looked up.

Once trusted, the existing pipeline takes it from there: ``logo_service`` draws the page's mark from it and
``source_refresh`` re-checks it (ruling 26). Behind ``CICADA_ALLOW_CONNECTOR_FETCH`` on the Sleep tail; bounded per
run; never raises into Sleep. The per-page "looked up on" cache lives outside every bank
(``$CICADA_HOME/site_lookup/<bank>.json``: page ids, days and outcomes only).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger

from api.services import authorship, entity_body, fact_sources, markdown_parser, page_lock, reading_hosts, site_sources, text_fold

SCOPE_TYPES = frozenset({"company", "tool", "location"})
AUTHOR = fact_sources.CICADA
#: Pages fully examined per run, and Wikidata lookups (each a handful of small requests) per run.
PAGE_BUDGET = 40
LOOKUP_BUDGET = 20
ROUTE_LOOKUP_BUDGET = 60
#: A page looked up and left without a site is looked at again after this long, or sooner when it gained conversations.
RETRY_DAYS = 30
MAX_EPISODES = 40
MAX_LINE_CHARS = 400
MAX_ALIAS_QUERIES = 2
MAX_PROPOSALS = 2
SEARCH_LIMIT = 7
MIN_CONTENT_HITS = 2
CLASS_DEPTH = 5
MAX_JSON_BYTES = 512 * 1024
TIMEOUT_SECONDS = 4.0
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
#: Wikimedia's User-Agent policy asks for a contact; the project's own page is it. No person's identifier, ever.
USER_AGENT = "Cicada/1 (https://github.com/rorosaga/cicada) httpx"
CACHE_DIR = "site_lookup"

BASIS_RECORD = "record"
BASIS_LOOKUP = "lookup"

# The class roots a page type agrees with (Wikidata ids, checked live 2026-10-26).
ORG_ROOTS = frozenset({"Q43229", "Q4830453", "Q783794", "Q2385804", "Q38723", "Q3918", "Q163740", "Q327333",
                       "Q31855", "Q16917", "Q484652", "Q6881511"})
TOOL_ROOTS = frozenset({"Q7397", "Q166142", "Q35127", "Q1668024", "Q2424752", "Q9143", "Q1172284", "Q115305900",
                        "Q4182287", "Q3220391"})
PLACE_ROOTS = frozenset({"Q2221906", "Q17334923", "Q486972", "Q41176", "Q515", "Q6256", "Q82794", "Q33506",
                         "Q22698", "Q1248784"})
HUMAN = "Q5"
#: A country's (or sovereign state's) "official website" is its government's portal, not the place's own mark.
NOT_A_SITE = frozenset({"Q6256", "Q3624078"})
_AGREES = {"company": ("org",), "tool": ("tool",), "location": ("place",)}

#: A name only the person uses, or a thing that is theirs: never sent, never looked up.
_PRIVATE_NAME = re.compile(r"[/\\~@]|://|['’]s\b|^\s*(?:the|my|our|a|an|el|la|mi|nuestro|nuestra)\s", re.IGNORECASE)
_OWN_THING = re.compile(
    r"\b(?:built|created|made|designed|developed|founded|started|owned|run|coined|named) by (?:the )?(?:person|user|"
    r"speaker|owner)\b|\bthe (?:person|user|speaker|owner)['’]s (?:own|project|startup|side project|app|team|"
    r"home|house|flat|apartment|room|desk|office)\b|\b(?:their|his|her) own\b",
    re.IGNORECASE)
#: Words a public proper name may carry in lower case. The name particles (da, do, das, dos, di, du, van, von, der,
#: le; owner via the coordinator, 2026-10-29) let "Jardim da Estrela" read as a name. They never make a PERSON public:
#: a person needs ruling 44's whole local test and then exactly one encyclopedia match (`web_context.local_verdict`
#: never answers True for a person).
_NAME_STOP = frozenset("of the and for de del la le el y at in on & a an da do das dos di du van von der".split())
_FACT_LINE = re.compile(r"\b(?:website|web site|homepage|home page|domain|official site|url|site)\b", re.IGNORECASE)
_BARE_DOMAIN = re.compile(r"(?<![\w@.-])((?:[a-z0-9-]+\.)+[a-z]{2,})(?![\w-])", re.IGNORECASE)


# ---- who may be looked at ------------------------------------------------------------------------------------------


def _names(fm: dict) -> list[str]:
    raw = [fm.get("name")] + [a for a in (fm.get("aliases") or []) if isinstance(a, str)]
    out: list[str] = []
    for value in raw:
        text = " ".join(str(value or "").split())
        if text and text not in out:
            out.append(text)
    return out


def proper_name(name: str) -> bool:
    """A name that reads as a public proper name: no path, handle, possessive or leading article; at most six words;
    one word, or every significant word capitalised ("Northwind University", "Acme Cloud" — not "the lab at my school")."""
    text = " ".join(str(name or "").split())
    if len(text) < 2 or len(text) > 80 or _PRIVATE_NAME.search(text) or _BARE_DOMAIN.fullmatch(text):
        return False
    words = text.split(" ")
    if len(words) > 6:
        return False
    if len(words) == 1:
        return any(ch.isalpha() for ch in text)
    significant = [w for w in words if w.lower() not in _NAME_STOP]
    return bool(significant) and all(w[:1].isupper() or w[:1].isdigit() for w in significant)


@dataclass
class Bank:
    """What the bank says about people and projects — the names never sent anywhere."""
    person_names: frozenset[str] = frozenset()
    project_names: frozenset[str] = frozenset()
    #: Every word of those people's names (3+ letters): never a "distinctive" word of a page's summary.
    person_words: frozenset[str] = frozenset()


def bank_names(memory_path: Path) -> Bank:
    from api.services import web_settle

    facts = web_settle.bank_facts(Path(memory_path))
    persons = set(facts.person_names) | set(facts.owner_names) | set(facts.pending_person_names)
    folded = frozenset(text_fold.fold(n) for n in persons if n)
    return Bank(person_names=folded, project_names=frozenset(facts.project_names),
                person_words=frozenset(w for n in folded for w in text_fold.words(n) if len(w) >= 3))


def _names_a_person(text: str, persons: frozenset[str]) -> bool:
    hay = f" {' '.join(text_fold.words(text))} "
    return any(len(n) >= 3 and f" {' '.join(text_fold.words(n))} " in hay for n in persons)


def has_trusted_site(fm: dict) -> bool:
    return any(fact_sources.same_predicate(s.get("predicate"), fact_sources.WEBSITE) and fact_sources.trusted(s)
               for s in fact_sources.as_sources(fm.get("sources")))


def skip_reason(fm: dict, bank: Bank) -> str | None:
    """Why this page is not looked at — None when it is in scope. Never a person, the owner, a project, a page that
    already has a trusted site, a name that is not a public proper name, a name that carries a person's or a project's
    name, or a thing the page says is the person's own."""
    kind = str(fm.get("type") or "").strip().lower()
    if kind not in SCOPE_TYPES:
        return "type"
    if fm.get("owner") is True:
        return "owner"
    if str(fm.get("status") or "") in ("archived", "dropped"):
        return "archived"
    if has_trusted_site(fm):
        return "has_site"
    name = " ".join(str(fm.get("name") or "").split())
    if not proper_name(name):
        return "private_name"
    folded = text_fold.fold(name)
    if _names_a_person(name, bank.person_names):
        return "person_name"
    if folded in bank.project_names:
        return "project"
    if _OWN_THING.search(" ".join([str(fm.get("description") or ""), str(fm.get("summary") or "")])):
        return "own_thing"
    return None


# ---- the record ----------------------------------------------------------------------------------------------------


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text_fold.fold(text))


def name_keys(fm: dict) -> set[str]:
    """The page's names squashed ("northwinduniversity", "nw") and the acronyms of its multi-word names ("nwu" for
    "Northwind West University")."""
    keys: set[str] = set()
    for name in _names(fm):
        if not proper_name(name):
            continue
        squashed = _squash(name)
        if len(squashed) >= 2:
            keys.add(squashed)
        words = [w for w in text_fold.words(name) if w not in _NAME_STOP]
        if len(words) >= 3:
            keys.add("".join(w[0] for w in words))
    return keys


def site_origin(value: str) -> str | None:
    """``https://<registrable site>`` for a URL or bare domain on a public, non-platform host — the site, not the page
    (a bookmark on ``careers.<org>.edu`` gives ``https://<org>.edu``)."""
    origin = site_sources.origin_of(value)
    if not origin:
        return None
    site = reading_hosts.site_of(origin)
    if not site or "." not in site:
        return None
    return site_sources.origin_of(site)


def label_matches(origin: str, keys: set[str]) -> bool:
    """The site's own label ("<org>" of ``<org>.edu``, ``<org>.co.uk``) IS one of the page's name keys."""
    site = reading_hosts.site_of(origin)
    label = _squash(site.split(".")[0]) if site else ""
    return bool(label) and label in keys


@dataclass(frozen=True)
class Candidate:
    origin: str
    #: ``{"episode", "start", "end", "kind": "user"}`` (the person's own line) or ``{"page": true}``.
    evidence: dict

    @property
    def own_words(self) -> bool:
        return bool(self.evidence.get("episode"))


#: A bare word with a dot is a domain only under a real-looking TLD: any two-letter country code that is not also a
#: common file extension, or one of these. "cv2.namedWindow" or "main.py" is code, never a site.
_GTLDS = frozenset("""com org net edu gov int mil io ai app dev info biz tech xyz cloud site online store page blog news
global group academy institute university school health lab network systems software solutions studio design agency
company foundation science museum art media digital world""".split())
#: Two-letter endings that are far more often code ("user.id", "file.py", "x.is") than a country's domain.
_FILE_EXTS = frozenset("py js ts md rs go rb sh cs kt pl ps db ml rm id in is if do as by on or of up".split())


def _real_tld(domain: str) -> bool:
    """A bare ``word.word`` reads as a domain: a real-looking TLD and no camelCase (``postgreSQLServer.id`` is code)."""
    if re.search(r"[a-z][A-Z]", domain):
        return False
    tld = domain.rsplit(".", 1)[-1].lower()
    return tld in _GTLDS or (len(tld) == 2 and tld.isalpha() and tld not in _FILE_EXTS)


def _urls_and_domains(text: str) -> list[str]:
    found = list(fact_sources.urls_in(text))
    # A wikilink names another page ("[[<tool>.ai]]"), never this one's site.
    stripped = re.sub(r"\[\[[^\]]*\]\]", " ", re.sub(r"https?://\S+", " ", text))
    found += [m.group(1) for m in _BARE_DOMAIN.finditer(stripped)
              if "@" not in stripped[max(0, m.start() - 1):m.start()] and _real_tld(m.group(1))]
    return found


def _own_line_hits(memory_path: Path, fm: dict, keys: set[str]) -> list[Candidate]:
    """Origins in a line of the person's own turn that names the page, whose label is the page's name."""
    from api.services import evidence, inbox_tend, source_proposals

    out: list[Candidate] = []
    episodes = sorted({str(e) for e in fm.get("source_episodes") or [] if str(e).startswith("ep_")})[-MAX_EPISODES:]
    for ep in episodes:
        doc = evidence.source_document(memory_path, ep)
        if doc is None:
            continue
        ep_fm, text = doc
        for turn in evidence.turns(text, override=authorship.of(ep_fm), gaps=evidence.gap_ranges(ep_fm, text)):
            if turn.role != "user":   # an agent's saved note is `assistant` (ruling 50, `authorship.of`)
                continue
            pos = turn.content_start
            for line in text[turn.content_start:turn.end].split("\n"):
                start = pos
                pos += len(line) + 1
                if "." not in line or len(line.strip()) > MAX_LINE_CHARS or not source_proposals.names_page(line, fm):
                    continue
                for raw in _urls_and_domains(line):
                    origin = site_origin(raw)
                    if origin and label_matches(origin, keys):
                        lead = len(line) - len(line.lstrip())
                        out.append(Candidate(origin, {"episode": ep, "start": start + lead,
                                                      "end": start + len(line.rstrip()), "kind": "user"}))
    return out


def _page_text_hits(fm: dict, body: str, keys: set[str]) -> list[Candidate]:
    """Origins the page itself carries — an alias that is a domain, a ``## Links`` entry, a key-fact line about its
    site or domain, its current ``website`` claim, a ``website`` source Sleep itself first proposed that no read has
    confirmed yet (:func:`sleeps_own_site`), a link or domain anywhere in its prose — whose label is the page's name
    (vision item 2, 2026-10-28: both are "on the page itself", ruling 40's own words)."""
    found: list[str] = [a for a in fm.get("aliases") or [] if isinstance(a, str) and _BARE_DOMAIN.fullmatch(a.strip())
                        and _real_tld(a.strip())]
    claim_site = site_sources._website_claim_origin(body)
    if claim_site:
        found.append(claim_site)
    found += [str(s.get("ref") or "") for s in fact_sources.as_sources(fm.get("sources")) if sleeps_own_site(s)]
    sections = entity_body.parse_sections(body or "")
    found += _urls_and_domains(sections.get("Links", ""))
    for line in str(sections.get("Key Facts", "")).splitlines():
        if _FACT_LINE.search(line):
            found += _urls_and_domains(line)
    found += _urls_and_domains(site_sources._strip_claims(body or ""))
    out: list[Candidate] = []
    for raw in found:
        origin = site_origin(raw)
        if origin and label_matches(origin, keys):
            out.append(Candidate(origin, {"page": True}))
    return out


#: The doubts about a proposal of Sleep's own that the homepage naming the page settles: it had not answered, or had
#: not named it. A proposal held for any other doubt (found only through an alias, the record naming another site, a
#: country conflict, a namesake, content that did not agree) still waits for the person.
HOMEPAGE_DOUBTS = frozenset({"homepage_unconfirmed", "not_fetched"})
#: Stage 1's official site (`fact_sources.propose_site(added_by="agent")`, the shape `coverage_report.writer_of`
#: reads as Stage 1's): these fields only (plus the nightly check's own), no proposal flag, no confirmation, no origin.
_STAGE1_FIELDS = frozenset({"ref", "kind", "predicate", "added_by", "added_at", "checked", "tries"})


def sleeps_own_site(source: dict) -> bool:
    """A ``website`` entry Sleep itself first proposed that nothing has confirmed yet — the kinds :func:`apply` may
    confirm in place once the homepage names the page (owner 2026-10-28, D; amends rulings 36 D5 and 40):

    - the engine-free backfill's entry (``site_sources``, ``added_by: cicada``, no proposal flag);
    - Stage 1's official site at page creation (``added_by: agent`` in :data:`_STAGE1_FIELDS`' shape);
    - Sleep's own proposal in "Confirm N links" (``added_by: cicada``, ``proposed``) held only because the homepage
      had not answered or not named it (:data:`HOMEPAGE_DOUBTS`; a proposal with no recorded doubt is the record's).

    Never the person's entry, one they took or removed, an identified agent's or a remote app's, nor a proposal held
    for any other doubt."""
    if not fact_sources.same_predicate(source.get("predicate"), fact_sources.WEBSITE) or source.get("origin") \
            or fact_sources.trusted(source):
        return False
    who = str(source.get("added_by") or "")
    if who == AUTHOR:
        if not fact_sources.is_proposed(source):
            return True
        evidence = source.get("evidence") if isinstance(source.get("evidence"), dict) else {}
        return evidence.get("reason") in HOMEPAGE_DOUBTS or not evidence.get("reason")
    return who == "agent" and not source.get(fact_sources.PROPOSED) and set(source) <= _STAGE1_FIELDS


def record_candidates(memory_path: Path | None, fm: dict, body: str) -> list[Candidate]:
    """What the record ties to this page, own words first, one per site."""
    keys = name_keys(fm)
    if not keys:
        return []
    found = (_own_line_hits(Path(memory_path), fm, keys) if memory_path is not None else []) + \
        _page_text_hits(fm, body, keys)
    out: list[Candidate] = []
    for cand in found:
        if all(c.origin != cand.origin for c in out):
            out.append(cand)
    return out


# ---- the lookup ----------------------------------------------------------------------------------------------------

JsonGet = Callable[[dict], Awaitable[dict | None]]


#: Wikimedia's API etiquette: one request at a time, spaced; a 429 is honoured (its Retry-After, capped) once.
MIN_INTERVAL = 0.2
MAX_RETRY_AFTER = 20.0
_throttle: dict = {"lock": None, "last": 0.0}


async def _spaced() -> None:
    import time

    if _throttle["lock"] is None:
        _throttle["lock"] = asyncio.Lock()
    async with _throttle["lock"]:
        wait = _throttle["last"] + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        _throttle["last"] = time.monotonic()


async def wikidata_get(params: dict) -> dict | None:
    """One Wikidata API call on Cicada's own rail: 4 s, ≤ 512 KB, no cookies, no proxy env, every hop through
    ``net_guard``, spaced :data:`MIN_INTERVAL` apart. A 429 waits its ``Retry-After`` (≤ :data:`MAX_RETRY_AFTER`) and
    asks once more with the same request; any other failure — a block included, never retried — is None."""
    from api.services import net_guard

    for attempt in (0, 1):
        await _spaced()
        try:
            import httpx

            async with httpx.AsyncClient(
                timeout=TIMEOUT_SECONDS, follow_redirects=False, headers={"User-Agent": USER_AGENT}, trust_env=False,
                event_hooks={"request": [net_guard.httpx_request_guard]},
            ) as client:
                async with client.stream("GET", WIKIDATA_API, params={**params, "format": "json"}) as resp:
                    if resp.status_code == 429 and attempt == 0:
                        try:
                            delay = float(resp.headers.get("retry-after") or 5)
                        except ValueError:
                            delay = 5.0
                        await asyncio.sleep(min(max(delay, 1.0), MAX_RETRY_AFTER))
                        continue
                    if resp.status_code != 200:
                        logger.debug(f"wikidata lookup answered {resp.status_code}")
                        return None
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in resp.aiter_bytes():
                        chunks.append(chunk)
                        size += len(chunk)
                        if size > MAX_JSON_BYTES:
                            return None
            data = json.loads(b"".join(chunks))
            return data if isinstance(data, dict) else None
        except Exception as exc:  # noqa: BLE001 — a failed lookup is no answer, never an error
            logger.debug(f"wikidata lookup failed: {type(exc).__name__}")
            return None
    return None


def _claim_values(data: dict | None, prop: str) -> list:
    """The non-deprecated values of one property, preferred first."""
    rows = ((data or {}).get("claims") or {}).get(prop) or []
    ranked = sorted((r for r in rows if isinstance(r, dict) and r.get("rank") != "deprecated"),
                    key=lambda r: 0 if r.get("rank") == "preferred" else 1)
    out = []
    for r in ranked:
        value = ((r.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(value, dict) and value.get("id"):
            out.append(value["id"])
        elif isinstance(value, str):
            out.append(value)
    return out


@dataclass
class Lookup:
    outcome: str                      # trusted-candidate | proposal | none
    sites: list[str] = field(default_factory=list)
    item: str | None = None
    label: str = ""
    labels: list[str] = field(default_factory=list)
    reason: str = ""
    description: str = ""
    via_alias: bool = False


class Classes:
    """P279 ancestry, cached for a run (and by the caller across runs): class id -> parent ids."""

    def __init__(self, get: JsonGet, cache: dict | None = None):
        self.get = get
        self.parents: dict[str, list[str]] = dict(cache or {})

    async def _parents(self, qid: str) -> list[str]:
        if qid not in self.parents:
            data = await self.get({"action": "wbgetclaims", "entity": qid, "property": "P279"})
            if data is None:
                return []
            self.parents[qid] = _claim_values(data, "P279")[:12]
        return self.parents[qid]

    async def kinds(self, classes: list[str]) -> set[str]:
        """Which of org / tool / place the classes reach within :data:`CLASS_DEPTH` steps up P279."""
        roots = {"org": ORG_ROOTS, "tool": TOOL_ROOTS, "place": PLACE_ROOTS}
        found: set[str] = set()
        seen: set[str] = set()
        level = [c for c in classes if isinstance(c, str)]
        for _ in range(CLASS_DEPTH + 1):
            nxt: list[str] = []
            for qid in level:
                if qid in seen:
                    continue
                seen.add(qid)
                found |= {k for k, ids in roots.items() if qid in ids}
                if len(seen) > 120:
                    return found
                nxt += await self._parents(qid)
            if not nxt:
                break
            level = nxt
        return found


def _country_words(text: str) -> set[str]:
    from api.services.countries import canonical_countries

    return canonical_countries(text)


def page_context(fm: dict, body: str) -> str:
    """What the page itself says about where the thing is: tags, description, summary and key facts."""
    sections = entity_body.parse_sections(site_sources._strip_claims(body or ""))
    parts = [" ".join(str(t) for t in fm.get("tags") or []), str(fm.get("description") or ""),
             str(sections.get("Summary") or ""), str(sections.get("Key Facts") or "")]
    return " ".join(parts)[:6000]


def queries(fm: dict, bank: Bank) -> list[str]:
    """The page's name, then at most two aliases that read as public proper names — nothing that names a person."""
    out: list[str] = []
    for i, name in enumerate(_names(fm)):
        if not proper_name(name) or _names_a_person(name, bank.person_names) or len(name) < (2 if i == 0 else 3):
            continue
        if name.lower() not in (q.lower() for q in out):
            out.append(name)
        if len(out) > MAX_ALIAS_QUERIES:
            break
    return out


async def lookup(fm: dict, body: str, bank: Bank, get: JsonGet, classes: Classes) -> Lookup:
    """Wikidata's official website for the page — see the module docstring. ``trusted-candidate`` still needs the
    homepage's corroboration; ``proposal`` carries up to :data:`MAX_PROPOSALS` sites; ``none`` carries a reason."""
    kind = str(fm.get("type") or "").strip().lower()
    wanted = _AGREES.get(kind, ())
    folded_names = {text_fold.fold(n) for n in _names(fm)}
    for query in queries(fm, bank):
        data = await get({"action": "wbsearchentities", "search": query, "language": "en", "uselang": "en",
                          "type": "item", "limit": SEARCH_LIMIT})
        if data is None:
            return Lookup("none", reason="lookup_failed")
        hits = [h for h in data.get("search") or [] if isinstance(h, dict) and h.get("id")]
        exact = [h for h in hits if text_fold.fold(str((h.get("match") or {}).get("text") or "")) in folded_names
                 or text_fold.fold(str(h.get("label") or "")) in folded_names]
        if not exact:
            continue
        via_alias = text_fold.fold(query) != text_fold.fold(str(fm.get("name") or ""))
        agreeing: list[dict] = []
        for hit in exact:
            qid = hit["id"]
            p31 = await get({"action": "wbgetclaims", "entity": qid, "property": "P31"})
            classes_of = _claim_values(p31, "P31")
            if HUMAN in classes_of or NOT_A_SITE & set(classes_of):
                continue
            kinds = await classes.kinds(classes_of)
            agrees = any(k in kinds for k in wanted)
            if not agrees and kind == "location" and "org" in kinds:
                # A campus, a museum run as an institution: a sited organisation is a public place too.
                coords = await get({"action": "wbgetclaims", "entity": qid, "property": "P625"})
                agrees = bool(((coords or {}).get("claims") or {}).get("P625"))
            if not agrees:
                # Another kind of thing that shares the name: not this page's, not even worth asking about.
                continue
            p856 = await get({"action": "wbgetclaims", "entity": qid, "property": "P856"})
            raw = [u for u in _claim_values(p856, "P856") if isinstance(u, str)]
            sites: list[str] = []
            for url in raw:
                origin = site_origin(url)
                if origin and origin not in sites:
                    sites.append(origin)
            # An agreeing item whose only site is a platform's page still counts (its site is that platform): the
            # match must be ONE thing, not one thing with a usable site.
            agreeing.append({"id": qid, "label": str(hit.get("label") or ""), "sites": sites,
                             "raw_sites": {reading_hosts.site_of(u) for u in raw} - {""},
                             "description": str(hit.get("description") or "")})
        listed = [a for a in agreeing if a["raw_sites"]]
        if not agreeing:
            continue
        if not listed:
            return Lookup("none", item=agreeing[0]["id"], reason="no_official_site")
        if len(set().union(*(a["raw_sites"] for a in listed))) == 1:
            # One site, whichever of its items (a product and its maker, an item and its duplicate) lists it.
            best = listed[0]
            if not best["sites"]:
                return Lookup("none", item=best["id"], reason="no_official_site")
            found = Lookup("trusted-candidate", sites=best["sites"][:1], item=best["id"], label=best["label"],
                           labels=[best["label"]], description=best["description"], via_alias=via_alias)
            if await _country_conflict(best["id"], fm, body, get):
                found.outcome, found.reason = "proposal", "country_conflict"
            return found
        # Several things of the right kind share the name: ambiguous. Only a site whose own label is the page's name is
        # worth putting in front of the person; the rest are noise.
        keys = name_keys(fm)
        sites: list[str] = []
        for a in listed:
            if a["sites"] and label_matches(a["sites"][0], keys) and a["sites"][0] not in sites:
                sites.append(a["sites"][0])
        if sites:
            return Lookup("proposal", sites=sites[:MAX_PROPOSALS], item=listed[0]["id"], reason="ambiguous")
        return Lookup("none", item=listed[0]["id"], reason="ambiguous")
    return Lookup("none", reason="no_match")


async def _country_conflict(qid: str, fm: dict, body: str, get: JsonGet) -> bool:
    """The page names one or more countries and none of them is the item's (P17). No P17, or a page that names no
    country, is no conflict."""
    page = _country_words(page_context(fm, body))
    if not page:
        return False
    data = await get({"action": "wbgetclaims", "entity": qid, "property": "P17"})
    countries = _claim_values(data, "P17")[:4]
    if not countries:
        return False
    labels = await get({"action": "wbgetentities", "ids": "|".join(countries), "props": "labels|aliases",
                        "languages": "en|es"})
    words: list[str] = []
    for ent in ((labels or {}).get("entities") or {}).values():
        for lang in ("en", "es"):
            label = ((ent.get("labels") or {}).get(lang) or {}).get("value")
            if label:
                words.append(label)
            words += [a.get("value", "") for a in (ent.get("aliases") or {}).get(lang) or [] if isinstance(a, dict)]
    item = _country_words(" ; ".join(words))
    if not item:
        return False
    return not (page & item)


# ---- corroboration -------------------------------------------------------------------------------------------------

FetchIdentity = Callable[..., Awaitable]


def homepage_names(identity, names: list[str]) -> bool:
    """The site's own title or site name carries the entity's name (``site_sources._name_present``), on the site that
    was asked (a redirect to another site is no corroboration)."""
    if getattr(identity, "status", "") != "ok" or getattr(identity, "cross_site", False):
        return False
    heading = f"{identity.title} | {identity.site_name}"
    return site_sources._name_present(heading, [n for n in names if n.strip()])


#: Words a summary uses about anything — dates, sizes, the way Cicada writes — that say nothing about WHICH thing it is.
_GENERIC = frozenset("""january february march april may june july august september october november december enero
febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre monday tuesday wednesday thursday
friday saturday sunday million millions billion billions thousand hundred described reported mentioned considered
planned planning using users conversation conversations person people company companies something things around
later earlier which during another between possible little among options summary opened closed confirmed recorded
discussed introduced outcome position profile range scheduled successful assigned estimated""".split())


def content_agrees(fm: dict, body: str, description: str, identity, exclude: frozenset[str] = frozenset()) -> bool:
    """At least one distinctive word of the page's own summary or key facts (``site_sources._distinctive_tokens``,
    less dates, sizes and the people's names in ``exclude``) is in the item's Wikidata description or on the site's
    homepage — the namesake guard ("a browser company called <org-a>" is not a hotel chain of that name). A page
    that says nothing distinctive agrees with nothing."""
    tokens = [t for t in site_sources._distinctive_tokens(fm, body) if t not in _GENERIC and t not in exclude]
    if not tokens:
        return False
    # The curated words only: the item's description and what the site says about itself in its head. The body's
    # excerpt was measured too loose — on a real bank copy it matched "reports", "questions", "lists" on namesakes.
    parts = [description or ""]
    if identity is not None and getattr(identity, "status", "") == "ok":
        parts += [identity.title, identity.site_name, identity.meta_description]
    words = set(text_fold.words(" ".join(parts)))
    stems = {text_fold.stem(w) for w in words}
    # Two, as Cicada's own site check asks (``site_sources.judge``): one shared word ("search", "options") is chance.
    return sum(1 for t in tokens if t in words or text_fold.stem(t) in stems) >= MIN_CONTENT_HITS


# ---- the decision --------------------------------------------------------------------------------------------------


@dataclass
class Finding:
    entity_id: str
    name: str
    type: str
    site: str | None = None
    basis: str | None = None             # record | lookup
    trusted: bool = False
    proposals: list[str] = field(default_factory=list)
    why: str = ""
    item: str | None = None
    evidence: dict = field(default_factory=dict)
    reason: str = ""                     # why nothing (or why only a proposal)
    looked_up: bool = False

    @property
    def outcome(self) -> str:
        return "trusted" if self.trusted else "proposal" if self.proposals else "none"


def _why_record(cand: Candidate, name: str, corroborated: bool) -> str:
    where = "you gave it in your own words" if cand.own_words else "the page's own record carries it"
    tail = f", and its homepage names {name}" if corroborated else ""
    return f"Found by Cicada: {where}{tail}"


def _why_lookup(name: str, item: str) -> str:
    return f"Found by Cicada: official site listed on Wikidata ({item}), and its homepage names {name}"


async def decide(memory_path: Path | None, entity_id: str, fm: dict, body: str, bank: Bank, *,
                 get: JsonGet | None, classes: Classes | None, fetch_identity: FetchIdentity | None,
                 allow_lookup: bool = True) -> Finding:
    """The one decision for one page (read-only): the record first, then the lookup; trusted only on corroboration."""
    name = str(fm.get("name") or entity_id)
    finding = Finding(entity_id, name, str(fm.get("type") or ""))
    names = _names(fm)
    removed = lambda origin: fact_sources.is_tombstoned(fm, origin, fact_sources.WEBSITE)  # noqa: E731
    cands = [c for c in record_candidates(memory_path, fm, body) if not removed(c.origin)]
    for cand in cands:
        identity = await fetch_identity(cand.origin) if fetch_identity is not None else None
        named = identity is not None and homepage_names(identity, names)
        # The person's own located line whose link is the page's own name (the D5 settle rule's shape) stands on their
        # words when the site exists but will not show itself to a bot (a block, a consent wall) — or when nothing was
        # fetched at all (a read-only caller). A site that does not answer is no site.
        own = cand.own_words and (identity is None or getattr(identity, "status", "") in ("blocked", "interstitial"))
        if named or own:
            finding.site, finding.basis, finding.trusted = cand.origin, BASIS_RECORD, True
            finding.evidence = dict(cand.evidence)
            finding.why = _why_record(cand, name, named)
            return finding
    record_sites = [c.origin for c in cands]
    if allow_lookup and get is not None and classes is not None:
        finding.looked_up = True
        result = await lookup(fm, body, bank, get, classes)
        finding.item = result.item
        sites = [s for s in result.sites if not removed(s)]
        if result.outcome == "trusted-candidate" and sites:
            site = sites[0]
            if record_sites and reading_hosts.site_of(site) not in {reading_hosts.site_of(s) for s in record_sites}:
                finding.proposals = [site] + [s for s in record_sites if s != site][:MAX_PROPOSALS - 1]
                finding.basis, finding.reason = BASIS_LOOKUP, "record_names_another_site"
                finding.evidence = {"lookup": "wikidata", "item": result.item}
                return finding
            identity = await fetch_identity(site) if fetch_identity is not None else None
            named = identity is not None and homepage_names(identity, names + result.labels)
            same_thing = content_agrees(fm, body, result.description, identity, bank.person_words)
            finding.evidence = {"lookup": "wikidata", "item": result.item}
            if named and same_thing and not result.via_alias:
                finding.site, finding.basis, finding.trusted = site, BASIS_LOOKUP, True
                finding.why = _why_lookup(name, str(result.item))
                return finding
            if result.via_alias and not same_thing:
                # Found only through an alias, and nothing the page says is on the item or its site: a namesake.
                finding.reason = "namesake"
                return finding
            if result.via_alias:
                # An alias can be another thing the page conflates with its subject: the person decides.
                finding.proposals, finding.basis, finding.reason = [site], BASIS_LOOKUP, "matched_by_alias"
                return finding
            finding.proposals, finding.basis = [site], BASIS_LOOKUP
            finding.reason = ("not_fetched" if identity is None else "homepage_unconfirmed" if not named
                              else "content_unconfirmed")
            return finding
        if result.outcome == "proposal" and sites:
            finding.proposals, finding.basis, finding.reason = sites[:MAX_PROPOSALS], BASIS_LOOKUP, result.reason
            finding.evidence = {"lookup": "wikidata", "item": result.item}
            return finding
        finding.reason = result.reason
    if record_sites:
        finding.proposals, finding.basis = record_sites[:MAX_PROPOSALS], BASIS_RECORD
        finding.evidence = dict(cands[0].evidence)
        finding.reason = finding.reason or "homepage_unconfirmed"
    return finding


# ---- writing -------------------------------------------------------------------------------------------------------


def trusted_entry(finding: Finding, today: str) -> dict:
    """A trusted ``website`` source by Cicada: ``verified`` says how and, in words, why — the card's "Found by Cicada"
    line. The person undoes it by removing the source (remembered, never re-added)."""
    how = "wikidata+name" if finding.basis == BASIS_LOOKUP else "record+name" if "homepage" in finding.why \
        else "record"
    verified = {"at": today, "how": how, "why": finding.why}
    if finding.item and finding.basis == BASIS_LOOKUP:
        verified["item"] = finding.item
    entry = {"ref": finding.site, "kind": fact_sources.KIND_URL, "predicate": fact_sources.WEBSITE,
             "added_by": AUTHOR, "added_at": today, "access": fact_sources.ACCESS_PUBLIC, "verified": verified}
    if finding.evidence:
        entry["evidence"] = dict(finding.evidence)
    return entry


def apply(fm: dict, finding: Finding, today: str) -> int:
    """Put the finding on ``fm`` (pure over the dict; the caller writes). A trusted site upgrades an entry Sleep itself
    first proposed for the same site in place (:func:`sleeps_own_site` — owner 2026-10-28, D), else is added — never
    over the person's entry, an identified agent's, or a proposal held for a doubt the homepage does not settle;
    proposals are added as ``proposed`` entries the review lists, or mark Cicada's own unconfirmed entry for the same
    site as proposed. Never over a tombstone, a trusted site or a cap. Returns how many entries were added or
    changed."""
    existing = [s for s in (fm.get("sources") or []) if isinstance(s, dict)]
    if has_trusted_site(fm):
        return 0
    changed = 0
    if finding.trusted and finding.site:
        if fact_sources.is_tombstoned(fm, finding.site, fact_sources.WEBSITE):
            return 0
        new = trusted_entry(finding, today)
        for s in existing:
            if fact_sources.same_predicate(s.get("predicate"), fact_sources.WEBSITE) and \
                    reading_hosts.site_of(str(s.get("ref") or "")) == reading_hosts.site_of(finding.site):
                if not sleeps_own_site(s):
                    # The person's entry, an identified agent's, or a proposal held for a doubt the homepage does not
                    # settle: never upgraded behind them (ruling 36 D5). An unproposed one keeps the nightly check.
                    return 0
                s.pop("checked", None)
                s.pop("tries", None)
                s.pop(fact_sources.PROPOSED, None)
                s["verified"] = new["verified"]
                s["access"] = fact_sources.ACCESS_PUBLIC
                fm["sources"] = existing
                return 1
        if len(existing) >= fact_sources.MAX_SOURCES:
            return 0
        fm["sources"] = existing + [new]
        return 1
    for site in finding.proposals:
        if fact_sources.is_tombstoned(fm, site, fact_sources.WEBSITE):
            continue
        same = [s for s in existing if fact_sources.same_predicate(s.get("predicate"), fact_sources.WEBSITE)
                and reading_hosts.site_of(str(s.get("ref") or "")) == reading_hosts.site_of(site)]
        if same:
            entry = same[0]
            # Only Cicada's own unconfirmed entry joins the review; another writer's is left as that writer put it.
            if str(entry.get("added_by") or fact_sources.USER) == AUTHOR and not entry.get(fact_sources.PROPOSED):
                entry[fact_sources.PROPOSED] = True
                evidence = entry.get("evidence") if isinstance(entry.get("evidence"), dict) else None
                entry["evidence"] = evidence = dict(evidence or finding.evidence or {"page": True})
                if finding.reason:
                    # The doubt it is held for travels with it: `sleeps_own_site` may later confirm only a proposal
                    # held for the homepage, never one held for an alias, a namesake or content (review of #510).
                    evidence["reason"] = finding.reason
                changed += 1
            continue
        if len(existing) >= fact_sources.MAX_SOURCES or sum(
                1 for s in existing if fact_sources.same_predicate(s.get("predicate"), fact_sources.WEBSITE)) \
                >= fact_sources.MAX_PER_PREDICATE:
            break
        evidence = dict(finding.evidence) or {"page": True}
        if finding.reason:
            evidence["reason"] = finding.reason
        existing.append({"ref": site, "kind": fact_sources.KIND_URL, "predicate": fact_sources.WEBSITE,
                         "added_by": AUTHOR, "added_at": today, fact_sources.PROPOSED: True, "evidence": evidence})
        changed += 1
    if changed:
        fm["sources"] = existing
    return changed


# ---- the cache outside the bank ------------------------------------------------------------------------------------


def _cache_path(memory_path: Path) -> Path:
    from api.services.auth import cicada_home
    from api.services.logo_service import bank_name

    return cicada_home() / CACHE_DIR / f"{bank_name(Path(memory_path))}.json"


def _classes_path() -> Path:
    from api.services.auth import cicada_home

    return cicada_home() / CACHE_DIR / "classes.json"


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — a derived cache: missing or broken reads as empty
        return {}


def _write_json(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        logger.debug(f"site lookup cache not written: {type(exc).__name__}")


def _due(entry: dict | None, fm: dict, today: date) -> bool:
    if not isinstance(entry, dict):
        return True
    try:
        at = date.fromisoformat(str(entry.get("at"))[:10])
    except ValueError:
        return True
    grew = len(fm.get("source_episodes") or []) > int(entry.get("n") or 0)
    return grew or (today - at) >= timedelta(days=RETRY_DAYS)


# ---- the Sleep step ------------------------------------------------------------------------------------------------


def _queue(memory_path: Path, skip: frozenset[str], bank: Bank, cache: dict, today: date,
           force: bool = False) -> list[tuple[str, dict]]:
    """In-scope pages with no trusted site, due a look, busiest first (most conversations, then id)."""
    from api.services import bank_index

    rows: list[tuple[int, str, dict]] = []
    for f in bank_index.files(Path(memory_path), "entities"):
        fm = f.frontmatter or {}
        rel = f"entities/{f.stem}.md"
        if rel in skip or skip_reason(fm, bank) is not None:
            continue
        if not force and not _due(cache.get(f.stem), fm, today):
            continue
        rows.append((len(fm.get("source_episodes") or []), f.stem, fm))
    rows.sort(key=lambda r: (-r[0], r[1]))
    return [(stem, fm) for _, stem, fm in rows]


async def run(memory_path: Path, *, report: "site_sources.Report", skip: frozenset[str] = frozenset(),
              page_budget: int = PAGE_BUDGET, lookup_budget: int = LOOKUP_BUDGET, get: JsonGet | None = None,
              fetch_identity: FetchIdentity | None = None, today: date | None = None) -> "site_sources.Report":
    """Sleep's step (and the route's): examine up to ``page_budget`` due pages, look up at most ``lookup_budget`` on
    Wikidata, write each finding to its page's frontmatter (``report.touch`` before the write, so the caller can
    restore). The caller holds the network gate and commits ``report.paths``. A page that fails is logged by class and
    skipped; this never raises for one page."""
    from api.services import bank_index, link_enrichment

    memory_path = Path(memory_path)
    today = today or date.today()
    get = get or wikidata_get
    fetch_identity = fetch_identity or (lambda url: link_enrichment.fetch_identity(url, None))
    cache = await asyncio.to_thread(_read_json, _cache_path(memory_path))
    classes = Classes(get, await asyncio.to_thread(_read_json, _classes_path()))
    bank = await asyncio.to_thread(bank_names, memory_path)
    queue = await asyncio.to_thread(_queue, memory_path, skip, bank, cache, today)
    lookups = 0
    try:
        for entity_id, _fm in queue[:page_budget]:
            rel = f"entities/{entity_id}.md"
            path = memory_path / rel
            try:
                parsed = await asyncio.to_thread(markdown_parser.parse, path)
                fm, body = dict(parsed.frontmatter), parsed.body
                finding = await decide(memory_path, entity_id, fm, body, bank, get=get, classes=classes,
                                       fetch_identity=fetch_identity, allow_lookup=lookups < lookup_budget)
                lookups += 1 if finding.looked_up else 0
                if finding.outcome == "none" and not finding.looked_up and lookups >= lookup_budget:
                    report.bump("org_deferred")
                    continue
                report.bump(f"org_{finding.outcome}")
                if finding.outcome != "none":
                    wrote = await asyncio.to_thread(_write_finding, memory_path, rel, finding, today.isoformat(),
                                                    report)
                    report.bump("org_written", wrote)
                cache[entity_id] = {"at": today.isoformat(), "outcome": finding.outcome,
                                    "n": len(fm.get("source_episodes") or [])}
            except Exception as exc:  # noqa: BLE001 — one page never stops the step
                logger.warning(f"org site step: one page failed ({type(exc).__name__})")
                report.bump("org_failed")
    finally:
        await asyncio.to_thread(_write_json, _cache_path(memory_path), cache)
        await asyncio.to_thread(_write_json, _classes_path(), classes.parents)
        if report.paths:
            bank_index.invalidate(memory_path)
    return report


@page_lock.locked
def _write_page_locked(memory_path: Path, entity_id: str, finding: Finding, today: str, report) -> int:
    path = Path(memory_path) / "entities" / f"{entity_id}.md"
    parsed = markdown_parser.parse(path)
    fm = parsed.frontmatter
    changed = apply(fm, finding, today)
    if changed:
        report.touch(f"entities/{entity_id}.md")   # before the write: a failure after it can still restore the page
        markdown_parser.write(path, fm, parsed.body)
    return changed


def _write_finding(memory_path: Path, rel: str, finding: Finding, today: str, report) -> int:
    return _write_page_locked(memory_path, Path(rel).stem, finding, today, report)
