"""LinkedIn connections — a people directory that enriches who is already in memory (owner 2026-10-16, G154's pattern).

The person's LinkedIn data export carries ``Connections.csv``: one row per person they are connected to (First Name,
Last Name, URL, Email Address — usually blank —, Company, Position, Connected On, after a few lines of notes). It holds
other people, so the save-list importer refuses it by name (G71); it comes in only through its own door —
``POST /sources/linkedin-connections`` (the app's LinkedIn tile → Connections, the person's drop or pick).

**The promotion rail decides the shape, as it did for Contacts (G154).** Hundreds of dormant connections would flood
the graph, and a page needs conversations. So:

- a connection matches **exactly one existing ``person`` page** — by its profile link when a page already lists that
  link as a source, else by its folded full name (either order) or an alias; never the owner's page, never a page
  that already names a *different* LinkedIn profile, and never when two connections land on one page or one
  connection on two pages. **No page is ever created and nothing is said about an unmatched name.**
- on a match: the profile link becomes a G61 source ``{ref, kind: url, predicate: linkedin, added_by: cicada}`` —
  where to look the person up, not a copy; a removal the person made (``sources_removed``) is respected: the link is
  never re-added and that connection writes nothing more on that page (the person said it is not this person). Company and position become claims ``works-at`` / ``role`` observed ``external:linkedin`` (``source_trust:
  external``, ``authored_by: cicada``) dated as of the export, and ``connected-on`` records the day the two connected.
  None of it is the person's own words.
- **newest wins** (ruling 26's spirit): Cicada's own LinkedIn claims for a predicate are one dated line — a newer
  export (or a profile the person's agent read, :func:`apply_profile`) with a different value closes the current one
  and supersedes it; an older export changes nothing; the same value again writes nothing, so a re-import is a no-op.
  Any other claim on the page — the person's, Sleep's, an agent's — is never touched.
- the email column is never read into anything: not a page, not the directory, not a log (G154's rule for numbers
  and addresses).

**The directory** — every connection's names, link, company, position and day connected, outside every bank at
``$CICADA_HOME/people/<bank>/linkedin-connections.json`` (0600) — is what lets a person mentioned *later* be matched
then: Sleep's engine-free tail runs :func:`rematch` against it, so a page Sleep promotes tonight gains its LinkedIn
link and facts in the same run's own ``cicada`` commit. An older export never replaces a newer directory.

**Two ways in, one directory (G245, ruling 78 (c), 2026-11-24).** The export file above, and now the person's own agent:
it opens the connections page, sorted by recently added, in their own signed-in browser and records ``{name,
profile_url, headline, connected}`` per row through ``cicada_record_saved_list`` (platform ``linkedin-connections``,
off until the person turns it on; the connections page only, never a profile or the contact-info overlay, and no email
field exists). :func:`record_read` **merges** into this directory by profile link: it never deletes a row, never moves
``exported_on`` backwards and keeps the finer day (:func:`parse_connected`: a page that says "3 weeks ago" is stored as a
day and a precision, ``day`` · ``week`` · ``month``, computed from the day it was read — nothing relative is stored).
:func:`list_rows` is the list the app draws (``GET /sources/linkedin-connections/list``) and :func:`range_rows` the one
read door for the person's agents; neither writes a name anywhere, and neither is on a remote door.

**The person gets the page, never the connection** (owner 2026-11-24). A connection never makes a page. A person's page
is born by the rules that already exist, and the kept connection that matches it attaches in the write that births it
(:class:`Attacher`: Sleep's Stage 5 create and an agent's first claim about a new person), not a night later. A name-only
match is refused when the bank holds a same-name doubt for that name, when two connections or two pages share it, or when
the page names a different profile (:func:`_hits`); a refusal writes nothing and is counted, never named.

No model runs and nothing is fetched: the profile link is stored, never opened. The person's agent may open it later
in the person's own browser, when the person asks about that one person — the ``linkedin-people`` skill and
``cicada_record_profile``.

**The photo (owner 2026-10-17).** The profile link this import adds records how the page was matched
(``match``: :data:`MATCH_LINK` — the person or an identified agent already listed that link as their account; :data:`MATCH_NAME` — the
connection's full name is the page's own name; :data:`MATCH_ALIAS` — it is only one of the page's aliases). A
confident match (:data:`CONFIDENT_MATCHES`: link or name) is the person's connection, so its link drives the
profile-photo rung right away (``person_photo.is_own_account``), behind that rung's own off-by-default proxy gate;
an alias-only match is a guess the person has not confirmed, and its link draws no photo until they take the source.
An ambiguous match writes nothing at all, as before. A link written before the field existed gets it at the next
import or Sleep's rematch.
"""
from __future__ import annotations

import csv
import fcntl
import hashlib
import io
import json
import os
import re
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

from loguru import logger

from api.services import (bank_index, episode_scrub, evidence, fact_sources, markdown_parser, page_lock,
                          people_directory)
from api.services.claims import Claim, MalformedClaimsBlockError, parse_claims, write_claims

CHANNEL_ID = "linkedin-connections"
OBSERVER = "external:linkedin"
SOURCE_PREDICATE = "linkedin"
#: The claim origins this module owns (newest wins across both): the export, and a profile the person's agent read.
ORIGIN_EXPORT = "linkedin/connections"
ORIGIN_PROFILE = "linkedin/profile"
ORIGINS = frozenset({ORIGIN_EXPORT, ORIGIN_PROFILE})
AUTHOR = fact_sources.CICADA
WORKS_AT = "works-at"
ROLE = "role"
CONNECTED_ON = "connected-on"
#: The fields a connection can carry onto a page, in write order.
FACT_PREDICATES = (WORKS_AT, ROLE, CONNECTED_ON)
TRIGGER_IMPORT = "capture/linkedin-connections"
TRIGGER_REMATCH = "sleep/linkedin-connections"
DIRECTORY_FILE = "linkedin-connections.json"
MAX_BYTES = 32 * 1024 * 1024
MAX_CONNECTIONS = 30_000
MAX_FIELD = 160
#: How a connection's page was matched — stamped on the profile link this module adds (``match``).
MATCH_KEY = "match"
MATCH_LINK = "link"
MATCH_NAME = "name"
MATCH_ALIAS = "alias"
#: The matches that are the person's connection beyond doubt: their link may draw the page's photo before they take it.
CONFIDENT_MATCHES = frozenset({MATCH_LINK, MATCH_NAME})
SLEEP_REFUSAL = "Cicada is tidying up your memory right now — add your LinkedIn connections again in a minute."
#: The forget's 409 while Sleep holds the pages (its tail may be reading the kept export).
FORGET_SLEEP_REFUSAL = ("Cicada is tidying up your memory right now — forget your kept connections again in a "
                        "minute.")
_DATE_FORMATS = ("%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%d-%b-%y", "%d-%b-%Y", "%m/%d/%y", "%m/%d/%Y", "%B %d, %Y",
                 "%b %d, %Y")
_SLUG_RE = re.compile(r"[^/?#\s]{1,100}")


class PayloadError(ValueError):
    """A file the backend cannot read as LinkedIn connections — answered 422, nothing written."""


