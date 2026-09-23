"""One intake for every chat export (Track I T2 — design §9.1, spec decision 13).

Before this module there were two chat-import pipelines that disagreed
(design F3, R7 §1.2). ``POST /conversations/upload`` — the one the ``+`` sheet
and the upload overlay used — rejected zips, sent every ``.html`` (a Gemini
``MyActivity.html`` included) to the ChatGPT scraper, and never stamped
``origin``, so a Claude export imported there read "Unattributed" on the
Sources page and "Claude Code" in the Sleep queue. ``POST /banks/{name}/import``
stamped origins but read ONE zip member. Both are now thin shims over
:func:`import_bytes`, and the app talks to the routes below.

No LLM runs here (CLAUDE.md: nothing at capture time). The sniff stages
nothing — the G71 §4.3 contract ``/sources/upload?preview=true`` already
keeps: Confirm re-posts the same bytes, and nothing is cached between the two.
The vendor parsers stay in ``conversations.py``; this module decides which one
a file needs, and what the file holds besides (R-IA7, R-IA8).
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile
from loguru import logger
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import (
    BankImportDateRange,
    IntakeCounts,
    IntakeDelta,
    IntakeIgnored,
    IntakeImportResponse,
    IntakeSniffResponse,
    IntakeTitle,
)
from api.routers import conversations as conv
from api.services import bank_index, bank_registry, media_ingestor

router = APIRouter()

#: Files every export carries that are not conversations (R-IA8). Reported by
#: name in ``ignored[]``; never parsed, never an error.
SKIPPED_MEMBERS: dict[str, str] = {
    "users.json": "account details, not conversations",
    "user.json": "account details, not conversations",
    "message_feedback.json": "ratings you gave replies, not conversations",
    "model_comparisons.json": "model comparisons, not conversations",
    "shared_conversations.json": "links you shared; the chats are in conversations.json",
}
CHAT_HTML = "chat.html"
CHAT_HTML_SKIP = "a viewer page with the same chats as conversations.json"
CHAT_HTML_REASON = ("This looks like ChatGPT's chat.html viewer. "
                    "Drop conversations.json or the whole .zip.")
OTHER_ACTIVITY = "Google activity for another product"
NOT_GEMINI_REASON = ("This is Google activity for another product. "
                     "Export only Gemini Apps from Takeout.")
NOT_A_CHAT_PAGE = "This page isn't a chat export Cicada can read."
EMPTY_ZIP_REASON = "This zip has no conversations Cicada can read."
EMPTY_EXPORT_REASON = "Nothing in this file is a conversation."
#: Refusals the sniff never hands on to the saved-content parser (R-IA8). Both
#: pages are full of ``<a href>`` links, which ``media_ingestor``'s Netscape
#: parser would happily preview as bookmarks — a Search or YouTube activity
#: page would import the person's search history as "saved links".
FINAL_REFUSALS = frozenset({CHAT_HTML_REASON, NOT_GEMINI_REASON})
MAX_SNIFF_TITLES = 5000

#: ``detect_source`` result -> (wire format, vendor, origin, counts key).
_JSON_SHAPES = {
    "anthropic": ("claude", "claude", "claude-export", "conversations"),
    "anthropic_memories": ("claude_memories", "claude", "claude-export", "memories"),
    "anthropic_projects": ("claude_projects", "claude", "claude-export", "projects"),
    "chatgpt": ("chatgpt", "chatgpt", "chatgpt-export", "conversations"),
}
#: Looked up at call time, so a test's monkeypatch of a parser still lands.
_JSON_PARSERS = {
    "anthropic": lambda data: conv.parse_anthropic_conversations(data),
    "anthropic_memories": lambda data: conv.parse_anthropic_memories(data),
    "anthropic_projects": lambda data: conv.parse_anthropic_projects(data),
    "chatgpt": lambda data: conv.parse_chatgpt_json(data),
}
#: The labels ``/conversations/upload`` always answered with (its ``source``).
_SOURCE_LABELS = {
    "claude": "Claude — Conversations",
    "claude_memories": "Claude — Memories",
    "claude_projects": "Claude — Projects",
    "chatgpt": "ChatGPT — Conversations",
    "gemini": "Gemini — Activity",
}


@dataclass
class ParsedExport:
    """Everything one uploaded file holds, before anything is staged."""

    episodes: list[dict] = field(default_factory=list)
    format: str = "unknown"
    vendors: set[str] = field(default_factory=set)
    origins: set[str] = field(default_factory=set)
    members: list[str] = field(default_factory=list)
    ignored: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def vendor(self) -> str | None:
        return next(iter(self.vendors)) if len(self.vendors) == 1 else None

    @property
    def origin(self) -> str | None:
        return next(iter(self.origins)) if len(self.origins) == 1 else None

    def absorb(self, other: "ParsedExport") -> None:
        self.episodes += other.episodes
        self.members += other.members
        self.ignored += other.ignored
        self.warnings += other.warnings
        self.vendors |= other.vendors
        self.origins |= other.origins
        for key, value in other.counts.items():
            self.counts[key] = self.counts.get(key, 0) + value
        if self.format == "unknown":
            self.format = other.format


def source_label(parsed: ParsedExport) -> str:
    return _SOURCE_LABELS.get(parsed.format, parsed.format)


def parse_export(content: bytes, filename: str) -> ParsedExport:
    """Detect and parse one file — a zip, a JSON export, a Takeout activity page —
    into episodes, every one stamped with its origin (R-IA7). Raises
    ``HTTPException(400, reason)``; the reason is written for the person (the
    panel shows it verbatim)."""
    path = filename or ""
    base = PurePosixPath(path).name
    low = base.lower()
    if low.endswith(".zip"):
        return _parse_zip(content)
    if low in SKIPPED_MEMBERS:
        return ParsedExport(ignored=[{"name": base, "reason": SKIPPED_MEMBERS[low]}])
    if low.endswith((".html", ".htm")):
        return _parse_html(content, path, base)
    if low.endswith(".json") or not low:
        return _parse_json(content, base)
    raise HTTPException(400, "Unsupported file format. Use .json, .html, or .zip")


def _is_activity_page(base: str, text: str) -> bool:
    """The heuristics ``parse_export_bytes`` always used to spot a Takeout page."""
    return "myactivity" in base.lower() or "mdl-typography" in text or "outer-cell" in text


def _is_gemini_activity(path: str, text: str) -> bool:
    """Takeout's "My Activity" is per product. Inside a zip the folder says which
    (``My Activity/Gemini Apps/MyActivity.html``); a page dropped alone is
    Gemini's when it names Gemini — or Bard, its old name — anywhere."""
    lowered = path.lower()
    if "/" in lowered:
        return "gemini" in lowered or "bard" in lowered
    text = text.lower()
    return "gemini" in text or "bard" in text


