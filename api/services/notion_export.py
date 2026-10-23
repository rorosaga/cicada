"""A Notion export (Markdown & CSV) through the one intake — G219, slice 1 (no credentials, no network).

The memory is meant to replace the tables a person kept elsewhere ("I used to keep all my project ideas in a Notion
table; now I can just tell you"), so a one-time move has to work: the person exports a workspace or a page from Notion
as *Markdown & CSV*, drops the zip on any intake door, and the pages arrive as episodes Sleep reads. No model runs here
(capture is file I/O), and nothing is ever written back to Notion (ruling 38).

What Notion writes, and what this module reads of it:

* every page is ``<Title> <32-hex id>.md`` — the id is the page's own, so it keys the episode (``notion:<id>``) and a
  second import of the same page updates it in place or skips it (the stager's hash), never duplicates it;
* a page's sub-pages sit in a folder of the same name, which gives the breadcrumb (``In: Parent › Child``);
* a database is ``<Name> <id>.csv`` (plus ``<Name> <id>_all.csv`` in newer exports — every row, where the plain one is
  the view's) beside a folder ``<Name> <id>/`` holding one ``.md`` per row, whose first lines are the row's
  properties as ``Key: value``;
* a big export is a zip of ``…-Part-N.zip`` zips, read one level down.

**One episode per database row, not one per database.** A row is one idea with its own dates: it is dated when it was
created (read on time — an idea table of three years is not three years of ideas said today), an edit to one row
re-queues that row alone instead of the whole table, Sleep reads a row as one small unit, and a row maps one to one
onto a backlog item when the person names the database as a project's backlog (G150, a later slice). The CSV row and
the row's own page are the same thing: the CSV gives every property (the row page may hold a truncated title), the
page gives the body; a CSV row with no page of its own is still kept, keyed by its database and title.

Dates: a row is dated by its own *Created* property, else its *Last edited* one; a plain page has no date in a
Markdown export, so it is stamped the day it is imported but is **untimed** (``UNDATED_SOURCE``, one of
``episode_time.UNTIMED_SOURCES``): its facts are kept, and nothing it mentions counts as mentioned that day — three
years of pages are never three years of mentions today (review of #455, B2).

Whose words: a database row whose *Created by* names someone other than the owner is theirs (``assistant``); with no
owner name known, a database written by more than one person is. A page or table with no *Created by* is the person's
own export and their words (the smallest honest rule: Notion's Markdown export names no author for a plain page).

What is read (B1): only ``.md`` and ``.csv`` members, each at most ``MAX_MEMBER_BYTES`` and all together at most
``MAX_TOTAL_BYTES``; part zips one level down only; everything left out is said in the preview's warnings.
Links between pages become their words (a relative ``….md`` path means nothing in the bank) and embedded files are
left out; web links stay. Every body is scrubbed by the stager before it is hashed.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import PurePosixPath

from api.services import episode_ids, folder_source

ORIGIN = "notion-export"
SOURCE_PREFIX = "notion:"
SCRUB_WRITER = "notion"
#: A part zip (``…-Part-N.zip``) is opened only one level down and only up to this size: one part is held in memory at a
#: time, and a zip inside a part is never opened (review of #455, B1 — a zip three levels deep was fully parsed).
MAX_PART_BYTES = 256 * 1024 * 1024
#: One page or CSV is read at most this large; every page and CSV together at most ``MAX_TOTAL_BYTES``. Nothing else in
#: the export (images, videos, PDFs) is ever read — a 1.5 GB zero-filled ``photo.png`` in a 1.5 MB upload took the
#: sniff to 2.6 GB of memory before (B1). Each bound is checked against the declared size and again while reading, so a
#: header that lies stops at the cap.
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_PAGES = 20_000
#: B2 — a page with no date of its own (every plain page, a row without Created / Last edited) is stamped the day it
#: is imported, which is not when anything in it was said: its episodes carry this source, one of
#: ``episode_time.UNTIMED_SOURCES``, so they give facts and never activity (the memory-export rule). Dated rows keep
#: ``ORIGIN`` and stay time signals.
UNDATED_SOURCE = "notion-export-undated"
#: A row whose "Created by" names someone other than the owner is someone else's words (``assistant``, the folder rule).
_AUTHOR = ("created by", "author")
TITLE_CAP = 300
PROPERTY_CAP = 2000
MEMBERS_SHOWN = 20

_ID = re.compile(r"^(?P<name>.*?)\s+(?P<id>[0-9a-f]{32})$")
_PROPERTY = re.compile(r"^(?P<key>[^:\n]{1,60}):\s?(?P<value>.*)$")
_REL_LINK = re.compile(r"(!?)\[([^\]]*)\]\(([^)\s]+)\)")
_CREATED = ("created", "created time", "created at", "created on", "date created")
_EDITED = ("last edited time", "last edited", "edited", "last updated", "updated", "updated at")
_FORMATS = ("%B %d, %Y %I:%M %p", "%B %d, %Y %H:%M", "%B %d, %Y", "%b %d, %Y %I:%M %p", "%b %d, %Y",
            "%Y/%m/%d %I:%M %p", "%Y/%m/%d %H:%M", "%Y/%m/%d", "%Y-%m-%d %H:%M", "%Y-%m-%d",
            "%m/%d/%Y %I:%M %p", "%m/%d/%Y")


@dataclass
class Parsed:
    """What one export holds, before anything is staged — the intake wraps it as its ``ParsedExport``."""

    episodes: list[dict] = field(default_factory=list)
    members: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    pages: int = 0
    rows: int = 0
    #: Database rows whose "Created by" names someone other than the owner.
    by_others: int = 0


def _split(stem: str) -> tuple[str, str | None]:
    """``"Project ideas 0123…cdef"`` → ``("Project ideas", "0123…cdef")``; no id → ``(stem, None)``."""
    m = _ID.match(stem)
    return (m.group("name").strip(), m.group("id")) if m else (stem.strip(), None)


def _bounded(zf: zipfile.ZipFile, info: zipfile.ZipInfo, cap: int) -> bytes | None:
    """The member's bytes, or ``None`` when it is (or turns out to be) larger than ``cap`` — never more read."""
    if info.file_size > cap:
        return None
    try:
        with zf.open(info) as fh:
            data = fh.read(cap + 1)
    except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError):
        return None
    return None if len(data) > cap else data