#: How exactly a connection's day is known: the page or file gave the day (``day``), or only "3 weeks ago" (``week``) or
#: "2 months ago" (``month``), which :func:`parse_connected` turns into a day computed from the read day.
PRECISIONS = ("day", "week", "month")
_FINENESS = {"day": 3, "week": 2, "month": 1}


@dataclass
class Connection:
    first: str
    last: str
    url: str | None = None
    company: str = ""
    position: str = ""
    connected_on: str | None = None
    #: The line under the person's name on the connections page, as the page showed it (free words, never split into a
    #: company and a position: "Founder | Building X" is not "Founder at X").
    headline: str = ""
    precision: str | None = None
    #: ``read`` for a row only the person's agent has read (a later export never drops it), else ``export``.
    src: str = "export"
    #: Which of several rows with no profile link and one name this is (0 for the first, so a lone row's id is what it
    #: always was); set by :func:`_number`. Two such rows are two connections until something says otherwise.
    dup: int = 0

    @property
    def name(self) -> str:
        return " ".join(p for p in (self.first, self.last) if p)

    @property
    def id(self) -> str:
        key = self.url or f"name:{self.name.lower()}" + (f"#{self.dup}" if self.dup else "")
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict:
        out = {"id": self.id, "first": self.first, "last": self.last}
        for key in ("url", "company", "position", "connected_on", "headline"):
            if getattr(self, key):
                out[key] = getattr(self, key)
        if self.connected_on:
            out["precision"] = self.precision if self.precision in PRECISIONS else "day"
        if self.src == "read":
            out["src"] = "read"
        return out

    @classmethod
    def from_dict(cls, raw: dict) -> "Connection | None":
        if not isinstance(raw, dict):
            return None
        first, last = _clean(raw.get("first")), _clean(raw.get("last"))
        if not (first or last):
            return None
        day = _day(raw.get("connected_on"))
        precision = raw.get("precision") if raw.get("precision") in PRECISIONS else ("day" if day else None)
        return cls(first, last, profile_url(raw.get("url")), _clean(raw.get("company")), _clean(raw.get("position")),
                   day, _clean(raw.get("headline")), precision, "read" if raw.get("src") == "read" else "export")


@dataclass
class Parsed:
    connections: list[Connection]
    exported_on: str | None = None
    skipped: int = 0


@dataclass
class Report:
    connections: int = 0
    matched: int = 0
    ambiguous: int = 0
    unmatched: int = 0
    sources_added: int = 0
    claims_written: int = 0
    claims_closed: int = 0
    older: int = 0
    removed_kept_out: int = 0
    #: A name-only match refused because the bank holds a same-name doubt for that name — counted, never named.
    doubted: int = 0
    exported_on: str = ""
    paths: list[str] = field(default_factory=list)

    def counts(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k != "paths"}


# --------------------------------------------------------------------------- reading the file


def _clean(value) -> str:
    """One scrubbed line, capped — a name, a company or a title as it may be stored."""
    text = " ".join(str(value or "").split())[:MAX_FIELD].strip()
    if not text:
        return ""
    cleaned, n = episode_scrub.scrub(text)
    episode_scrub.record(CHANNEL_ID, n)
    return cleaned.strip()


def _day(value) -> str | None:
    text = " ".join(str(value or "").split())
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


_ISO_DAY = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_WORD_DAY = re.compile(r"\b([A-Za-z]{3,9}\.? \d{1,2}, \d{4}|\d{1,2} [A-Za-z]{3,9}\.? \d{4})\b")
_AGO = re.compile(r"\b(?:(\d{1,3})|an?|one)\s*(minutes?|mins?|hours?|hrs?|days?|weeks?|wks?|months?|mos?|years?|yrs?)\b",
                  re.IGNORECASE)
#: Days a unit stands for, and how exactly "N <unit> ago" says the day (matched by the unit's first letters). A year is
#: stored as twelve months to the month: a page that says "2 years ago" knows the day no better than that.
_UNITS = (("min", 0, "day"), ("ho", 0, "day"), ("hr", 0, "day"), ("da", 1, "day"), ("we", 7, "week"),
          ("wk", 7, "week"), ("mo", 30, "month"), ("ye", 365, "month"), ("yr", 365, "month"))


def parse_connected(value, read_day: str) -> tuple[str | None, str | None]:
    """``(day, precision)`` for the date a connections page showed: an ISO day or a date the export writes (``day``), else
    the page's own words — "Connected 3 weeks ago", "yesterday", "2 months ago" — counted back from ``read_day`` (the day
    the page was read) and stored as that day with the precision the words had (``day`` · ``week`` · ``month``): nothing
    relative is ever stored. ``(None, None)`` for words it does not know (another language) or a day in the future or
    before 2003."""
    text = " ".join(str(value or "").split())
    if not text:
        return None, None
    precision = "day"
    day = None
    for pattern in (_ISO_DAY, _WORD_DAY):
        if (found := pattern.search(text)) is not None and (day := _day(found.group(1))) is not None:
            break
    if day is None:
        day = _day(text)
    if day is None:
        lowered, base = text.lower(), date.fromisoformat(read_day)
        if re.search(r"\b(today|just now)\b", lowered):
            day = base.isoformat()
        elif re.search(r"\byesterday\b", lowered):
            day = (base - timedelta(days=1)).isoformat()
        elif (ago := _AGO.search(text)) is not None:
            unit = ago.group(2).lower()
            span, precision = next((d, p) for prefix, d, p in _UNITS if unit.startswith(prefix))
            try:
                day = (base - timedelta(days=(int(ago.group(1)) if ago.group(1) else 1) * span)).isoformat()
            except OverflowError:
                return None, None
    return (day, precision) if day and "2003-01-01" <= day <= read_day else (None, None)


def profile_url(raw) -> str | None:
    """A LinkedIn member profile as one canonical link (``https://www.linkedin.com/in/<slug>``), or None for anything
    else — a company page, a post, another host, a non-link."""
    text = str(raw or "").strip()
    if not text.startswith(("http://", "https://")):
        return None
    try:
        parsed = urlparse(text)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    if not (host == "linkedin.com" or host.endswith(".linkedin.com")):
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) != 2 or parts[0].lower() != "in" or not _SLUG_RE.fullmatch(parts[1]):
        return None
    return f"https://www.linkedin.com/in/{parts[1]}"


def _slug(url) -> str | None:
    found = profile_url(url)
    return found.rsplit("/", 1)[1].lower() if found else None


