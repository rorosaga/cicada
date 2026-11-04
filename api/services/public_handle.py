"""Is a public handle a named person? (Ruling 54 and 54a, owner 2026-11-04; amends ruling 44's public test for this one
question.)

The owner, on "is <handle> the same as <full name>?": "could've been resolved from a search, like how claude code would
solve it if i ask it rn." Sleep's own lookup is ON on plan runs (``CICADA_PUBLIC_HANDLE_LOOKUP=off`` turns it off); the
step that works it is ``settling_agent``, its limit on what leaves is ``name_guard``. This module is the question.

**Which questions** (:func:`test`, engine-free): an open "Is A the same as B?" between two person PAGES (never a held
mention), exactly one side a handle (``person_leads.is_handle``) and the other a full name (not relation-shaped, not the
owner, not a role-only page). Then, by what can answer it:

* a tracked source on either page (ruling 26's ``tracked``: the person's own, one they took, one Cicada's read confirmed)
  — the page's Where to check is opened first, whoever the person is (54a); opening a link already on the page is not a
  search;
* a web search only when neither page is known personally, the named side carries ruling 44's public cue, and both
  names clear ``name_guard`` (:attr:`Pair.searchable`). A private person's name never goes in a search.

Otherwise it stays for the person, with the reason (``guarded_tie``, ``guarded_not_public``, ``walled_source``,
``proposed_source``, ``no_public_cue`` …).

**What settles** (:func:`weigh`, checked here on the bytes opened, never on the model's word). Each source must be a page
Cicada opened whose text names the person and the handle (in words, or by a link to the account's profile), with a quote
that is really on it. Then ONE is enough only when it is: a tracked source of either page; an encyclopedia article; the
person's own domain (their name is the domain). Otherwise TWO independent voices: different sites, not the same words,
with an account's own pages (its profile, ``<handle>.github.io``) counting as one voice. A walled profile is never
opened: its search result counts as that one voice only when the result is the account's own link and its title names
the person. **A single profile never settles** (anyone can type a name into one); there is no reading of a "verified"
mark, since the walled sites that have one are never opened. **Parody, stale, namesake:** a source whose surroundings say
parody, fan account, unofficial, formerly, no longer (X's own "formerly Twitter" aside) leaves it open, and the model is
told to answer not sure for a namesake (what memory says about them does not fit). Anything else leaves it open.

**What it writes** (:func:`settle`): one cited claim on the named person's page — "<Name> goes by “<handle>” online",
predicate ``goes-by``, its object the handle's page (observer ``agent``, ``source_trust: external``, origin
``web-check``) — its citations in one ``web-check`` episode, and moves the question to "Settled by a check"
(``web_settle.undo`` takes it all back and the question returns, never checked again). Never a merge: the two pages
stay, and the person merges them with one tap. Never the owner's page. While the claim stands, the pair is not asked
again (``pair_evidence.answered_by_check``).

**The person's own local agent**, on their ask (``cicada_record_check``), keeps the stricter test below (:func:`_agent_test`)
and its two pinned searches (:func:`queries`): Cicada cannot observe that agent's searches, so the limit there can only
be who is offered at all.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from api.services import name_guard, pair_evidence, person_leads

#: Conversations that ARE public content the person read or saved (an episode's ``source``).
PUBLIC_CONTENT_SOURCES = name_guard.PUBLIC_SOURCES
#: Chats and the person's address book: a name said here (outside a link) is someone from their life.
CHAT_SOURCES = frozenset({
    "imessage", "messages", "whatsapp", "telegram-chats", "email", "gmail", "contacts", "linkedin",
    "linkedin-connections", "profile-read",
})
#: The one platform word a handle's query may carry: the site the record links its account on.
SITE_WORDS = {"x": "twitter", "github": "github", "instagram": "instagram", "linkedin": "linkedin"}
SEARCH_PER_NAME = 40
#: A side with more spellings than this cannot be read for every chat: it stays private (``unbounded``).
MAX_SPELLINGS = 8
REASON = "public_handle"
_URL = re.compile(r"https?://[^\s)>\]\"']+")
_CHAT_FIELDS = ("title", "correspondent", "participants", "chat", "chat_name", "sender", "from", "to")


@dataclass(frozen=True)
class Pair:
    """One handle question: which side is the handle, which the named person, and why it passed or not."""
    reason: str
    handle_id: str = ""
    handle: str = ""
    named_id: str = ""
    name: str = ""
    site: str = ""
    #: May a web search be tried (both names clear ``name_guard``)? False: only the pages' tracked sources.
    searchable: bool = False

    @property
    def public(self) -> bool:
        return self.reason == REASON


def _full_name(name: str) -> bool:
    from api.services import web_settle

    words = [w for w in str(name or "").split() if w[:1].isalpha()]
    return len(words) >= 2 and not person_leads.is_handle(name) and not web_settle.relation_shaped(name)


def _in_contacts(fm: dict) -> bool:
    from api.services import contacts_local, linkedin_people

    if fm.get(contacts_local.FRONTMATTER_KEY):
        return True
    for source in fm.get("sources") or []:
        if not isinstance(source, dict):
            continue
        ref = str(source.get("ref") or "")
        if ref.startswith(contacts_local.REF_SCHEME) or str(source.get("predicate") or "") == \
                linkedin_people.SOURCE_PREDICATE:
            return True
    return False


def _outside_links(text: str) -> str:
    return _URL.sub(" ", text or "")


def _conversations(memory_path: Path, page_fm: dict, names: list[str]) -> tuple[list[str], bool]:
    """``(conversation ids naming the side, bounded?)`` — the page's own and what the lexical index finds."""
    from api.services import search_service

    found = [str(e) for e in (page_fm.get("source_episodes") or []) if str(e).startswith("ep_")]
    bounded = True
    if pair_evidence.fresh_index(memory_path) != "ready":
        return found, False   # a chat the index has not read yet could name them: err private
    for name in names[:MAX_SPELLINGS]:
        try:
            hits = search_service.search(memory_path, name, kinds=("episode",), mode="prefix",
                                         per_kind=SEARCH_PER_NAME, vectors=False).results
        except Exception:  # noqa: BLE001 — an unreadable index cannot rule a chat out: err private
            return found, False
        if len(hits) >= SEARCH_PER_NAME:
            bounded = False
        found += [str(h.episode_id or h.id) for h in hits if str(h.episode_id or h.id or "").startswith("ep_")]
    return list(dict.fromkeys(found)), bounded