def _parse_html(content: bytes, path: str, base: str) -> ParsedExport:
    text = content.decode("utf-8", errors="replace")
    if base.lower() == CHAT_HTML:
        raise HTTPException(400, CHAT_HTML_REASON)
    if _is_activity_page(base, text):
        if not _is_gemini_activity(path, text):
            raise HTTPException(400, NOT_GEMINI_REASON)
        episodes = conv.parse_gemini_myactivity(text)
        return ParsedExport(episodes, "gemini", {"gemini"}, {"gemini-export"}, [base],
                            counts={"prompts": len(episodes)})
    episodes = conv._stamp_origin(conv._parse_chatgpt_html(text), "chatgpt-export")
    if not episodes:
        raise HTTPException(400, NOT_A_CHAT_PAGE)
    return ParsedExport(episodes, "chatgpt", {"chatgpt"}, {"chatgpt-export"}, [base],
                        counts={"conversations": len(episodes)})


def _parse_json(content: bytes, base: str) -> ParsedExport:
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(400, f"Failed to parse file: {e}")
    source = conv.detect_source(data, base)
    shape = _JSON_SHAPES.get(source)
    if shape is None:
        raise HTTPException(400, "Unrecognized JSON export format")
    fmt, vendor, origin, key = shape
    episodes = conv._stamp_origin(_JSON_PARSERS[source](data), origin)
    return ParsedExport(episodes, fmt, {vendor}, {origin}, [base or "export.json"],
                        counts={key: len(episodes)})


