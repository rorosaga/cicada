"""G61 S3-b — an official site is a source, confirmed on Cicada's own rail; a picture is drawn from it.

``website`` is one predicate among many on a page's ``sources:`` (see ``fact_sources``). This module is everything
that puts one there without the person's hand and decides how far to lean on it:

- :func:`sanitize_website` — Stage 1 may propose ONE official site for a ``company``, ``tool`` or ``project``; only an
  https origin of a public, non-platform, non-walled host survives (never a profile, an article, a repo host, a social
  page, and never a value for any other type).
- :func:`candidates` / :func:`propose` — an engine-free backfill for pages that have none: the page's own current
  ``website`` claim, else a URL in its ``## Links`` whose host is the page's own name (or whose title says "official").
  Nothing else — **never a domain guessed from a name**.
- :func:`judge` / :func:`verify` — Cicada's own read (``link_enrichment.fetch_identity``, the link rail's transport)
  confirms a proposed site: the page's name must be on it AND two distinctive words of the page's own summary. A
  namesake fails the second half ("a company called Fireworks" does not verify a fireworks-show site). Outcomes follow
  D1: verified -> stamped; a wrong or walled site -> removed and remembered (``sources_removed``, by ``cicada``); thin
  content -> kept "not confirmed" (one tap of "Use this site" trusts it); a network failure -> tried up to three nights.

A proposed site is UNVERIFIED (``fact_sources.trusted`` says no) until a stamp or the person says otherwise, and only a
trusted ``website`` source ever draws a picture (``logo_service.domain_for``). Nothing here writes a page's body or a
``decay_class``; every write is a page's frontmatter, committed by the caller (``commit_message``): the Sleep tail's
step and ``POST /maintenance/verify-sites`` both go through one ``cicada``-authored, path-scoped commit.

ToS rail: a walled host (``reading_hosts.is_walled``) or a platform host is never fetched — :func:`verify` refuses one
before any request, and ``fetch_identity`` refuses it again. One fetch per site per run, at the link rail's own numbers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import urlparse

from loguru import logger

from api.services import entity_body, fact_sources, git_service, markdown_parser, reading_hosts, text_fold

TRIGGER = "sleep/site-check"
ROUTE_TRIGGER = "user/companion_app"
AUTHOR = fact_sources.CICADA
SITE_TYPES = frozenset({"company", "tool", "project"})
MAX_TRIES = 3
RECHECK_DAYS = 30
TAIL_BUDGET = 25
ROUTE_BUDGET = 100

#: A page on one of these is a profile, an article or a code host — somebody's page ABOUT the entity, never its own
#: site, so it is never proposed, never fetched and never drawn as the entity's mark. Closed; walled hosts
#: (``reading_hosts.is_walled``) are refused on top of it.
PLATFORM_HOSTS = frozenset({
    "github.com", "gitlab.com", "bitbucket.org", "npmjs.com", "pypi.org", "crates.io", "rubygems.org",
    "huggingface.co", "wikipedia.org", "wikimedia.org", "medium.com", "substack.com", "youtube.com", "youtu.be",
    "vimeo.com", "twitter.com", "x.com", "linkedin.com", "facebook.com", "instagram.com", "reddit.com", "tiktok.com",
    "crunchbase.com", "producthunt.com", "play.google.com", "apps.apple.com", "docs.google.com", "notion.so",
    "google.com", "bing.com", "duckduckgo.com", "archive.org", "news.ycombinator.com", "stackoverflow.com",
    "arxiv.org", "doi.org", "bsky.app", "threads.net", "t.me", "discord.com", "slack.com",
})

_STOP = frozenset("""about above after again against because before between could during every first found from have
into more most other should since some such than that their them then there these they this those through under until
very what when where which while with would your yours""".split())
_URL_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)|(https?://[^\s<>\")\]]+)")
_OFFICIAL = re.compile(r"\b(official|homepage|home page|website|web site)\b", re.IGNORECASE)
_SUBSTANTIAL = 200   # characters of visible text below which a page is "thin" (a JS shell says nothing either way)


def is_platform(url_or_host: str) -> bool:
    """A walled or platform host: never proposed, never fetched, never a picture."""
    if reading_hosts.is_walled(url_or_host if "://" in url_or_host else f"https://{url_or_host}"):
        return True
    site = reading_hosts.site_of(url_or_host)
    return site in PLATFORM_HOSTS or any(site.endswith("." + p) for p in PLATFORM_HOSTS)


def origin_of(value) -> str | None:
    """``https://host`` for a public, non-platform host, else None. Only https; a path, query and fragment go."""
    text = str(value or "").strip()
    if not text:
        return None
    if "://" not in text:
        text = "https://" + text
    try:
        parsed = urlparse(text)
        host = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    if parsed.scheme not in ("https", "http") or parsed.port not in (None, 443, 80):
        return None
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host or not reading_hosts.is_public_name(host):
        return None
    if re.fullmatch(r"[\d.]+", host) or is_platform(host):
        return None
    return f"https://{host}"


