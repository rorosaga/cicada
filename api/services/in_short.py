"""In short: Sleep's 2–3 sentence summary of a long page the person talks about a lot (ruling 48 part 5; vision item 5
part B, 2026-10-29).

**When** (:func:`qualifies`) — bank facts only, never page views (CLAUDE.md: nothing learned from the telemetry ledger
is auto-applied): the article (the page's prose, the claims fence left out) is at least :data:`MIN_WORDS` words, and
at least :data:`MIN_CONVERSATIONS` of the page's conversations are from the last :data:`WINDOW_DAYS` days (a
conversation's id carries its own local day — ruling 34 — and a feed item or a watched day is no conversation,
``episode_time.counts_as_activity``). A page whose article has not changed since its summary was written is skipped
(``article`` hash), so a quiet night costs nothing.

**Who** (:func:`run_tail`) — Sleep's engine-free tail, on the engine the person's own choice resolves to
(``engine_select.resolve_settings``: plan-first, rulings 31/46/46a), a scheduled run on a plan only through ruling
4b's switch, a metered key only when the person chose it. The small tier — each engine's own "disambiguation" model
(haiku on the Claude plan) — because a summary is a short read, not a judgement. At most :data:`PER_RUN` pages a run
(``in_short_per_run``; 0 is off), busiest first. A plan limit is a pause: the rest waits for the next run.

**Where it lives** — the page's frontmatter, ``in_short: {text, written_at, model, conversations, article}``: a
derived field, never the prose, so ``cicada_edit_page`` and pinned fixes never touch it, and nobody hand-edits it (the
app has no editor for it; it is regenerated when the article changes). It is committed alone, as Sleep (``In short
<day>``, trigger ``sleep/in-short``, ``Cicada-Author:`` the model). ``page_blocks.summary`` serves it to the card and
``cicada_recall_detail(include=["summary"])`` to every agent — one function per door.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from api.services import bank_index

STAGE = "in_short"
MIN_WORDS = 400
MIN_CONVERSATIONS = 5
WINDOW_DAYS = 30
PER_RUN = 10
#: The article the model reads, clipped: an owner-sized page is summarised from its opening, never sent whole.
MAX_ARTICLE_CHARS = 9_000
MAX_SUMMARY_CHARS = 600
TIMEOUT_S = 90
_EPISODE_DAY = re.compile(r"^ep_(\d{4}-\d{2}-\d{2})_")
_SENTENCE_END = re.compile(r"[.!?…](?:[\"'”’)\]]*)(?=\s|$)")


# ---- the article and its facts ---------------------------------------------------------------------------------------


def article(body: str) -> str:
    """The page's prose: the body with its claims fence (and anything after it) left out."""
    from api.services.claims import claims_block_start

    text = body or ""
    start = claims_block_start(text)
    return (text[:start] if start is not None else text).strip()


def words(text: str) -> int:
    return len(re.findall(r"[\w’'-]+", text or ""))


def digest(text: str) -> str:
    return hashlib.sha1(" ".join((text or "").split()).encode()).hexdigest()[:16]


def recent_conversations(memory_path: Path, fm: dict, today: date) -> int:
    """How many of the page's conversations are from the last :data:`WINDOW_DAYS` days, by each id's own day; a feed
    item, a watched day or an import record is not a conversation."""
    from api.services import episode_time

    since = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    count = 0
    for ep in dict.fromkeys(str(e) for e in (fm.get("source_episodes") or []) if e):
        m = _EPISODE_DAY.match(ep)
        if not m or m.group(1) < since or m.group(1) > today.isoformat():
            continue
        entry = bank_index.file(Path(memory_path), "episodes", f"{ep}.md")
        if entry is None or not episode_time.counts_as_activity(entry.frontmatter):
            continue
        count += 1
    return count


@dataclass
class Candidate:
    entity_id: str
    name: str
    type: str
    article: str
    conversations: int
    article_hash: str