def _parse_zip(content: bytes) -> ParsedExport:
    """Every member a parser knows, not just the first (design §9.1 item 2; the
    G76-disclosed gap: a Claude zip's memories.json and projects.json were
    dropped because conversations.json won). Named extras go to ``ignored[]``;
    the rest (images, attachments) is one counted warning (R-IA8)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as e:
        raise HTTPException(400, f"Invalid zip file: {e}")
    out = ParsedExport()
    others = 0
    for info in sorted(zf.infolist(), key=lambda i: i.filename):
        if info.is_dir():
            continue
        member = PurePosixPath(info.filename)
        base, low = member.name, member.name.lower()
        if base.startswith(".") or "__MACOSX" in member.parts:
            continue
        if low in SKIPPED_MEMBERS:
            out.ignored.append({"name": base, "reason": SKIPPED_MEMBERS[low]})
            continue
        if low == CHAT_HTML:
            out.ignored.append({"name": base, "reason": CHAT_HTML_SKIP})
            continue
        if low == "myactivity.html" and "/" in info.filename and not _is_gemini_activity(info.filename, ""):
            out.ignored.append({"name": "/".join(member.parts[-2:]), "reason": OTHER_ACTIVITY})
            continue
        if not low.endswith((".json", ".html", ".htm")):
            others += 1
            continue
        try:
            part = parse_export(zf.read(info), info.filename)
        except HTTPException:
            others += 1
            continue
        out.absorb(part)
    if not out.episodes and not out.members:
        raise HTTPException(400, EMPTY_ZIP_REASON)
    if others == 1:
        out.warnings.append("1 other file in the zip isn't a conversation (images, attachments, settings).")
    elif others:
        out.warnings.append(f"{others} other files in the zip aren't conversations (images, attachments, settings).")
    return out


# --- What staging WOULD do (R-IA5) --------------------------------------------


@dataclass
class StagePlan:
    create: list[dict] = field(default_factory=list)
    update: list[dict] = field(default_factory=list)
    skip: list[dict] = field(default_factory=list)
    #: skipped because the pre-Track-I Gemini parser already staged it (R-IA9)
    legacy: list[dict] = field(default_factory=list)


def _body_hash(episode: dict) -> str:
    body = "\n".join(conv._message_line(m) for m in episode.get("messages", []))
    return hashlib.sha256(body.encode()).hexdigest()[:12]


def plan(episodes: list[dict], memory_path: Path) -> StagePlan:
    """What ``conversations._stage_episodes`` WOULD do to ``memory_path``, writing
    nothing (design §9.1 item 1). Mirrors its decision rule clause for clause —
    ``test_plan_agrees_with_stage_for_new_grown_and_unchanged`` runs both over the
    same fixtures, so a change to one side that misses the other goes red.
    Reads frontmatter through ``bank_index`` (cached by mtime and size), not a
    re-parse per call: a sniff runs on every drop."""
    source_hashes: dict = {}
    known: set[str] = set()
    for f in bank_index.files(memory_path, "episodes"):
        fm = f.frontmatter
        digest = fm.get("content_hash")
        if digest:
            known.add(digest)
        sid = fm.get("source_id")
        if sid:
            source_hashes[sid] = digest
    out = StagePlan()
    for ep in episodes:
        legacy = ep.get("legacy_hash")
        if legacy and legacy in known:
            out.skip.append(ep)
            out.legacy.append(ep)
            continue
        digest = _body_hash(ep)
        sid = ep.get("source_id")
        if sid:
            if sid not in source_hashes:
                out.create.append(ep)
            elif source_hashes[sid] == digest:
                out.skip.append(ep)
                continue
            else:
                out.update.append(ep)
            source_hashes[sid] = digest
            known.add(digest)
            continue
        if digest in known:
            out.skip.append(ep)
            continue
        out.create.append(ep)
        known.add(digest)
    return out


# --- Import -------------------------------------------------------------------


@dataclass
class ImportResult:
    bank: str
    active: bool
    parsed: ParsedExport
    created: int = 0
    updated: int = 0
    skipped: int = 0
    date_from: str | None = None
    date_to: str | None = None


def resolve_target(settings: Settings, bank: str | None, *, scaffold: bool = True) -> tuple[str, Path, bool]:
    """``(name, dir, is_active)`` for ``bank`` (``None`` = the active bank). The
    sniff passes ``scaffold=False``: it must not create a directory either."""
    root = settings.memory_root
    registry = bank_registry.load_registry(root)
    active = registry.get("active", bank_registry.DEFAULT_BANK)
    name = bank or active
    if name not in (registry.get("banks", {}) or {}):
        raise HTTPException(404, f"Unknown bank '{name}'")
    target = bank_registry.bank_dir(root, name)
    if scaffold:
        bank_registry.scaffold_bank(target, git_init=False)
    return name, target, name == active


def date_range(episodes: list[dict]) -> tuple[str | None, str | None]:
    dates = sorted(d for d in (e.get("original_date") for e in episodes) if d)
    return (dates[0], dates[-1]) if dates else (None, None)


def import_bytes(content: bytes, filename: str, settings: Settings, *, bank: str | None = None) -> ImportResult:
    """Parse, plan, stage — the one import every route shares (R-IA10)."""
    name, target, active = resolve_target(settings, bank)
    parsed = parse_export(content, filename)
    date_from, date_to = date_range(parsed.episodes)
    staging = plan(parsed.episodes, target)
    legacy = {id(e) for e in staging.legacy}
    todo = [e for e in parsed.episodes if id(e) not in legacy]
    created, updated, skipped = conv._stage_episodes(todo, target / "episodes")
    if not active and created + updated:
        # G87: staged into a bank Sleep does not read until someone switches to it.
        logger.warning(f"Import into NON-active bank '{name}': {created + updated} episode(s) staged")
    logger.info(f"Intake ({parsed.format}): {created} new, {updated} updated, {skipped + len(legacy)} unchanged")
    return ImportResult(name, active, parsed, created, updated, skipped + len(legacy), date_from, date_to)


def _import_response(result: ImportResult) -> IntakeImportResponse:
    return IntakeImportResponse(
        episodes_staged=result.created,
        episodes_updated=result.updated,
        duplicates_skipped=result.skipped,
        date_range=BankImportDateRange(**{"from": result.date_from, "to": result.date_to}),
        format=result.parsed.format,
        active=result.active,
        bank=result.bank,
        vendor=result.parsed.vendor,
        origin=result.parsed.origin,
        members=result.parsed.members,
        ignored=[IntakeIgnored(**i) for i in result.parsed.ignored],
    )


# --- Sniff (R-IA11) -----------------------------------------------------------


def sniff_bytes(content: bytes, filename: str, settings: Settings, bank: str | None) -> IntakeSniffResponse:
    name = PurePosixPath(filename or "").name
    try:
        parsed = parse_export(content, filename)
    except HTTPException as exc:
        reason = str(exc.detail)
        if reason not in FINAL_REFUSALS:
            saved = media_ingestor.preview_upload(content, filename)
            if saved.recognized:
                return IntakeSniffResponse(recognized=True, kind="saved", platform=saved.platform,
                                           members=[name], counts=IntakeCounts(items=saved.total),
                                           warnings=saved.warnings)
        return IntakeSniffResponse(recognized=False, reason=reason)
    if not parsed.episodes:
        return IntakeSniffResponse(
            recognized=False,
            ignored=[IntakeIgnored(**i) for i in parsed.ignored],
            reason=None if parsed.ignored else EMPTY_EXPORT_REASON,
            warnings=parsed.warnings,
        )
    _, target, _ = resolve_target(settings, bank, scaffold=False)
    staging = plan(parsed.episodes, target)
    date_from, date_to = date_range(parsed.episodes)
    titles = sorted(({"title": str(e.get("title") or "Untitled"), "date": e.get("original_date")}
                     for e in parsed.episodes), key=lambda t: t["date"] or "", reverse=True)
    return IntakeSniffResponse(
        recognized=True,
        kind="chat",
        vendor=parsed.vendor,
        origin=parsed.origin,
        members=parsed.members,
        ignored=[IntakeIgnored(**i) for i in parsed.ignored],
        counts=IntakeCounts(**parsed.counts),
        date_range=BankImportDateRange(**{"from": date_from, "to": date_to}),
        delta=IntakeDelta(new=len(staging.create), grown=len(staging.update), unchanged=len(staging.skip)),
        titles=[IntakeTitle(**t) for t in titles[:MAX_SNIFF_TITLES]],
        titles_truncated=len(titles) > MAX_SNIFF_TITLES,
        warnings=parsed.warnings,
    )


@router.post("/intake/sniff", response_model=IntakeSniffResponse)
async def sniff(
    file: UploadFile,
    bank: str | None = Query(None, max_length=128),
    settings: Settings = Depends(get_settings),
) -> IntakeSniffResponse:
    """What a dropped file IS — vendor, counts, date range, new · grown · already
    here, the titles — staging nothing (G71 §4.3). Titles cross loopback to the
    one panel that asked and are never logged or stored."""
    content = await file.read()
    return await run_in_threadpool(sniff_bytes, content, file.filename or "", settings, bank)


@router.post("/intake/import", response_model=IntakeImportResponse)
async def import_file(
    file: UploadFile,
    response: Response,
    bank: str | None = Query(None, max_length=128),
    settings: Settings = Depends(get_settings),
) -> IntakeImportResponse:
    """Stage a chat export into ``bank`` (default: the active one). Chat only —
    a saved-content file commits through ``/sources/upload`` (R-IA32)."""
    content = await file.read()
    result = await run_in_threadpool(import_bytes, content, file.filename or "", settings, bank=bank)
    return _import_response(result)
