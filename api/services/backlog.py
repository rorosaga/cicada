"""G150 — a project's backlog is memory: one markdown file per item, and this
module is the ONE reader and writer of them.

Before G150, "put it in the backlog" meant an agent edited a markdown table in
some repository (the owner, 2026-09-24: "that backlog itself i believe should
go in cicada project memory … with the brief task and an appended
notes/description"). The table was invisible to Cicada, to every other agent
and to the person's own app. Now each item lives in the bank beside the
project it belongs to — `backlog/<project-id>/<item-id>.md` — with
frontmatter for what a list needs, a `## Description` for the reasoning, and
`## Notes`, an append-only log signed by whoever wrote each entry (R-B1).

Every path goes through here — REST (`routers/backlog.py`), MCP
(`mcp_tools.backlog` and its two writers, stdio and remote), the importer
(`backlog_import.py`) and the demo generator — so the id rule, the scrub, the
append-only notes and the status alphabet cannot drift between writers (the
`progress.py` precedent, G141 §5.1). Callers pass the ACTIVE bank's path (the
split-brain rule) and commit the memory-relative `paths` a write returns
themselves, each under its own author and trigger (R-B7). Nothing here
commits, and nothing here raises on a normal input: a refusal is a dict whose
`action` is `error`, `not_found`, `duplicate` or `exists`, with one `error`
sentence, and it wrote nothing (the `agentic_write` contract).

The rails, each a G150 ruling:

* **Never an entity page** (R-B1, R-B3). This module never writes
  `entities/`: no `last_referenced` bump, no prefix, no claim.
* **Ids are addresses** (R-B2): `<PREFIX><n>`, max+1 per prefix (G114's
  lesson), claimed by an exclusive create so the backend and every stdio MCP
  process can mint at once.
* **Notes are append-only** (R-B4, R-B5): git history is a note's edit log,
  and a status move is itself a signed note.
* **Scrubbed** (R-B10): a description is where a pasted key lands.
"""
from __future__ import annotations

import fcntl
import os
import re
import unicodedata
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml
from loguru import logger

from api.services import bank_index, markdown_parser

BACKLOG_DIR = "backlog"
STATUSES = ("open", "doing", "done", "dropped")
OPEN_STATUSES = frozenset({"open", "doing"})
TRIAGES = ("apply", "research", "decide")
LINK_KINDS = ("pr", "commit", "url", "doc", "entity")
USER = "user"
CICADA = "cicada"
AGENT = "agent"
TITLE_CHARS = 200
DESCRIPTION_CHARS = 20_000
NOTE_CHARS = 8_000
LINK_CHARS = 500
MAX_LINKS = 20
MINT_TRIES = 50
# Bumped when a reader's wire changes shape for the same files; the REST ETags
# fold it beside `git_service.AUTHOR_SHAPE` (R-B18).
BACKLOG_SHAPE = "g150-1"
ID_RE = re.compile(r"^([A-Z]{1,6})(\d{1,6})([a-z]?)$")
_LOOSE_ID = re.compile(r"^([A-Za-z]{1,6})(\d{1,6})([A-Za-z]?)$")
_PREFIX_RE = re.compile(r"^[A-Z]{1,6}$")
_NOTE_HEAD = re.compile(r"^### (\d{4}-\d{2}-\d{2}) · (.+?)[ \t]*$", re.M)
_HEADING = re.compile(r"(?m)^#{1,3}(?=[ \t])")
DESCRIPTION_HEAD = "## Description"
NOTES_HEAD = "## Notes"
NO_DESCRIPTION = "_No description yet._"


@dataclass
class Note:
    """One `### <day> · <who>` entry (R-B4). `by`, `at` and `session` come
    from the frontmatter sidecar; a note appended by hand has none of them."""
    day: str
    who: str
    text: str
    by: str | None = None
    at: str | None = None
    session: str | None = None