def _last_name(raw) -> str:
    """LinkedIn's Last Name field often carries credentials after a comma (``Example, PhD``): the name is before it."""
    return _clean(str(raw or "").split(",", 1)[0])


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _from_zip(data: bytes) -> tuple[bytes, str | None]:
    """The archive's own ``Connections.csv`` (the shallowest) and the day the export wrote it."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise PayloadError("That archive could not be opened.") from exc
    with archive:
        members = [m for m in archive.infolist() if not m.is_dir() and Path(m.filename).name.lower() == "connections.csv"]
        if not members:
            raise PayloadError("That archive has no Connections.csv — request LinkedIn's export with Connections ticked.")
        member = min(members, key=lambda m: m.filename.count("/"))
        if member.file_size > MAX_BYTES:
            raise PayloadError("Connections.csv is too large to read.")
        stamped = None
        try:
            stamped = date(*member.date_time[:3]).isoformat()
        except ValueError:
            stamped = None
        return archive.read(member), stamped


def parse(data: bytes, filename: str = "") -> Parsed:
    """``Connections.csv``, or a LinkedIn export ``.zip`` carrying it. The notes LinkedIn writes above the header are
    skipped; a row with neither name is skipped; the Email Address column is never read."""
    if len(data) > MAX_BYTES:
        raise PayloadError("That file is too large to be a LinkedIn connections export.")
    exported_on = None
    if data[:2] == b"PK":
        data, exported_on = _from_zip(data)
    rows = list(csv.reader(io.StringIO(_decode(data))))
    header_at = None
    for i, row in enumerate(rows[:50]):
        cells = [c.strip().lower() for c in row]
        if "first name" in cells and "last name" in cells:
            header_at = i
            break
    if header_at is None:
        raise PayloadError("This is not LinkedIn's Connections.csv: it has no First Name and Last Name columns.")
    header = [c.strip().lower() for c in rows[header_at]]

    def col(name: str) -> int | None:
        return header.index(name) if name in header else None

    first_i, last_i, url_i = col("first name"), col("last name"), col("url")
    company_i, position_i, on_i = col("company"), col("position"), col("connected on")
    out: list[Connection] = []
    skipped = 0

    def cell(row: list[str], i: int | None) -> str:
        return row[i] if i is not None and i < len(row) else ""

    for row in rows[header_at + 1:]:
        if not any(c.strip() for c in row):
            continue
        first, last = _clean(cell(row, first_i)), _last_name(cell(row, last_i))
        if not (first or last):
            skipped += 1
            continue
        out.append(Connection(first, last, profile_url(cell(row, url_i)), _clean(cell(row, company_i)),
                              _clean(cell(row, position_i)), _day(cell(row, on_i))))
        if len(out) > MAX_CONNECTIONS:
            raise PayloadError(f"At most {MAX_CONNECTIONS:,} connections in one export.")
    _number(out)
    return Parsed(out, exported_on, skipped)


def as_of(exported_on: str | None, parsed: Parsed, today: date | None = None) -> str:
    """The day the export's facts are true as of: what the caller says (the file's own date, read by the app), else
    the archive member's date, else today — never a future day."""
    today = today or date.today()
    for candidate in (exported_on, parsed.exported_on):
        day = _day(candidate) if candidate else None
        if day and "2003-01-01" <= day <= today.isoformat():
            return day
    return today.isoformat()


# --------------------------------------------------------------------------- matching


@dataclass
class _Index:
    names: dict[str, set[str]]
    slugs: dict[str, set[str]]          # a profile slug a page already lists → that page
    page_slugs: dict[str, set[str]]     # page → every LinkedIn slug its sources name
    companies: dict[str, set[str]]      # folded company name → company page ids
    page_names: dict[str, str] = field(default_factory=dict)          # page → its own folded name
    page_aliases: dict[str, set[str]] = field(default_factory=dict)   # page → its folded aliases
    listed_by_others: dict[str, set[str]] = field(default_factory=dict)  # page → slugs a non-Cicada source lists


_fold = people_directory.fold


def _owner_ids(memory_path: Path) -> set[str]:
    """The owner's page by id as well as by its ``owner: true`` flag — a bank whose owner page predates the flag is
    still never matched as one of the person's connections."""
    from api.services import owner_identity

    try:
        return {owner_identity.resolve_observer(memory_path)}
    except Exception:  # noqa: BLE001 - an unreadable owner.json names no page; the flag still applies
        return set()


def _removed_slug(fm: dict, url: str | None) -> bool:
    """Did the person (or anyone) take this LinkedIn profile off the page — in any spelling of its link, under any
    predicate? A removal is respected by every automatic writer (G61), so the import never re-touches that page."""
    slug = _slug(url)
    removed = fm.get(fact_sources.REMOVED_KEY)
    if not slug or not isinstance(removed, list):
        return False
    return any(isinstance(r, dict) and _slug(r.get("ref")) == slug for r in removed)


def _index(memory_path: Path) -> _Index:
    idx = _Index({}, {}, {}, {})
    owners = _owner_ids(memory_path)
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter or {}
        if fm.get("status") == "dropped":
            continue
        kind = str(fm.get("type") or "")
        labels = people_directory.labels(fm, f.stem)
        if kind == "company":
            for label in labels:
                if key := _fold(label):
                    idx.companies.setdefault(key, set()).add(f.stem)
            continue
        if kind != "person" or fm.get("owner") is True or f.stem in owners:
            continue
        for label in labels:
            if key := _fold(label):
                idx.names.setdefault(key, set()).add(f.stem)
        idx.page_names[f.stem] = _fold(labels[0])
        idx.page_aliases[f.stem] = {k for a in labels[1:] if (k := _fold(a))}
        for source in fact_sources.as_sources(fm.get("sources")):
            if slug := _slug(source.get("ref")):
                idx.slugs.setdefault(slug, set()).add(f.stem)
                idx.page_slugs.setdefault(f.stem, set()).add(slug)
                if _vouched(source):
                    idx.listed_by_others.setdefault(f.stem, set()).add(slug)
    return idx


def _vouched(source: dict) -> bool:
    """Did somebody other than Cicada give this link as the person's own account — the person (added or took it) or an
    identified agent, with no fact attached or a profile predicate? The photo rung's own test
    (``person_photo.is_own_account``), so a link a model attached from a claim's cited words or an unidentified
    proposal can never turn an alias-only match into a confident one. Cicada's own link is never its own voucher."""
    from api.services import person_photo

    if str(source.get("added_by") or fact_sources.USER).strip().lower() == AUTHOR:
        return False
    return person_photo.is_own_account(source)


def _name_keys(c: Connection) -> set[str]:
    return people_directory.name_keys(c.first, c.last)


def from_connections(source: dict) -> bool:
    """The link the person's own connections put on a page they matched confidently: their data, so it counts as given
    (a photo, and where to look this person up), never an alias-only guess. It is no tracked source: nothing re-reads it on
    a schedule (ruling 54a, owner 2026-11-04). A visit stays on the person's ask, ≤ 10 a day (``cicada_record_profile``)."""
    return (str(source.get("added_by") or "").strip().lower() == AUTHOR
            and str(source.get("predicate") or "").strip().lower() == SOURCE_PREDICATE
            and source.get(MATCH_KEY) in CONFIDENT_MATCHES)


def alias_only(memory_path: Path, entity_id: str, url: str) -> bool:
    """Is this page's link for ``url`` only an alias-only guess from the connections, not yet taken by the person?"""
    path = Path(memory_path) / "entities" / f"{entity_id}.md"
    if not path.exists():
        return False
    for source in fact_sources.as_sources(markdown_parser.parse(path).frontmatter.get("sources")):
        if profile_url(source.get("ref")) == profile_url(url) and not fact_sources.trusted(source) \
                and str(source.get("added_by") or "").strip().lower() == AUTHOR and source.get(MATCH_KEY) == MATCH_ALIAS:
            return True
    return False


