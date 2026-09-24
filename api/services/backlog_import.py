"""G150 R-B15 — file an existing markdown backlog into a project's backlog.

The shape it reads is this repository's own. `docs/goals/memory-evolution.md`
keeps one table row per idea — `| G<n>[ 💸] | **Title** (the owner's words) |
the reasoning | status |` — under `## ` headings that may name a triage, and a
backlog elsewhere may keep `### G<n> — Title` sections with a `Status:` line.
Both are read, for ONE id prefix per run (default `G`, so a file's `R1`
research rows are not filed); nothing else in the file is.

Ids and states are kept — a G-id is a permanent address (CLAUDE.md) — the raw
status cell survives as the first note, and an id already on the backlog is
skipped, never updated: the bank's copy may hold notes the file does not. A
second run therefore changes nothing and commits nothing. Every row goes
through `backlog.add_item` (the ONE writer), so the scrub and the file shape
are every other door's.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from loguru import logger

from api.services import backlog

MAX_CHARS = 2_000_000
IMPORT_TRIGGER = "user/backlog_import"
PAID = "💸"
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_DATE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")
_PR = re.compile(r"\bPR\s*#(\d+)")
_CELL = re.compile(r"(?<!\\)\|")
_HEADING = re.compile(r"^#{1,3}\s")
_STATUS_LINE = re.compile(r"^\s*(?:\*\*)?status(?:\*\*)?\s*:\s*(?:\*\*)?\s*(?P<s>.+?)\s*$", re.I)
# R-B15: the FIRST mark in a status cell wins ("🛠️ slice 1 ✅; slice 2 open" is
# still under way). A variation selector after a mark (🛠️, 🅿️) does not
# matter to `in`.
_MARKS = (("✅", "done"), ("🛠", "doing"), ("🟡", "doing"), ("🔬", "doing"),
          ("🔲", "open"), ("❓", "open"), ("🅿", "open"))
_HINTS = {"❓": "decide", "🔬": "research"}
_TRIAGE_WORDS = {"APPLY": "apply", "RESEARCH": "research", "DECIDE": "decide"}


@dataclass
class Row:
    id: str
    title: str
    description: str
    status_cell: str
    triage: str | None
    paid: bool
    created: str | None


@dataclass
class ImportReport:
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    error: str | None = None


def status_of(cell: str) -> tuple[str, str | None]:
    """`(status, triage hint)` for a status cell: the first mark decides;
    with none, "merged", "closed" or a bare dash mean the row was set aside."""
    text = cell or ""
    hits = sorted((text.find(mark), state, mark) for mark, state in _MARKS if mark in text)
    if hits:
        _pos, state, mark = hits[0]
        return state, _HINTS.get(mark)
    low = text.strip().lower()
    if low in ("—", "–", "-") or "merged" in low or "closed" in low:
        return "dropped", None
    return "open", None


def _cells(line: str) -> list[str]:
    parts = _CELL.split(line.strip())
    return [p.strip().replace("\\|", "|") for p in parts[1:-1]]


def _plain(text: str) -> str:
    text = _MD_LINK.sub(r"\1", text or "")
    return " ".join(re.sub(r"[*_`]", "", text).split()).strip(" ()")


def _title(cell: str) -> tuple[str, str]:
    """The item cell's first bold span is the brief task; what surrounds it
    (the owner's quoted words, a date) opens the description. A row with no
    bold span — a merged row's italic note — is its own title."""
    m = _BOLD.search(cell or "")
    if m is None:
        return _plain(cell), ""
    return _plain(m.group(1)), (cell[: m.start()] + cell[m.end():]).strip()


def _table_row(cells: list[str], triage: str | None, heading_date: str | None) -> Row:
    title, rest = _title(cells[1])
    if len(cells) >= 4:
        reasoning, status_cell = " | ".join(cells[2:-1]), cells[-1]
    else:
        reasoning, status_cell = cells[2], ""
    date = _DATE.search(cells[1])
    return Row(id=cells[0].replace(PAID, "").strip(), title=title,
               description="\n\n".join(x for x in (rest, reasoning) if x.strip()), status_cell=status_cell.strip(),
               triage=triage, paid=PAID in cells[0], created=date.group(1) if date else heading_date)


def _section_row(iid: str, heading_rest: str, body: list[str], triage: str | None,
                 heading_date: str | None) -> Row:
    status_cell, kept = "", []
    for line in body:
        m = _STATUS_LINE.match(line)
        if m and not status_cell:
            status_cell = m.group("s")
        else:
            kept.append(line)
    title = _plain(heading_rest.replace(PAID, "").strip().lstrip("—–:·- ").strip())
    date = _DATE.search(heading_rest)
    return Row(id=iid, title=title, description="\n".join(kept).strip(), status_cell=status_cell.strip(),
               triage=triage, paid=PAID in heading_rest, created=date.group(1) if date else heading_date)


def parse(text: str, prefix: str = "G") -> list[Row]:
    """Every row of `prefix` in `text`, in file order. An id seen twice keeps
    its first row — a later mention is a cross-reference, not a new idea."""
    pre = re.escape(prefix)
    head_id = re.compile(rf"^({pre}\d{{1,6}}[a-z]?)\s*(?:{PAID})?\s*$")
    section = re.compile(rf"^###\s+({pre}\d{{1,6}}[a-z]?)\b(.*)$")
    rows: list[Row] = []
    triage: str | None = None
    heading_date: str | None = None
    lines = (text or "").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("## "):
            triage = _TRIAGE_WORDS.get(line[3:].strip().split(" ", 1)[0].strip("*").upper())
            m = _DATE.search(line)
            heading_date = m.group(1) if m else None
            i += 1
            continue
        s = section.match(line)
        if s:
            body: list[str] = []
            j = i + 1
            while j < len(lines) and not _HEADING.match(lines[j]):
                body.append(lines[j])
                j += 1
            rows.append(_section_row(s.group(1), s.group(2), body, triage, heading_date))
            i = j
            continue
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = _cells(stripped)
            if len(cells) >= 3 and head_id.match(cells[0]):
                rows.append(_table_row(cells, triage, heading_date))
        i += 1
    seen: set[str] = set()
    out: list[Row] = []
    for row in rows:
        if row.id not in seen:
            seen.add(row.id)
            out.append(row)
    return out


def _cut(title: str) -> str:
    if len(title) <= backlog.TITLE_CHARS:
        return title
    cut = title[: backlog.TITLE_CHARS - 1].rsplit(" ", 1)[0].rstrip(" ,;:—–-")
    return f"{cut}…"


def _links(row: Row) -> list[dict]:
    refs = dict.fromkeys(f"#{n}" for n in _PR.findall(f"{row.description}\n{row.status_cell}"))
    return [{"kind": "pr", "ref": r} for r in refs][: backlog.MAX_LINKS]


def import_markdown(memory_path: Path, *, project: str, text: str, prefix: str = "G", author: str = backlog.USER,
                    now: datetime | None = None, tz_name: str | None = None) -> ImportReport:
    """File every `prefix` row of `text` on `project`'s backlog. Never raises;
    commits nothing — the caller commits `report.paths` (R-B7)."""
    report = ImportReport()
    prefix = (prefix or "").strip()
    if not re.fullmatch(r"[A-Z]{1,6}", prefix):
        report.error = "a prefix is 1 to 6 capital letters, like G"
        return report
    if len(text or "") > MAX_CHARS:
        report.error = "that file is too large to import"
        return report
    got = backlog.project_page(Path(memory_path), project)
    if isinstance(got, dict):
        report.error = got["error"]
        return report
    stem = got[0]
    for row in parse(text, prefix):
        title = _cut(row.title)
        description = row.description if title == row.title else f"{row.title}\n\n{row.description}".strip()
        status, hint = status_of(row.status_cell)
        note = ("Imported from a backlog file. Its status there: " + row.status_cell) if row.status_cell \
            else "Imported from a backlog file."
        result = backlog.add_item(memory_path, project=stem, title=title, description=description, author=author,
                                  triage=row.triage or hint, paid=row.paid, links=_links(row), status=status,
                                  item_id=row.id, created=row.created, first_note=note, now=now, tz_name=tz_name)
        action = result.get("action")
        if action == "added":
            report.created.append(row.id)
            report.paths += result["paths"]
        elif action == "exists":
            report.skipped.append(row.id)
        else:
            report.failed.append(row.id)
            logger.warning(f"backlog import: {row.id} not filed ({action})")
    return report


def import_file(memory_path: Path, project: str, source: Path, *, prefix: str = "G") -> ImportReport:
    """`scripts/import-backlog.sh`'s entry point: read, import, and commit what
    was created in ONE `Backlog import` commit as the person — or none."""
    from api.services import git_service, handshake, when

    memory_path = Path(memory_path)
    report = import_markdown(memory_path, project=project, text=Path(source).read_text(encoding="utf-8"),
                             prefix=prefix)
    if report.paths and (memory_path / ".git").exists():
        day = datetime.now(when.zone(handshake.local_timezone())).date().isoformat()
        git_service.commit_paths_sync(memory_path, backlog.commit_message(
            report.paths, action="created", subject="Backlog import", trigger=IMPORT_TRIGGER, day=day), report.paths)
    return report
