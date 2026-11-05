"""Sleep reads an added recording's words once and writes its page's Summary and Why it matters (ROR-117 / G43, owner
ruling 68, 2026-11-05).

The owner: "a markdown attached to it which can have the summary, why its relevant, if there is a transcription
available anywhere". :mod:`media_pages` makes the page with both sections empty and hidden; this fills them.

**Prose only.** The read writes the two sections and a record of itself (``media.read``) — no claim, no question, no
page, no link, no mention, no episode. The words stay the recording's (``evidence_kind`` is not touched), so nothing
here promotes a page or moves a decay clock. A photo with no text, or a file with no words, has nothing to read and
gets no action: describing a picture needs an engine that takes images, which is a separate decision.

**One bounded call per item** (:func:`build_messages`), on the engine's small tier like :mod:`in_short`, through
``providers.resolve_llm_fn`` (the one door ``sensitive_hold`` sits in). The read is the words from the start in time
order up to :data:`READ_CHARS` characters, whole passages only; a longer recording is read from its beginning and the
Summary says so ("Read from the first 33 minutes."), so the page never claims what was not read. At haiku list price
($1 / $5 per million tokens in / out) a one-hour recording (about 55,000 characters of speech) reads :data:`READ_CHARS`
(~7,500 tokens) plus ~900 of directions and memory view in, ~250 out: about $0.01.

**Once per version of the words** (``media.read.words``, a hash of the item's full text). The same words are never read
twice, a re-posted transcript that changed is read again, and a failure is tried again at most :data:`MAX_FAILS` times
for those words, :data:`RETRY_H` hours apart (``read.json`` in the store, outside every bank). A plan limit is a pause,
not a failure.

**Never over the person's or an agent's words.** A section is Sleep's to write only while it is empty or still the
exact text this module wrote (``media.read.summary`` / ``.why`` hold a hash of it); an edit by the person or an agent
(``cicada_edit_page``, a typed line) makes it theirs, and a read whose every section is theirs never runs. Pinned
fixes (G198) are applied again over what is written.

**Why it matters is earned.** The model is shown a small view of what memory holds, chosen by the recording's own
words with no model: the owner's page, and the few pages that the recording's distinctive words find (title, type, one
line). It writes one or two sentences tying the recording to something named there, or nothing; code keeps the
sentence only if it names one of those pages, so an unrelated recording leaves the section empty, and empty stays
hidden.

Never raises into the cycle."""
from __future__ import annotations

import asyncio
import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from api.services import bank_index, media_files, media_pages

STAGE = "media_read"
TRIGGER = "sleep/media-read"
TRIGGER_CLICK = "files/read"
PER_RUN = 5
#: The words one call reads, from the start: whole passages, so a little under or over by one passage.
READ_CHARS = 30_000
MAX_FAILS = 3
RETRY_H = 12
TIMEOUT_S = 120
SUMMARY = "Summary"
WHY = "Why it matters"
MAX_SUMMARY_CHARS = 900
MAX_WHY_CHARS = 420
#: Pages the memory view shows, and the distinctive words it searches by.
VIEW_PAGES = 4
VIEW_TERMS = 12
TERM_MAX_PAGES = 12
LINE_CHARS = 160
_SENTENCE_END = re.compile(r"[.!?…](?:[\"'”’)\]]*)(?=\s|$)")
_HEADING = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.M)
_TERM = re.compile(r"[^\W\d_]{4,}")