def _read_side(memory_path: Path, page_fm: dict, names: list[str], own: list[str], handle: str = "",
               ) -> tuple[str | None, bool, str]:
    """``(private reason or None, said in public content?, the site the record links the handle's account on)``.
    ``names``: every spelling of the side, read for a chat (err private); ``own``: the same less the other side's own
    name (an alias that IS the other side never credits this side with public content)."""
    from api.services import evidence

    if len(names) > MAX_SPELLINGS:
        return "unbounded", False, ""
    episodes, bounded = _conversations(memory_path, page_fm, names)
    if not bounded:
        return "unbounded", False, ""
    public, site = False, ""
    for eid in episodes:
        doc = evidence.source_document(memory_path, eid)
        if doc is None:
            continue
        ep_fm, text = doc
        source = str(ep_fm.get("source") or "").strip().lower()
        if source in CHAT_SOURCES:
            labels = " ".join(str(ep_fm.get(k) or "") for k in _CHAT_FIELDS)
            if pair_evidence.names_in(names, _outside_links(text)) or pair_evidence.names_in(names, labels):
                return "chat", False, ""
        if not pair_evidence.names_in(own, text) and not (handle and _links_handle(text, handle)):
            continue
        if source in PUBLIC_CONTENT_SOURCES:
            public = True
        if handle and not site:
            site = _site_in(text, handle)
    return None, public, site


def _links_handle(text: str, handle: str) -> bool:
    return bool(_site_in(text, handle))


def _site_in(text: str, handle: str) -> str:
    key = person_leads.handle_key(handle)
    for url in _URL.findall(text or ""):
        found = person_leads.profile_handle(url)
        if found is not None and found[1] == key and found[0] in SITE_WORDS:
            return found[0]
    return ""


def enabled() -> bool:
    """Sleep's own lookup: on (ruling 54, owner 2026-11-04); ``CICADA_PUBLIC_HANDLE_LOOKUP=off`` turns it off, as the
    variable always did. ``CICADA_ALLOW_CONNECTOR_FETCH``'s reading: opt out, anything else is on."""
    return os.environ.get("CICADA_PUBLIC_HANDLE_LOOKUP", "on").strip().lower() not in ("off", "0", "false", "no")


