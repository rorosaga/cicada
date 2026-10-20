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
import hashlib
import io
import json
import os
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
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
_DATE_FORMATS = ("%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%d-%b-%y", "%d-%b-%Y", "%m/%d/%y", "%m/%d/%Y")
_SLUG_RE = re.compile(r"[^/?#\s]{1,100}")


class PayloadError(ValueError):
    """A file the backend cannot read as LinkedIn connections — answered 422, nothing written."""


@dataclass
class Connection:
    first: str
    last: str
    url: str | None = None
    company: str = ""
    position: str = ""
    connected_on: str | None = None

    @property
    def name(self) -> str:
        return " ".join(p for p in (self.first, self.last) if p)

    @property
    def id(self) -> str:
        key = self.url or f"name:{self.name.lower()}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict:
        out = {"id": self.id, "first": self.first, "last": self.last}
        for key in ("url", "company", "position", "connected_on"):
            if getattr(self, key):
                out[key] = getattr(self, key)
        return out

    @classmethod
    def from_dict(cls, raw: dict) -> "Connection | None":
        if not isinstance(raw, dict):
            return None
        first, last = _clean(raw.get("first")), _clean(raw.get("last"))
        if not (first or last):
            return None
        return cls(first, last, profile_url(raw.get("url")), _clean(raw.get("company")), _clean(raw.get("position")),
                   _day(raw.get("connected_on")))


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
        labels = [fm.get("name") or f.stem.replace("-", " "), *(fm.get("aliases") or [])]
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


def match(memory_path: Path, connections: list[Connection]) -> tuple[dict[str, Connection], int, int]:
    """``({page id: connection}, ambiguous, unmatched)``. A page that already lists a connection's profile link is
    that connection's page; otherwise its full name (either order) or an alias must name exactly one person page, and
    that page must not already name a different LinkedIn profile. Two connections on one page — duplicate names —
    match neither."""
    idx = _index(memory_path)
    claims: dict[str, list[Connection]] = {}
    ambiguous = unmatched = 0
    for c in connections:
        slug = _slug(c.url)
        hits = set(idx.slugs.get(slug, set())) if slug else set()
        if not hits:
            for key in _name_keys(c):
                hits |= idx.names.get(key, set())
            # A page that already names another LinkedIn profile is someone else of the same name.
            hits = {h for h in hits if not (slug and idx.page_slugs.get(h) and slug not in idx.page_slugs[h])}
        if len(hits) == 1:
            claims.setdefault(next(iter(hits)), []).append(c)
        elif hits:
            ambiguous += 1
        else:
            unmatched += 1
    matched = {eid: found[0] for eid, found in claims.items() if len(found) == 1}
    ambiguous += sum(len(found) for found in claims.values() if len(found) > 1)
    return matched, ambiguous, unmatched


# --------------------------------------------------------------------------- writing one page


def _claim_id(entity_id: str, predicate: str, value: str, day: str) -> str:
    digest = hashlib.sha256(f"{predicate}\x00{_fold(value)}\x00{day}".encode("utf-8")).hexdigest()[:8]
    return f"clm_{entity_id}_{predicate}_li_{digest}"


def _text(predicate: str, name: str, value: str, day: str, *, read: bool) -> str:
    said = f"as {'their profile showed' if read else 'LinkedIn listed'} on {day}"
    if predicate == WORKS_AT:
        return f"{name} works at {value} ({said})"
    if predicate == ROLE:
        return f"{name}'s position: {value} ({said})"
    return f"Connected with {name} on LinkedIn on {value}"


def _company_node(companies: dict[str, set[str]], value: str) -> str | None:
    hits = companies.get(_fold(value), set())
    return next(iter(hits)) if len(hits) == 1 else None


def _same(claim: Claim, value: str, node: str | None) -> bool:
    return _fold(claim.object) in {_fold(value), _fold(node or "")} - {""}


def _reconcile(claims: list[Claim], entity_id: str, name: str, predicate: str, value: str, day: str, *,
               origin: str, node: str | None, evidence_rows: list, authored_by: str, today: str) -> tuple[str, int]:
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
        id=cid, text=_text(predicate, name, value, day, read=origin == ORIGIN_PROFILE), subject=entity_id,
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


@page_lock.locked
def _apply_page(memory_path: Path, entity_id: str, facts: dict[str, str], *, url: str | None, day: str, origin: str,
                companies: dict[str, set[str]], report: Report, evidence_by: dict[str, list] | None = None,
                authored_by: str = AUTHOR, add_source: bool = True, how: str | None = None) -> bool:
    """Write one person's LinkedIn link and facts onto their page. Returns whether the page changed."""
    path = Path(memory_path) / "entities" / f"{entity_id}.md"
    if not path.exists():
        return False
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    if fm.get("type") != "person" or fm.get("status") == "dropped":
        return False
    name = str(fm.get("name") or entity_id.replace("-", " ").title())
    today = date.today().isoformat()
    changed = False
    if url and add_source:
        current = [s for s in (fm.get("sources") or []) if isinstance(s, dict)]
        listed = any(_slug(s.get("ref")) == _slug(url) for s in current)
        if fact_sources.is_tombstoned(fm, url, SOURCE_PREDICATE) or _removed_slug(fm, url):
            # The person took this profile off this page: it is not theirs to Cicada either — no link, no facts.
            report.removed_kept_out += 1
            return False
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
    body = parsed.body
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
                                             authored_by=authored_by, today=today)
                if outcome == "written":
                    report.claims_written += 1
                    report.claims_closed += closed
                    wrote = True
                elif outcome == "older":
                    report.older += 1
            if wrote:
                body = write_claims(body, claims)
                changed = True
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
    matched, report.ambiguous, report.unmatched = match(memory_path, connections)
    report.matched = len(matched)
    idx = _index(memory_path) if matched else None
    companies = idx.companies if idx else {}
    for eid in sorted(matched):
        rel = f"entities/{eid}.md"
        if rel in skip:
            continue
        c = matched[eid]
        if _apply_page(memory_path, eid, _facts(c), url=c.url, day=day, origin=ORIGIN_EXPORT, companies=companies,
                       report=report, how=basis(idx, eid, c)):
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


def save_directory(bank: str, connections: list[Connection], day: str) -> bool:
    """Keep the export's connections for later matches — unless a newer export is already kept. Returns whether it
    wrote. 0600, written by a rename."""
    held = load_directory(bank)
    if str(held.get("exported_on") or "") > day:
        return False
    payload = {"v": 1, "exported_on": day, "imported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
               "connections": [c.to_dict() for c in connections]}
    people_directory.save_json(bank, DIRECTORY_FILE, payload)
    return True


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
    day = _day(held.get("exported_on"))
    if not rows or not day:
        return Report()
    connections = [c for c in (Connection.from_dict(r) for r in rows) if c is not None]
    return apply(memory_path, connections, day=day, skip=skip)


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