def sanitize_website(entity: dict) -> None:
    """Stage-1 rail on ONE extracted entity dict: keep ``website`` only for a company, tool or project, and only as an
    https origin of a public, non-platform host. Anything else is dropped, so the writer never sees it. Mutates in
    place; never raises."""
    if "website" not in entity:
        return
    value = entity.pop("website")
    if str(entity.get("type") or "").strip().lower() not in SITE_TYPES or not isinstance(value, str):
        return
    origin = origin_of(value)
    if origin:
        entity["website"] = origin


# ---- the engine-free backfill ---------------------------------------------------------------------------------------


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text_fold.fold(text))


def _names(fm: dict) -> list[str]:
    raw = [fm.get("name")] + [a for a in (fm.get("aliases") or []) if isinstance(a, str)]
    return [n for n in (_squash(str(x or "")) for x in raw) if len(n) >= 3]


def _website_claim_origin(body: str) -> str | None:
    from api.services.claims import parse_claims

    try:
        claims = parse_claims(body or "")
    except Exception:
        return None
    for claim in claims:
        if claim.valid_to is not None or claim.superseded_by:
            continue
        if (claim.predicate or "").strip().lower() == "website":
            origin = origin_of(claim.object)
            if origin:
                return origin
    return None


def _links_origin(fm: dict, body: str) -> str | None:
    """A ``## Links`` URL whose site label folds equal to the page's name or an alias, or whose link title says
    "official" / "homepage" / "website". Nothing else."""
    section = entity_body.parse_sections(body or "").get("Links", "")
    names = _names(fm)
    for line in section.splitlines():
        for m in _URL_LINK.finditer(line):
            title, url = (m.group(1) or ""), (m.group(2) or m.group(3) or "").rstrip(").,")
            origin = origin_of(url)
            if not origin:
                continue
            label = _squash(reading_hosts.site_of(origin).split(".")[0])
            if (label and label in names) or _OFFICIAL.search(title):
                return origin
    return None


def _has_website_source(fm: dict) -> bool:
    return any(fact_sources.same_predicate(s.get("predicate"), fact_sources.WEBSITE)
               for s in fact_sources.as_sources(fm.get("sources")))


def candidates(memory_path: Path) -> list[tuple[str, str]]:
    """``[(entity_id, origin)]`` for company/tool/project pages that are live and hold no ``website`` source, found by
    a zero-LLM rule (:func:`_website_claim_origin`, then :func:`_links_origin`) and not tombstoned. Read-only."""
    from api.services import bank_index

    out: list[tuple[str, str]] = []
    for f in bank_index.files(Path(memory_path), "entities"):
        fm = f.frontmatter or {}
        if str(fm.get("type") or "").lower() not in SITE_TYPES or str(fm.get("status") or "") in ("archived", "dropped"):
            continue
        if _has_website_source(fm):
            continue
        body = f.body()
        origin = _website_claim_origin(body) or _links_origin(fm, body)
        if origin and not fact_sources.is_tombstoned(fm, origin, fact_sources.WEBSITE):
            out.append((f.stem, origin))
    return sorted(out)