def digest(text: str) -> str:
    return hashlib.sha1(" ".join((text or "").split()).encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- the page's two sections


def section(body: str, title: str) -> tuple[int, int] | None:
    """``(start, end)`` of a section's text (after its heading line, up to the next ``## `` heading), or None."""
    heads = list(_HEADING.finditer(body or ""))
    for i, m in enumerate(heads):
        if m.group(1).strip().casefold() == title.casefold():
            return m.end(), heads[i + 1].start() if i + 1 < len(heads) else len(body)
    return None


def section_text(body: str, title: str) -> str:
    span = section(body, title)
    return (body[span[0]:span[1]] if span else "").strip()


def set_section(body: str, title: str, text: str) -> str:
    """The body with a section's text replaced (created at the end when the page has none)."""
    span = section(body, title)
    if span is None:
        return body
    text = text.strip()
    inner = f"\n\n{text}\n\n" if text else "\n\n"
    if span[1] >= len(body):
        inner = inner.rstrip("\n") + "\n" if text else "\n\n"
    return body[:span[0]] + inner + body[span[1]:]


def writable(fm: dict, body: str) -> set[str]:
    """The sections Sleep may write: present, and empty or still exactly what it wrote. A page with the heading gone
    was edited by hand."""
    media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
    record = media.get("read") if isinstance(media.get("read"), dict) else {}
    out = set()
    for title, key in ((SUMMARY, "summary"), (WHY, "why")):
        if section(body, title) is None:
            continue
        text = section_text(body, title)
        if not text or (record.get(key) and digest(text) == record.get(key)):
            out.add(title)
    return out


# --------------------------------------------------------------------------- what is read


def _clock(seconds: float) -> str:
    return media_files.clock(seconds)


def view(passages: list[dict], limit: int = READ_CHARS) -> tuple[str, float | None]:
    """``(text, covered_s)``: the words in time order, one line a passage with its start, whole passages up to
    ``limit`` characters (the first always). ``covered_s`` is where the read stopped when it did not reach the end, else
    None."""
    lines: list[str] = []
    used = 0
    covered: float | None = None
    for i, p in enumerate(passages):
        line = f"[{_clock(p['start'])}{', on screen' if p.get('from') == 'picture' else ''}] {p['text']}"
        if lines and used + len(line) > limit:
            covered = max(float(passages[i - 1].get("end") or 0), float(passages[i - 1].get("start") or 0))
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines), covered


def words_version(passages: list[dict]) -> str:
    return digest("\n".join(p["text"] for p in passages))