@dataclass
class Item:
    id: str
    project: str
    title: str
    status: str = "open"
    triage: str | None = None
    paid: bool = False
    created: str = ""
    updated: str = ""
    added_by: str = USER
    session: str | None = None
    links: list[dict] = field(default_factory=list)
    order: int | None = None
    description: str = ""
    notes: list[Note] = field(default_factory=list)
    # From the sidecar when only the frontmatter was read (a list row).
    note_count: int = 0
    last_note_at: str | None = None
    last_note_by: str | None = None

    @property
    def path(self) -> str:
        """Memory-relative — what a caller commits and a commit line names."""
        return f"{BACKLOG_DIR}/{self.project}/{self.id}.md"


def _error(message: str, **extra) -> dict:
    return {"action": "error", "error": message, **extra}


# --------------------------------------------------------------------------- #
# who and when
# --------------------------------------------------------------------------- #


def author_id(author: str | None) -> str:
    value = (author or "").strip()
    return value or AGENT


def who_label(by: str | None) -> str:
    """A note heading's words for an author id (R-B4): "You", "Cicada", a
    harness's product name through the one harness → name map, else "An
    agent" — `fact_sources.voiced_hint`'s rule, so an agent is named the same
    way on a conflict card and in a backlog note."""
    value = (by or "").strip()
    if value == USER:
        return "You"
    if value == CICADA:
        return "Cicada"
    from api.services.source_overview import HARNESS_LABELS, UNKNOWN

    label = HARNESS_LABELS.get(value) if value != UNKNOWN else None
    return label or "An agent"


def author_of(note: Note) -> str:
    """The author id behind a note: the sidecar's, else read back from the
    heading's words — a hand-written "You" is the person (R-B4)."""
    if note.by:
        return note.by
    if note.who == "You":
        return USER
    if note.who == "Cicada":
        return CICADA
    from api.services.source_overview import HARNESS_LABELS

    return next((k for k, v in HARNESS_LABELS.items() if v == note.who), AGENT)


def _clock(now: datetime | None, tz_name: str | None) -> tuple[str, str]:
    """`(day, at)`: the writer's day in the machine zone (R-B11 — the person's
    calendar, like every G141 date) and the UTC instant to the second,
    `Z`-suffixed — round 4's C2 `recorded_ts` shape, so a note can be joined
    to the turn it was written in at read (R-B6)."""
    from api.services import handshake, when

    tz = when.zone(tz_name or handshake.local_timezone())
    instant = (now or datetime.now(tz)).replace(microsecond=0)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=tz)
    return instant.astimezone(tz).date().isoformat(), when.utc_z(instant)


def local_day(at: str | None, tz_name: str | None) -> str | None:
    """The day an instant fell on in `tz_name` — the wire's `lastNoteDay`."""
    from api.services import when

    instant = when.parse_instant(at) if at else None
    return instant.astimezone(when.zone(tz_name)).date().isoformat() if instant else None


def status_line(old: str, new: str) -> str:
    return f"Moved from {old} to {new}."


# --------------------------------------------------------------------------- #
# projects and ids
# --------------------------------------------------------------------------- #


def project_page(memory_path: Path, project: str) -> tuple[str, dict] | dict:
    """`(stem, frontmatter)` for a live project page, or a refusal (R-B14).

    Resolves ids, names and aliases like every project reader; re-reads the
    real stem on a case-insensitive filesystem (`progress._page`'s reason). A
    miss, a non-project and a dropped page are refused, and nothing here ever
    creates a page."""
    from api.services.id_utils import resolve_entity_file

    ref = (project or "").strip()
    page = resolve_entity_file(Path(memory_path), ref) if ref else None
    if page is None or not page.is_file():
        return {"action": "not_found", "error": f"no project {ref!r}; nothing was written"}
    page = next((f for f in page.parent.glob("*.md") if f.name.lower() == page.name.lower()), page)
    try:
        fm = markdown_parser.parse(page).frontmatter or {}
    except Exception:  # noqa: BLE001 — an unreadable page is a refusal, never a raise
        return _error(f"{page.stem} can't be read; nothing was written")
    kind = str(fm.get("type") or "page")
    if kind != "project":
        return {"action": "not_found", "error": f"{page.stem} is a {kind}, not a project; nothing was written"}
    if str(fm.get("status") or "active") == "dropped":
        return {"action": "not_found", "error": f"{page.stem} was dropped from memory; nothing was written"}
    return page.stem, fm


