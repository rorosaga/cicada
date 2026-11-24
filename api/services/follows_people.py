"""The accounts the person follows — a directory outside every bank that attaches to pages that already exist and never
makes one (G245, ruling 79 (b); owner 2026-11-24, "Should the accounts you follow be read?": "2. yes").

The owner said of LinkedIn connections that "a linkedin connection doesnt need a page just for the sake of having a page,
the person is what gets a page". A followed account is treated the same way, in the same shape as
:mod:`linkedin_people`:

* **Kept outside every bank and git**, per site, at ``$CICADA_HOME/people/<bank>/follows-<site>.json`` (0600, written by a
  rename, ``people_directory``): a display name, a handle, the profile link, the day first seen, and ``gone_on`` — nothing
  else. No bio, no counts, no picture, no "follows back". No episode, no media page, nothing in git, nothing logged but
  counts. Forgetting the directory removes everything it holds; so does trashing the bank.
* **A follow is not a mention and not acquaintance** (ruling 44): it never touches promotion, decay, ``last_referenced``,
  a conversation count or a page's ``learned_on``, and it never makes a page. A page that already exists gains a profile
  link and one dated ``followed-on`` claim, in Sleep's tail in its own commit (:func:`rematch`) or in the write that
  births the page (:class:`Attacher`).
* **How sure.** X display names are free text, so a match on the name alone is only a **proposed** link (``proposed:
  true``, the grouped "Confirm N links" review) and no claim; a page that already holds the account's link is the match
  beyond doubt, and gets the claim. Refusals write nothing and are counted, never named: a same-name doubt in the bank, two
  pages or two followed accounts of one name, a page that names another profile. A removal the person made
  (``sources_removed``) is respected by every writer here.
* **Bounded, because the list has no limit and the agent's "I reached the end" is its own word** (``SITES``): a hard
  row cap per read, and a row is marked gone only when a whole read that is not cut off, returned at least
  :data:`TRUSTED_SHARE` of what the last trusted whole read returned, AND two such reads in a row agree it is missing
  (:data:`MISSES_TO_GONE`). A read that stopped early, was cut by its row cap, or came back much smaller marks nothing.
  The ``followed-on`` claim closes only on a ``gone_on``.
* **Names never leave.** ``name_guard.store_names`` reads these files, so a name or handle known only from here is never
  in a web query (rulings 44, 54). No model reads the directory, and no remote or agent door reaches it.

Every number and word that belongs to the site rather than to the idea is in ``SITES`` — one constant — because the live
look at X's Following page has not been made (see the table's own comment).
"""
from __future__ import annotations

import fcntl
import hashlib
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

from loguru import logger

from api.services import bank_index, evidence, fact_sources, markdown_parser, page_lock, people_directory
from api.services.claims import Claim, MalformedClaimsBlockError, parse_claims, write_claims

AUTHOR = fact_sources.CICADA
PREDICATE = "followed-on"
TRIGGER_REMATCH = "sleep/follows"
FILE_PREFIX = "follows-"
FILE_SUFFIX = ".json"
MAX_FIELD = 120
#: The forget's 409 while Sleep holds the pages (its tail may be reading the kept list).
FORGET_SLEEP_REFUSAL = ("Cicada is tidying up your memory right now — forget the accounts you follow again in a minute.")

#: How a followed account's page was matched — stamped on the profile link this module adds (``match``).
MATCH_KEY = "match"
MATCH_LINK = "link"
MATCH_NAME = "name"

#: The pages a followed account may attach to: a person, an organisation or a tool. A "creator" is one of the first two;
#: there is no type of its own. Never a project, a place, a concept, a media page (a media page is a saved thing, not the
#: account that made it) or the owner's own page.
ATTACH_TYPES = frozenset({"person", "company", "tool"})

#: A whole read counts toward "gone" only if it returned at least this share of what the last trusted whole read did.
TRUSTED_SHARE = 0.9
#: Two whole, trusted reads in a row that agree an account is missing mark it gone.
MISSES_TO_GONE = 2
#: A row gone this long is dropped from the file (it no longer counts toward anything).
GONE_KEEP_DAYS = 180
#: The file never holds more than this many rows, gone ones included, whatever a read says.
FILE_ROWS_FACTOR = 2
#: A pass whose last call is older than this is no longer one read.
PASS_WINDOW = timedelta(hours=3)
#: At most this many rows in one list answer (the route and the app).
MAX_ROWS = 200