@dataclass
class _Read:
    files: list[tuple[str, bytes]] = field(default_factory=list)
    others: int = 0
    skipped: list[str] = field(default_factory=list)
    total: int = 0


def _litter(path: PurePosixPath) -> bool:
    return path.name.startswith(".") or "__MACOSX" in path.parts


def _walk(zf: zipfile.ZipFile, out: _Read, *, depth: int) -> None:
    for info in sorted(zf.infolist(), key=lambda i: i.filename):
        path = PurePosixPath(info.filename)
        if info.is_dir() or _litter(path):
            continue
        suffix = path.suffix.lower()
        if suffix == ".zip":
            if depth > 0:
                out.skipped.append(f"{path.name}: a zip inside a part, not opened")
                continue
            data = _bounded(zf, info, MAX_PART_BYTES)
            if data is None:
                out.skipped.append(f"{path.name}: a part larger than {MAX_PART_BYTES // (1024 * 1024)} MB, not read")
                continue
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as inner:
                    _walk(inner, out, depth=depth + 1)
            except zipfile.BadZipFile:
                out.skipped.append(f"{path.name}: not a zip Cicada can open")
            continue
        if suffix not in (".md", ".csv"):
            out.others += 1            # never read: images, videos, PDFs, attachments
            continue
        room = min(MAX_MEMBER_BYTES, MAX_TOTAL_BYTES - out.total)
        data = _bounded(zf, info, room) if room > 0 else None
        if data is None:
            why = ("past what one import reads" if room < MAX_MEMBER_BYTES
                   else f"larger than {MAX_MEMBER_BYTES // (1024 * 1024)} MB")
            out.skipped.append(f"{path.name}: {why}")
            continue
        out.total += len(data)
        out.files.append((info.filename, data))


def _files(zf: zipfile.ZipFile) -> _Read:
    """The export's pages and CSVs only — part zips opened one level down, every read bounded (B1) — and what was
    left out, said in the preview."""
    out = _Read()
    _walk(zf, out, depth=0)
    return out


def _shape(names: list[str]) -> bool:
    texts = [PurePosixPath(n) for n in names if n.lower().endswith((".md", ".csv"))]
    if not texts:
        return False
    keyed = sum(1 for p in texts if _split(p.stem.removesuffix("_all"))[1])
    return keyed > 0 and keyed * 2 >= len(texts)