def initials(name: str) -> str:
    """R-B2's default prefix: the first letters of up to four words, or the
    first three letters of a one-word name ("Orchard" → ORC, "Rover Arm
    Project" → RAP). ASCII letters only after NFKD folding, so an id is
    typeable anywhere; "T" (task) when nothing is left."""
    folded = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii")
    words = [w for w in re.split(r"[^A-Za-z0-9]+", folded) if w and w[0].isalpha()]
    if not words:
        return "T"
    if len(words) == 1:
        return re.sub(r"[^A-Z]", "", words[0].upper())[:3] or "T"
    return "".join(w[0].upper() for w in words[:4])


def _folder(memory_path: Path, stem: str) -> Path:
    return Path(memory_path) / BACKLOG_DIR / stem


def _item_files(memory_path: Path, stem: str) -> list[Path]:
    folder = _folder(memory_path, stem)
    return sorted(p for p in folder.glob("*.md") if p.is_file()) if folder.is_dir() else []


def prefix_for(memory_path: Path, stem: str, fm: dict | None) -> str:
    """R-B2: the page's `backlog_prefix:`, else the prefix most of the
    project's items already share (ties alphabetical) — so an imported G-row
    backlog continues at G<max+1> without this module ever writing an entity
    page (R-B3) — else the name's initials."""
    stated = str((fm or {}).get("backlog_prefix") or "").strip().upper()
    if _PREFIX_RE.match(stated):
        return stated
    shared = Counter(m.group(1) for m in (ID_RE.match(p.stem) for p in _item_files(memory_path, stem)) if m)
    if shared:
        top = max(shared.values())
        return sorted(k for k, v in shared.items() if v == top)[0]
    return initials(str((fm or {}).get("name") or stem.replace("-", " ")))


def next_number(memory_path: Path, stem: str, prefix: str) -> int:
    """1 + the highest number already filed under `prefix` — never a count
    (G114: a count collides after any gap)."""
    top = 0
    for p in _item_files(memory_path, stem):
        m = ID_RE.match(p.stem)
        if m and m.group(1) == prefix:
            top = max(top, int(m.group(2)))
    return top + 1


def normalize_id(raw: str | None) -> str | None:
    """`rap3` → `RAP3`, `G074a` → `G74a`; anything else (a path, a word) → None."""
    m = _LOOSE_ID.match((raw or "").strip())
    return f"{m.group(1).upper()}{int(m.group(2))}{m.group(3).lower()}" if m else None


def item_path(memory_path: Path, stem: str, item: str) -> Path | None:
    iid = normalize_id(item)
    if iid is None:
        return None
    exact = _folder(memory_path, stem) / f"{iid}.md"
    if exact.is_file():
        return exact
    return next((p for p in _item_files(memory_path, stem) if p.stem.upper() == iid.upper()), None)


def resolve_item(memory_path: Path, ref: str, project: str | None = None) -> tuple[str, str] | dict:
    """An item named the way an agent names it (R-B13): `RAP3`,
    `rover-arm-project/RAP3`, or `RAP3` with `project`. A bare id two
    projects both hold is refused with both addresses — never guessed."""
    raw = (ref or "").strip()
    if "/" in raw:
        project, raw = raw.rsplit("/", 1)
    iid = normalize_id(raw)
    if iid is None:
        return _error(f"{ref!r} isn't an item id like RAP3; nothing was read")
    if project:
        got = project_page(memory_path, project)
        if isinstance(got, dict):
            return got
        stem = got[0]
        if item_path(memory_path, stem, iid) is None:
            return {"action": "not_found", "error": f"no {iid} on {stem}'s backlog"}
        return stem, iid
    root = Path(memory_path) / BACKLOG_DIR
    holders = sorted(d.name for d in root.iterdir()
                     if d.is_dir() and item_path(memory_path, d.name, iid) is not None) if root.is_dir() else []
    if not holders:
        return {"action": "not_found", "error": f"no backlog item {iid}"}
    if len(holders) > 1:
        both = ", ".join(f"{h}/{iid}" for h in holders)
        return _error(f"{iid} is on more than one backlog ({both}) — name it as <project>/{iid}")
    return holders[0], iid


