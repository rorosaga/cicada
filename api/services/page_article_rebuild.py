"""Rebuild an existing bank's pages as articles — run by the person, never automatically (G194 articles,
``api.scripts.rebuild_page_articles``).

Sleep writes a page's article when the page next gains material (`conflict_resolver`, ``page_articles_enabled``).
Pages that already rest on two or more conversations and are not mentioned again would stay fact sheets; this
rewrites them with the same writer, from the same inputs, under the same rails: the record (Key Facts, History,
Links, Open Questions, Related, the claims fence) is kept item for item, the lead and Article are written from it,
a page's old Summary sentences the article does not carry become Key Facts, and every written paragraph records the
sources of the inputs it cites (`entity_article`).

Which pages: active or decaying machine pages (never one with human prose, `entity_body.has_human_prose`) resting on
two or more conversations, not media (which has its own card), without an article yet unless ``rewrite`` says so.

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
    claims, conflict_resolver, entity_article, entity_body, git_service, json_parse, markdown_parser, page_lock,
    section_provenance, write_admission,
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


@dataclass
class Survey:
    """Counts only — never a name, a path or a word of the bank."""

    pages: int = 0
    inactive: int = 0
    media: int = 0
    human: int = 0
    one_conversation: int = 0
    already_articles: int = 0
    over_budget: int = 0
    selected: int = 0
    prompt_chars: int = 0
    calls: int = 0
    invalid: int = 0
    paragraphs_left_out: dict = field(default_factory=dict)
    written: int = 0
    changed_since_read: int = 0
    committed: bool = False
    engine: str | None = None       # the resolved engine label (never a key or a secret)
    engine_reason: str | None = None
    _jobs: list[Job] = field(default_factory=list, repr=False)
    _models: set = field(default_factory=set, repr=False)

    def counts(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


def survey(memory_path, settings, *, entity_ids=None, limit: int | None = None, rewrite: bool = False,
           today: str | None = None) -> Survey:
    """Which pages would be rebuilt, with their writer inputs. ``entity_ids`` (named pages) and ``limit`` (the first N
    selected, by id) narrow the sample. Read-only."""
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
        if not entity_article.eligible(fm, []):
            result.one_conversation += 1
            continue
        if entity_article.stamped(fm, sections) and not rewrite:
            result.already_articles += 1
            continue
        if limit is not None and result.selected >= limit:
            continue
        change = {"id": path.stem, "source_episodes": []}
        writer = conflict_resolver._article_job(change, {"frontmatter": fm, "body": page_body}, {}, context)
        if writer is None:
            result.over_budget += 1
            continue
        result.selected += 1
        result.prompt_chars += len(writer["prompt"])
        result._jobs.append(Job(path, text, fm, page_body, writer))
    return result


async def write(result: Survey, settings) -> Survey:
    """One writer call per selected page, at most ``agent_max_concurrency`` at once, on ``settings`` as
    :func:`resolve_engine` resolved them. Engine errors propagate (a plan limit stops the rebuild; nothing has been
    written)."""
    from api.services import providers

    resolve_llm_fn = providers.resolve_llm_fn
    completion = conflict_resolver._litellm().acompletion
    llm_fn = resolve_llm_fn(settings, model=settings.effective_consolidation_model, completion=completion,
                            stage="merge")

    async def one(job: Job) -> None:
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
        await conflict_resolver._overlap_pages(result._jobs, one, concurrency=concurrency)
    return result


def compose(job: Job, *, today: str) -> tuple[dict, str]:
    """The page's new frontmatter and body: the record as it is, the written lead and Article, the stamp and each
    paragraph's provenance."""
    fm = dict(job.frontmatter)
    prose = claims.strip_claims_block(job.body)
    sections = entity_article.compose(prose, str(fm.get("type") or "concept"), {}, job.article)
    body = claims.preserve_claims_blocks(job.body, entity_body.render_sections(sections))
    entity_article.stamp(fm, entity_body.parse_sections(claims.strip_claims_block(body)), written=today)
    section_provenance.refresh(fm, job.body, body, {"summary": job.article["lead"],
                                                    section_provenance.INPUTS: list(job.article["records"])})
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
          today: str | None = None) -> Survey:
    """Write the rebuilt pages and commit them in ONE commit. Raises :class:`SleepRunning` before writing anything
    when Sleep holds the pages or a run is in progress."""
    memory_path = Path(memory_path)
    today = today or date.today().isoformat()
    rels: list[str] = []
    with write_admission.admitted(memory_path, refuse=lambda: SleepRunning("Sleep is holding this bank's pages")):
        if sleep_running():
            raise SleepRunning("a Sleep run is in progress; rebuild after it ends")
        with page_lock.page_lock(memory_path):
            for job in result._jobs:
                if job.article is None:
                    continue
                if job.path.read_text(encoding="utf-8") != job.text:
                    result.changed_since_read += 1
                    continue
                fm, body = compose(job, today=today)
                markdown_parser.write(job.path, fm, body)
                rels.append(f"entities/{job.path.name}")
            result.written = len(rels)
            if rels and (memory_path / ".git").exists():
                engine = result.engine
                message = git_service.build_commit_message(
                    f"Pages rebuilt as articles: {len(rels)} page(s)",
                    [f"{rel}: article (trigger: {TRIGGER})" for rel in rels],
                    authors=sorted(result._models) or ["cicada"], engine=engine,
                )
                git_service.commit_paths_sync(memory_path, message, rels)
                result.committed = True
    if rels:
        logger.info(f"page articles: {len(rels)} page(s) rebuilt")
    return result


def run(memory_path, settings, *, mode: str, sleep_running: Callable[[], bool] = lambda: True,
        entity_ids=None, limit: int | None = None, rewrite: bool = False, preview_dir=None,
        allow_metered: bool = False) -> Survey:
    """``mode``: ``"dry"`` (counts), ``"preview"`` (calls, files in ``preview_dir``) or ``"apply"``.

    The engine is resolved first, as a person-started Sleep resolves it (:func:`resolve_engine`), and named in the
    counts. The dry run only reports it (``engine_refused`` says why a call would be refused); preview and apply
    raise :class:`EngineRefused` before any call."""
    result = survey(memory_path, settings, entity_ids=entity_ids, limit=limit, rewrite=rewrite)
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
    asyncio.run(write(result, settings))
    if mode == "preview":
        result.written = preview(result, preview_dir)
        return result
    return apply(memory_path, result, sleep_running=sleep_running, settings=settings)


def dumps(result: Survey) -> str:
    return json.dumps(result.counts(), sort_keys=True)