def coverage_sentence(covered_s: float | None) -> str:
    if covered_s is None:
        return ""
    minutes = max(1, int(covered_s // 60))
    return f"Read from the first {minutes} minute{'' if minutes == 1 else 's'}."


@dataclass
class Candidate:
    entity_id: str
    name: str
    media_type: str
    file_id: str
    words: str
    stamp: str | None
    text: str
    covered_s: float | None
    length_s: float | None
    body: str
    writable: set[str]
    memory: list[tuple[str, str]] = field(default_factory=list)   # (page title, the line shown)
    owner_line: str = ""


def candidate(memory_path: Path, entity_id: str, fm: dict, body: str, *, force: bool = False,
              now: datetime | None = None) -> Candidate | None:
    """The page that should be read now, or None: not a live file page, no words, already read for these words, nothing
    of it left for Sleep to write, or failed enough times. ``force`` (the person's click) skips the version and retry
    memory but never the person's own sections."""
    if not media_pages.is_file_page(fm) or str(fm.get("status") or "") in ("archived", "dropped"):
        return None
    fid = media_pages.file_id_of(fm)
    if not fid:
        return None
    free = writable(fm, body)
    if not free or (force and SUMMARY not in free):
        return None
    meta, passages, stamp = media_files.read_passages(memory_path, fid)
    if meta is None or not passages:
        return None
    state = media_files.read_state(memory_path, fid)
    media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
    record = media.get("read") if isinstance(media.get("read"), dict) else {}
    if not force and record and state.get("stamp") == stamp:
        return None
    version = words_version(passages)
    if not force:
        if record.get("words") == version:
            media_files.write_read_state(memory_path, fid, {**state, "stamp": stamp, "words": version})
            return None
        if state.get("words") == version and int(state.get("fails") or 0) >= MAX_FAILS:
            return None
        failed = _when(state.get("failed_at"))
        current = now or datetime.now(timezone.utc)
        if state.get("words") == version and failed is not None and (current - failed).total_seconds() < RETRY_H * 3600:
            return None
    text, covered = view(passages)
    length = meta.get("duration_s")
    return Candidate(entity_id, " ".join(str(fm.get("name") or entity_id).split()),
                     str(media.get("media_type") or "recording"), fid, version, stamp, text, covered,
                     float(length) if isinstance(length, (int, float)) and length else None, body, free)


def _when(raw) -> datetime | None:
    try:
        out = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def candidates(memory_path: Path, *, skip: frozenset[str] = frozenset(), cap: int = PER_RUN,
               now: datetime | None = None) -> list[Candidate]:
    """Tonight's pages, oldest recording first, at most ``cap``."""
    from api.services import markdown_parser

    mp = Path(memory_path)
    pages = []
    for f in bank_index.files(mp, "entities"):
        fm = f.frontmatter or {}
        if f"entities/{f.stem}.md" in skip or not media_pages.is_file_page(fm):
            continue
        pages.append((str((fm.get("media") or {}).get("recorded_at") or ""), f.stem))
    out: list[Candidate] = []
    for _, entity_id in sorted(pages):
        if len(out) >= cap:
            break
        try:
            parsed = markdown_parser.parse(mp / "entities" / f"{entity_id}.md", ledger=False)
            c = candidate(mp, entity_id, parsed.frontmatter, parsed.body, now=now)
        except Exception:  # noqa: BLE001 - an unreadable page is no candidate
            continue
        if c is not None:
            out.append(c)
    return out


# --------------------------------------------------------------------------- what memory holds, by the words


def _first_sentence(text: str) -> str:
    text = " ".join((text or "").replace("**", "").split())
    m = _SENTENCE_END.search(text)
    out = text[:m.end()] if m else text
    return out if len(out) <= LINE_CHARS else out[:LINE_CHARS].rsplit(" ", 1)[0] + "…"


def _line_of(memory_path: Path, entity_id: str) -> tuple[str, str, str]:
    """``(name, type, one line)`` of a page: its In short, else its Summary's first sentence."""
    from api.services import entity_body, markdown_parser

    parsed = markdown_parser.parse(Path(memory_path) / "entities" / f"{entity_id}.md", ledger=False)
    fm = parsed.frontmatter
    short = fm.get("in_short") if isinstance(fm.get("in_short"), dict) else {}
    text = str(short.get("text") or "") or entity_body.parse_sections(parsed.body).get("Summary", "")
    return " ".join(str(fm.get("name") or entity_id).split()), str(fm.get("type") or ""), _first_sentence(text)


def terms_of(text: str) -> list[str]:
    """The recording's most repeated longer words, most repeated first — a search key, never shown."""
    counts = Counter(w.casefold() for w in _TERM.findall(re.sub(r"^\[[^\]]*\]\s?", "", text or "", flags=re.M)))
    repeated = [w for w, n in counts.most_common() if n >= 2]
    return (repeated or [w for w, _ in counts.most_common()])[:VIEW_TERMS]


def memory_view(memory_path: Path, c: Candidate) -> None:
    """Fill ``c.owner_line`` and ``c.memory``: the owner's page and the pages the recording's distinctive words find,
    rarest word first, with no model. A word found on more than :data:`TERM_MAX_PAGES` pages is too common to say
    anything and is dropped."""
    from api.services import search_service

    mp = Path(memory_path)
    owner_id = None
    for f in bank_index.files(mp, "entities"):
        if (f.frontmatter or {}).get("owner") is True:
            owner_id = f.stem
            break
    score: dict[str, float] = {}
    for term in terms_of(c.text):
        try:
            resp = search_service.search(mp, term, kinds=("entity",), mode="prefix", per_kind=TERM_MAX_PAGES)
        except Exception:  # noqa: BLE001 - a search that fails shows less, never fails the read
            continue
        total = int((resp.totals or {}).get("entity") or len(resp.results))
        if not 1 <= total <= TERM_MAX_PAGES:
            continue
        for hit in resp.results:
            if hit.id in (c.entity_id, owner_id) or hit.type == "media" or hit.status in ("archived", "dropped"):
                continue
            score[hit.id] = score.get(hit.id, 0.0) + 1.0 / total
    if owner_id:
        try:
            name, _kind, line = _line_of(mp, owner_id)
            c.owner_line = f"{name}: {line}".strip(": ")
        except Exception:  # noqa: BLE001
            pass
    for entity_id, _ in sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))[:VIEW_PAGES]:
        try:
            name, kind, line = _line_of(mp, entity_id)
        except Exception:  # noqa: BLE001
            continue
        c.memory.append((name, f"{name} ({kind}){': ' + line if line else ''}"))