# --------------------------------------------------------------------------- #
# text
# --------------------------------------------------------------------------- #


def _scrub(text: str | None, bank: str) -> str:
    """R-B10: every writer scrubs, and the count is ledgered as `backlog`."""
    from api.services import episode_scrub

    cleaned, n = episode_scrub.scrub(text or "")
    episode_scrub.record("backlog", n, bank=bank)
    return cleaned


def _block(text: str, cap: int) -> str:
    """Markdown made safe for the item's own structure (R-B4): trimmed,
    capped, and every level 1–3 heading demoted to `####`, so a pasted
    "## Notes" or "### 2026-09-01 · You" can never start a section or forge a
    note. Nothing else about the markdown changes.

    Every line break is normalised first, a lone `\r` included (task 1 review
    round 1): the heading pattern never saw one as a line start, but
    `markdown_parser.parse` reads the file back with universal newlines, so
    "x\r### 2026-01-01 · You" read back as a note signed by the person."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return _HEADING.sub("####", text)[:cap].rstrip()


def _title(text: str) -> str:
    return " ".join((text or "").split())[:TITLE_CHARS]


def fold_title(text: str) -> str:
    """R-B9's comparison: lower case, single spaces — exact, never fuzzy."""
    return " ".join((text or "").lower().split())


def validate_links(raw) -> list[dict] | str:
    """`[{kind, ref}]` for a write, or one sentence saying what is wrong — a
    writer names a bad kind rather than having it dropped silently."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        return "links is a list of {kind, ref}; nothing was written"
    out: list[dict] = []
    for entry in raw:
        kind = str(entry.get("kind") or "").strip().lower() if isinstance(entry, dict) else ""
        ref = " ".join(str(entry.get("ref") or "").split())[:LINK_CHARS] if isinstance(entry, dict) else ""
        if kind not in LINK_KINDS or not ref:
            return f"a link is {{kind, ref}} with kind one of {', '.join(LINK_KINDS)}; nothing was written"
        if {"kind": kind, "ref": ref} not in out:
            out.append({"kind": kind, "ref": ref})
    return out[:MAX_LINKS]


def _clean_links(raw) -> list[dict]:
    """The reader's half: a hand-edited bad entry is skipped, never raised."""
    out: list[dict] = []
    for entry in raw if isinstance(raw, list) else []:
        if isinstance(entry, dict):
            kind = str(entry.get("kind") or "").strip().lower()
            ref = str(entry.get("ref") or "").strip()
            if kind in LINK_KINDS and ref and {"kind": kind, "ref": ref} not in out:
                out.append({"kind": kind, "ref": ref})
    return out[:MAX_LINKS]


def _find_heading(text: str, heading: str) -> int:
    m = re.search(rf"(?m)^{re.escape(heading)}[ \t]*$", text)
    return m.start() if m else -1


def parse_body(body: str) -> tuple[str, list[tuple[str, str, str]]]:
    """`(description, [(day, who, text)])` from an item's body. Tolerant: a
    body with no `## Description` is all description, and text under
    `## Notes` before its first note is kept as the description's tail —
    never dropped."""
    text = body or ""
    at = _find_heading(text, NOTES_HEAD)
    head, tail = (text[:at], text[at + len(NOTES_HEAD):]) if at >= 0 else (text, "")
    d = _find_heading(head, DESCRIPTION_HEAD)
    description = (head[d + len(DESCRIPTION_HEAD):] if d >= 0 else head).strip()
    if description == NO_DESCRIPTION:
        description = ""
    heads = list(_NOTE_HEAD.finditer(tail))
    stray = (tail[: heads[0].start()] if heads else tail).strip()
    if stray:
        description = f"{description}\n\n{stray}".strip()
    notes = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(tail)
        notes.append((m.group(1), m.group(2).strip(), tail[m.end():end].strip()))
    return description, notes