@dataclass(frozen=True)
class Site:
    """Everything about one site's following list that is the site's own. UNMEASURED: the live look at X's Following page
    has not been made, so ``max_screens`` and the ``reserved`` words are estimates a first real read must confirm (the
    PR that adds a site records what the look found). ``max_rows`` is the plan's number (2026-11-24)."""
    key: str
    name: str
    #: The saved-list key that reads it (``saved_lists.PLATFORMS``).
    platform: str
    #: The hosts a profile link may be on, the first is the canonical one.
    hosts: tuple[str, ...]
    #: A profile link's one path segment must look like this, and not be one of the site's own words.
    handle: re.Pattern
    reserved: frozenset[str]
    #: Hard cap on the accounts one read keeps. A list past it is said to be "more than" this and marks nothing gone.
    max_rows: int = 2000
    #: How far down one read scrolls before it stops and says so. Unmeasured: rows per screen and whether the list ends.
    max_screens: int = 300
    #: Where the person's Following list is, from their profile link.
    path: str = "/following"

    @property
    def host(self) -> str:
        return self.hosts[0]

    @property
    def file(self) -> str:
        return f"{FILE_PREFIX}{self.key}{FILE_SUFFIX}"

    def following_url(self, profile: str | None) -> str:
        """The person's own Following list, from their recorded profile link."""
        base = str(profile or "").rstrip("/")
        return f"{base}{self.path}" if base else f"https://{self.host}/"


SITES: dict[str, Site] = {
    "x": Site(
        key="x", name="X", platform="x-following", hosts=("x.com", "twitter.com"),
        handle=re.compile(r"[A-Za-z0-9_]{1,15}"),
        reserved=frozenset({"i", "home", "search", "explore", "settings", "messages", "notifications", "intent", "share",
                            "hashtag", "login", "signup", "about", "compose", "tos", "privacy", "jobs", "following",
                            "followers", "verified_followers", "who_to_follow", "lists", "communities", "premium"}),
    ),
}


def site(key: str) -> Site:
    return SITES[key]


def site_of_platform(platform: str) -> Site:
    return next(s for s in SITES.values() if s.platform == platform)


def has_site(platform: str) -> bool:
    return any(s.platform == platform for s in SITES.values())


# --------------------------------------------------------------------------- one row


def _clean(value, limit: int = MAX_FIELD) -> str:
    return " ".join(str(value or "").split())[:limit]


def profile_of(s: Site, raw) -> tuple[str, str] | None:
    """``(handle, canonical link)`` for a link to one account's own profile on this site, else ``None``: a post, a list,
    a search, another host, a reserved path, or anything that is not one short handle. The handle may also be given bare
    (``@name``) and is then the profile on the canonical host."""
    text = str(raw or "").strip()
    if text and not text.startswith(("http://", "https://")):
        text = f"https://{s.host}/{text.lstrip('@')}" if "/" not in text else ""
    try:
        parsed = urlparse(text)
        host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("mobile.")
    except ValueError:
        return None
    if host not in s.hosts:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) != 1:
        return None
    handle = parts[0].lstrip("@")
    if not s.handle.fullmatch(handle) or handle.lower() in s.reserved:
        return None
    return handle, f"https://{s.host}/{handle}"


