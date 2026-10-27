"""Leads that two person pages may be one person (G209): engine-free, and never a decision.

One person used to live on the bank three times: a full-name page already listing a handle among its aliases, a page
titled by that handle, and a pending line "handle (Full Name)". Stage 2 compared an in-cycle create by name only, an
exact page always won over another page's alias, and the extractor's parenthetical form parked as a literal name.

What this module reads off the record, and nothing more:

- **an alias**: a person page lists a name that another person page carries as its own;
- **a profile link**: a person page links an account (``x.com/<h>``, ``github.com/<h>``, ``instagram.com/<h>``,
  ``linkedin.com/in/<h>``) whose handle is another person page's name;
- **a named handle**: an extraction or pending line of the form ``Full Name (handle)`` or ``handle (Full Name)``.

Each is a lead, never proof (2026-10-08: an alias is a lead; ruling 29: never who a person is without their words):
Stage 2 turns a lead into the existing "Possible duplicate of …" question and never merges on it, and
``api.scripts.person_leads_dry_run`` lists them for a bank. A handle is never guessed from a name: it must already be
written on the record.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from api.services import role_people

_PAREN = re.compile(r"^\s*([^()]+?)\s*\(\s*([^()]+?)\s*\)\s*$")
_HANDLE = re.compile(r"^@?[A-Za-z0-9_][A-Za-z0-9_.-]{1,38}$")
_WORD = re.compile(r"[^\W\d_][\w'.-]*", re.UNICODE)
_MD_LINK = re.compile(r"\]\((https?://[^)\s]+)")
_BARE_URL = re.compile(r"https?://[^\s)>\]\"']+")

#: Hosts whose first path segment is an account, and the paths on them that are not one.
_PROFILE_HOSTS = {"x.com": "x", "twitter.com": "x", "github.com": "github", "instagram.com": "instagram"}
_NOT_ACCOUNTS = frozenset({
    "home", "i", "search", "explore", "intent", "share", "settings", "hashtag", "messages", "notifications",
    "login", "signup", "about", "orgs", "topics", "features", "marketplace", "sponsors", "p", "reel", "reels",
    "stories", "accounts", "tv",
})


def handle_key(text: str) -> str:
    """The comparison key of a name or handle: trimmed, lowercase, without a leading ``@``."""
    return str(text or "").strip().lower().lstrip("@")


def is_handle(text: str) -> bool:
    """An account handle as people write it: ``@name``, or one lowercase token (``bob_example``, ``bex42``).

    A capitalised word is a name, and a relation or role word ("mom", "ceo") is never a handle."""
    text = str(text or "").strip()
    if not _HANDLE.match(text):
        return False
    if text.startswith("@"):
        return True
    return text == text.lower() and text.lower() not in role_people.ROLE_WORDS


def _is_full_name(text: str) -> bool:
    words = _WORD.findall(text)
    return len(words) >= 2 and not is_handle(text)


def split_named_handle(name: str) -> tuple[str, str] | None:
    """``Full Name (handle)`` or ``handle (Full Name)`` -> ``(Full Name, handle)``; anything else -> ``None``.

    The extractor writes this form when the record itself paired the two, so it is one mention under one name with the
    handle as its alias; it is never read as two people, and never as proof about some other page."""
    match = _PAREN.match(str(name or ""))
    if match is None:
        return None
    outside, inside = match.group(1).strip(), match.group(2).strip()
    if is_handle(inside) and _is_full_name(outside):
        return outside, inside
    if is_handle(outside) and _is_full_name(inside):
        return inside, outside
    return None


def profile_handle(url: str) -> tuple[str, str] | None:
    """``(site, handle)`` for a link to an account's own profile, else ``None``.

    Only the profile itself counts: ``github.com/<h>`` (not a repository under it), ``x.com/<h>`` and its posts'
    ``x.com/<h>/status/…`` path, ``instagram.com/<h>``, ``linkedin.com/in/<h>``."""
    try:
        parts = urlsplit(str(url or "").strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower().removeprefix("www.").removeprefix("mobile.")
    segments = [s for s in parts.path.split("/") if s]
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        if len(segments) >= 2 and segments[0] == "in":
            return "linkedin", segments[1].lower()
        return None
    site = _PROFILE_HOSTS.get(host)
    if site is None or not segments or segments[0].lower() in _NOT_ACCOUNTS:
        return None
    handle = segments[0].lstrip("@")
    if not _HANDLE.match(handle):
        return None
    if site == "github" and len(segments) != 1:
        return None
    if site == "x" and len(segments) > 1 and segments[1] != "status":
        return None
    if site == "instagram" and len(segments) != 1:
        return None
    return site, handle.lower()


def page_urls(page: dict) -> list[str]:
    """The links a page carries: its ``sources:`` refs, then every link written in its body."""
    fm = page.get("frontmatter") or {}
    urls: list[str] = []
    for source in fm.get("sources") or []:
        ref = source.get("ref") if isinstance(source, dict) else source
        if isinstance(ref, str) and ref.startswith("http"):
            urls.append(ref)
    body = str(page.get("body") or "")
    urls += _MD_LINK.findall(body)
    urls += [u for u in _BARE_URL.findall(body) if u not in urls]
    return urls


def page_aliases(page: dict) -> list[str]:
    values = (page.get("frontmatter") or {}).get("aliases")
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    return [text for text in (str(v or "").strip() for v in values) if text]


def page_name(page: dict) -> str:
    return str((page.get("frontmatter") or {}).get("name") or page.get("id") or "")


@dataclass(frozen=True)
class Lead:
    """``page`` may be the same person as ``holder``: ``holder`` carries ``page``'s name as ``kind``.

    ``kind`` is ``alias`` (the holder lists the name among its aliases), ``profile:<site>`` (the holder links that
    account) or ``named_handle`` (the record paired the two names in one mention). ``page`` is the one a merge would
    fold away, the handle-titled page; ``holder`` the page that would keep it."""
    page: str
    holder: str
    kind: str
    key: str


#: The types one organisation, lab, project or tool is written under (2026-10-27): a lab Stage 1 called a company in one
#: conversation and a project in another is still one thing, so an alias lead crosses these three — and only these.
ORG_TYPES = frozenset({"company", "project", "tool"})
PERSON_TYPES = frozenset({"person"})


def _page_type(page: dict) -> str:
    return str((page.get("frontmatter") or {}).get("type") or "").lower()


class PersonIndex:
    """The bank's person pages, keyed for leads: by name, by alias and by profile handle. Built once per read.

    ``types`` widens it to another family (2026-10-27, :data:`ORG_TYPES`): the same alias lead — a page lists, among
    the names it goes by, a name another page of the family carries as its own — for organisations, labs, projects
    and tools. A profile handle is a person's only. Never a lead on a shared WORD: the alias must be the other page's
    whole name."""

    def __init__(self, pages: list[dict], types: frozenset[str] = PERSON_TYPES):
        self.types = frozenset(types)
        self.by_id: dict[str, dict] = {}
        self.by_name: dict[str, list[str]] = {}
        self.alias_holders: dict[str, list[str]] = {}
        self.handle_holders: dict[str, list[tuple[str, str]]] = {}
        people = self.types == PERSON_TYPES
        for page in pages:
            if _page_type(page) not in self.types or not page.get("id"):
                continue
            if str((page.get("frontmatter") or {}).get("status") or "active") in ("dropped", "archived") and not people:
                continue
            pid = str(page["id"])
            self.by_id[pid] = page
            self.by_name.setdefault(handle_key(page_name(page)), []).append(pid)
            for alias in page_aliases(page):
                holders = self.alias_holders.setdefault(handle_key(alias), [])
                if pid not in holders:
                    holders.append(pid)
            for url in page_urls(page) if people else ():
                found = profile_handle(url)
                if found is None:
                    continue
                holders = self.handle_holders.setdefault(found[1], [])
                if (pid, found[0]) not in holders:
                    holders.append((pid, found[0]))

    def holders_of(self, name: str, *, exclude: str = "") -> list[tuple[str, str]]:
        """The person pages other than ``exclude`` that carry ``name`` as an alias or a linked account, as
        ``(page id, kind)``, aliases first."""
        key = handle_key(name)
        out: list[tuple[str, str]] = []
        for pid in self.alias_holders.get(key, ()):
            if pid != exclude and all(pid != held for held, _ in out):
                out.append((pid, "alias"))
        for pid, site in self.handle_holders.get(key, ()):
            if pid != exclude and all(pid != held for held, _ in out):
                out.append((pid, f"profile:{site}"))
        return out

    def leads_for(self, page_id: str) -> list[Lead]:
        """Every lead that touches ``page_id``: other pages carrying its name, and other pages its own aliases and
        linked accounts name."""
        page = self.by_id.get(page_id)
        if page is None:
            return []
        leads: list[Lead] = []
        own = handle_key(page_name(page))
        for holder, kind in self.holders_of(own, exclude=page_id):
            leads.append(Lead(page=page_id, holder=holder, kind=kind, key=own))
        names = [(handle_key(a), "alias") for a in page_aliases(page)]
        names += [(found[1], f"profile:{found[0]}") for found in map(profile_handle, page_urls(page)) if found]
        for key, kind in names:
            for other in self.by_name.get(key, ()):
                if other != page_id:
                    lead = Lead(page=other, holder=page_id, kind=kind, key=key)
                    if lead not in leads:
                        leads.append(lead)
        return leads

    def all_leads(self) -> list[Lead]:
        seen: set[tuple[str, str]] = set()
        out: list[Lead] = []
        for pid in self.by_id:
            for lead in self.leads_for(pid):
                if (lead.page, lead.holder) not in seen:
                    seen.add((lead.page, lead.holder))
                    out.append(lead)
        return out


_ANSWERED = re.compile(r"_Resolved ambiguous mention '(.+?)' into this entity\._")


def answered_note(mention: str) -> str:
    """The line a person's "same" answer leaves on the page it merged a mention into (``inbox_service``)."""
    return f"_Resolved ambiguous mention '{mention}' into this entity._"


def answered_same(page: dict, name: str) -> bool:
    """Did the person answer that ``name`` is this page? Their merge answer left :func:`answered_note` in its body: the
    person's own word on the record (ruling 29), so Stage 2 sends the name there and never asks again."""
    key = handle_key(name)
    return any(handle_key(m) == key for m in _ANSWERED.findall(str(page.get("body") or "")))


def lead_reason(lead: Lead, holder_name: str) -> str:
    """The question's context in words: what on the record made the two pages meet."""
    if lead.kind == "alias":
        return f"{holder_name} already lists “{lead.key}” among the other names it goes by."
    if lead.kind.startswith("profile:"):
        return f"{holder_name} links the {lead.kind.split(':', 1)[1]} account “{lead.key}”."
    return f"A conversation named “{lead.key}” together with {holder_name}."