def looks_like(zf: zipfile.ZipFile) -> bool:
    """A Notion Markdown & CSV export: most of its ``.md``/``.csv`` files carry Notion's 32-hex page id, and it holds
    no chat export. Decided by names alone (a part zip is opened to read its names)."""
    names = [i.filename for i in zf.infolist() if not i.is_dir()]
    if any(PurePosixPath(n).name.lower() in ("conversations.json", "memories.json", "projects.json") for n in names):
        return False
    if _shape(names):
        return True
    parts = [i for i in zf.infolist() if i.filename.lower().endswith(".zip") and i.file_size <= MAX_PART_BYTES]
    for info in parts:
        data = _bounded(zf, info, MAX_PART_BYTES)
        if data is None:
            continue
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as inner:
                if _shape([i.filename for i in inner.infolist() if not i.is_dir()]):
                    return True
        except zipfile.BadZipFile:
            continue
    return False


def parse_date(text: str | None) -> datetime | None:
    """A Notion date cell as an aware instant: ISO first, then the formats Notion writes ("October 1, 2026 3:04 PM",
    "2026/10/01"). A time with no offset is this Mac's local time — the export is the person's own."""
    raw = " ".join(str(text or "").split())
    if not raw:
        return None
    raw = raw.split(" → ")[0].strip()          # a date range: its start
    raw = re.sub(r"\s*\((?:[A-Z]{2,5}|GMT[+-]?\d*|UTC)\)$", "", raw)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        parsed = None
        for fmt in _FORMATS:
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    return parsed if parsed.tzinfo is not None else parsed.astimezone()


def _when(props: dict[str, str]) -> datetime | None:
    lowered = {k.strip().lower(): v for k, v in props.items()}
    for keys in (_CREATED, _EDITED):
        for key in keys:
            if (at := parse_date(lowered.get(key))) is not None:
                return at
    return None


def _decode(data: bytes) -> str:
    return data.decode("utf-8-sig", errors="replace").replace("\r\n", "\n")


def _links(text: str) -> str:
    """A link to another page of the export (a relative path) becomes its words; an embedded file is left out; a web
    link stays as written."""
    def swap(m: re.Match) -> str:
        bang, words, target = m.group(1), m.group(2), m.group(3)
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
            return m.group(0)
        return "" if bang else words
    return _REL_LINK.sub(swap, text)


def _split_page(text: str, *, row: bool) -> tuple[str | None, dict[str, str], str]:
    """``(title from the H1, properties, the rest)``. Only a database row's page has a property block: on a plain page
    a first line like "Note: …" is the person's words, never a property."""
    lines = text.split("\n")
    title = None
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and lines[i].startswith("# "):
        title = lines[i][2:].strip()
        i += 1
    props: dict[str, str] = {}
    if row:
        while i < len(lines) and not lines[i].strip():
            i += 1
        j = i
        while j < len(lines) and (m := _PROPERTY.match(lines[j])):
            props[m.group("key").strip()] = m.group("value").strip()
            j += 1
        if props and (j == len(lines) or not lines[j].strip()):
            i = j
        else:
            props = {}
    return title, props, "\n".join(lines[i:]).strip()


def _clip(text: str, cap: int = TITLE_CAP) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= cap else text[: cap - 1].rstrip() + "…"