def basis(idx: _Index, entity_id: str, c: Connection) -> str | None:
    """How ``c`` is this page's connection: the person or an identified agent already listed its link as their account (``link``, :func:`_vouched`), its full name
    is the page's own name (``name``), or only an alias (``alias``). ``None`` when only Cicada's own earlier link ties
    them (the page was renamed since) — the link keeps whatever it recorded then."""
    slug = _slug(c.url)
    if slug and slug in idx.listed_by_others.get(entity_id, set()):
        return MATCH_LINK
    keys = _name_keys(c)
    if idx.page_names.get(entity_id) in keys:
        return MATCH_NAME
    if keys & idx.page_aliases.get(entity_id, set()):
        return MATCH_ALIAS
    return None


def _doubted(memory_path: Path, idx: _Index) -> set[str]:
    """The folded names the bank holds a same-name doubt for (`same_name_doubts`: two people of one name, held apart or
    flagged for a look): every ref in a doubted pair or a flagged pair is a page id (its names count) or a held line's own
    name. Read once per match; a name-only match on any of them is refused, never guessed."""
    from api.services import same_name_doubts

    try:
        pages, pairs = same_name_doubts.flagged(memory_path)
        refs = set(pages) | {r for pair in pairs for r in pair} | {r for pair in same_name_doubts.pairs(memory_path)
                                                                    for r in pair}
    except Exception:  # noqa: BLE001 - an unreadable doubt file refuses nothing it cannot name
        return set()
    keys: set[str] = set()
    for ref in refs:
        keys.add(_fold(ref))
        if ref in idx.page_names:
            keys.add(idx.page_names[ref])
            keys |= idx.page_aliases.get(ref, set())
    return keys - {""}


def _hits(idx: _Index, c: Connection, doubted: set[str] = frozenset()) -> tuple[set[str], bool]:
    """``(the person pages this connection lands on, refused)``. A page that already lists the connection's profile link
    is its page; otherwise the folded full name (either order) or an alias names it — and then a page that already names
    a *different* LinkedIn profile is someone else of the same name, and a name the bank holds a same-name doubt for
    matches nobody (``refused``: counted, writes nothing)."""
    slug = _slug(c.url)
    hits = set(idx.slugs.get(slug, set())) if slug else set()
    if hits:
        return hits, False
    keys = _name_keys(c)
    for key in keys:
        hits |= idx.names.get(key, set())
    hits = {h for h in hits if not (slug and idx.page_slugs.get(h) and slug not in idx.page_slugs[h])}
    if hits and keys & doubted:
        return set(), True
    return hits, False


def _match(memory_path: Path, connections: list[Connection]) -> tuple[dict[str, Connection], int, int, int]:
    idx = _index(memory_path)
    doubted = _doubted(memory_path, idx)
    claims: dict[str, list[Connection]] = {}
    ambiguous = unmatched = refused = 0
    for c in connections:
        hits, doubt = _hits(idx, c, doubted)
        if doubt:
            refused += 1
        elif len(hits) == 1:
            claims.setdefault(next(iter(hits)), []).append(c)
        elif hits:
            ambiguous += 1
        else:
            unmatched += 1
    matched = {eid: found[0] for eid, found in claims.items() if len(found) == 1}
    ambiguous += sum(len(found) for found in claims.values() if len(found) > 1)
    return matched, ambiguous, unmatched, refused


def match_counts(memory_path: Path, connections: list[Connection]) -> dict[str, int]:
    """What these connections would land on in this bank — counts only, nothing written, never a name: ``people`` (exactly
    one person page each), ``ambiguous`` (two people or two connections of one name), ``doubted`` (refused for a same-name
    doubt)."""
    from api.services import demo_guard

    if not connections or demo_guard.is_demo(Path(memory_path)):
        return {"people": 0, "ambiguous": 0, "doubted": 0}
    matched, ambiguous, _unmatched, doubted = _match(Path(memory_path), connections)
    return {"people": len(matched), "ambiguous": ambiguous, "doubted": doubted}


def match(memory_path: Path, connections: list[Connection]) -> tuple[dict[str, Connection], int, int]:
    """``({page id: connection}, ambiguous, unmatched)``. A page that already lists a connection's profile link is
    that connection's page; otherwise its full name (either order) or an alias must name exactly one person page, and
    that page must not already name a different LinkedIn profile. Two connections on one page — duplicate names —
    match neither, and a name the bank holds a same-name doubt for matches nobody (counted in ``ambiguous`` here;
    ``apply``'s report says it apart)."""
    matched, ambiguous, unmatched, refused = _match(memory_path, connections)
    return matched, ambiguous + refused, unmatched


# --------------------------------------------------------------------------- writing one page


def _claim_id(entity_id: str, predicate: str, value: str, day: str) -> str:
    digest = hashlib.sha256(f"{predicate}\x00{_fold(value)}\x00{day}".encode("utf-8")).hexdigest()[:8]
    return f"clm_{entity_id}_{predicate}_li_{digest}"


def _text(predicate: str, name: str, value: str, day: str, *, read: bool, precision: str | None = None) -> str:
    said = f"as {'their profile showed' if read else 'LinkedIn listed'} on {day}"
    if predicate == WORKS_AT:
        return f"{name} works at {value} ({said})"
    if predicate == ROLE:
        return f"{name}'s position: {value} ({said})"
    if precision in ("week", "month"):
        # The page said "N weeks ago": the day is that count back from the day it was read, known to the week or month.
        return f"Connected with {name} on LinkedIn around {value} (known to the {precision})"
    return f"Connected with {name} on LinkedIn on {value}"


def _company_node(companies: dict[str, set[str]], value: str) -> str | None:
    hits = companies.get(_fold(value), set())
    return next(iter(hits)) if len(hits) == 1 else None


def _same(claim: Claim, value: str, node: str | None) -> bool:
    return _fold(claim.object) in {_fold(value), _fold(node or "")} - {""}


def _reconcile(claims: list[Claim], entity_id: str, name: str, predicate: str, value: str, day: str, *,
               origin: str, node: str | None, evidence_rows: list, authored_by: str, today: str,
               precision: str | None = None) -> tuple[str, int]:
    """One fact against this module's own dated line for ``predicate``: ``(outcome, closed)`` where outcome is
    ``same`` (nothing written), ``older`` (a newer LinkedIn value is already held), or ``written``."""
    mine = [c for c in claims if c.origin in ORIGINS and c.observer == OBSERVER and c.predicate == predicate]
    current = [c for c in mine if not c.valid_to]
    newest = max([c.valid_from or "" for c in mine] + [c.valid_to or "" for c in mine], default="")
    if any(_same(c, value, node) for c in current):
        return "same", 0
    if newest and day < newest:
        return "older", 0
    cid = _claim_id(entity_id, predicate, value, day)
    if any(c.id == cid for c in claims):
        return "same", 0
    new = Claim(
        id=cid, text=_text(predicate, name, value, day, read=origin == ORIGIN_PROFILE, precision=precision),
        subject=entity_id,
        predicate=predicate, object=node or value, object_kind="node" if node else "literal", observer=OBSERVER,
        context="career" if predicate != CONNECTED_ON else "general", epistemic="explicit", source_trust="external",
        confidence=0.9, valid_from=value if predicate == CONNECTED_ON else day, recorded_at=today,
        authored_by=authored_by, origin=origin, evidence=list(evidence_rows) or [evidence.reasoning()])
    closed = 0
    for old in current:
        old.valid_to = day
        old.superseded_by = cid
        new.supersedes = old.id
        closed += 1
    claims.append(new)
    return "written", closed