# --------------------------------------------------------------------------- the call

SYSTEM = (
    "You write two short notes on one recording, from its words. Answer with one JSON object: "
    '{"summary": "...", "why": "..."}.\n'
    "summary: two to four plain sentences saying what the recording is about, from the words alone. Say 'the recording', "
    "never 'you'; the speakers are not necessarily the person. No lists, no headings, no quotes, no names, numbers or "
    "dates the words do not give. Leave it empty when the summary is not asked for.\n"
    "why: one or two sentences saying how this recording connects to something named in 'What memory holds', only when "
    "the words themselves clearly tie it to that named thing; use the name as written, with no brackets. Otherwise an "
    "empty string. Never guess a connection.\n"
    "Never mention memory, these notes, or yourself."
)


def build_messages(c: Candidate) -> list[dict]:
    length = f", {_clock(c.length_s)} long" if c.length_s else ""
    held = ["What memory holds:"]
    held += [f"- The person: {c.owner_line}"] if c.owner_line else []
    held += [f"- {line}" for _, line in c.memory] or ["- (nothing the words find)"]
    cover = (f"The words, from the start up to {_clock(c.covered_s)} only (the rest is not shown):"
             if c.covered_s is not None else "The words:")
    asked = "" if SUMMARY in c.writable else "The summary is not asked for: leave it empty.\n"
    user = f"Recording: {c.name} ({c.media_type}{length})\n{asked}\n" + "\n".join(held) + f"\n\n{cover}\n{c.text}"
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


_HELD = re.compile(r"\[held back[^\]]*\]", re.I)


def _plain(text: Any) -> str:
    """The model's text as one line. A mark the door left where it held a value back is dropped, never repeated."""
    text = _HELD.sub("", str(text or "")).replace("**", "").replace("\r", " ")
    return " ".join(text.split()).strip().strip('"“”').strip()


def _sentences(text: str) -> int:
    return len(_SENTENCE_END.findall(text))


def _usable(text: str, limit: int, most: int) -> bool:
    return bool(text) and len(text) <= limit and not text.startswith(("#", "-", "*", "{", "[", ">")) \
        and "[[" not in text and "```" not in text and 1 <= _sentences(text) <= most


#: Consecutive words a note may share with the recording. Ruling 68 keeps the words outside every bank, and a note is
#: committed: a short memo "summarised" by repeating it would put the memo in git history.
ECHO_WORDS = 8
#: A page's name shorter than this says nothing as a match: "Go" or "Ed" would tie a recording to a page by chance.
MIN_NAME_CHARS = 3


def _echoes(note: str, words: str) -> bool:
    """True when ``note`` repeats :data:`ECHO_WORDS` or more consecutive words of the recording, ignoring case and marks."""
    said = re.findall(r"\w+", (words or "").casefold())
    runs = {tuple(said[i:i + ECHO_WORDS]) for i in range(len(said) - ECHO_WORDS + 1)}
    wrote = re.findall(r"\w+", note.casefold())
    return any(tuple(wrote[i:i + ECHO_WORDS]) in runs for i in range(len(wrote) - ECHO_WORDS + 1))