def _norm(title: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", title.lower())


def _episode(source_id: str, title: str, body: str, when: datetime | None, extra: dict) -> dict:
    source = ORIGIN if when is not None else UNDATED_SOURCE
    # `source` rides the extras too: the stager merges extras on every update, so a row that gains a date (or loses
    # one) moves between timed and untimed in place.
    ep = {"title": _clip(title) or "Untitled", "source_id": source_id, "source": source, "origin": ORIGIN,
          "body": body, "writer": SCRUB_WRITER, "extra": {"evidence_kind": "user", **extra, "source": source}}
    if when is not None:
        ep["timestamp"] = when.astimezone(timezone.utc).isoformat()
        ep["original_date"] = episode_ids.id_day(when.astimezone(timezone.utc))
    return ep


def _sections(source_id: str, title: str, head: str, content: str, when: datetime | None,
              extra: dict) -> list[dict]:
    """One episode per page, or one per H2 section of a long one (the watched folders' rule, so Sleep never reads one
    enormous unit) — each section keyed ``notion:<id>#<slug>``."""
    if len(content) <= folder_source.SPLIT_CHARS:
        return [_episode(source_id, title, (head + "\n\n" + content).strip() if content else head, when, extra)]
    out = []
    for slug, heading, section in folder_source.split_sections(content):
        out.append(_episode(f"{source_id}#{slug}", f"{title} › {heading}" if heading else title,
                            (head + "\n\n" + section.strip()).strip(), when, extra))
    return out


def _fold(name: str) -> str:
    return " ".join(str(name or "").casefold().split())


def _author(props: dict[str, str]) -> str | None:
    lowered = {k.strip().lower(): v for k, v in props.items()}
    return next((lowered[k].strip() for k in _AUTHOR if (lowered.get(k) or "").strip()), None)


def _by_other(author: str | None, owners: set[str], authors_in_db: set[str]) -> bool:
    """Whether a row is someone else's words. Its "Created by" decides: the owner's own name (or alias) is the person;
    any other name is not. With no owner name known, a database written by more than one person marks every row as
    not the person's own — a shared table's rows are never credited to them on a guess. No "Created by" (a plain page,
    a database without that property): the person's export, the person's words."""
    if not author:
        return False
    if owners:
        return _fold(author) not in owners
    return len(authors_in_db) > 1


def _score(page_props: dict[str, str], csv_props: dict[str, str]) -> int:
    norm = {k.strip().lower(): " ".join(v.split()) for k, v in csv_props.items()}
    return sum(1 for k, v in page_props.items() if norm.get(k.strip().lower()) == " ".join(v.split()) and v.strip())


def parse_zip(zf: zipfile.ZipFile, owner_names: tuple[str, ...] | list[str] = ()) -> Parsed:
    owners = {_fold(n) for n in owner_names if str(n or "").strip()}
    read = _files(zf)
    files = read.files
    out = Parsed()
    pages: dict[str, tuple[str, bytes]] = {}          # path -> (page id, bytes)
    tables: dict[str, PurePosixPath] = {}              # "<parent>/<db stem>" -> csv path (the _all one wins)
    for name, data in files:
        path = PurePosixPath(name)
        if path.suffix.lower() == ".md":
            _, pid = _split(path.stem)
            if pid:
                pages[name] = (pid, data)
            else:
                read.others += 1
            continue
        stem = path.stem
        key = str(path.parent / stem.removesuffix("_all"))
        if _split(stem.removesuffix("_all"))[1] and (stem.endswith("_all") or key not in tables):
            tables[key] = path
    blobs = dict(files)
    parsed_pages: dict[str, tuple[str | None, dict[str, str], str]] = {}

    def page_of(name: str, *, row: bool) -> tuple[str | None, dict[str, str], str]:
        if name not in parsed_pages:
            parsed_pages[name] = _split_page(_decode(pages[name][1]), row=row)
        return parsed_pages[name]

    def crumbs(path: PurePosixPath) -> list[str]:
        return [_split(part)[0] for part in path.parent.parts if _split(part)[1]]

    used: set[str] = set()
    authors_by_db: dict[str, set[str]] = {}
    # Database rows: the CSV's row joined to the row's own page, in the database's folder.
    for key, csv_path in sorted(tables.items()):
        db_title, db_id = _split(PurePosixPath(key).name)
        row_pages = sorted(n for n in pages if str(PurePosixPath(n).parent) == key)
        by_title: dict[str, list[str]] = {}
        for n in row_pages:
            by_title.setdefault(_norm(_split(PurePosixPath(n).stem)[0]), []).append(n)
        reader = csv.reader(io.StringIO(_decode(blobs[str(csv_path)])))
        header = next(reader, None) or []
        if not header:
            continue
        out.members.append(csv_path.name)
        title_key = header[0].strip()
        rows = []
        for cells in reader:
            if any(c.strip() for c in cells):
                rows.append({h.strip(): (cells[i].strip() if i < len(cells) else "")
                             for i, h in enumerate(header) if h.strip()})
        authors = authors_by_db.setdefault(key, set())
        authors |= {_fold(a) for r in rows if (a := _author(r))}
        seen_titles: dict[str, int] = {}
        for props in rows:
            title = props.get(title_key, "") or "Untitled"
            norm = _norm(title)
            candidates = [n for n in by_title.get(norm, []) if n not in used]
            if not candidates:   # Notion cuts a long title in the file name: a page name the title starts with
                candidates = [n for t, ns in by_title.items() if t and norm.startswith(t) for n in ns if n not in used]
            content = ""
            if candidates:
                # B3 — rows that share a title ("Untitled") each take the page whose own properties agree with the
                # row, never merely the first in file order, and the page's own properties win: a re-export in another
                # sort order can never swap two rows' dates or statuses.
                match = max(candidates, key=lambda n: (_score(page_of(n, row=True)[1], props), -candidates.index(n)))
                used.add(match)
                _, page_props, content = page_of(match, row=True)
                props = {**props, **page_props}
                source_id = SOURCE_PREFIX + pages[match][0]
            else:
                seen_titles[norm] = seen_titles.get(norm, 0) + 1
                digest = hashlib.sha256(title.encode()).hexdigest()[:12]
                n = seen_titles[norm]
                source_id = f"{SOURCE_PREFIX}{db_id}:{digest}" + (f"-{n}" if n > 1 else "")
            other = _by_other(_author(props), owners, authors)
            out.episodes += _row(source_id, title, db_title, db_id, props, title_key,
                                 crumbs(PurePosixPath(key + ".csv")), content, by_other=other)
            out.rows += 1
            out.by_others += int(other)
    # Every other page: a database row with no CSV line, or a plain page.
    for name in sorted(pages):
        if name in used:
            continue
        pid = pages[name][0]
        path = PurePosixPath(name)
        parent = str(path.parent)
        row = parent in tables
        h1, props, content = page_of(name, row=row)
        title = h1 or _split(path.stem)[0] or "Untitled"
        trail = crumbs(path)
        if row:
            db_title, db_id = _split(PurePosixPath(parent).name)
            author = _author(props)
            other = _by_other(author, owners, authors_by_db.get(parent, set()) | ({_fold(author)} if author else set()))
            out.episodes += _row(SOURCE_PREFIX + pid, title, db_title, db_id, props, None, trail[:-1], content,
                                 by_other=other)
            out.rows += 1
            out.by_others += int(other)
            continue
        content = _links(content)
        if not content.strip():
            continue        # a title over its sub-pages and nothing else: the sub-pages carry the words
        head = f"# {_clip(title)}" + (f"\n\n**In:** {' › '.join(trail)}" if trail else "")
        out.episodes += _sections(SOURCE_PREFIX + pid, title, head, content, None, {"notion_kind": "page"})
        out.pages += 1
    if out.pages + out.rows > MAX_PAGES:
        raise ValueError(f"This export holds more than {MAX_PAGES:,} pages; export a smaller part of the workspace.")
    out.members = (out.members + sorted({PurePosixPath(n).name for n in pages if n not in used}))[:MEMBERS_SHOWN]
    if read.others:
        n = read.others
        out.warnings.append(f"{n} other file{'' if n == 1 else 's'} in the export (images, attachments) "
                            f"{'is' if n == 1 else 'are'} left out, never read.")
    for line in read.skipped[:10]:
        out.warnings.append(f"Left out: {line}.")
    if len(read.skipped) > 10:
        out.warnings.append(f"…and {len(read.skipped) - 10} more left out.")
    if out.by_others:
        n = out.by_others
        out.warnings.append(f"{n} database row{'' if n == 1 else 's'} {'was' if n == 1 else 'were'} created by someone "
                            "else and kept as their words, not yours.")
    return out


def _row(source_id: str, title: str, db_title: str, db_id: str | None, props: dict[str, str],
         title_key: str | None, trail: list[str], content: str, *, by_other: bool = False) -> list[dict]:
    lines = [f"# {_clip(title)}", "", f"**Database:** {_clip(db_title)}" + (f" (in {' › '.join(trail)})" if trail
                                                                              else "")]
    for key, value in props.items():
        if key == title_key or not value.strip():
            continue
        lines.append(f"**{_clip(key, 60)}:** {_clip(value, PROPERTY_CAP)}")
    extra = {"notion_kind": "row", "notion_by_other": by_other}
    if by_other:
        extra["evidence_kind"] = "assistant"     # someone else's words, never the person's (the folder rule)
    if db_id:
        extra["notion_database"] = db_id
    return _sections(source_id, title, "\n".join(lines), _links(content), _when(props), extra)