def test(memory_path: Path, fm: dict, facts, *, agent: bool = False) -> Pair:
    """Ruling 54's test for one ``merge_suggestion``: :attr:`Pair.public` when the settling step, or (``agent``) the
    person's own local agent on their ask, may work it. Sleep's step only when :func:`enabled`."""
    memory_path = Path(memory_path)
    if not agent and not enabled():
        return Pair("off")
    if fm.get("held_mention"):
        return Pair("held_mention")
    a_id, b_id = str(fm.get("entity_id") or ""), str(fm.get("merge_target_hint") or "")
    a_fm, b_fm = facts.pages.get(a_id), facts.pages.get(b_id)
    if a_fm is None or b_fm is None or a_id == b_id:
        return Pair("no_page")
    if any(str(x.get("type") or "").strip().lower() != "person" for x in (a_fm, b_fm)):
        return Pair("not_people")
    names = {a_id: " ".join(str(a_fm.get("name") or a_id).split()), b_id: " ".join(str(b_fm.get("name") or b_id).split())}
    handles = [eid for eid in (a_id, b_id) if person_leads.is_handle(names[eid])]
    if len(handles) != 1:
        return Pair("no_handle")
    handle_id = handles[0]
    named_id = b_id if handle_id == a_id else a_id
    handle, name = person_leads.handle_key(names[handle_id]), names[named_id]
    if not _full_name(name):
        return Pair("not_a_full_name")
    for eid, page_fm in ((a_id, a_fm), (b_id, b_fm)):
        if eid == facts.owner_id or page_fm.get("owner") is True:
            return Pair("owner")
        if page_fm.get("unnamed") or page_fm.get("owner_roles"):
            return Pair("relation_only")
    from api.services import text_fold

    if text_fold.fold(name) in facts.owner_names or handle in facts.owner_names:
        return Pair("owner")
    if agent:
        return _agent_test(memory_path, facts, handle_id, handle, named_id, name, names)
    return _settling_test(memory_path, facts, handle_id, handle, named_id, name)


def _private_on_record(memory_path: Path, facts, handle_id: str, named_id: str) -> str | None:
    """Ruling 44's own local checks: a page the record says the person knows, or a named side with no public cue."""
    from api.services import web_context

    for eid in (handle_id, named_id):
        page = web_context.load_page(memory_path, eid)
        if page is None:
            return "no_page"
        private = web_context.known_personally(memory_path, page, facts)
        if private:
            return private
        if eid == named_id and not web_context.PUBLIC_ROLE.search(" ".join([
                web_context._prose(page.body), " ".join(str(t) for t in page.fm.get("tags") or []),
                " ".join(str(c.text or "") for c in page.claims)])):
            return "no_public_cue"
    return None


def _settling_test(memory_path: Path, facts, handle_id: str, handle: str, named_id: str, name: str) -> Pair:
    """Sleep's step: the question stands when something may answer it — a tracked source, or a search both names clear."""
    from api.services import settling_agent

    why = _private_on_record(memory_path, facts, handle_id, named_id)
    if why is None:
        try:
            guard = name_guard.guard_for(memory_path, facts)
        except name_guard.GuardUnreadable:
            why = "guard_unreadable"
        else:
            why = next((f"guarded_{r}" for r in (guard.clears(name), guard.clears(handle)) if r), None)
    tracked, kinds = settling_agent.tracked_public(memory_path, (named_id, handle_id))
    if why is not None and not tracked:
        return Pair("walled_source" if kinds["walled"] else "proposed_source" if kinds["proposed"] else why)
    return Pair(REASON, handle_id=handle_id, handle=handle, named_id=named_id, name=name,
                site=_site_on_record(memory_path, facts.pages.get(handle_id) or {}, handle), searchable=why is None)


def _site_on_record(memory_path: Path, page_fm: dict, handle: str) -> str:
    from api.services import evidence

    for eid in [str(e) for e in (page_fm.get("source_episodes") or [])][:8]:
        doc = evidence.source_document(memory_path, eid)
        if doc is not None and (site := _site_in(doc[1], handle)):
            return site
    return ""