def render_body(description: str, notes: list[Note]) -> str:
    parts = [DESCRIPTION_HEAD, "", description.strip() or NO_DESCRIPTION, "", NOTES_HEAD]
    for n in notes:
        parts += ["", f"### {n.day} · {n.who}", "", n.text.strip()]
    return "\n".join(parts)


def _sidecar(fm: dict | None) -> list[dict]:
    """The `notes:` sidecar, positions kept (a malformed entry is `{}`)."""
    raw = (fm or {}).get("notes")
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for entry in raw:
        entry = entry if isinstance(entry, dict) else {}
        out.append({k: str(entry[k]) for k in ("by", "at", "session") if entry.get(k) not in (None, "")})
    return out


def _render(item: Item) -> str:
    """R-B1's key order; empty keys omitted; the sidecar last, like `turns`."""
    fm: dict = {"id": item.id, "title": item.title, "project": item.project, "status": item.status}
    if item.triage:
        fm["triage"] = item.triage
    if item.paid:
        fm["paid"] = True
    fm["created"] = item.created
    fm["updated"] = item.updated
    fm["added_by"] = item.added_by
    if item.session:
        fm["session"] = item.session
    if item.links:
        fm["links"] = item.links
    if item.order is not None:
        fm["order"] = item.order
    if item.notes:
        fm["notes"] = [{k: v for k, v in (("at", n.at), ("by", n.by), ("session", n.session)) if v}
                       for n in item.notes]
    dumped = yaml.dump(fm, default_flow_style=False, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{dumped}\n---\n\n{render_body(item.description, item.notes)}\n"


# --------------------------------------------------------------------------- #
# reading
# --------------------------------------------------------------------------- #


def _from_fm(fm: dict, path: Path, stem: str) -> Item:
    """A list row from frontmatter alone (R-B2: the file name is the id)."""
    side = _sidecar(fm)
    last = side[-1] if side else {}
    status = str(fm.get("status") or "open").strip().lower()
    triage = str(fm.get("triage") or "").strip().lower() or None
    order = fm.get("order")
    return Item(
        id=path.stem, project=stem, title=str(fm.get("title") or path.stem),
        status=status if status in STATUSES else "open",
        triage=triage if triage in TRIAGES else None, paid=fm.get("paid") is True,
        created=str(fm.get("created") or "")[:10], updated=str(fm.get("updated") or fm.get("created") or "")[:10],
        added_by=str(fm.get("added_by") or USER), session=str(fm.get("session") or "") or None,
        links=_clean_links(fm.get("links")),
        order=order if isinstance(order, int) and not isinstance(order, bool) else None,
        note_count=len(side), last_note_at=last.get("at"), last_note_by=last.get("by"))


def _read(path: Path, stem: str) -> Item | None:
    try:
        parsed = markdown_parser.parse(path)
    except Exception as exc:  # noqa: BLE001 — one unreadable file never fails a caller
        logger.warning(f"backlog: skipping unreadable {path.name}: {type(exc).__name__}")
        return None
    item = _from_fm(parsed.frontmatter or {}, path, stem)
    description, raw = parse_body(parsed.body)
    side = _sidecar(parsed.frontmatter)
    if len(side) > len(raw):
        side = []   # R-B4: a note deleted by hand — positions no longer mean anything
    item.description = description
    item.notes = [Note(day=d, who=w, text=t, **(side[i] if i < len(side) else {}))
                  for i, (d, w, t) in enumerate(raw)]
    item.note_count = len(item.notes)
    item.last_note_at = item.notes[-1].at if item.notes else None
    item.last_note_by = author_of(item.notes[-1]) if item.notes else None
    return item


def sort_items(items: list[Item]) -> list[Item]:
    """R-B19's order: a hand-set `order` first (ascending), then the most
    recently touched, then the highest number — stable sorts, last key first."""
    def number(i: Item) -> int:
        m = ID_RE.match(i.id)
        return int(m.group(2)) if m else 0

    out = sorted(items, key=number, reverse=True)
    out.sort(key=lambda i: (i.updated, i.last_note_at or ""), reverse=True)
    out.sort(key=lambda i: (i.order is None, i.order if i.order is not None else 0))
    return out


def list_items(memory_path: Path, stem: str) -> list[Item]:
    """Every item of a project from frontmatter alone — `bank_index`'s cache,
    no body parse — in R-B19's order. A file whose name is not an id, or
    whose frontmatter will not parse, is skipped."""
    files = bank_index.files(Path(memory_path), f"{BACKLOG_DIR}/{stem}")
    return sort_items([_from_fm(f.frontmatter or {}, f.path, stem) for f in files if ID_RE.match(f.path.stem)])


def get_item(memory_path: Path, stem: str, item: str) -> Item | None:
    path = item_path(memory_path, stem, item)
    return _read(path, stem) if path is not None else None


def counts(items: list[Item]) -> dict[str, int]:
    out = {s: 0 for s in STATUSES}
    for i in items:
        out[i.status] = out.get(i.status, 0) + 1
    return out


def open_counts(memory_path: Path) -> dict[str, int]:
    """`{project: n}` of items `open` or `doing` — `_state.md`'s
    `backlog_open` (R-B16); a project with none is absent."""
    root = Path(memory_path) / BACKLOG_DIR
    out: dict[str, int] = {}
    if root.is_dir():
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            n = sum(1 for i in list_items(memory_path, folder.name) if i.status in OPEN_STATUSES)
            if n:
                out[folder.name] = n
    return out


def stamp(memory_path: Path) -> str:
    """`sync_service`'s `backlog` component (R-B16): folders, item files and
    the newest mtime, from a stat walk two levels deep — no parse, so
    `GET /sync/version` stays well under 10 ms."""
    root = Path(memory_path) / BACKLOG_DIR
    dirs = files = newest = 0
    try:
        with os.scandir(root) as outer:
            for d in outer:
                if not d.is_dir():
                    continue
                dirs += 1
                # The folder's own mtime moves on any create, rename or
                # unlink inside it, so a hand rename that keeps the file's
                # mtime still moves the stamp (review round 1).
                newest = max(newest, d.stat().st_mtime_ns)
                with os.scandir(d.path) as inner:
                    for e in inner:
                        if e.is_file() and e.name.endswith(".md"):
                            files += 1
                            newest = max(newest, e.stat().st_mtime_ns)
    except OSError:
        # Missing, a plain file, or unreadable: degrade to the partial counts
        # rather than raise into every sync read (review round 1).
        pass
    return f"{dirs}:{files}:{newest}"


# --------------------------------------------------------------------------- #
# writing
# --------------------------------------------------------------------------- #


def _claim(path: Path, text: str) -> bool:
    """Create `path` only if nobody has (`O_EXCL`) — R-B2's cross-process
    half: the backend and every stdio MCP process mint in the same folder,
    and check-then-write would let two of them take one number."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return True


@contextmanager
def _locked(path: Path):
    """An exclusive advisory lock on the item file for one read-modify-write
    — two processes appending notes to one item never lose one."""
    fd = os.open(path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield fd
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _write_fd(fd: int, text: str) -> None:
    data = memoryview(text.encode("utf-8"))
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    while data:
        data = data[os.write(fd, data):]


def _session(session: str | None) -> str | None:
    return (session or "").strip() or None


def add_item(memory_path: Path, *, project: str, title: str, description: str = "", author: str,
             triage: str | None = None, paid: bool = False, links=None, session: str | None = None,
             status: str = "open", item_id: str | None = None, created: str | None = None,
             first_note: str | None = None, now: datetime | None = None, tz_name: str | None = None) -> dict:
    """File one item on a project's backlog (R-B1).

    `item_id`, `status`, `created` and `first_note` are the importer's
    (R-B15): an import keeps the file's id and state and says where it came
    from; every other writer mints the next number and opens it. Returns
    `{action: "added", item, paths}`, or a refusal that wrote nothing:
    `not_found` (no such project), `duplicate` (an open item already holds the
    title — R-B9 — with `item_id` and `project`), `exists` (the importer's id is
    taken, with `item_id`) or `error`."""
    try:
        memory_path = Path(memory_path)
        got = project_page(memory_path, project)
        if isinstance(got, dict):
            return got
        stem, fm = got
        bank = memory_path.name
        if status not in STATUSES:
            return _error(f"a status is one of {', '.join(STATUSES)}; nothing was written")
        triage = (triage or "").strip().lower() or None
        if triage is not None and triage not in TRIAGES:
            return _error(f"triage is one of {', '.join(TRIAGES)}; nothing was written")
        links_ok = validate_links(links)
        if isinstance(links_ok, str):
            return _error(links_ok)
        clean_title = _title(_scrub(title, bank))
        if not clean_title:
            return _error("give the item a title — the brief task, in one line; nothing was written")
        if item_id is None:
            folded = fold_title(clean_title)
            clash = next((i for i in list_items(memory_path, stem)
                          if i.status in OPEN_STATUSES and fold_title(i.title) == folded), None)
            if clash is not None:
                return {"action": "duplicate", "item_id": clash.id, "project": stem,
                        "error": f"{clash.id} already holds this — add what you found to it as a note"}
        day, at = _clock(now, tz_name)
        by = author_id(author)
        item = Item(id="", project=stem, title=clean_title, status=status, triage=triage, paid=bool(paid),
                    created=(created or day)[:10], updated=day, added_by=by, session=_session(session),
                    links=[{**link, "ref": _scrub(link["ref"], bank)} for link in links_ok],
                    description=_block(_scrub(description, bank), DESCRIPTION_CHARS))
        if first_note:
            item.notes = [Note(day=day, who=who_label(by), text=_block(_scrub(first_note, bank), NOTE_CHARS),
                               by=by, at=at, session=item.session)]
        folder = _folder(memory_path, stem)
        if item_id is not None:
            iid = normalize_id(item_id)
            if iid is None:
                return _error(f"{item_id!r} isn't an item id; nothing was written")
            item.id = iid
            if not _claim(folder / f"{iid}.md", _render(item)):
                return {"action": "exists", "item_id": iid, "project": stem,
                        "error": f"{iid} is already on this backlog"}
        else:
            prefix = prefix_for(memory_path, stem, fm)
            n = next_number(memory_path, stem, prefix)
            for _ in range(MINT_TRIES):
                item.id = f"{prefix}{n}"
                if _claim(folder / f"{item.id}.md", _render(item)):
                    break
                n += 1
            else:
                return _error("couldn't take a new id; nothing was written")
        item.note_count = len(item.notes)
        item.last_note_at = item.notes[-1].at if item.notes else None
        item.last_note_by = by if item.notes else None
        return {"action": "added", "item": item, "paths": [item.path]}
    except Exception as exc:  # noqa: BLE001 — never raise on a normal input
        logger.warning(f"backlog.add_item failed: {type(exc).__name__}: {exc}")
        return _error(f"{type(exc).__name__}: {exc}")


def _update(memory_path: Path, project: str, item: str, change) -> dict:
    """One locked read-modify-write of an existing item. `change(item)`
    mutates it and returns None, or returns a reply that writes nothing."""
    got = project_page(memory_path, project)
    if isinstance(got, dict):
        return got
    stem = got[0]
    path = item_path(memory_path, stem, item)
    if path is None:
        return {"action": "not_found",
                "error": f"no {normalize_id(item) or item!r} on {stem}'s backlog; nothing was written"}
    with _locked(path) as fd:
        current = _read(path, stem)
        if current is None:
            return _error(f"{path.stem} can't be read; nothing was written")
        verdict = change(current)
        if isinstance(verdict, dict):
            return verdict
        current.note_count = len(current.notes)
        current.last_note_at = current.notes[-1].at if current.notes else None
        current.last_note_by = author_of(current.notes[-1]) if current.notes else None
        _write_fd(fd, _render(current))
    return {"action": "updated", "item": current, "paths": [current.path]}


def add_note(memory_path: Path, *, project: str, item: str, note: str, author: str, status: str | None = None,
             session: str | None = None, now: datetime | None = None, tz_name: str | None = None) -> dict:
    """Append one signed note (R-B4) — and, with `status`, move the item in
    the same write, the move said as the note's last line (R-B5). A note that
    says nothing and moves nothing is `unchanged`, and so is a move to the
    state the item is already in with no words."""
    try:
        memory_path = Path(memory_path)
        if status is not None and status not in STATUSES:
            return _error(f"a status is one of {', '.join(STATUSES)}; nothing was written")
        text = _block(_scrub(note, memory_path.name), NOTE_CHARS)
        if not text and status is None:
            return _error("say what you found; nothing was written")
        by = author_id(author)
        day, at = _clock(now, tz_name)

        def change(it: Item):
            body = text
            if status is not None and status != it.status:
                body = f"{body}\n\n{status_line(it.status, status)}".strip()
                it.status = status
            if not body:
                return {"action": "unchanged", "item": it, "paths": []}
            it.notes.append(Note(day=day, who=who_label(by), text=body, by=by, at=at, session=_session(session)))
            it.updated = day
            return None

        return _update(memory_path, project, item, change)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"backlog.add_note failed: {type(exc).__name__}: {exc}")
        return _error(f"{type(exc).__name__}: {exc}")


def update_item(memory_path: Path, *, project: str, item: str, author: str, title: str | None = None,
                status: str | None = None, triage: str | None = None, paid: bool | None = None, links=None,
                session: str | None = None, now: datetime | None = None, tz_name: str | None = None) -> dict:
    """The person's edits (and a script's): a title, a triage (`""` clears
    it), the 💸 flag, the links, a status. A status move is written as a
    signed note — the one change the card's notes must show (R-B5); the
    others live in git history."""
    try:
        memory_path = Path(memory_path)
        bank = memory_path.name
        if all(v is None for v in (title, status, triage, paid, links)):
            return _error("say what to change: a title, a status, a triage, the paid flag or the links")
        if status is not None and status not in STATUSES:
            return _error(f"a status is one of {', '.join(STATUSES)}; nothing was written")
        new_triage = None if triage is None else (triage.strip().lower() or "")
        if new_triage and new_triage not in TRIAGES:
            return _error(f"triage is one of {', '.join(TRIAGES)}; nothing was written")
        new_title = None if title is None else _title(_scrub(title, bank))
        if title is not None and not new_title:
            return _error("a title can't be empty; nothing was written")
        links_ok = None if links is None else validate_links(links)
        if isinstance(links_ok, str):
            return _error(links_ok)
        by = author_id(author)
        day, at = _clock(now, tz_name)

        def change(it: Item):
            before = (it.title, it.status, it.triage, it.paid, it.links)
            if new_title is not None:
                it.title = new_title
            if new_triage is not None:
                it.triage = new_triage or None
            if paid is not None:
                it.paid = bool(paid)
            if links_ok is not None:
                it.links = [{**link, "ref": _scrub(link["ref"], bank)} for link in links_ok]
            if status is not None and status != it.status:
                it.notes.append(Note(day=day, who=who_label(by), text=status_line(it.status, status), by=by,
                                     at=at, session=_session(session)))
                it.status = status
            if (it.title, it.status, it.triage, it.paid, it.links) == before:
                return {"action": "unchanged", "item": it, "paths": []}
            it.updated = day
            return None

        return _update(memory_path, project, item, change)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"backlog.update_item failed: {type(exc).__name__}: {exc}")
        return _error(f"{type(exc).__name__}: {exc}")


def commit_message(paths: list[str], *, action: str, subject: str, trigger: str, day: str, author: str = USER,
                   session: str | None = None) -> str:
    """The house commit for a backlog write (R-B7): one manifest line per
    file, the author trailer, the conversation when there is one — what
    `parse_cycle_body` and `cicada_timeline` already read."""
    from api.services import git_service

    return git_service.build_commit_message(
        f"{subject} {day}", [f"{p}: {action} (source: n/a, trigger: {trigger})" for p in dict.fromkeys(paths)],
        authors=[author], sessions=[session] if session else None)