def _names(note: str, name: str) -> bool:
    """True when ``note`` holds the page's name as whole words: "Ana" never matches inside "analysis"."""
    name = (name or "").strip()
    if len(name) < MIN_NAME_CHARS:
        return False
    return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", note, re.I) is not None


def decide(c: Candidate, answer: dict | None) -> tuple[str | None, str | None, bool]:
    """``(summary, why, answered)``: what code keeps of the model's answer. ``why`` is kept only when it names a page the
    memory view showed; a summary the writable section needs but did not get makes the answer unusable
    (``answered`` False), so the read counts as a failure and is tried again within its bound."""
    if not isinstance(answer, dict):
        return None, None, False
    summary = _plain(answer.get("summary")) if SUMMARY in c.writable else ""
    why = _plain(answer.get("why")) if WHY in c.writable else ""
    if SUMMARY in c.writable and (not _usable(summary, MAX_SUMMARY_CHARS, 4) or _echoes(summary, c.text)):
        return None, None, False
    if why and (not _usable(why, MAX_WHY_CHARS, 2) or _echoes(why, c.text)
                or not any(_names(why, name) for name, _ in c.memory)):
        why = ""
    if summary and (note := coverage_sentence(c.covered_s)):
        summary = f"{summary} {note}"
    return summary or None, why or None, True


def small_tier(resolved):
    from api.services import in_short

    return in_short.small_tier(resolved)


async def engine_for(settings, *, user_triggered: bool) -> tuple[Any, str | None, str]:
    from api.services import in_short

    return await in_short.engine_for(settings, user_triggered=user_triggered)


def default_llm_fn(resolved, *, sink: Callable[..., None] | None = None):
    from api.services import providers

    return providers.resolve_llm_fn(resolved, stage=STAGE, is_async=False, sink=sink)


async def ask(settings, fn: Callable[..., Any], c: Candidate) -> tuple[dict | None, str | None]:
    """One call. ``(answer or None, the model that answered)``. A plan limit raises (the caller pauses); the plan
    account's own identity in an answer drops it (G148)."""
    from api.services import engine_identity, json_parse, web_lookup

    messages = build_messages(c)
    resp = await asyncio.to_thread(fn, messages=messages, timeout=TIMEOUT_S)
    model = web_lookup._model_of(resp)
    try:
        parsed = json_parse.parse_json_object(web_lookup._content(resp))
    except Exception:  # noqa: BLE001 - an answer that is not JSON changes nothing
        return None, model
    plan_ids = await engine_identity.aidentities(settings)
    if plan_ids and engine_identity.leaks(parsed, "\n".join(m["content"] for m in messages), plan_ids):
        return None, model
    return (parsed if isinstance(parsed, dict) else None), model


# --------------------------------------------------------------------------- writing


def write(memory_path: Path, c: Candidate, summary: str | None, why: str | None, model: str | None, *,
          now: datetime | None = None) -> bool:
    """The two sections and the read's record, under the page lock. False when the page changed under us (the next run
    reads it again) or Sleep may no longer write what it was asked to."""
    from api.services import markdown_parser, page_edits, page_lock

    path = Path(memory_path) / "entities" / f"{c.entity_id}.md"
    now = now or datetime.now(timezone.utc)
    with page_lock.page_lock(Path(memory_path)):
        parsed = markdown_parser.parse(path)
        if parsed.body != c.body:
            return False
        fm = parsed.frontmatter
        free = writable(fm, parsed.body)
        media = dict(fm.get("media") or {})
        old = dict(media.get("read") or {}) if isinstance(media.get("read"), dict) else {}
        record = {"words": c.words, "by": model or "", "at": now.date().isoformat()}
        if c.covered_s is not None:
            record["covers_s"] = int(c.covered_s)
        body = parsed.body
        for title, key, text in ((SUMMARY, "summary", summary), (WHY, "why", why)):
            if title not in free:
                if old.get(key):
                    record[key] = old[key]
                continue
            if title not in c.writable:
                continue
            body = set_section(body, title, text or "")
            if text:
                record[key] = digest(text)
        body, _ = page_edits.apply_corrections(fm, body)
        media["read"] = record
        fm["media"] = media
        markdown_parser.write(path, fm, body)
    return True