def _apply_to(fm: dict, body: str, entity_id: str, facts: dict[str, str], *, url: str | None, day: str, origin: str,
              companies: dict[str, set[str]], report: Report, evidence_by: dict[str, list] | None = None,
              authored_by: str = AUTHOR, add_source: bool = True, how: str | None = None,
              precision: str | None = None) -> tuple[dict, str, bool]:
    """One person's LinkedIn link and facts onto a page held in memory: ``(frontmatter, body, changed)``. The page is
    written by the caller — in place for an existing page (:func:`_apply_page`), or as part of the write that births it
    (:class:`Attacher`)."""
    fm = dict(fm)
    name = str(fm.get("name") or entity_id.replace("-", " ").title())
    today = date.today().isoformat()
    changed = False
    if url and add_source:
        current = [s for s in (fm.get("sources") or []) if isinstance(s, dict)]
        listed = any(_slug(s.get("ref")) == _slug(url) for s in current)
        if fact_sources.is_tombstoned(fm, url, SOURCE_PREDICATE) or _removed_slug(fm, url):
            # The person took this profile off this page: it is not theirs to Cicada either — no link, no facts.
            report.removed_kept_out += 1
            return fm, body, False
        if not listed and len(current) < fact_sources.MAX_SOURCES:
            fm["sources"] = current + [{"ref": url, "kind": fact_sources.KIND_URL, "predicate": SOURCE_PREDICATE,
                                        "added_by": AUTHOR, "added_at": today, **({MATCH_KEY: how} if how else {})}]
            report.sources_added += 1
            changed = True
        elif listed and how:
            # Cicada's own link from an earlier import (or one from before ``match`` existed) records this match.
            for source in current:
                if (_slug(source.get("ref")) == _slug(url) and str(source.get("added_by") or "") == AUTHOR
                        and source.get(MATCH_KEY) != how):
                    source[MATCH_KEY] = how   # the same dict ``fm["sources"]`` holds
                    changed = True
    if any(facts.values()):
        try:
            claims = parse_claims(body, strict=True)
        except MalformedClaimsBlockError:
            claims = None
            logger.warning("LinkedIn connections: a page's claims block is malformed; its facts were left out")
        if claims is not None:
            wrote = False
            for predicate in FACT_PREDICATES:
                value = facts.get(predicate) or ""
                if not value:
                    continue
                node = _company_node(companies, value) if predicate == WORKS_AT else None
                outcome, closed = _reconcile(claims, entity_id, name, predicate, value, day, origin=origin, node=node,
                                             evidence_rows=(evidence_by or {}).get(predicate) or [],
                                             authored_by=authored_by, today=today,
                                             precision=precision if predicate == CONNECTED_ON else None)
                if outcome == "written":
                    report.claims_written += 1
                    report.claims_closed += closed
                    wrote = True
                elif outcome == "older":
                    report.older += 1
            if wrote:
                body = write_claims(body, claims)
                changed = True
    return fm, body, changed


@page_lock.locked
def _apply_page(memory_path: Path, entity_id: str, facts: dict[str, str], *, url: str | None, day: str, origin: str,
                companies: dict[str, set[str]], report: Report, evidence_by: dict[str, list] | None = None,
                authored_by: str = AUTHOR, add_source: bool = True, how: str | None = None,
                precision: str | None = None) -> bool:
    """Write one person's LinkedIn link and facts onto their page. Returns whether the page changed."""
    path = Path(memory_path) / "entities" / f"{entity_id}.md"
    if not path.exists():
        return False
    parsed = markdown_parser.parse(path)
    if parsed.frontmatter.get("type") != "person" or parsed.frontmatter.get("status") == "dropped":
        return False
    fm, body, changed = _apply_to(parsed.frontmatter, parsed.body, entity_id, facts, url=url, day=day, origin=origin,
                                  companies=companies, report=report, evidence_by=evidence_by,
                                  authored_by=authored_by, add_source=add_source, how=how, precision=precision)
    if changed:
        markdown_parser.write(path, fm, body)
    return changed


def _facts(c: Connection) -> dict[str, str]:
    return {WORKS_AT: c.company, ROLE: c.position, CONNECTED_ON: c.connected_on or ""}


def apply(memory_path: Path, connections: list[Connection], *, day: str, skip: frozenset[str] = frozenset()) -> Report:
    """Match and write — the import's body and the tail's rematch. Pages in ``skip`` (memory-relative, dirty before a
    tail run) are left alone. Idempotent: a connection already on its page writes nothing."""
    memory_path = Path(memory_path)
    report = Report(connections=len(connections), exported_on=day)
    matched, report.ambiguous, report.unmatched, report.doubted = _match(memory_path, connections)
    report.matched = len(matched)
    idx = _index(memory_path) if matched else None
    companies = idx.companies if idx else {}
    for eid in sorted(matched):
        rel = f"entities/{eid}.md"
        if rel in skip:
            continue
        c = matched[eid]
        if _apply_page(memory_path, eid, _facts(c), url=c.url, day=day, origin=ORIGIN_EXPORT, companies=companies,
                       report=report, how=basis(idx, eid, c), precision=c.precision):
            report.paths.append(rel)
    if report.paths:
        bank_index.invalidate(memory_path)
    return report


def preview(memory_path: Path, data: bytes, filename: str = "", *, exported_on: str | None = None) -> dict:
    """What an import would do — counts only, nothing written, nothing kept."""
    parsed = parse(data, filename)
    matched, ambiguous, unmatched = match(Path(memory_path), parsed.connections)
    return {"connections": len(parsed.connections), "matched": len(matched), "ambiguous": ambiguous,
            "unmatched": unmatched, "skipped": parsed.skipped,
            "with_company": sum(1 for c in parsed.connections if c.company),
            "exported_on": as_of(exported_on, parsed)}


def import_connections(memory_path: Path, data: bytes, filename: str = "", *, exported_on: str | None = None,
                       bank: str | None = None) -> Report:
    """The import: match and write, then keep the directory outside the bank for later matches. The caller holds the
    write admission and commits ``report.paths`` once, as the person."""
    memory_path = Path(memory_path)
    parsed = parse(data, filename)
    day = as_of(exported_on, parsed)
    report = apply(memory_path, parsed.connections, day=day)
    save_directory(bank or memory_path.name, parsed.connections, day)
    return report


# --------------------------------------------------------------------------- the directory (outside every bank)


def directory_path(bank: str) -> Path:
    """``$CICADA_HOME/people/<bank>/linkedin-connections.json`` (`people_directory`). Pure: a read never conjures a
    folder — :func:`save_directory` creates it."""
    return people_directory.path(bank, DIRECTORY_FILE)


def load_directory(bank: str) -> dict:
    return people_directory.load_json(bank, DIRECTORY_FILE)