def site_hint(pair: Pair) -> str:
    word = SITE_WORDS.get(pair.site, "")
    return f" Memory links this account on {word}." if word else ""


def _agent_test(memory_path: Path, facts, handle_id: str, handle: str, named_id: str, name: str,
                names: dict[str, str]) -> Pair:
    """The person's own local agent, whose searches Cicada cannot see: only a pair no chat or card touches is offered."""
    for page_fm in (facts.pages[handle_id], facts.pages[named_id]):
        if _in_contacts(page_fm):
            return Pair("contacts")
    private = _private_on_record(memory_path, facts, handle_id, named_id)
    if private:
        return Pair(private)
    site = ""
    spellings = {eid: pair_evidence.side_names(memory_path, eid, names[eid]) for eid in (handle_id, named_id)}
    for eid, page_fm in ((handle_id, facts.pages[handle_id]), (named_id, facts.pages[named_id])):
        other = pair_evidence.spelling(names[named_id if eid == handle_id else handle_id])
        own = [n for n in spellings[eid] if n != other]
        private, public, found_site = _read_side(memory_path, page_fm, spellings[eid], own,
                                                 handle=handle if eid == handle_id else "")
        if private:
            return Pair(private)
        if not public:
            return Pair("no_public_content")
        site = site or found_site
    return Pair(REASON, handle_id=handle_id, handle=handle, named_id=named_id, name=name, site=site, searchable=True)


def queries(pair: Pair) -> tuple[str, str]:
    """The person's own agent's two searches: the handle with its platform word (or ``@``), and the full name alone."""
    word = SITE_WORDS.get(pair.site, "")
    return (f"{pair.handle} {word}" if word else f"@{pair.handle}", pair.name)


def quote_states(pair: Pair, quote: str) -> bool:
    """Do the quoted words name both the handle and the name? Checked here, never taken on the model's word."""
    return (pair_evidence.names_in([pair_evidence.spelling(pair.handle)], quote)
            and pair_evidence.names_in([pair_evidence.spelling(pair.name)], quote))


@dataclass(frozen=True)
class Weighed:
    ok: bool
    reason: str = ""
    ref: str = ""
    quote: str = ""
    also: tuple[dict, ...] = ()


#: Words that say an account is not, or no longer, the person's: read around the quote on the page.
_NOT_THEM = re.compile(r"\b(parody|satire|fan (?:account|page)|unofficial|not affiliated|impersonat\w+)\b", re.IGNORECASE)
_STALE = re.compile(r"\b(formerly|previously|used to be|old (?:handle|account|username)|no longer|renamed|moved to)\b",
                    re.IGNORECASE)
_TWITTER_ASIDE = re.compile(r"\(?\b(?:formerly|previously)(?: known as)? twitter\b\)?", re.IGNORECASE)
_ENCYCLOPEDIA = ("wikipedia.org", "wikidata.org")
_AROUND = 200