def note_failure(memory_path: Path, c: Candidate, *, now: datetime | None = None) -> None:
    state = media_files.read_state(memory_path, c.file_id)
    fails = int(state.get("fails") or 0) + 1 if state.get("words") == c.words else 1
    media_files.write_read_state(memory_path, c.file_id, {**state, "words": c.words, "fails": fails,
                                                         "failed_at": (now or datetime.now(timezone.utc)).isoformat()})


def note_read(memory_path: Path, c: Candidate) -> None:
    media_files.write_read_state(memory_path, c.file_id, {"stamp": c.stamp, "words": c.words, "fails": 0})


# --------------------------------------------------------------------------- Sleep's tail


@dataclass
class Report:
    looked: int = 0
    written: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    paths: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    engine: str | None = None
    reason: str | None = None
    before: dict[str, bytes | None] = field(default_factory=dict)
    settled_items: list[str] = field(default_factory=list)   # web_lookup.restore's hook: never used here

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1


async def read_one(memory_path: Path, settings, fn: Callable[..., Any], c: Candidate, report: Report, *,
                   trigger: str = TRIGGER) -> bool:
    """Read one page and write it. False on a failure (already noted). A plan limit propagates."""
    await asyncio.to_thread(memory_view, memory_path, c)
    answer, model = await ask(settings, fn, c)
    summary, why, answered = decide(c, answer)
    if not answered:
        await asyncio.to_thread(note_failure, memory_path, c)
        report.skip("unusable")
        return False
    rel = f"entities/{c.entity_id}.md"
    if rel not in report.before:
        try:
            report.before[rel] = (Path(memory_path) / rel).read_bytes()
        except OSError:
            report.before[rel] = None
    if not await asyncio.to_thread(write, memory_path, c, summary, why, model):
        report.skip("changed")
        return False
    await asyncio.to_thread(note_read, memory_path, c)
    report.written += 1
    report.paths.append(rel)
    report.lines.append(f"{rel}: updated (media_read, trigger: {trigger})")
    if model and model not in report.models:
        report.models.append(model)
    return True


async def run_tail(memory_path: Path, settings, *, user_triggered: bool, llm_fn: Callable[..., Any] | None = None,
                   engine: tuple[Any, str | None, str] | None = None, skip: frozenset[str] = frozenset(),
                   report: Report | None = None) -> Report:
    """Read tonight's recordings. Never raises; the caller commits ``report.paths`` (and on a failed commit calls
    ``web_lookup.restore(memory_path, report)``). No qualifying page: no engine is resolved and nothing is sent."""
    from api.services import demo_guard, engine_errors

    report = report if report is not None else Report()
    memory_path = Path(memory_path)
    cap = int(getattr(settings, "media_read_per_run", PER_RUN) or 0)
    if cap <= 0:
        report.reason = "off"
        return report
    if demo_guard.is_demo(memory_path):
        report.reason = "demo"
        return report
    todo = await asyncio.to_thread(candidates, memory_path, skip=skip, cap=cap)
    if not todo:
        report.reason = "nothing"
        return report
    resolved, label, why = engine if engine is not None else await engine_for(settings, user_triggered=user_triggered)
    report.engine = label
    if resolved is None:
        report.reason = why
        return report
    fn = llm_fn or default_llm_fn(resolved)
    for c in todo:
        report.looked += 1
        try:
            await read_one(memory_path, settings, fn, c, report)
        except (engine_errors.EngineThrottled, engine_errors.EngineExhausted, engine_errors.EngineOverage):
            report.skip("plan_limit")
            break   # a plan limit is a pause: the rest waits for the next run
        except Exception as exc:  # noqa: BLE001 - one recording never stops the rest
            logger.info(f"media read: a read failed ({type(exc).__name__})")
            await asyncio.to_thread(note_failure, memory_path, c)
            report.skip("engine_error")
    return report


