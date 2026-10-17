"""Rebuild an existing bank's pages as articles — run by the person, never automatically (G194 articles,
``api.scripts.rebuild_page_articles``).

Sleep writes a page's article when the page next gains material (`conflict_resolver`, ``page_articles_enabled``).
Pages that would get one and are not mentioned again would stay fact sheets; this rewrites them with the same
writer, from the same inputs, under the same rails: the record (Key Facts, History, Links, Open Questions, Related,
the claims fence) is kept item for item, the lead and Article are written from it, a page's old Summary sentences
the article does not carry become Key Facts, and every written paragraph records the sources of the inputs it cites
(`entity_article`).

Which pages: active or decaying machine pages (never one with human prose, `entity_body.has_human_prose`) that the
writer would take (`entity_article.worth_writing`: two or more conversations, or one whose record holds
``page_article_min_material`` inputs — owner 2026-10-17, "uncap what the agents can write to"), not media (which has
its own card), without an article yet unless ``rewrite`` says so. Newest-mentioned first (``last_referenced``), so a
run stopped part-way has done the pages the person is most likely to open.

The run is resumable: :func:`run` in ``apply`` mode writes and commits in batches (``batch_size`` pages a commit), so
a stop — a plan limit, Sleep starting, the person's Ctrl-C between batches — keeps every batch before it, and running
it again picks up where it stopped: a finished page is already an article (with ``rewrite``, a page whose article
was written today counts as finished).

* :func:`survey` counts, read-only, never a name or a word of the bank;
* :func:`write` makes the model calls — never inside the bank's write admission (G183), at most
  ``agent_max_concurrency`` at once;
* :func:`apply` writes what came back in ONE ``cicada`` commit, inside the admission, refused while Sleep runs; a page
  written since it was read is skipped (its writer's to commit);
* :func:`preview` writes ``<id>.before.md`` / ``<id>.after.md`` into a directory outside the bank and touches nothing
  in it — for a before/after on a scratch copy.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from loguru import logger

from api.services import (
    claims, conflict_resolver, entity_article, entity_body, git_service, json_parse, markdown_parser, page_edits,
    page_lock, section_provenance, write_admission,
)

TRIGGER = "maintenance/page-articles"


class SleepRunning(RuntimeError):
    """Sleep holds this bank's pages, or a run is in progress: write nothing."""


class EngineRefused(RuntimeError):
    """No engine the person chose can write the articles, or the one that resolves spends money they did not agree
    to here: call nothing. ``engine`` is the resolved engine's label (never a key)."""

    def __init__(self, message: str, engine: str | None = None):
        super().__init__(message)
        self.engine = engine


#: Engines that bill per call on the person's own API key. A plan (``claude-cli``, ``codex-cli``) and the local engine
#: (``ollama``) do not.
METERED_ENGINES = frozenset({"litellm"})


async def resolve_engine(settings, *, allow_metered: bool = False):
    """The engine a person-started Sleep would use now (`engine_select.resolve_settings`, ``user_triggered=True``:
    the engine picked in Settings → Engines, a plan when one is chosen and connected), as ``(settings, label, why)``.

    Raises :class:`EngineRefused` before any call when it resolves to the API-key engine and either the model's key is
    not in the environment (nothing is connected) or ``allow_metered`` is false — a rebuild of many pages on a metered
    key is spending the person agrees to by name (ruling 4's and ruling 12's spirit), never a fallback."""
    from api.services import engine_select

    resolved, why = await engine_select.resolve_settings(settings, user_triggered=True)
    label = engine_select.engine_label(resolved)
    if label in METERED_ENGINES:
        model = str(getattr(resolved, "effective_consolidation_model", "") or "").strip()
        if not model or not _key_present(model):
            raise EngineRefused(
                f"No engine is connected for this ({why}): connect a plan or a local engine in Settings → Engines, "
                "or set an API key and pass --allow-metered.", engine=label)
        if not allow_metered:
            raise EngineRefused(
                f"The engine that resolves is an API key, billed per call ({why}). Rebuilding pages this way spends "
                "money: pass --allow-metered to agree to it, or choose a plan or a local engine in Settings → Engines.",
                engine=label)
    return resolved, label, why


