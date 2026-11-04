"""Is a public handle a named person? A web lookup may say, with a cited claim (PROPOSED ruling 54, owner direction
2026-11-04; amends ruling 44's public test for this one question; built behind this rule, the owner decides).

The owner, on "is <handle> the same as <full name>?": "could've been resolved from a search, like how claude code would
solve it if i ask it rn." Ruling 44 lets a person be looked up only when Wikidata has exactly ONE human with an
encyclopedia article by that name — a developer known by a handle almost never has one, so the question stayed in the
inbox though a public profile answers it.

**Which questions** (:func:`test`, engine-free, err private; anything that fails stays for the person): an open
"Is A the same as B?" between two person PAGES (never a held mention), where

1. exactly one side is a handle (``person_leads.is_handle``: ``@name`` or one lowercase token) and the other a full
   name (two words or more, not relation-shaped, not the owner, not a role-only page);
2. neither page is known personally on the record — ruling 44's own checks (``web_context.known_personally``: an
   acquaintance relation, a sentence naming the owner with an acquaintance word, a conversation from a personal
   channel) — and the named side carries ruling 44's public cue (a public role or public work);
3. neither page carries the person's address book or LinkedIn connections (a card's source, its photo, an import's
   source);
4. no conversation from a chat (Messages, WhatsApp, Telegram chats, e-mail, LinkedIn, a profile read on request) says
   either name outside a link to public content, or has it in its title or as its correspondent — a shared link to a
   post by that account is the post, not the person; and
5. each name is said in at least one conversation that IS public content the person read or saved (a saved link or
   bookmark, a watched video, a read page, a paper, a repository, a tab group) — :data:`PUBLIC_CONTENT_SOURCES`.

Bounded: :data:`SEARCH_PER_NAME` conversations per spelling from the lexical index, plus each page's own; a spelling
whose search fills that bound could hide a chat, so it fails (``unbounded``).

**What is sent where** (:func:`queries`): to the plan's own web search tool (the ``claude -p`` call with web search
as its one tool, ``web_lookup``), exactly two pinned queries, each alone: the handle with the one platform word the
record links it on (``<handle> github``, ``<handle> twitter``, ``<handle> instagram``, ``<handle> linkedin``), else
``@<handle>``; and the full name alone. Nothing else is searched; every search the engine reports is held to those
two, word for word, or nothing is settled. The prompt itself goes to the same engine that already read these
conversations in Sleep, with at most two scrubbed lines of where the handle was mentioned (``web_settle.local_context``,
other people's names taken out). A metered key is never spent on it: plan runs only.

**What settles** (:func:`settle`): only a sure answer that the handle IS that person, with the link of a public page
whose quoted words name both the handle and the name (checked here, not taken on the model's word). It writes one
cited claim on the named person's page — "<Name> goes by “<handle>” online", predicate ``goes-by``, its object the
handle's page (observer ``agent``, ``source_trust: external``, origin ``web-check``) — its citation in one
``web-check`` episode, and moves the question to "Settled by a check" (``web_settle.undo`` takes it all back and the
question returns, never checked again). Never a merge: the two pages stay, and the person merges them with one tap
if they want (a handle page may also hold other things, such as an agent named after the handle). While the claim
stands, the pair is not asked again (``pair_evidence.answered_by_check``). Any other answer settles nothing.

Sleep's own lookup is OFF until the owner rules (``CICADA_PUBLIC_HANDLE_LOOKUP=on`` turns it on, :func:`enabled`); the
person's own local agent, asked by them, may settle one through ``cicada_record_check`` either way.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from api.services import pair_evidence, person_leads

#: Conversations that ARE public content the person read or saved (an episode's ``source``).
PUBLIC_CONTENT_SOURCES = frozenset({
    "youtube", "watch-history", "watch-history-month", "video-watch", "bookmark", "url", "link", "media", "tab-group",
    "reading-history", "page-read", "listening-history", "arxiv", "crossref", "github",
})
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
    """Sleep's own lookup: OFF until the owner rules on proposed ruling 54 (coordinator, 2026-11-04: a privacy-rail
    change is built switched off and decided by the owner); ``CICADA_PUBLIC_HANDLE_LOOKUP=on`` turns it on."""
    return os.environ.get("CICADA_PUBLIC_HANDLE_LOOKUP", "off").strip().lower() in ("on", "1", "true", "yes")


def test(memory_path: Path, fm: dict, facts, *, agent: bool = False) -> Pair:
    """Proposed ruling 54's test for one ``merge_suggestion``: :attr:`Pair.public` when a lookup may answer it.
    ``agent``: the person's own local agent asked, on their ask (``cicada_record_check``) — the same test, whatever the
    switch; Sleep's own lookup only when :func:`enabled`."""
    from api.services import web_context

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
        if _in_contacts(page_fm):
            return Pair("contacts")
    from api.services import text_fold

    if text_fold.fold(name) in facts.owner_names or handle in facts.owner_names:
        return Pair("owner")
    for eid in (handle_id, named_id):
        page = web_context.load_page(memory_path, eid)
        if page is None:
            return Pair("no_page")
        private = web_context.known_personally(memory_path, page, facts)
        if private:
            return Pair(private)
        if eid == named_id and not web_context.PUBLIC_ROLE.search(" ".join([
                web_context._prose(page.body), " ".join(str(t) for t in page.fm.get("tags") or []),
                " ".join(str(c.text or "") for c in page.claims)])):
            return Pair("no_public_cue")
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
    return Pair(REASON, handle_id=handle_id, handle=handle, named_id=named_id, name=name, site=site)


def queries(pair: Pair) -> tuple[str, str]:
    """The two searches, and only these: the handle with its platform word (or ``@``), and the full name alone."""
    word = SITE_WORDS.get(pair.site, "")
    return (f"{pair.handle} {word}" if word else f"@{pair.handle}", pair.name)


def quote_states(pair: Pair, quote: str) -> bool:
    """Do the quoted words name both the handle and the name? Checked here, never taken on the model's word."""
    return (pair_evidence.names_in([pair_evidence.spelling(pair.handle)], quote)
            and pair_evidence.names_in([pair_evidence.spelling(pair.name)], quote))


def settle(memory_path: Path, item_id: str, *, ref: str, quote: str, checker: str, checker_kind: str,
           origin: str = "sleep", engine: str | None = None, session_frontmatter: dict | None = None,
           facts=None):
    """Settle one public-handle question with a cited ``goes-by`` claim on the named page (see the module docstring).
    Raises ``web_settle.NotSettleable`` with nothing written."""
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
    if not quote_states(pair, quote):
        raise web_settle.NotSettleable("The quote must name both the handle and the person, as the page says them.")
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
                                           session_frontmatter=session_frontmatter)
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