@contextmanager
def _locked(bank: str) -> Iterator[None]:
    """Read-modify-write of the directory under an ``flock`` (the backend's import and a stdio server's read both write it)."""
    folder = people_directory.ensure(bank)
    with open(folder / ".linkedin.lock", "a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _number(rows: list[Connection]) -> list[Connection]:
    """Tell apart the rows that have no profile link and share a name (``Connection.dup``), in file order, so no id and
    no key ever merges two of them: the same-name refusals compare ids."""
    seen: dict[str, int] = {}
    for c in rows:
        if c.url:
            c.dup = 0
            continue
        base = f"{c.first}\x00{c.last}".lower()
        c.dup = seen.get(base, 0)
        seen[base] = c.dup + 1
    return rows


def _absorb_linkless(rows: list[Connection]) -> list[Connection]:
    """An export row with no profile link and a later read of one person with a link are one connection only when that
    can be told safely: the name is the only one of its kind among all the rows but those two, the read is the agent's
    (``src: read``) and both give the same connected day to the day. Anything less keeps them apart — two rows — and the
    same-name refusal fires, as it must when two people may share a name."""
    groups: dict[str, list[Connection]] = {}
    for c in rows:
        groups.setdefault(_fold(c.name), []).append(c)
    drop: set[int] = set()
    for group in groups.values():
        if len(group) != 2:
            continue
        linkless = [c for c in group if not c.url]
        linked = [c for c in group if c.url]
        if len(linkless) != 1 or len(linked) != 1:
            continue
        a, b = linkless[0], linked[0]
        if (b.src == "read" and a.src == "export" and a.connected_on and a.connected_on == b.connected_on
                and a.precision in (None, "day") and b.precision == "day"):
            b.company, b.position = b.company or a.company, b.position or a.position
            drop.add(id(a))
    return [c for c in rows if id(c) not in drop]


def _write_rows(bank: str, held: dict, rows: list[Connection], *, exported_on: str | None,
                read_on: str | None, imported: bool = False) -> None:
    """``imported``: this write is an export's import, so ``imported_at`` is now; a read keeps the day it was set."""
    _number(rows)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    payload = {"v": 1, "imported_at": now if imported else (held.get("imported_at") or now),
               "connections": [c.to_dict() for c in rows]}
    if exported_on:
        payload["exported_on"] = exported_on
    if read_on:
        payload["read_on"] = read_on
    people_directory.save_json(bank, DIRECTORY_FILE, payload)


def _rows(held: dict) -> list[Connection]:
    raw = held.get("connections") if isinstance(held.get("connections"), list) else []
    return _number([c for c in (Connection.from_dict(r) for r in raw) if c is not None])


def _finer(new: tuple[str | None, str | None], old: tuple[str | None, str | None]) -> bool:
    """Is the day ``new`` finer than ``old``? Only a day known to a finer precision replaces one; the same precision
    keeps the day already held, so a re-read never moves it."""
    return bool(new[0]) and (not old[0] or _FINENESS.get(new[1] or "", 0) > _FINENESS.get(old[1] or "", 0))


def save_directory(bank: str, connections: list[Connection], day: str) -> bool:
    """Keep the export's connections for later matches — unless a newer export is already kept. Returns whether it
    wrote. 0600, written by a rename. A row only the person's agent has read (``src: read``: connected since the export,
    or not in it) is kept beside the export's: an export never drops what a read added."""
    with _locked(bank):
        held = load_directory(bank)
        if str(held.get("exported_on") or "") > day:
            return False
        # A row with no profile link is never keyed: two of one name are two connections (and so a same-name refusal), and
        # the previous export's such rows go with it — the new export carries them again.
        exported = {_slug(c.url) or c.id: c for c in connections if c.url}
        kept: list[Connection] = []
        for old in _rows(held):
            if not old.url:
                if old.src == "read":
                    kept.append(old)
                continue
            key = _slug(old.url) or old.id
            if key in exported:
                new = exported.pop(key)
                if not _finer((new.connected_on, new.precision), (old.connected_on, old.precision)) and old.connected_on:
                    new.connected_on, new.precision = old.connected_on, old.precision
                new.headline = new.headline or old.headline
                kept.append(new)
            elif old.src == "read":
                kept.append(old)
        merged = kept + [c for c in connections if not c.url or (_slug(c.url) or c.id) in exported]
        _write_rows(bank, held, _absorb_linkless(merged), exported_on=day, read_on=held.get("read_on"), imported=True)
    return True


@dataclass
class ReadReport:
    """What one agent read of the connections page did to the directory — counts only, never a name."""
    seen: int = 0
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    dropped: int = 0     # a row with no member profile link, or no name
    undated: int = 0     # a row whose date the page showed in words this module does not read
    full: int = 0        # rows past MAX_CONNECTIONS
    known: list[bool] = field(default_factory=list)   # per row: already held, nothing new
    rows: list[Connection] = field(default_factory=list)   # the rows this read named, as kept (never logged)


def record_read(bank: str, rows: list, read_day: str) -> ReadReport:
    """The person's agent read the connections page (``cicada_record_saved_list``, platform ``linkedin-connections``):
    merge its rows into the directory by profile link. Never deletes a row; never moves ``exported_on`` backwards; the
    finer day stays (:func:`_finer`); a row with no member profile link is left out (it cannot be told from another of the
    same name). Nothing is written into any bank, and no model reads the rows."""
    report = ReadReport()
    with _locked(bank):
        held = load_directory(bank)
        current = _rows(held)
        by_slug = {_slug(c.url): c for c in current if c.url}
        changed = False
        for row in rows:
            row = row if isinstance(row, dict) else {}
            url = profile_url(row.get("profile_url") or row.get("url"))
            name = _clean(str(row.get("name") or "").split(",", 1)[0])
            if not url or not name:
                report.dropped += 1
                continue
            first, _, last = name.partition(" ")
            day, precision = parse_connected(row.get("connected"), read_day)
            if row.get("connected") and not day:
                report.undated += 1
            headline = _clean(row.get("headline"))
            report.seen += 1
            old = by_slug.get(_slug(url))
            report.rows.append(old if old is not None else Connection(first, last.strip(), url))
            if old is None:
                if len(current) >= MAX_CONNECTIONS:
                    report.full += 1
                    report.known.append(False)
                    continue
                new = Connection(first, last.strip(), url, "", "", day, headline, precision if day else None, "read")
                report.rows[-1] = new
                current.append(new)
                by_slug[_slug(url)] = new
                report.added += 1
                report.known.append(False)
                changed = True
                continue
            moved = False
            if headline and headline != old.headline:
                old.headline, moved = headline, True
            if _finer((day, precision), (old.connected_on, old.precision)):
                old.connected_on, old.precision, moved = day, precision, True
            if not (old.first or old.last):
                old.first, old.last, moved = first, last.strip(), True
            report.updated += int(moved)
            report.unchanged += int(not moved)
            report.known.append(not moved)
            changed = changed or moved
        if changed:
            # ``exported_on`` is the export file's own day and never moves here (so an older export is still refused
            # only by a newer export); a read keeps its own day beside it.
            _write_rows(bank, held, _absorb_linkless(current), exported_on=held.get("exported_on"),
                        read_on=max(str(held.get("read_on") or ""), read_day))
    return report


def forget_directory(bank: str) -> int:
    """The person's "Forget kept connections" (review of #391): this bank's kept export is deleted, so Sleep's rematch
    and nothing else ever reads it again. What earlier matches wrote on pages stays. Returns how many were kept."""
    kept = status(bank)["connections"]
    directory_path(bank).unlink(missing_ok=True)
    return int(kept or 0)


#: A bank's trash and rename take the whole people directory along (`people_directory`), Contacts' waiting cards too.
forget = people_directory.forget
rename = people_directory.rename


def status(bank: str) -> dict:
    """What the app shows under Connections: the kept export's day and size — never a name."""
    held = load_directory(bank)
    rows = held.get("connections") if isinstance(held.get("connections"), list) else []
    return {"exported_on": held.get("exported_on"), "imported_at": held.get("imported_at"), "connections": len(rows)}


def rematch(memory_path: Path, *, bank: str | None = None, skip: frozenset[str] = frozenset()) -> Report:
    """Sleep's tail: the kept directory against tonight's pages, so a person who got a page since the import gains
    their LinkedIn link and facts. Writes nothing when no directory is kept or nothing new matches."""
    from api.services import demo_guard

    memory_path = Path(memory_path)
    if demo_guard.is_demo(memory_path):
        return Report()   # a demo bank never takes in the person's real connections (R-CS16)
    held = load_directory(bank or memory_path.name)
    rows = held.get("connections") if isinstance(held.get("connections"), list) else []
    day = _day(held.get("exported_on")) or _day(held.get("read_on"))
    if not rows or not day:
        return Report()
    connections = [c for c in (Connection.from_dict(r) for r in rows) if c is not None]
    return apply(memory_path, connections, day=day, skip=skip)


# --------------------------------------------------------------------------- a page's birth

class Attacher:
    """The kept connection that matches a person page being **born** attaches in the write that births it — not at the
    tail of a night's Sleep (owner 2026-11-24: "the person is what gets a page"; the connection never does).

    One instance serves one run (Sleep's Stage 5 create loop) or one write (an agent's first claim about a new person):
    the directory and the bank's person-page index are read once, on the first person born, and every page born since
    is added to that index, so two pages of one name born in one run see each other and refuse. Nothing happens, and
    nothing is read, when the bank is a demo bank, the directory is not kept, or it holds nothing dated. Never mints a
    page, never calls a model or the network. Refusals — a name the bank holds a same-name doubt for, two connections or
    two pages of one name — write nothing and are counted in :attr:`report`, never named."""

    def __init__(self, memory_path: Path, *, bank: str | None = None) -> None:
        self.memory_path = Path(memory_path)
        self.bank = bank or self.memory_path.name
        self.report = Report()
        self._ready: bool | None = None
        self._day = ""
        self._by_key: dict[str, list[Connection]] = {}
        self._by_slug: dict[str, Connection] = {}
        self._idx: _Index | None = None
        self._doubted: set[str] = set()
        self._owners: set[str] = set()

    def _load(self) -> bool:
        if self._ready is not None:
            return self._ready
        self._ready = False
        from api.services import demo_guard

        if demo_guard.is_demo(self.memory_path) or not directory_path(self.bank).exists():
            return False
        held = load_directory(self.bank)
        rows = _rows(held)
        self._day = _day(held.get("exported_on")) or _day(held.get("read_on")) or ""
        if not rows or not self._day:
            return False
        for c in rows:
            for key in _name_keys(c):
                self._by_key.setdefault(key, []).append(c)
            if slug := _slug(c.url):
                self._by_slug[slug] = c
        self._idx = _index(self.memory_path)
        self._doubted = _doubted(self.memory_path, self._idx)
        self._owners = _owner_ids(self.memory_path)
        self._ready = True
        return True

    def _register(self, entity_id: str, labels: list) -> None:
        idx = self._idx
        keys = [_fold(label) for label in labels]
        for key in keys:
            if key:
                idx.names.setdefault(key, set()).add(entity_id)
        idx.page_names[entity_id] = keys[0] if keys else ""
        idx.page_aliases[entity_id] = {k for k in keys[1:] if k}

    def attach(self, fm: dict, body: str, entity_id: str) -> tuple[dict, str]:
        """``(frontmatter, body)`` of the page being born, with the one connection that matches it written on — the
        profile link as a ``sources:`` entry and works-at, role and connected-on as dated claims observed
        ``external:linkedin`` (what :func:`apply` writes on an existing page). Unchanged for anyone else, and for a page
        the person's own, dropped or not a person."""
        if fm.get("type") != "person" or fm.get("owner") is True or fm.get("status") == "dropped":
            return fm, body
        if not self._load():
            return fm, body
        idx = self._idx
        if entity_id in self._owners:
            return fm, body
        labels = people_directory.labels(fm, entity_id)
        self._register(entity_id, labels)
        found: dict[str, Connection] = {}
        for label in labels:
            for c in self._by_key.get(_fold(label), []):
                found[c.id] = c
        for source in fact_sources.as_sources(fm.get("sources")):
            if (slug := _slug(source.get("ref"))) and slug in self._by_slug:
                found[self._by_slug[slug].id] = self._by_slug[slug]
                idx.slugs.setdefault(slug, set()).add(entity_id)
                idx.page_slugs.setdefault(entity_id, set()).add(slug)
                if _vouched(source):
                    idx.listed_by_others.setdefault(entity_id, set()).add(slug)
        landing: list[Connection] = []
        for c in found.values():
            hits, doubt = _hits(idx, c, self._doubted)
            if doubt:
                self.report.doubted += 1
            elif hits == {entity_id}:
                landing.append(c)
            elif hits:
                self.report.ambiguous += 1
        if len(landing) != 1:
            self.report.ambiguous += len(landing) if landing else 0
            return fm, body
        c = landing[0]
        new_fm, new_body, changed = _apply_to(
            fm, body, entity_id, _facts(c), url=c.url, day=self._day, origin=ORIGIN_EXPORT, companies=idx.companies,
            report=self.report, how=basis(idx, entity_id, c), precision=c.precision)
        if not changed:
            return fm, body
        self.report.matched += 1
        self.report.paths.append(f"entities/{entity_id}.md")
        if slug := _slug(c.url):
            idx.slugs.setdefault(slug, set()).add(entity_id)
            idx.page_slugs.setdefault(entity_id, set()).add(slug)
        return new_fm, new_body


# --------------------------------------------------------------------------- the list (the person's own view)

#: The most rows one request returns.
MAX_ROWS = 200
#: The agents' read door: connections in a date range, at most this many.
AGENT_ROWS = 50


def _headline(c: Connection) -> str:
    """The line under a connection's name: what the page showed, else the export's position at its company."""
    if c.headline:
        return c.headline
    return f"{c.position} at {c.company}" if c.position and c.company else (c.position or c.company)


def _page_for(idx: _Index, doubted: set[str], by_key: dict[str, list[Connection]], c: Connection) -> str | None:
    """The one person page this connection is — exactly one, by :func:`_hits`' rules — or ``None``. A name another
    connection shares matches neither, as in :func:`apply`."""
    hits, _ = _hits(idx, c, doubted)
    if len(hits) != 1:
        return None
    page = next(iter(hits))
    slug = _slug(c.url)
    if not (slug and slug in idx.page_slugs.get(page, set())):
        for key in _name_keys(c):
            if any(other.id != c.id for other in by_key.get(key, [])):
                return None
    return page


def list_rows(memory_path: Path, bank: str, *, query: str = "", since: str | None = None, until: str | None = None,
              offset: int = 0, limit: int = 50) -> dict:
    """The person's connections, newest first, each with the matched page when there is exactly one — read from the
    directory at this moment and written nowhere. ``query`` is words of a name or a headline (folded like search);
    ``since`` and ``until`` bound the day, inclusive (a row with no day is outside any range). One page index is read for
    the request, only when a row is returned."""
    held = load_directory(bank)
    rows = _rows(held)
    words = people_directory.fold(query).split()
    if words:
        rows = [c for c in rows if all(w in people_directory.fold(f"{c.name} {_headline(c)}") for w in words)]
    since_day, until_day = _day(since), _day(until)
    if since_day or until_day:
        rows = [c for c in rows if c.connected_on and (not since_day or c.connected_on >= since_day)
                and (not until_day or c.connected_on <= until_day)]
    rows.sort(key=lambda c: c.name.lower())
    rows.sort(key=lambda c: c.connected_on or "", reverse=True)
    dated = [c for c in rows if c.connected_on]
    rows = dated + [c for c in rows if not c.connected_on]
    total = len(rows)
    limit = max(1, min(int(limit), MAX_ROWS))
    offset = max(0, int(offset))
    page_rows = rows[offset:offset + limit]
    out: list[dict] = []
    if page_rows:
        from api.services import demo_guard

        idx = None if demo_guard.is_demo(Path(memory_path)) else _index(Path(memory_path))
        doubted = _doubted(Path(memory_path), idx) if idx else set()
        by_key: dict[str, list[Connection]] = {}
        for c in _rows(held):
            for key in _name_keys(c):
                by_key.setdefault(key, []).append(c)
        for c in page_rows:
            out.append({"id": c.id, "name": c.name, "headline": _headline(c), "url": c.url, "day": c.connected_on,
                        "precision": c.precision if c.connected_on else None,
                        "page": _page_for(idx, doubted, by_key, c) if idx else None})
    return {"rows": out, "total": total, "offset": offset,
            "next": offset + limit if offset + limit < total else None,
            "exportedOn": held.get("exported_on"), "readOn": held.get("read_on"), "kept": len(_rows(held))}


def commit_message(report: Report, today: date, *, trigger: str = TRIGGER_REMATCH) -> str:
    from api.services import git_service

    return git_service.build_commit_message(
        f"LinkedIn connections {today.isoformat()}",
        [f"{p}: updated (source: n/a, trigger: {trigger})" for p in report.paths], authors=[AUTHOR])


def restore(memory_path: Path, report: Report) -> None:
    """Undo a tail run whose commit failed, so no later ``git add -A`` sweeps it under another author."""
    from api.services import git_service

    memory_path = Path(memory_path)
    if report.paths and (memory_path / ".git").exists():
        try:
            git_service.run_git_write_sync(memory_path, "checkout", "--", *report.paths)
        except git_service.GitError as exc:
            logger.warning(f"LinkedIn rematch restore failed: {type(exc).__name__}")
    bank_index.invalidate(memory_path)


# --------------------------------------------------------------------------- a profile the person's agent read


def page_profile(memory_path: Path, entity_id: str) -> str | None:
    """The one LinkedIn profile link a person page lists (any adder), or None when it lists none or several."""
    path = Path(memory_path) / "entities" / f"{entity_id}.md"
    if not path.exists():
        return None
    fm = markdown_parser.parse(path).frontmatter
    found = {profile_url(s.get("ref")) for s in fact_sources.as_sources(fm.get("sources"))} - {None}
    return next(iter(found)) if len(found) == 1 else None


def apply_profile(memory_path: Path, entity_id: str, *, company: str, position: str, day: str,
                  evidence_by: dict[str, list], authored_by: str) -> Report:
    """What the person's agent read on one person's profile, as the newest dated LinkedIn facts on their page."""
    memory_path = Path(memory_path)
    report = Report(connections=1, matched=1, exported_on=day)
    companies = _index(memory_path).companies
    if _apply_page(memory_path, entity_id, {WORKS_AT: _clean(company), ROLE: _clean(position)}, url=None, day=day,
                   origin=ORIGIN_PROFILE, companies=companies, report=report, evidence_by=evidence_by,
                   authored_by=authored_by, add_source=False):
        report.paths.append(f"entities/{entity_id}.md")
        bank_index.invalidate(memory_path)
    return report


#: ``cicada_record_profile``: nothing in bulk — a profile is read because the person asked about that one person.
MAX_PROFILE_READS_PER_DAY = 10
PROFILE_SOURCE = "profile-read"
PROFILE_OUTCOMES = ("read", "needs_login", "blocked", "not_found", "failed")
READS_FILE = "linkedin-profile-reads.json"


def reads_today(bank: str, *, today: str | None = None) -> int:
    """How many profiles this bank recorded today (UTC) — a count by day, outside every bank; never a name."""
    path = directory_path(bank).with_name(READS_FILE)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    day = today or datetime.now(timezone.utc).date().isoformat()
    return int(data.get(day) or 0) if isinstance(data, dict) else 0


def count_read(bank: str, *, today: str | None = None) -> None:
    day = today or datetime.now(timezone.utc).date().isoformat()
    path = directory_path(bank).with_name(READS_FILE)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps({day: reads_today(bank, today=day) + 1}), encoding="utf-8")
    os.chmod(path, 0o600)