def qualifies(memory_path: Path, entity_id: str, fm: dict, body: str, today: date) -> Candidate | None:
    """A page that should get (or refresh) its In short tonight, or None. Owner page, archived and dropped pages never
    do: the owner's page is the person, not a topic."""
    if fm.get("owner") is True or str(fm.get("status") or "") in ("archived", "dropped"):
        return None
    convs = recent_conversations(memory_path, fm, today)
    if convs < MIN_CONVERSATIONS:
        return None
    prose = article(body)
    if words(prose) < MIN_WORDS:
        return None
    h = digest(prose)
    held = fm.get("in_short")
    if isinstance(held, dict) and str(held.get("article") or "") == h and str(held.get("text") or "").strip():
        return None
    return Candidate(entity_id, " ".join(str(fm.get("name") or entity_id).split()),
                     str(fm.get("type") or "concept"), prose, convs, h)


def candidates(memory_path: Path, *, today: date, skip: frozenset[str] = frozenset(), cap: int = PER_RUN) -> list[Candidate]:
    """Tonight's pages, busiest first, at most ``cap``. The conversation count is read from the frontmatter cache for
    every page; only the pages that pass it are parsed for their article."""
    from api.services import markdown_parser

    mp = Path(memory_path)
    busy = []
    for f in bank_index.files(mp, "entities"):
        rel = f"entities/{f.stem}.md"
        if rel in skip:
            continue
        fm = f.frontmatter or {}
        if fm.get("owner") is True or str(fm.get("status") or "") in ("archived", "dropped"):
            continue
        n = recent_conversations(mp, fm, today)
        if n >= MIN_CONVERSATIONS:
            busy.append((n, f.stem))
    busy.sort(key=lambda t: (-t[0], t[1]))
    out: list[Candidate] = []
    for _, entity_id in busy:
        if len(out) >= cap:
            break
        try:
            parsed = markdown_parser.parse(mp / "entities" / f"{entity_id}.md", ledger=False)
        except Exception:  # noqa: BLE001 — an unreadable page is no candidate
            continue
        c = qualifies(mp, entity_id, parsed.frontmatter, parsed.body, today)
        if c is not None:
            out.append(c)
    return out


# ---- the model call --------------------------------------------------------------------------------------------------

SYSTEM = (
    "You write the 'In short' line at the top of one page of a person's private memory: two or three plain sentences "
    "saying what this is and why it matters to them now, from the page alone. Address the person as 'you'. No lists, "
    "no headings, no quotes, no dates you were not given, nothing the page does not say. Never mention the page, "
    "memory, Cicada or yourself. Answer with the sentences only."
)


def build_messages(c: Candidate) -> list[dict]:
    text = c.article if len(c.article) <= MAX_ARTICLE_CHARS else c.article[:MAX_ARTICLE_CHARS].rsplit(" ", 1)[0] + " …"
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Page: {c.name} ({c.type})\n\n{text}"}]


def clean(text: str) -> str | None:
    """The model's answer as the stored line, or None when it is not 1–3 sentences of plain prose."""
    out = " ".join(str(text or "").replace("**", "").split()).strip().strip('"“”').strip()
    if not out or len(out) > MAX_SUMMARY_CHARS or out.startswith(("#", "-", "*", "{", "[")):
        return None
    sentences = len(_SENTENCE_END.findall(out))
    if not 1 <= sentences <= 3:
        return None
    return out


def small_tier(resolved):
    """The same engine on its own small model (the engine's "disambiguation" tier: haiku on the Claude plan) — the
    person's own setting for that tier is kept. Never a different engine, never a different bill."""
    if not hasattr(resolved, "model_copy"):
        return resolved
    updates = {}
    for main, small in (("agent_model", "agent_disambiguation_model"), ("codex_model", "codex_disambiguation_model"),
                        ("cli_engine_model", "cli_engine_disambiguation_model"),
                        ("litellm_model", "litellm_disambiguation_model")):
        value = str(getattr(resolved, small, "") or "").strip()
        if value:
            updates[main] = value
    return resolved.model_copy(update=updates) if updates else resolved