def _on(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def _voice(url: str, handle: str) -> tuple[str, str]:
    """``(who is speaking, kind)``: an account's own pages are one voice whatever the site."""
    from api.services import reading_hosts

    host = reading_hosts.host_of(url) or ""
    found = person_leads.profile_handle(url)
    if found is not None and found[1] == handle:
        return f"account:{handle}", "account"
    if host == f"{handle}.github.io":
        return f"account:{handle}", "account"
    if any(_on(host, d) for d in _ENCYCLOPEDIA):
        return reading_hosts.site_of(url), "encyclopedia"
    return reading_hosts.site_of(url), "other"


def _own_domain(url: str, name: str) -> bool:
    from api.services import reading_hosts

    squeezed = "".join(pair_evidence.spelling(name).split())
    label = (reading_hosts.host_of(url) or "").removeprefix("www.").split(".")[0].replace("-", "")
    return len(squeezed) >= 5 and label == squeezed


def weigh(pair: Pair, rows, pages: dict, results: dict[str, str]) -> Weighed:
    """Do these sources settle it? Engine-free, on the bytes Cicada opened (see the module docstring)."""
    from api.services import evidence

    name_key, handle_key = pair_evidence.spelling(pair.name), pair_evidence.spelling(pair.handle)
    voices: dict[str, dict] = {}
    alone: dict | None = None
    quotes: set[str] = set()
    for row in (rows if isinstance(rows, list) else [])[:8]:
        if not isinstance(row, dict):
            continue
        url, quote = str(row.get("url") or "").strip(), str(row.get("quote") or "").strip()
        page = pages.get(url)
        if page is None:
            title = results.get(url)
            found = person_leads.profile_handle(url)
            if title and found is not None and found[1] == pair.handle \
                    and pair_evidence.names_in([name_key], title):
                voices.setdefault(f"account:{pair.handle}", {"ref": url, "quote": title, "opened": False})
            continue
        hit = evidence.locate(page.text, quote) if quote else None
        if hit is None:
            continue
        around = _TWITTER_ASIDE.sub(" ", page.text[max(0, hit[0] - _AROUND):hit[1] + _AROUND])
        if _NOT_THEM.search(around):
            return Weighed(False, "parody")
        if _STALE.search(around):
            return Weighed(False, "stale")
        voice, kind = _voice(url, pair.handle)
        linked = any((person_leads.profile_handle(link) or ("", ""))[1] == pair.handle for link in page.links)
        quote_name = pair_evidence.names_in([name_key], quote)
        quote_handle = pair_evidence.names_in([handle_key], quote)
        trusted_page = bool(page.tracked_for) or kind != "other" or _own_domain(url, pair.name)
        if trusted_page:
            says = (pair_evidence.names_in([name_key], page.text)
                    and (quote_handle or linked or kind == "account" or pair_evidence.names_in([handle_key], page.text)))
        else:   # someone else's page: the quote itself says it
            says = quote_name and (quote_handle or linked)
        if not says:
            continue
        folded = pair_evidence.spelling(quote)
        if folded in quotes:
            continue   # the same words on two sites: one source copied the other
        quotes.add(folded)
        entry = {"ref": url, "quote": quote, "opened": True}
        if page.tracked_for or kind == "encyclopedia" or _own_domain(url, pair.name):
            alone = alone or entry
        current = voices.get(voice)
        if current is None or not current.get("opened"):
            voices[voice] = entry
    opened = [v for v in voices.values() if v.get("opened")]
    if not opened:
        return Weighed(False, "no_source")
    if alone is not None:
        also = tuple({"ref": v["ref"], "quote": v["quote"]} for v in opened if v["ref"] != alone["ref"])
        return Weighed(True, ref=alone["ref"], quote=alone["quote"], also=also)
    if len(voices) >= 2:
        first = opened[0]
        also = tuple({"ref": v["ref"], "quote": v["quote"]} for v in voices.values() if v["ref"] != first["ref"])
        return Weighed(True, ref=first["ref"], quote=first["quote"], also=also)
    return Weighed(False, "one_source")


def settle(memory_path: Path, item_id: str, *, ref: str, quote: str, checker: str, checker_kind: str,
           origin: str = "sleep", engine: str | None = None, session_frontmatter: dict | None = None,
           facts=None, weighed: bool = False, also: tuple[dict, ...] = ()):
    """Settle one public-handle question with a cited ``goes-by`` claim on the named page (see the module docstring).
    ``weighed``: :func:`weigh` already held the sources up on the bytes opened (Sleep's step). An agent's answer has
    only its quote, which must name both. Raises ``web_settle.NotSettleable`` with nothing written."""
    from api.services import bank_index, episode_ids, markdown_parser, web_settle
    from api.services.claims import Claim, MalformedClaimsBlockError, parse_claims, write_claims

    memory_path = Path(memory_path)
    item_path = memory_path / "inbox" / f"{item_id}.md"
    if not item_path.exists():
        raise web_settle.NotSettleable("That question is no longer open.")
    facts = facts or web_settle.bank_facts(memory_path)
    parsed_item = markdown_parser.parse(item_path)
    agent = checker_kind == "agent"
    if web_settle.classify(memory_path, parsed_item.frontmatter, parsed_item.body, facts,
                           agent=agent) != ("public", REASON):
        raise web_settle.NotSettleable("That question is not about a public handle a lookup may answer; it stays for "
                                       "the person.")
    pair = test(memory_path, parsed_item.frontmatter, facts, agent=agent)
    ref, host = web_settle.check_ref(ref, "public")
    quote = web_settle.clean_quote(quote)
    if not quote:
        raise web_settle.NotSettleable("The answer needs a short quote from the page, in its own words.")
    if not weighed and not quote_states(pair, quote):
        raise web_settle.NotSettleable("The quote must name both the handle and the person, as the page says them.")
    if pair.named_id == facts.owner_id or pair.handle_id == facts.owner_id:
        raise web_settle.NotSettleable("Never on the owner's own page; the question stays.")
    entity_path = memory_path / "entities" / f"{pair.named_id}.md"
    if not entity_path.exists():
        raise web_settle.NotSettleable("The named person's page is gone; the question stays.")
    today = date.today().isoformat()
    page = markdown_parser.parse(entity_path)
    try:
        claims = parse_claims(page.body, strict=True)
    except MalformedClaimsBlockError as exc:
        raise web_settle.NotSettleable("The page's claims could not be read; the question stays.") from exc
    predicate = pair_evidence.GOES_BY
    claim_id = web_settle._claim_id(pair.named_id, predicate, pair.handle_id, today)
    if any(x.id == claim_id for x in claims):
        raise web_settle.NotSettleable("That answer is already on the page.")
    c = web_settle.Candidate(
        item_id=item_id, kind=web_settle.PAIR, scope="public", entity_id=pair.named_id,
        name=f"{pair.handle} and {pair.name}", entity_type="person", has_page=True, predicate=predicate, options=[],
        category=[])
    episode_id = web_settle._write_episode(memory_path, c=c, ref=ref, host=host, quote=quote,
                                           checker_label=checker if checker and checker != "agent" else "an agent",
                                           checker_kind=checker_kind, origin=origin,
                                           session_frontmatter=session_frontmatter, also=also)
    answer = f"{pair.name} goes by “{pair.handle}” online"
    try:
        claim = Claim(
            id=claim_id, text=answer, subject=pair.named_id, predicate=predicate, object=pair.handle_id,
            object_kind="node", observer="agent", source_trust="external", origin=web_settle.ORIGIN,
            authored_by=checker or "agent", confidence=0.8, valid_from=today, recorded_at=today,
            evidence=list(web_settle._evidence_for(memory_path, episode_id, quote)))
        claims.append(claim)
        markdown_parser.write(entity_path, page.frontmatter, write_claims(page.body, claims))
    except BaseException:
        (memory_path / "episodes" / f"{episode_id}.md").unlink(missing_ok=True)
        bank_index.invalidate(memory_path)
        raise
    settled_dir = memory_path / "inbox" / web_settle.SETTLED_DIR
    settled_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "at": episode_ids.utc_now_iso(), "by": checker or "agent", "by_kind": checker_kind, "scope": "public",
        "ref": ref, "host": host, "quote": quote, "answer": answer, "predicate": predicate,
        "entity_id": pair.named_id, "entity_name": pair.name, "claim_id": claim.id, "claim_ids": [claim.id],
        "episode": episode_id, "held": False, "closed": [], "relation": "goes_by",
        "pair": [str(parsed_item.frontmatter.get("entity_id") or ""),
                 str(parsed_item.frontmatter.get("merge_target_hint") or "")],
        "handle": pair.handle_id, **({"engine": engine} if engine else {}),
        **({"also": [{"ref": str(x.get("ref") or ""), "quote": str(x.get("quote") or "")} for x in also]} if also else {}),
    }
    markdown_parser.write(settled_dir / f"{item_id}.md", {**parsed_item.frontmatter, "settled": record},
                          parsed_item.body)
    item_path.unlink()
    bank_index.invalidate(memory_path)
    trigger = "sleep/web-check" if origin == "sleep" else f"mcp/{checker or 'agent'}"
    paths = [f"episodes/{episode_id}.md", f"entities/{pair.named_id}.md", f"inbox/{item_id}.md",
             f"inbox/{web_settle.SETTLED_DIR}/{item_id}.md"]
    lines = [f"episodes/{episode_id}.md: created (source: {item_id}, trigger: {trigger})",
             f"entities/{pair.named_id}.md: updated (source: {episode_id}, trigger: {trigger})",
             f"inbox/{item_id}.md: settled (source: {episode_id}, trigger: {trigger})"]
    return web_settle.Settled(item_id=item_id, entity_id=pair.named_id, claim_id=claim.id, episode_id=episode_id,
                              paths=paths, lines=lines)