def write_profile_episode(memory_path: Path, *, entity_id: str, name: str, url: str, summary: str, quotes: list[str],
                          reader: str, via: str | None = None, session_frontmatter: dict | None = None) -> str:
    """One episode of what the person's agent read on a profile: ``assistant: <summary>``, then ``attachment
    [linkedin.com]: as <reader> read it`` and one ``> <quote>`` line per quote — so a quote cited by a claim is a
    ``page`` span, text an agent REPORTED from the page, never the person's words (``check_record``'s shape).
    ``processed: true`` (Sleep never re-reads it raw). Everything is scrubbed before it is written."""
    from api.services import episode_ids, reading_asks

    memory_path = Path(memory_path)
    via_clean = reading_asks.clean_via(via)
    summary, n = episode_scrub.scrub(" ".join(str(summary or "").split())[:500])
    episode_scrub.record(CHANNEL_ID, n, bank=memory_path.name)
    label = reader if reader and reader != "agent" else "an agent"
    lines = [f"assistant: {summary or f'Read the LinkedIn profile of {name}.'}"]
    if quotes:
        lines += ["", f"attachment [linkedin.com]: as {label} read it", *(f"> {q}" for q in quotes)]
    episodes_dir = memory_path / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    episode_id = episode_ids.next_episode_id(episodes_dir, datetime.now().strftime("%Y-%m-%d"))
    frontmatter = {
        "id": episode_id, "timestamp": episode_ids.utc_now_iso(), "source": PROFILE_SOURCE, "origin": "mcp",
        "title": f"LinkedIn profile: {name}"[:120], "processed": True, "processed_by": "agent",
        "checked_ref": url, "checked_host": "linkedin.com", "entity_id": entity_id,
        **({"via": via_clean} if via_clean else {}),
        **(session_frontmatter or {}),
    }
    return episode_ids.create_episode(episodes_dir, frontmatter, "\n".join(lines))


def profile_evidence(memory_path: Path, episode_id: str, value: str, quotes: list[str]) -> list:
    """The span of the first quote that names ``value`` (exact words, never fuzzy), else the episode as reasoning."""
    folded = _fold(value)
    for quote in quotes:
        if folded and folded in _fold(quote):
            return [evidence.verify(memory_path, episode_id, quote)]
    return [evidence.reasoning(episode_id)]