@dataclass
class Row:
    handle: str
    name: str
    url: str
    #: The first day a read showed the account, and the day the current stretch of following began (differs after an
    #: unfollow and a follow again).
    first_seen: str
    since: str
    last_seen: str
    gone_on: str | None = None
    #: Consecutive whole, trusted reads that did not show it.
    missed: int = 0

    @property
    def id(self) -> str:
        return hashlib.sha256(self.handle.lower().encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict:
        out = {"handle": self.handle, "name": self.name, "url": self.url, "first_seen": self.first_seen,
               "since": self.since, "last_seen": self.last_seen}
        if self.gone_on:
            out["gone_on"] = self.gone_on
        if self.missed:
            out["missed"] = self.missed
        return out

    @classmethod
    def from_dict(cls, raw) -> "Row | None":
        if not isinstance(raw, dict) or not raw.get("handle"):
            return None
        handle = _clean(raw.get("handle"), 40)
        day = _clean(raw.get("first_seen"), 10)
        try:
            missed = max(0, int(raw.get("missed") or 0))
        except (TypeError, ValueError):
            missed = 0   # a hand-edited file never fails a read
        return cls(handle, _clean(raw.get("name")), _clean(raw.get("url"), 200), day,
                   _clean(raw.get("since"), 10) or day, _clean(raw.get("last_seen"), 10) or day,
                   _clean(raw.get("gone_on"), 10) or None, missed)


# --------------------------------------------------------------------------- the directory (outside every bank)


def directory_path(bank: str, site_key: str) -> Path:
    return people_directory.path(bank, SITES[site_key].file)


def _load(bank: str, site_key: str) -> dict:
    return people_directory.load_json(bank, SITES[site_key].file)


def _rows(held: dict) -> list[Row]:
    raw = held.get("rows") if isinstance(held.get("rows"), list) else []
    return [r for r in (Row.from_dict(x) for x in raw) if r is not None]


@contextmanager
def _locked(bank: str, site_key: str) -> Iterator[None]:
    folder = people_directory.ensure(bank)
    with open(folder / f".follows-{site_key}.lock", "a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _save(bank: str, s: Site, held: dict, rows: list[Row]) -> None:
    payload = {k: v for k, v in held.items() if k not in ("rows", "v", "site")}
    payload.update(v=1, site=s.key, rows=[r.to_dict() for r in rows])
    people_directory.save_json(bank, s.file, payload)


def kept_sites(bank: str) -> list[str]:
    """The sites whose directory file exists for this bank."""
    return [k for k in SITES if directory_path(bank, k).exists()]


def live(rows: list[Row]) -> list[Row]:
    return [r for r in rows if not r.gone_on]


def status(bank: str, site_key: str = "x") -> dict:
    """What the Sources page counts: how many accounts are followed now and how many have gone — never a name."""
    held = _load(bank, site_key)
    rows = _rows(held)
    return {"following": len(live(rows)), "gone": len(rows) - len(live(rows)), "read_on": held.get("read_on"),
            "whole_on": held.get("whole_on")}


def following_count(bank: str, site_key: str = "x") -> int:
    return status(bank, site_key)["following"]


def forget(bank: str, site_key: str | None = None) -> int:
    """The person's "Forget": this bank's kept following list is deleted, and nothing reads it again. Pages that already
    gained a link or a claim keep them. Returns how many accounts were kept."""
    kept = 0
    for key in ([site_key] if site_key else list(SITES)):
        if key not in SITES:
            continue
        kept += len(_rows(_load(bank, key)))
        directory_path(bank, key).unlink(missing_ok=True)
        people_directory.path(bank, f".follows-{key}.lock").unlink(missing_ok=True)
    return kept


#: A bank's trash and rename take the whole people directory along (`people_directory`).
forget_bank = people_directory.forget
rename = people_directory.rename


# --------------------------------------------------------------------------- one read


@dataclass
class ReadReport:
    """What one agent read of the Following list did to the directory — counts only, never a name."""
    seen: int = 0          # distinct valid accounts this call showed that the pass had not met yet
    accounts: int = 0      # every row of this call that was an account's own profile link, new to the pass or not
    added: int = 0
    updated: int = 0       # a changed display name, or an account back after being gone
    unchanged: int = 0
    dropped: int = 0       # a row with no profile link of this site, or a reserved path
    full: int = 0          # accounts past the row cap, not kept
    over_cap: bool = False  # this pass reached the cap: it says "more than N" and marks nothing gone
    finished: bool = False  # the agent said it reached the end and the pass was whole (it could judge a "gone")
    trusted: bool = False   # the finished pass was large enough to count toward "gone"
    short: bool = False     # the finished pass was much smaller than the last trusted one
    first_whole: bool = False
    partial: bool = False   # a call said it continued a read this file never saw start
    marked_gone: int = 0
    passed: int = 0         # distinct accounts in the pass so far
    rows: list[Row] = field(default_factory=list)   # the rows this call named, as kept (never logged)


def _now_iso(now: datetime | None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _parse(value) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def record_read(bank: str, site_key: str, items: list, read_day: str, *, continues: bool = False,
                reached_end: bool = False, now: datetime | None = None) -> ReadReport:
    """The person's agent read the Following list (``cicada_record_saved_list``, platform ``x-following``): merge its rows
    into the directory by handle. One *pass* is one read, however many calls it takes (``continues`` ties them).

    A row seen is certainly followed, so it is current at once (``last_seen``, no longer gone). Whether an account the
    read did NOT show is gone is decided only when a call says ``reached_end`` AND the pass is whole: it began in this
    file, it never reached the row cap, and (when an earlier trusted whole read exists) it returned at least
    :data:`TRUSTED_SHARE` of that read's count. Then every live row it did not show gains a miss, and the second miss in a
    row marks it gone on ``read_day``. The first whole read has nothing to compare with and judges nobody. A new pass that
    starts while one is open drops the open one: a read that stopped is never finished later by another."""
    s = SITES[site_key]
    report = ReadReport()
    moment = _parse(_now_iso(now))
    with _locked(bank, site_key):
        held = _load(bank, site_key)
        rows = _rows(held)
        by_handle = {r.handle.lower(): r for r in rows}
        found = held.get("pass") if isinstance(held.get("pass"), dict) else None
        opened = _parse((found or {}).get("at"))
        carries = bool(continues and found is not None and opened is not None and moment - opened < PASS_WINDOW)
        if carries:
            seen = set(found.get("seen") or [])
            partial = bool(found.get("partial"))
            over = bool(found.get("over_cap"))
            calls = int(found.get("calls") or 0)
        else:
            seen, partial, over, calls = set(), bool(continues), False, 0
        report.partial = partial
        for raw in items:
            raw = raw if isinstance(raw, dict) else {}
            got = profile_of(s, raw.get("url") or raw.get("profile_url") or raw.get("handle"))
            if got is None:
                report.dropped += 1
                continue
            handle, url = got
            report.accounts += 1
            row_id = hashlib.sha256(handle.lower().encode("utf-8")).hexdigest()[:12]
            if row_id in seen:
                continue
            if len(seen) >= s.max_rows:
                over = True
                report.full += 1
                continue
            seen.add(row_id)
            name = _clean(raw.get("name") or raw.get("author"))
            old = by_handle.get(handle.lower())
            if old is None:
                if len(rows) >= s.max_rows * FILE_ROWS_FACTOR:
                    report.full += 1
                    continue
                old = Row(handle, name or handle, url, read_day, read_day, read_day)
                rows.append(old)
                by_handle[handle.lower()] = old
                report.added += 1
            else:
                moved = False
                if name and name != old.name:
                    old.name, moved = name, True
                if old.gone_on:
                    old.gone_on, old.since, moved = None, read_day, True
                old.url = url
                old.last_seen, old.missed = read_day, 0
                report.updated += int(moved)
                report.unchanged += int(not moved)
            report.rows.append(old)
        report.seen = len(report.rows)
        report.passed = len(seen)
        if not seen and not report.full:
            return report   # no account in this pass at all (a page that was not the list): nothing is kept, no pass opened
        # A call that shows only accounts the pass already met (the natural "scrolled on, nothing new, that was the end")
        # still counts: it can say the end, and the pass is judged on what it has.
        report.over_cap = over
        pass_state = {"at": _now_iso(now), "calls": calls + 1, "seen": sorted(seen), "partial": partial,
                      "over_cap": over}
        out = dict(held)
        if reached_end:
            _finish(held, out, rows, seen, report, partial=partial, over=over, read_day=read_day)
            out.pop("pass", None)
        else:
            out["pass"] = pass_state
        out["read_on"] = max(str(held.get("read_on") or ""), read_day)
        _save(bank, s, out, rows)
    return report


def _finish(held: dict, out: dict, rows: list[Row], seen: set[str], report: ReadReport, *, partial: bool, over: bool,
            read_day: str) -> None:
    """The agent said this pass reached the end of the list: judge "gone" only if the pass can be trusted. Mutates the rows
    and ``out`` (the file's own bookkeeping)."""
    report.finished = not partial and not over
    if not report.finished:
        return
    previous = held.get("whole_count")
    count = len(seen)
    if isinstance(previous, int) and previous > 0:
        report.trusted = count >= previous * TRUSTED_SHARE
        report.short = not report.trusted
    else:
        report.first_whole = True   # nothing to compare with: it judges nobody, and becomes the reference
    if report.trusted:
        for r in rows:
            if r.gone_on or hashlib.sha256(r.handle.lower().encode("utf-8")).hexdigest()[:12] in seen:
                continue
            r.missed += 1
            if r.missed >= MISSES_TO_GONE:
                r.gone_on = read_day
                report.marked_gone += 1
    if report.trusted or report.first_whole:
        out["whole_count"] = count
        out["whole_on"] = read_day
    cutoff = (date.fromisoformat(read_day) - timedelta(days=GONE_KEEP_DAYS)).isoformat() if _is_day(read_day) else ""
    if cutoff:
        rows[:] = [r for r in rows if not (r.gone_on and r.gone_on < cutoff)]


def _is_day(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


# --------------------------------------------------------------------------- matching a page


@dataclass
class _Index:
    names: dict[str, set[str]]            # folded label → page ids (person pages need a two-part label)
    handles: dict[str, set[str]]          # handle (lower) → pages that HOLD a link to it
    page_handles: dict[str, set[str]]     # page → every X handle it names, held or only proposed
    types: dict[str, str]
    owners: set[str]
    removed: dict[str, set[str]] = field(default_factory=dict)   # page → handles the person took off it


def _fold(text) -> str:
    return people_directory.fold(text)


def _owner_ids(memory_path: Path) -> set[str]:
    from api.services import owner_identity

    try:
        return {owner_identity.resolve_observer(memory_path)}
    except Exception:  # noqa: BLE001 - an unreadable owner.json names no page; the flag still applies
        return set()


def _holds(source: dict) -> bool:
    """Does this ``sources:`` entry count as the page holding the account's link? Not a link only Cicada proposed and the
    person has not taken: that is a guess, never a tie."""
    return not fact_sources.is_proposed(source)


def _page_handles(s: Site, fm: dict) -> tuple[set[str], set[str]]:
    """``(handles the page holds, handles it names at all)`` on this site, from its ``sources:``. A held link is one the
    person or anyone gave, but not a proposal still waiting for the person (:func:`_holds`)."""
    held: set[str] = set()
    named: set[str] = set()
    for source in fact_sources.as_sources(fm.get("sources")):
        got = profile_of(s, source.get("ref"))
        if got is None:
            continue
        named.add(got[0].lower())
        if _holds(source):
            held.add(got[0].lower())
    return held, named


def _removed_handles(s: Site, fm: dict) -> set[str]:
    removed = fm.get(fact_sources.REMOVED_KEY)
    out: set[str] = set()
    for row in removed if isinstance(removed, list) else []:
        got = profile_of(s, row.get("ref")) if isinstance(row, dict) else None
        if got is not None:
            out.add(got[0].lower())
    return out


def _labels_for(fm: dict, stem: str) -> list[str]:
    return people_directory.labels(fm, stem)


def _name_key_ok(kind: str, key: str) -> bool:
    """A folded label that may match a followed account by name: a person needs two parts (a first name alone never
    matches anybody), an organisation or a tool needs a real word."""
    if kind == "person":
        return " " in key
    return len(key) >= 3


def _index(s: Site, memory_path: Path) -> _Index:
    idx = _Index({}, {}, {}, {}, _owner_ids(memory_path))
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter or {}
        kind = str(fm.get("type") or "")
        if kind not in ATTACH_TYPES or fm.get("status") == "dropped" or fm.get("owner") is True or f.stem in idx.owners:
            continue
        _register(s, idx, f.stem, fm)
    return idx


def _register(s: Site, idx: _Index, entity_id: str, fm: dict) -> None:
    kind = str(fm.get("type") or "")
    idx.types[entity_id] = kind
    for label in _labels_for(fm, entity_id):
        if (key := _fold(label)) and _name_key_ok(kind, key):
            idx.names.setdefault(key, set()).add(entity_id)
    held, named = _page_handles(s, fm)
    for handle in held:
        idx.handles.setdefault(handle, set()).add(entity_id)
    if named:
        idx.page_handles[entity_id] = named
    if removed := _removed_handles(s, fm):
        idx.removed[entity_id] = removed


def _doubted(memory_path: Path) -> set[str]:
    """The folded names the bank holds a same-name doubt for (``same_name_doubts``): a name-only match on any is refused."""
    from api.services import same_name_doubts

    keys: set[str] = set()
    try:
        pages, pairs = same_name_doubts.flagged(memory_path)
        refs = set(pages) | {r for pair in pairs for r in pair} | {r for pair in same_name_doubts.pairs(memory_path)
                                                                    for r in pair}
    except Exception:  # noqa: BLE001 - an unreadable doubt file refuses nothing it cannot name
        return keys
    for ref in refs:
        keys.add(_fold(ref))
        path = Path(memory_path) / "entities" / f"{ref}.md"
        if path.exists():
            try:
                fm = markdown_parser.parse(path).frontmatter
            except Exception:  # noqa: BLE001
                continue
            keys |= {_fold(label) for label in _labels_for(fm, ref)}
    return keys - {""}


def _name_keys(row: Row) -> set[str]:
    key = _fold(row.name)
    if not key:
        return set()
    words = key.split()
    return {key} | ({" ".join(reversed(words))} if len(words) == 2 else set())


@dataclass
class Match:
    page: str | None = None
    how: str | None = None        # link | name
    refused: str | None = None    # doubt | ambiguous


def _resolve(idx: _Index, doubted: set[str], by_name: dict[str, list[Row]], row: Row) -> Match:
    """The one page this followed account is, by the rules in the module docstring. Pure."""
    handle = row.handle.lower()
    hits = {p for p in idx.handles.get(handle, set()) if handle not in idx.removed.get(p, set())}
    if hits:
        return Match(next(iter(hits)), MATCH_LINK) if len(hits) == 1 else Match(refused="ambiguous")
    keys = _name_keys(row)
    pages: set[str] = set()
    for key in keys:
        pages |= idx.names.get(key, set())
    # A page that already names a different profile of this site is someone else; one the person took this profile off
    # is not this account.
    pages = {p for p in pages if not (idx.page_handles.get(p) and handle not in idx.page_handles[p])
             and handle not in idx.removed.get(p, set())}
    if not pages:
        return Match()
    if keys & doubted:
        return Match(refused="doubt")
    if len(pages) != 1 or any(other.handle.lower() != handle for key in keys for other in by_name.get(key, [])):
        return Match(refused="ambiguous")
    return Match(next(iter(pages)), MATCH_NAME)


def _by_name(rows: list[Row]) -> dict[str, list[Row]]:
    out: dict[str, list[Row]] = {}
    for r in live(rows):
        for key in _name_keys(r):
            out.setdefault(key, []).append(r)
    return out


# --------------------------------------------------------------------------- writing one page


@dataclass
class Report:
    rows: int = 0
    matched: int = 0           # attached by a link the page held (claim)
    proposed: int = 0          # attached by name alone (a proposed link)
    ambiguous: int = 0
    doubted: int = 0
    sources_added: int = 0
    claims_written: int = 0
    claims_closed: int = 0
    removed_kept_out: int = 0
    paths: list[str] = field(default_factory=list)

    def counts(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k != "paths"}


def _claim_id(entity_id: str, site_key: str, since: str) -> str:
    digest = hashlib.sha256(f"{PREDICATE}\x00{site_key}\x00{since}".encode("utf-8")).hexdigest()[:8]
    return f"clm_{entity_id}_{PREDICATE}_{site_key}_{digest}"


def _mine(s: Site, claim: Claim) -> bool:
    return claim.predicate == PREDICATE and claim.observer == f"external:{s.key}" and claim.origin == f"follows/{s.key}"


def _apply_to(s: Site, fm: dict, body: str, entity_id: str, row: Row, match: Match, report: Report) -> tuple[dict, str, bool]:
    """One followed account onto a page held in memory: ``(frontmatter, body, changed)``. A link match (the page holds the
    link) writes the dated claim, or closes it when the account is gone; a name match adds a proposed link and no claim."""
    fm = dict(fm)
    today = date.today().isoformat()
    changed = False
    url = row.url
    if fact_sources.is_tombstoned(fm, url, s.key) or row.handle.lower() in _removed_handles(s, fm):
        report.removed_kept_out += 1
        return fm, body, False
    if match.how == MATCH_NAME:
        current = [x for x in (fm.get("sources") or []) if isinstance(x, dict)]
        listed = any((profile_of(s, x.get("ref")) or ("",))[0].lower() == row.handle.lower() for x in current)
        if not listed and not row.gone_on and len(current) < fact_sources.MAX_SOURCES:
            fm["sources"] = current + [{"ref": url, "kind": fact_sources.KIND_URL, "predicate": s.key, "added_by": AUTHOR,
                                        "added_at": today, MATCH_KEY: MATCH_NAME, fact_sources.PROPOSED: True}]
            report.sources_added += 1
            report.proposed += 1
            changed = True
        return fm, body, changed
    try:
        claims = parse_claims(body, strict=True)
    except MalformedClaimsBlockError:
        logger.warning("Follows: a page's claims block is malformed; its fact was left out")
        return fm, body, False
    mine = [c for c in claims if _mine(s, c)]
    current = [c for c in mine if not c.valid_to]
    if row.gone_on:
        for c in current:
            c.valid_to = row.gone_on
            report.claims_closed += 1
            changed = True
    elif not current:
        cid = _claim_id(entity_id, s.key, row.since)
        if not any(c.id == cid for c in claims):
            name = str(fm.get("name") or entity_id.replace("-", " ").title())
            claims.append(Claim(
                id=cid, text=f"{name} is followed by the person on {s.name} (first seen in their following list on {row.since})",
                subject=entity_id, predicate=PREDICATE, object=s.name, object_kind="literal",
                observer=f"external:{s.key}", context="general", epistemic="explicit", source_trust="external",
                confidence=0.9, valid_from=row.since, recorded_at=today, authored_by=AUTHOR, origin=f"follows/{s.key}",
                evidence=[evidence.reasoning()]))
            report.claims_written += 1
            changed = True
    if changed:
        body = write_claims(body, claims)
        report.matched += 1
    return fm, body, changed


@page_lock.locked
def _apply_page(memory_path: Path, s: Site, entity_id: str, row: Row, match: Match, report: Report) -> bool:
    path = Path(memory_path) / "entities" / f"{entity_id}.md"
    if not path.exists():
        return False
    parsed = markdown_parser.parse(path)
    fm = parsed.frontmatter
    if fm.get("type") not in ATTACH_TYPES or fm.get("status") == "dropped" or fm.get("owner") is True:
        return False
    new_fm, body, changed = _apply_to(s, fm, parsed.body, entity_id, row, match, report)
    if changed:
        markdown_parser.write(path, new_fm, body)
    return changed


def rematch(memory_path: Path, *, bank: str | None = None, skip: frozenset[str] = frozenset()) -> Report:
    """Sleep's tail: every kept following list against tonight's pages, so a page that exists (or was born since) gains the
    account's link or dated fact, and a page whose account has gone has the fact closed. Writes nothing when nothing is
    kept or nothing new matches; never makes a page; never counts as a mention."""
    from api.services import demo_guard

    memory_path = Path(memory_path)
    report = Report()
    if demo_guard.is_demo(memory_path):
        return report   # a demo bank never takes in the person's real accounts (R-CS16)
    bank = bank or memory_path.name
    for key, s in SITES.items():
        rows = _rows(_load(bank, key))
        if not rows:
            continue
        report.rows += len(rows)
        idx = _index(s, memory_path)
        doubted, by_name = _doubted(memory_path), _by_name(rows)
        for row in sorted(rows, key=lambda r: r.handle.lower()):
            match = _resolve(idx, doubted, by_name, row)
            if match.refused == "doubt":
                report.doubted += 1
            elif match.refused:
                report.ambiguous += 1
            if match.page is None or f"entities/{match.page}.md" in skip:
                continue
            if row.gone_on and match.how != MATCH_LINK:
                continue
            if _apply_page(memory_path, s, match.page, row, match, report):
                path = f"entities/{match.page}.md"
                if path not in report.paths:
                    report.paths.append(path)
    if report.paths:
        bank_index.invalidate(memory_path)
    return report


def commit_message(report: Report, today: date, *, trigger: str = TRIGGER_REMATCH) -> str:
    from api.services import git_service

    return git_service.build_commit_message(
        f"Followed accounts {today.isoformat()}",
        [f"{p}: updated (source: n/a, trigger: {trigger})" for p in report.paths], authors=[AUTHOR])


def restore(memory_path: Path, report: Report) -> None:
    """Undo a tail run whose commit failed, so no later ``git add -A`` sweeps it under another author."""
    from api.services import git_service

    memory_path = Path(memory_path)
    if report.paths and (memory_path / ".git").exists():
        try:
            git_service.run_git_write_sync(memory_path, "checkout", "--", *report.paths)
        except git_service.GitError as exc:
            logger.warning(f"Follows rematch restore failed: {type(exc).__name__}")
    bank_index.invalidate(memory_path)


def match_counts(memory_path: Path, site_key: str, rows: list[Row]) -> dict[str, int]:
    """What these accounts would land on in this bank — counts only, nothing written, never a name: ``confident`` (a page
    that holds the link), ``proposed`` (a name alone), ``refused`` (a doubt, or two of one name)."""
    from api.services import demo_guard

    out = {"confident": 0, "proposed": 0, "refused": 0}
    if not rows or demo_guard.is_demo(Path(memory_path)):
        return out
    s = SITES[site_key]
    idx, doubted, by_name = _index(s, Path(memory_path)), _doubted(Path(memory_path)), _by_name(rows)
    for row in rows:
        match = _resolve(idx, doubted, by_name, row)
        if match.refused:
            out["refused"] += 1
        elif match.how == MATCH_LINK:
            out["confident"] += 1
        elif match.how == MATCH_NAME:
            out["proposed"] += 1
    return out


# --------------------------------------------------------------------------- a page's birth


class Attacher:
    """The kept followed accounts attach to a page being **born**, in the write that births it — never the reason a page is
    made. One instance serves one run (Sleep's Stage 5 create loop) or one write (an agent's first claim about a new
    page): the directory and the bank's page index are read once, on the first page of an attachable type, and each page
    born since is added to that index, so two pages of one name born in one run see each other and refuse. Nothing is read
    when the bank is a demo bank or no following list is kept. Never a page, a model, or the network."""

    def __init__(self, memory_path: Path, *, bank: str | None = None) -> None:
        self.memory_path = Path(memory_path)
        self.bank = bank or self.memory_path.name
        self.report = Report()
        self._ready: bool | None = None
        self._loaded: list[tuple[Site, list[Row], dict[str, list[Row]], dict[str, Row], _Index]] = []
        self._doubted: set[str] = set()

    def _load(self) -> bool:
        if self._ready is not None:
            return self._ready
        self._ready = False
        from api.services import demo_guard

        if demo_guard.is_demo(self.memory_path):
            return False
        for key in kept_sites(self.bank):
            s = SITES[key]
            rows = _rows(_load(self.bank, key))
            if rows:
                self._loaded.append((s, rows, _by_name(rows), {r.handle.lower(): r for r in rows}, _index(s, self.memory_path)))
        if not self._loaded:
            return False
        self._doubted = _doubted(self.memory_path)
        self._ready = True
        return True

    def attach(self, fm: dict, body: str, entity_id: str) -> tuple[dict, str]:
        """``(frontmatter, body)`` of the page being born, with the one account that matches it written on — a proposed link
        for a name alone, the dated claim when the page already holds the account's link. Unchanged for anyone else, and
        for a page that is the owner's, dropped, or not a person, organisation or tool."""
        if fm.get("type") not in ATTACH_TYPES or fm.get("owner") is True or fm.get("status") == "dropped":
            return fm, body
        if not self._load():
            return fm, body
        for s, _rows_, by_name, by_handle, idx in self._loaded:
            if entity_id in idx.owners:
                continue
            _register(s, idx, entity_id, fm)
            found: dict[str, Row] = {}
            for label in _labels_for(fm, entity_id):
                for row in by_name.get(_fold(label), []):
                    found[row.handle.lower()] = row
            for handle in idx.page_handles.get(entity_id, set()):
                if handle in by_handle:
                    found[handle] = by_handle[handle]
            landing: list[tuple[Row, Match]] = []
            for row in found.values():
                match = _resolve(idx, self._doubted, by_name, row)
                if match.refused == "doubt":
                    self.report.doubted += 1
                elif match.refused:
                    self.report.ambiguous += 1
                elif match.page == entity_id:
                    landing.append((row, match))
            if len(landing) != 1:
                self.report.ambiguous += len(landing)
                continue
            row, match = landing[0]
            fm, body, changed = _apply_to(s, fm, body, entity_id, row, match, self.report)
            if changed:
                _register(s, idx, entity_id, fm)
                path = f"entities/{entity_id}.md"
                if path not in self.report.paths:
                    self.report.paths.append(path)
        return fm, body


# --------------------------------------------------------------------------- the list (the person's own view)


def list_rows(memory_path: Path, bank: str, site_key: str = "x", *, query: str = "", offset: int = 0, limit: int = 50,
              gone: bool = False) -> dict:
    """The accounts the person follows, newest first, each with the one page it is when there is exactly one (by the same
    rules as :func:`rematch`) — read from the directory at this moment and written nowhere. ``query`` is words of a name or
    a handle (folded like search). ``gone`` lists the accounts no longer followed instead."""
    s = SITES[site_key]
    held = _load(bank, site_key)
    every = _rows(held)
    rows = [r for r in every if bool(r.gone_on) == gone]
    words = _fold(query).split()
    if words:
        rows = [r for r in rows if all(w in _fold(f"{r.name} {r.handle}") for w in words)]
    rows.sort(key=lambda r: r.name.lower())
    rows.sort(key=lambda r: r.since, reverse=True)
    total = len(rows)
    limit = max(1, min(int(limit), MAX_ROWS))
    offset = max(0, int(offset))
    page_rows = rows[offset:offset + limit]
    out: list[dict] = []
    if page_rows:
        from api.services import demo_guard

        demo = demo_guard.is_demo(Path(memory_path))
        idx = None if demo else _index(s, Path(memory_path))
        doubted = set() if demo else _doubted(Path(memory_path))
        by_name = _by_name(every)
        for r in page_rows:
            match = _resolve(idx, doubted, by_name, r) if idx else Match()
            out.append({"id": r.id, "name": r.name, "handle": r.handle, "url": r.url, "day": r.since,
                        "page": match.page, "proposed": bool(match.page and match.how == MATCH_NAME),
                        "goneOn": r.gone_on})
    return {"rows": out, "total": total, "offset": offset, "next": offset + limit if offset + limit < total else None,
            "kept": len(live(every)), "gone": len(every) - len(live(every)), "readOn": held.get("read_on"),
            "wholeOn": held.get("whole_on"), "site": s.key, "siteName": s.name}