async def engine_for(settings, *, user_triggered: bool) -> tuple[Any, str | None, str]:
    """``(resolved settings on the small tier, engine label, reason)``; settings None when nothing may run."""
    from api.services import engine_select, web_lookup

    resolved, _why = await engine_select.resolve_settings(settings, user_triggered=user_triggered)
    label = engine_select.engine_label(resolved)
    if engine_select.no_engine(resolved):
        return None, label, "no_engine"
    mode = str(getattr(resolved, "llm_mode", "byok") or "byok").strip().lower()
    if mode in engine_select.SUBSCRIPTION_MODES and not user_triggered \
            and not engine_select.scheduled_plan_allowed(web_lookup._registry(settings)):
        return None, label, "scheduled_plan"   # ruling 4b: a scheduled run reaches a plan only through the switch
    return small_tier(resolved), label, "ok"


def default_llm_fn(resolved, *, sink: Callable[..., None] | None = None):
    from api.services import providers

    return providers.resolve_llm_fn(resolved, stage=STAGE, is_async=False, sink=sink)


# ---- Sleep's tail ----------------------------------------------------------------------------------------------------


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


def write(memory_path: Path, c: Candidate, text: str, model: str | None, *, now: datetime | None = None) -> bool:
    """Store one page's In short in its frontmatter, under the page lock. False when the page changed under us (its
    article no longer hashes the same) — the next run reads it again."""
    from api.services import markdown_parser, page_lock

    path = Path(memory_path) / "entities" / f"{c.entity_id}.md"
    now = now or datetime.now(timezone.utc)
    with page_lock.page_lock(Path(memory_path)):
        parsed = markdown_parser.parse(path)
        if digest(article(parsed.body)) != c.article_hash:
            return False
        fm = parsed.frontmatter
        fm["in_short"] = {"text": text, "written_at": now.isoformat(timespec="seconds"),
                          "model": model or "", "conversations": c.conversations, "article": c.article_hash}
        markdown_parser.write(path, fm, parsed.body)
    return True


async def run_tail(memory_path: Path, settings, *, user_triggered: bool, llm_fn: Callable[..., Any] | None = None,
                   engine: tuple[Any, str | None, str] | None = None, today: date | None = None,
                   skip: frozenset[str] = frozenset(), report: Report | None = None) -> Report:
    """Write tonight's In short lines. Never raises; the caller commits ``report.paths`` (and on a failed commit calls
    ``web_lookup.restore(memory_path, report)``). No qualifying page: no engine is resolved and nothing is sent."""
    from api.services import engine_errors, web_lookup

    report = report if report is not None else Report()
    memory_path = Path(memory_path)
    today = today or date.today()
    cap = int(getattr(settings, "in_short_per_run", PER_RUN) or 0)
    if cap <= 0:
        report.reason = "off"
        return report
    todo = await asyncio.to_thread(candidates, memory_path, today=today, skip=skip, cap=cap)
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
            resp = await asyncio.to_thread(fn, messages=build_messages(c), timeout=TIMEOUT_S)
        except (engine_errors.EngineThrottled, engine_errors.EngineExhausted, engine_errors.EngineOverage):
            report.skip("plan_limit")
            break   # a plan limit is a pause: the rest waits for the next run
        except Exception as exc:  # noqa: BLE001 — one page never stops the rest
            logger.info(f"in short: a summary failed ({type(exc).__name__})")
            report.skip("engine_error")
            continue
        text = clean(web_lookup._content(resp))
        if text is None:
            report.skip("unusable")
            continue
        model = web_lookup._model_of(resp)
        rel = f"entities/{c.entity_id}.md"
        if rel not in report.before:
            try:
                report.before[rel] = (memory_path / rel).read_bytes()
            except OSError:
                report.before[rel] = None
        try:
            done = await asyncio.to_thread(write, memory_path, c, text, model)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"in short: a page was not written ({type(exc).__name__})")
            report.skip("write_failed")
            continue
        if not done:
            report.skip("changed")
            continue
        report.written += 1
        report.paths.append(rel)
        report.lines.append(f"{rel}: updated (in_short, trigger: sleep/in-short)")
        if model and model not in report.models:
            report.models.append(model)
    return report