def _key_present(model: str) -> bool:
    """The model's provider key is in the environment (litellm's own check; never reads or prints the key)."""
    try:
        import litellm

        return bool(litellm.validate_environment(model=model).get("keys_in_environment"))
    except Exception:  # noqa: BLE001 - an unknown provider is no proof of a key
        return False


@dataclass
class Job:
    path: Path
    text: str            # the file as read: written only if it is still exactly this
    frontmatter: dict
    body: str
    writer: dict         # `conflict_resolver._article_job`'s inputs and prompt
    article: dict | None = None
    attempted: bool = False


@dataclass
class Survey:
    """Counts only — never a name, a path or a word of the bank."""

    pages: int = 0
    inactive: int = 0
    media: int = 0
    human: int = 0
    one_conversation: int = 0        # stubs: one conversation, less material than the writer's floor
    already_articles: int = 0
    over_budget: int = 0
    selected: int = 0
    one_conversation_selected: int = 0   # of ``selected``, resting on one conversation (the lifted gate's work)
    prompt_chars: int = 0
    estimated_calls: int = 0         # one writer call per selected page (no retry)
    batch_size: int = 0
    batches: int = 0                 # commits an apply makes at most
    commits: int = 0
    calls: int = 0
    invalid: int = 0
    # Pages whose call failed, by reason (`_page_failure`): each page is skipped, never the run.
    page_failures: dict = field(default_factory=dict)
    # Why the run stopped early (a plan limit, an engine that cannot answer, pages failing in a row), or None. The
    # pages written before the stop are kept (preview files, or the one commit); ``not_attempted`` were never asked.
    stopped: str | None = None
    not_attempted: int = 0
    paragraphs_left_out: dict = field(default_factory=dict)
    written: int = 0
    changed_since_read: int = 0
    committed: bool = False
    engine: str | None = None       # the resolved engine label (never a key or a secret)
    engine_reason: str | None = None
    _jobs: list[Job] = field(default_factory=list, repr=False)
    _models: set = field(default_factory=set, repr=False)
    _in_a_row: dict = field(default_factory=lambda: {"n": 0}, repr=False)

    def counts(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


def _newest_first(page) -> tuple:
    """Sort key: the latest mention first (``last_referenced``; a page with none last), then the id."""
    said = str((page[2] or {}).get("last_referenced") or "")[:10]
    return (-int(said.replace("-", "")) if said[:4].isdigit() and len(said) == 10 and said[4] == "-" else 1,
            page[0].stem)


def survey(memory_path, settings, *, entity_ids=None, limit: int | None = None, rewrite: bool = False,
           today: str | None = None, batch_size: int = 25) -> Survey:
    """Which pages would be rebuilt, with their writer inputs, newest-mentioned first. ``entity_ids`` (named pages)
    and ``limit`` (the first N selected) narrow the sample. Read-only."""
    memory_path = Path(memory_path)
    today = today or date.today().isoformat()
    result = Survey()
    pages: list[tuple[Path, str, dict, str]] = []
    for path in sorted((memory_path / "entities").glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
            parsed = markdown_parser.parse(path)
        except Exception:  # noqa: BLE001 - an unreadable page is not rebuilt
            continue
        pages.append((path, text, dict(parsed.frontmatter or {}), parsed.body))
    existing = [{"id": p.stem, "frontmatter": fm, "body": b} for p, _t, fm, b in pages]
    context = conflict_resolver._article_context(existing, settings, today, memory_path=memory_path)
    wanted = {str(e) for e in entity_ids or []}
    pages.sort(key=_newest_first)
    for path, text, fm, page_body in pages:
        if wanted and path.stem not in wanted:
            continue
        result.pages += 1
        if str(fm.get("status") or "active") in ("archived", "dropped"):
            result.inactive += 1
            continue
        if str(fm.get("type") or "") == "media":
            result.media += 1
            continue
        sections = entity_body.parse_sections(claims.strip_claims_block(page_body))
        if entity_body.has_human_prose(fm, sections):
            result.human += 1
            continue
        if entity_article.stamped(fm, sections) and (not rewrite or _written_on(fm) >= today):
            result.already_articles += 1   # with ``rewrite``: rewritten today, by this run or one it continues
            continue
        if limit is not None and result.selected >= limit:
            continue
        change = {"id": path.stem, "source_episodes": []}
        writer = conflict_resolver._article_job(change, {"frontmatter": fm, "body": page_body}, {}, context)
        if writer is None:
            if entity_article.eligible(fm, []):
                result.over_budget += 1
            else:
                result.one_conversation += 1   # Sleep keeps a one-conversation page over the budget a stub too
            continue
        if not entity_article.worth_writing(fm, [], writer["inputs"], min_material=context.get("min_material")):
            result.one_conversation += 1
            continue
        result.selected += 1
        result.one_conversation_selected += 0 if entity_article.eligible(fm, []) else 1
        result.prompt_chars += len(writer["prompt"])
        result._jobs.append(Job(path, text, fm, page_body, writer))
    result.estimated_calls = result.selected
    result.batch_size = max(1, int(batch_size or 1))
    result.batches = -(-result.selected // result.batch_size)
    return result


def _written_on(fm: dict) -> str:
    raw = (fm or {}).get(entity_article.FIELD)
    return str(raw.get("written") or "") if isinstance(raw, dict) else ""


#: Engine failures in a row (timeouts, lost connections, failed calls) after which the run stops: one page's trouble
#: is that page's, but every page failing is the engine's, and asking 1,000 more pages would only spend the wait.
MAX_FAILURES_IN_A_ROW = 5

_ENGINE_TROUBLE = {"timed_out", "connection_lost", "engine_failed"}


class _Stop(Exception):
    """Raised from one page to stop the run: no new page starts, the pages in flight finish."""

    def __init__(self, sentence: str):
        super().__init__(sentence)
        self.sentence = sentence


def _page_failure(exc: BaseException) -> str | None:
    """One page's failure as the reason it is skipped, or ``None`` when it is the engine's and stops the run.

    Stops: a plan limit (throttled, exhausted, overage), an engine that cannot be reached, a model that does not
    exist, and a metered provider's key, quota, rate limit or outage — every later page would meet it too. Skipped:
    a malformed, empty or unparseable answer (the same answer Sleep's article path falls back on), a timeout, a lost
    connection, a failed or refused call, a page too long for the model."""
    from api.services import engine_errors

    if isinstance(exc, (engine_errors.EngineThrottled, engine_errors.EngineExhausted,
                        engine_errors.EngineUnavailable, engine_errors.EngineModelNotFound)):
        return None
    try:
        import litellm

        lx = litellm.exceptions
        if isinstance(exc, lx.Timeout):
            return "timed_out"
        if isinstance(exc, lx.ContextWindowExceededError):
            return "too_long"
        if isinstance(exc, lx.ContentPolicyViolationError):
            return "refused"
        if isinstance(exc, (lx.APIError, lx.AuthenticationError, lx.NotFoundError, lx.RateLimitError,
                            lx.APIConnectionError, lx.BadRequestError, lx.InternalServerError,
                            lx.ServiceUnavailableError)):
            return None
    except Exception:  # pragma: no cover - litellm missing or renamed
        pass
    if isinstance(exc, engine_errors.EngineTimeout):
        return "timed_out"
    if isinstance(exc, engine_errors.EngineConnectionLost):
        return "connection_lost"
    if isinstance(exc, engine_errors.EngineProtocolError):
        return "unparsed"
    if isinstance(exc, engine_errors.EngineFailed):
        return "engine_failed"
    if isinstance(exc, engine_errors.EngineError):
        return None
    if isinstance(exc, (ValueError, TypeError, KeyError, AttributeError, IndexError)):
        return "unparsed"   # malformed, empty or unbalanced JSON (`json_parse`), or an answer of the wrong shape
    return "error"


async def write(result: Survey, settings, jobs: list[Job] | None = None) -> Survey:
    """One writer call per selected page (``jobs``, else every one), at most ``agent_max_concurrency`` at once, on
    ``settings`` as :func:`resolve_engine` resolved them.

    A page's own failure skips that page and is counted (:func:`_page_failure`); the run goes on. An engine failure
    every later page would meet — a plan limit, an unreachable engine, a metered key's quota — or
    :data:`MAX_FAILURES_IN_A_ROW` engine failures in a row stop the run: no new page starts, the pages in flight
    finish, and ``result.stopped`` says why. What was written before the stop is kept for :func:`preview` /
    :func:`apply`; nothing is lost to one page."""
    from api.services import providers

    resolve_llm_fn = providers.resolve_llm_fn
    completion = conflict_resolver._litellm().acompletion
    llm_fn = resolve_llm_fn(settings, model=settings.effective_consolidation_model, completion=completion,
                            stage="merge")

    in_a_row = result._in_a_row   # carried across batches: pages failing in a row is the run's, not a batch's

    async def one(job: Job) -> None:
        job.attempted = True
        try:
            await ask(job)
            in_a_row["n"] = 0
        except Exception as exc:  # noqa: BLE001 - sorted below: one page's trouble, or the run's
            reason = _page_failure(exc)
            if reason is None:
                raise _Stop(f"{type(exc).__name__}: {str(exc).strip()[:300]}") from exc
            result.page_failures[reason] = result.page_failures.get(reason, 0) + 1
            logger.warning(f"page articles: one page skipped ({reason}: {type(exc).__name__})")
            in_a_row["n"] = in_a_row["n"] + 1 if reason in _ENGINE_TROUBLE else 0
            if in_a_row["n"] >= MAX_FAILURES_IN_A_ROW:
                raise _Stop(f"{in_a_row['n']} pages in a row failed in the engine (last: {reason})") from exc

    async def ask(job: Job) -> None:
        response = await llm_fn(messages=[{"role": "user", "content": job.writer["prompt"]}],
                                response_format={"type": "json_object"})
        result.calls += 1
        model = getattr(response, "model", None)
        if isinstance(model, str) and model.strip():
            result._models.add(model.strip())
        raw = json_parse.parse_json_object(response.choices[0].message.content)
        written = entity_article.parse(raw, job.writer["inputs"], name=job.writer["name"],
                                       aliases=job.writer["aliases"], known=job.writer["known"])
        if written is None:
            result.invalid += 1
            return
        for reason, n in written.dropped.items():
            result.paragraphs_left_out[reason] = result.paragraphs_left_out.get(reason, 0) + n
        job.article = entity_article.payload(job.writer["inputs"], written, name=job.writer["name"],
                                             aliases=job.writer["aliases"])

    concurrency = max(1, int(getattr(settings, "agent_max_concurrency", 1) or 1))
    import uuid

    from api.services import agent_engine

    with agent_engine.use_scope(f"articles:{uuid.uuid4().hex}"):   # a plan throttle here never blocks Sleep's scope
        try:
            await conflict_resolver._overlap_pages(result._jobs if jobs is None else jobs, one,
                                                   concurrency=concurrency)
        except _Stop as stop:
            result.stopped = stop.sentence
            logger.warning(f"page articles: stopped early — {stop.sentence}")
    result.not_attempted = sum(1 for job in result._jobs if not job.attempted)
    return result


def compose(job: Job, *, today: str) -> tuple[dict, str]:
    """The page's new frontmatter and body: the record as it is, the written lead and Article, the stamp and each
    paragraph's provenance."""
    fm = dict(job.frontmatter)
    prose = claims.strip_claims_block(job.body)
    article = page_edits.correct_article(fm, job.article)   # G198: an edit's pinned fixes outlive the rewrite
    sections = entity_article.compose(prose, str(fm.get("type") or "concept"), {}, article)
    body = claims.preserve_claims_blocks(job.body, entity_body.render_sections(sections))
    body, _ = page_edits.apply_corrections(fm, body)   # and in the record the rebuild carried over
    entity_article.stamp(fm, entity_body.parse_sections(claims.strip_claims_block(body)), written=today)
    section_provenance.refresh(fm, job.body, body, {"summary": article["lead"],
                                                    section_provenance.INPUTS: list(article["records"])})
    return fm, body


def preview(result: Survey, out_dir, *, today: str | None = None) -> int:
    """``<id>.before.md`` and ``<id>.after.md`` per rebuilt page, in ``out_dir`` (which must not be inside the bank);
    the bank is not touched. Returns the pages written."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    today = today or date.today().isoformat()
    count = 0
    for job in result._jobs:
        if job.article is None:
            continue
        fm, body = compose(job, today=today)
        (out_dir / f"{job.path.stem}.before.md").write_text(job.text, encoding="utf-8")
        markdown_parser.write(out_dir / f"{job.path.stem}.after.md", fm, body)
        count += 1
    return count


def apply(memory_path, result: Survey, *, sleep_running: Callable[[], bool], settings=None,
          today: str | None = None, jobs: list[Job] | None = None) -> Survey:
    """Write the rebuilt pages (``jobs``, else every one) and commit them in ONE commit. Raises :class:`SleepRunning`
    before writing anything when Sleep holds the pages or a run is in progress."""
    memory_path = Path(memory_path)
    today = today or date.today().isoformat()
    rels: list[str] = []
    with write_admission.admitted(memory_path, refuse=lambda: SleepRunning("Sleep is holding this bank's pages")):
        if sleep_running():
            raise SleepRunning("a Sleep run is in progress; rebuild after it ends")
        with page_lock.page_lock(memory_path):
            for job in result._jobs if jobs is None else jobs:
                if job.article is None:
                    continue
                if job.path.read_text(encoding="utf-8") != job.text:
                    result.changed_since_read += 1
                    continue
                fm, body = compose(job, today=today)
                markdown_parser.write(job.path, fm, body)
                rels.append(f"entities/{job.path.name}")
            result.written += len(rels)
            if rels and (memory_path / ".git").exists():
                engine = result.engine
                message = git_service.build_commit_message(
                    f"Pages rebuilt as articles: {len(rels)} page(s)",
                    [f"{rel}: article (trigger: {TRIGGER})" for rel in rels],
                    authors=sorted(result._models) or ["cicada"], engine=engine,
                )
                git_service.commit_paths_sync(memory_path, message, rels)
                result.committed = True
                result.commits += 1
    if rels:
        logger.info(f"page articles: {len(rels)} page(s) rebuilt")
    return result


def run(memory_path, settings, *, mode: str, sleep_running: Callable[[], bool] = lambda: True,
        entity_ids=None, limit: int | None = None, rewrite: bool = False, preview_dir=None,
        allow_metered: bool = False, batch_size: int = 25) -> Survey:
    """``mode``: ``"dry"`` (counts), ``"preview"`` (calls, files in ``preview_dir``) or ``"apply"``.

    The engine is resolved first, as a person-started Sleep resolves it (:func:`resolve_engine`), and named in the
    counts. The dry run only reports it (``engine_refused`` says why a call would be refused); preview and apply
    raise :class:`EngineRefused` before any call.

    ``apply`` goes ``batch_size`` pages at a time — the calls, then that batch's one commit — so a stop keeps every
    batch before it: an engine stop (a plan limit is a pause, never retried here; ruling 15) commits what its batch
    wrote, and Sleep starting between batches ends the run there. Either way ``stopped`` says why, and running the
    command again continues with the pages not yet articles."""
    result = survey(memory_path, settings, entity_ids=entity_ids, limit=limit, rewrite=rewrite,
                    batch_size=batch_size)
    try:
        settings, result.engine, result.engine_reason = asyncio.run(
            resolve_engine(settings, allow_metered=allow_metered))
    except EngineRefused as exc:
        if mode != "dry":
            raise
        result.engine, result.engine_reason = exc.engine, f"refused: {exc}"
    if mode == "dry" or not result._jobs:
        return result
    if mode == "apply" and sleep_running():
        raise SleepRunning("a Sleep run is in progress; rebuild after it ends")   # before spending a call
    if mode == "preview":
        asyncio.run(write(result, settings))
        result.written = preview(result, preview_dir)
        return result
    jobs = result._jobs
    for start in range(0, len(jobs), result.batch_size):
        batch = jobs[start:start + result.batch_size]
        if start and sleep_running():
            result.stopped = "Sleep started; the batches before it are committed — run again after it ends"
            break
        asyncio.run(write(result, settings, batch))
        try:
            apply(memory_path, result, sleep_running=sleep_running, settings=settings, jobs=batch)
        except SleepRunning:
            if not start:
                raise
            result.stopped = "Sleep started; the batches before it are committed — run again after it ends"
            break
        if result.stopped:
            break
    result.not_attempted = sum(1 for job in jobs if not job.attempted)
    return result


def dumps(result: Survey) -> str:
    return json.dumps(result.counts(), sort_keys=True)