@dataclass
class Report:
    paths: list[str] = field(default_factory=list)      # memory-relative pages written (deduped, in order)
    counts: dict[str, int] = field(default_factory=dict)  # ids-free: proposed, fetched, verified, ...

    def bump(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n

    def touch(self, rel: str) -> None:
        if rel not in self.paths:
            self.paths.append(rel)


def propose(memory_path: Path, skip: frozenset[str] = frozenset(), report: Report | None = None) -> Report:
    """Write every :func:`candidates` site as an UNVERIFIED ``website`` source added by ``cicada``. Pages in ``skip``
    (dirty before the run) are left alone."""
    report = report or Report()
    memory_path = Path(memory_path)
    for entity_id, origin in candidates(memory_path):
        rel = f"entities/{entity_id}.md"
        if rel in skip:
            continue
        path = memory_path / rel
        parsed = markdown_parser.parse(path)
        if fact_sources.propose_site(parsed.frontmatter, origin, added_by=AUTHOR):
            report.touch(rel)   # before the write: an exception after it can still restore the page
            markdown_parser.write(path, parsed.frontmatter, parsed.body)
            report.bump("proposed")
    return report


# ---- judging --------------------------------------------------------------------------------------------------------


def _distinctive_tokens(fm: dict, body: str) -> list[str]:
    """Words (≥ 5 letters, stop-worded, not the page's own name) from the page's summary and key facts."""
    sections = entity_body.parse_sections(_strip_claims(body))
    text = " ".join(str(sections.get(k) or "") for k in ("Summary", "Key Facts"))
    name_words = set(text_fold.words(str(fm.get("name") or "")))
    seen: list[str] = []
    for w in text_fold.words(text):
        if len(w) >= 5 and w.isalpha() and w not in _STOP and w not in name_words and w not in seen:
            seen.append(w)
    return seen


def _strip_claims(body: str) -> str:
    from api.services.claims import strip_claims_block

    return strip_claims_block(body or "")


_SUFFIXES = frozenset({"inc", "ltd", "llc", "corp", "corporation", "co", "company", "gmbh", "plc", "limited", "sa", "ag",
                       "bv", "pty"})


def _name_tokens(name: str) -> list[str]:
    """A name's words without a company suffix ("Acme Inc" -> ["acme"]), folded."""
    words = [w for w in text_fold.words(name) if w]
    kept = [w for w in words if w not in _SUFFIXES]
    return kept or words


def _name_present(text: str, names: list[str]) -> bool:
    """The page's name (or an alias) is WHOLE-WORD in ``text``: as written, or with its company suffix stripped, or — for
    a name of several words — with every word present in any order ("OpenAI Codex" on "Codex | OpenAI")."""
    from api.services import evidence

    words = set(text_fold.words(text))
    for name in names:
        if evidence.locate(text, name, whole_word=True):
            return True
        tokens = _name_tokens(name)
        if tokens and all(t in words for t in tokens) and (len(tokens) > 1 or len(tokens[0]) >= 3):
            return True
    return False


def judge(fm: dict, body: str, identity) -> str:
    """``verified | unconfirmed | mismatch | unreachable`` — pure over a page and what its site said.

    ``verified`` needs the page's name (or an alias, company suffix aside, every word in any order) whole-word in the
    site's title or ``og:site_name`` AND at least two distinctive words of its own summary on the page.

    The destructive outcome is reserved for POSITIVE evidence: ``mismatch`` (the site is removed and remembered forever)
    only when the name IS on a substantial page but two or more of the summary's distinctive words are absent — the
    namesake ("a company called Fireworks" on a fireworks-show site). Everything else that is merely not proven —
    a name the matcher could not find, a thin JS shell, a redirect to another domain (the FINAL page is what is judged:
    a move from one domain to its canonical one is ordinary), a bot block or a consent page — is ``unconfirmed``: kept,
    "not confirmed", one tap of "Use this site" away. A network failure is ``unreachable``. A block is never a verdict."""
    status = identity.status
    if status in ("blocked", "interstitial"):
        return "unconfirmed"
    if status != "ok":
        return "unreachable"
    names = [str(fm.get("name") or "")] + [a for a in (fm.get("aliases") or []) if isinstance(a, str)]
    names = [n for n in names if n.strip()]
    heading = f"{identity.title} | {identity.site_name}"
    name_in_heading = _name_present(heading, names)
    page_text = " ".join((identity.title, identity.site_name, identity.meta_description, identity.excerpt))
    page_words = set(text_fold.words(page_text))
    tokens = _distinctive_tokens(fm, body)
    hits = [t for t in tokens if t in page_words]
    if name_in_heading and len(hits) >= 2:
        return "verified"
    substantial = len(identity.excerpt) >= _SUBSTANTIAL
    name_on_page = name_in_heading or _name_present(page_text, names)
    if substantial and name_on_page and len(tokens) >= 2 and len(hits) < 2:
        return "mismatch"
    return "unconfirmed"


# ---- verification ----------------------------------------------------------------------------------------------------

FetchIdentity = Callable[..., Awaitable]


def _pending(fm: dict, today: date) -> list[dict]:
    """The page's UNVERIFIED ``website`` entries that are due a look: not trusted, and not judged "not confirmed" (or
    unreachable three nights running) in the last :data:`RECHECK_DAYS`."""
    due: list[dict] = []
    for s in fact_sources.as_sources(fm.get("sources")):
        if not fact_sources.same_predicate(s.get("predicate"), fact_sources.WEBSITE) or fact_sources.trusted(s):
            continue
        checked = s.get("checked") if isinstance(s.get("checked"), dict) else None
        if checked and checked.get("outcome") in ("unconfirmed", "unreachable"):
            try:
                if today - date.fromisoformat(str(checked.get("at"))[:10]) < timedelta(days=RECHECK_DAYS):
                    continue
            except ValueError:
                pass
        due.append(s)
    return due


def _due_pages(memory_path: Path, skip: frozenset[str], today: date) -> list[tuple[str, int]]:
    """``[(memory-relative path, how many entries are due)]`` — a bank scan, so the caller runs it off the event loop."""
    from api.services import bank_index

    out: list[tuple[str, int]] = []
    for f in bank_index.files(Path(memory_path), "entities"):
        fm = f.frontmatter or {}
        rel = f"entities/{f.stem}.md"
        if rel in skip or str(fm.get("type") or "").lower() not in SITE_TYPES:
            continue
        due = _pending(fm, today)
        if due:
            out.append((rel, len(due)))
    return out


def _write_page(path: Path, fm: dict, body: str) -> None:
    markdown_parser.write(path, fm, body)


async def verify(memory_path: Path, *, budget: int = TAIL_BUDGET, skip: frozenset[str] = frozenset(),
                 fetch_fn: FetchIdentity | None = None, settings=None, today: date | None = None,
                 report: Report | None = None) -> Report:
    """Confirm proposed sites on Cicada's own rail — at most ``budget`` fetches, one per site per run, never a walled
    or platform host (refused before any request), pages in ``skip`` untouched. Writes frontmatter only; the caller
    commits ``report.paths`` — or, when this or a later step raises, restores them (``report`` is the caller's, filled as
    the run goes, so a page written before the failure is always on it). ``fetch_fn`` defaults to
    ``link_enrichment.fetch_identity`` (the tests inject one). The bank scan, each parse and each write run off the event
    loop (``asyncio.to_thread``); only the fetches are awaited on it."""
    import asyncio

    from api.services import bank_index, link_enrichment

    fetch_fn = fetch_fn or link_enrichment.fetch_identity
    report = report if report is not None else Report()
    today = today or date.today()
    memory_path = Path(memory_path)
    sites_seen: set[str] = set()
    try:
        for rel, due in await asyncio.to_thread(_due_pages, memory_path, skip, today):
            if report.counts.get("fetched", 0) >= budget:
                report.bump("deferred", due)
                continue
            path = memory_path / rel
            parsed = await asyncio.to_thread(markdown_parser.parse, path)
            pfm, body = parsed.frontmatter, parsed.body
            changed = False
            pending = _pending(pfm, today)
            for live in [s for s in (pfm.get("sources") or []) if isinstance(s, dict) and s in pending]:
                ref = str(live.get("ref") or "")
                site = reading_hosts.site_of(ref)
                if is_platform(ref):
                    # A platform host was put there by hand or by an older proposal: removed without a request.
                    _drop(pfm, live, "platform")
                    report.bump("platform")
                    changed = True
                    continue
                if site in sites_seen or report.counts.get("fetched", 0) >= budget:
                    report.bump("deferred")
                    continue
                sites_seen.add(site)
                report.bump("fetched")
                identity = await fetch_fn(ref, settings)
                verdict = judge(pfm, body, identity)
                changed |= _apply(pfm, live, verdict, today)
                report.bump(verdict)
            if changed:
                report.touch(rel)   # before the write: a failure after it can still restore the page
                await asyncio.to_thread(_write_page, path, pfm, body)
    finally:
        if report.paths:
            bank_index.invalidate(memory_path)
    return report


def _drop(fm: dict, entry: dict, reason: str) -> None:
    rows = [s for s in (fm.get("sources") or []) if s is not entry]
    fact_sources._push_tombstone(fm, entry, by=AUTHOR, reason=reason)
    if rows:
        fm["sources"] = rows
    else:
        fm.pop("sources", None)


def _apply(fm: dict, entry: dict, verdict: str, today: date) -> bool:
    if verdict == "verified":
        entry["verified"] = {"at": today.isoformat(), "how": "name+content"}
        entry["access"] = fact_sources.ACCESS_PUBLIC
        entry.pop("tries", None)
        entry.pop("checked", None)
    elif verdict == "mismatch":
        _drop(fm, entry, "mismatch")
    elif verdict == "unconfirmed":
        entry["checked"] = {"at": today.isoformat(), "outcome": "unconfirmed"}
        entry.pop("tries", None)
    else:   # unreachable: tried again on the next nights; a site down three nights is asked again in a month, never lost
        entry["tries"] = int(entry.get("tries") or 0) + 1
        if entry["tries"] >= MAX_TRIES:
            entry["checked"] = {"at": today.isoformat(), "outcome": "unreachable"}
            entry.pop("tries", None)
    return True


def commit_message(report: Report, today: date, trigger: str = TRIGGER) -> str:
    """``Site check <date>``, ``Cicada-Author: cicada``, no engine trailer (no LLM ran). Counts only in the body's
    lines; a page id is a path, never a URL, host or reason."""
    return git_service.build_commit_message(
        f"Site check {today.isoformat()}",
        [f"{p}: updated (source: n/a, trigger: {trigger})" for p in report.paths], authors=[AUTHOR])


def restore(memory_path: Path, report: Report) -> None:
    """Undo a run whose commit failed: the pages come back from HEAD, so the next ``git add -A`` writer never sweeps
    them under the wrong author (the G85 smear); the run is re-derived tomorrow."""
    from api.services import bank_index

    memory_path = Path(memory_path)
    if report.paths and (memory_path / ".git").exists():
        try:
            git_service.run_git_write_sync(memory_path, "checkout", "--", *report.paths)
        except git_service.GitError as exc:
            logger.warning(f"site-check restore failed: {type(exc).__name__}")
    bank_index.invalidate(memory_path)