# --------------------------------------------------------------------------- the person's click


class Refused(Exception):
    """A click that cannot be answered: ``status`` and a sentence in words."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


_INFLIGHT: set[tuple[str, str]] = set()


async def read_now(memory_path: Path, settings, file_id: str, *, llm_fn: Callable[..., Any] | None = None,
                   engine: tuple[Any, str | None, str] | None = None) -> dict:
    """``Read it now`` (ROR-117): the same function Sleep runs, for one page, on the person's click. Refused while
    Sleep holds the pages, on a demo bank, for a page with no words or nothing of its own left to write. The model is
    called outside the write window; the page is written (and committed alone) inside it."""
    from api.services import demo_guard, engine_errors, markdown_parser, web_lookup, web_settle, write_admission
    from api.services.sleep_refusal import SleepWriting

    memory_path = Path(memory_path)
    busy = "Sleep is updating your memory — try again in a moment."
    if demo_guard.is_demo(memory_path):
        raise Refused(409, demo_guard.REFUSAL)
    if write_admission.holding():
        raise SleepWriting(busy)
    entity_id = await asyncio.to_thread(media_pages.page_for, memory_path, file_id)
    if not entity_id:
        raise Refused(404, "No such file.")
    parsed = await asyncio.to_thread(markdown_parser.parse, memory_path / "entities" / f"{entity_id}.md", ledger=False)
    c = await asyncio.to_thread(candidate, memory_path, entity_id, parsed.frontmatter, parsed.body, force=True)
    if c is None:
        raise Refused(404, "There is nothing here to read.")
    resolved, label, _why = engine if engine is not None else await engine_for(settings, user_triggered=True)
    if resolved is None:
        raise Refused(409, "Choose how Cicada reads in Settings first.")
    key = (str(memory_path), file_id)
    if key in _INFLIGHT:
        raise Refused(409, "Already reading it.")
    _INFLIGHT.add(key)
    try:
        report = Report(engine=label)
        fn = llm_fn or default_llm_fn(resolved)
        await asyncio.to_thread(memory_view, memory_path, c)
        try:
            answer, model = await ask(settings, fn, c)
        except (engine_errors.EngineThrottled, engine_errors.EngineExhausted, engine_errors.EngineOverage):
            raise Refused(429, "The plan's limit is reached; try again later.")
        summary, why_text, answered = decide(c, answer)
        if not answered:
            await asyncio.to_thread(note_failure, memory_path, c)
            raise Refused(502, "It couldn't be read just now.")
        rel = f"entities/{entity_id}.md"
        report.before[rel] = (memory_path / rel).read_bytes()

        async def body() -> bool:
            if not await asyncio.to_thread(write, memory_path, c, summary, why_text, model):
                return False
            await asyncio.to_thread(note_read, memory_path, c)
            message = web_settle.commit_message("Recording notes",
                                                [f"{rel}: updated (media_read, trigger: {TRIGGER_CLICK})"],
                                                authors=[model or label or "agent"], engine=label)
            try:
                await asyncio.to_thread(web_settle.commit_sync, memory_path, message, [rel])
            except Exception:
                await asyncio.to_thread(web_lookup.restore, memory_path, report)
                raise
            return True

        done = await write_admission.run_admitted(memory_path, body, refuse=lambda: SleepWriting(busy))
        if not done:
            raise Refused(409, "The page changed meanwhile; try again.")
        return {"id": entity_id, "summary": bool(summary), "why": bool(why_text)}
    finally:
        _INFLIGHT.discard(key)
