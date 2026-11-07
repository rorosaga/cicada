"""The one-time class read of facts that have no class (ROR-129, owner 2026-11-07; ``api.scripts.read_fact_classes``).

A fact has its own relevance apart from its page (`decay_policy.fact_class`). The extraction model proposes a class when
it extracts or restates a fact, so every fact already in a memory has none, and on an evergreen page (the owner's, a
pinned one) a fact with none is lent ``active``: it fades with the rest. Measured on a real memory, 10 of 24 identity-shaped
facts (nationalities, a sibling, a cousin) would fall under 0.2 at the first charge. This reads the facts that have no
class, asks the model for one each — **the same class rule Stage 1 has** (`entity_extractor`'s FACT CLASS, in whatever
language the fact is in, judged by what it means, no word list) — and writes the answers.

Which facts: open, non-event facts with no class of their own, on a page the first charge newly reaches — an evergreen
page that is not media. Every other page's facts have faded by their page's class all along; nothing changes for them.
Never a fact the person set (``class_by: user``: "Keep this fact", or "let it fade") or one that already has a class.

Many facts a call (:data:`BATCH_FACTS`), so thousands of facts cost a few hundred small calls; the dry run prints the
calls and the estimated tokens and cost first (:func:`price`), and the run is refused on a metered key unless agreed to by
name. Every answer is stored — ``active`` too, as ``class_by: model`` — so a second run asks nothing new; an answer that is
not one of the four classes is left classless (counted ``unanswered``).

**Run it before** ``reset_fact_clocks``: the reset charges each fact by its class, and a fact the model calls evergreen is
charged nothing.

Person-started only, never by Sleep or a request. ``apply`` makes the calls (never inside the bank's write admission,
G183), then writes every answer in ONE commit authored by the model that answered (the engine as its trailer), refused
while Sleep runs; the commit is the undo. A plan limit or a failing engine stops the run: what came back is kept and
written; run it again for the rest. Counts only — never a page name or a word of the bank.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from loguru import logger

from api.services import (
    claims, claims_ledger, conflict_resolver, decay_policy, git_service, json_parse, markdown_parser,
    page_lock, write_admission,
)
from api.services.claim_reconciler import open_
from api.services.claims import Claim, is_event
from api.services.page_article_rebuild import EngineRefused, SleepRunning, _page_failure, resolve_engine

TRIGGER = "maintenance/fact-classes"
#: Facts in one call. Small enough that a malformed answer loses little, large enough that 8,000 facts are ~140 calls.
BATCH_FACTS = 60
CLASSES = ("evergreen", "durable", "active", "volatile")
#: An engine failure this many calls in a row ends the run (the answers so far are kept).
MAX_FAILURES_IN_A_ROW = 3
#: Estimated output tokens a fact's answer takes (``"12":"durable",``), and the fixed prompt's tokens a call carries.
OUTPUT_TOKENS_PER_FACT = 9
PROMPT_TOKENS = 330

#: The class rule — the same words as Stage 1's FACT CLASS (`entity_extractor`); a test keeps them equal.
RULE = """\
- evergreen: true for life once true (who someone's parent or sibling is, where they were born, their legal name, an
  allergy). Use it sparingly, only when you are sure; the person can undo it.
- durable: long-lived but can change (a degree, a long-held role or home, a lasting skill or taste).
- active: the default.
- volatile: a one-off or in-flight thing (a question asked, a plan, a balance, a debt, a price, today's task)."""

SYSTEM = f"""You sort the facts a person's memory holds into how long each stays true. Judge each by what it means, in \
whatever language it is written, never by a particular word in it.

{RULE}

When unsure, answer active.

Each fact is shown as: number. what it says (when it was said). Answer ONLY with JSON of this shape, covering every \
number, no other text:
{{"classes": {{"1": "active", "2": "evergreen"}}}}"""


@dataclass
class Fact:
    n: int               # its number in its call
    page: str            # the page's file stem
    claim_id: str
    text: str


@dataclass
class Batch:
    facts: list[Fact]
    heading: str
    answers: dict = field(default_factory=dict)   # claim id -> class
    attempted: bool = False


@dataclass
class Survey:
    """Counts only — never a name, a path or a word of the bank."""

    pages: int = 0
    eligible_pages: int = 0           # evergreen, not media
    dirty_pages: int = 0              # uncommitted changes: left to their writer
    facts_open: int = 0               # open, non-event facts on eligible pages
    already_classed: int = 0
    kept_by_person: int = 0           # class_by: user (a keep, or a let-fade): never touched
    to_read: int = 0
    calls_estimated: int = 0
    input_tokens_estimated: int = 0
    output_tokens_estimated: int = 0
    engine: str | None = None         # the resolved engine's label (never a key)
    engine_reason: str | None = None
    model: str | None = None
    cost_usd_estimated: float | None = None   # at the model's list price; None when it has none
    cost_basis: str | None = None             # what the figure is, in words
    # A run:
    calls: int = 0
    answered: int = 0
    unanswered: int = 0
    classes: dict = field(default_factory=dict)
    call_failures: dict = field(default_factory=dict)
    stopped: str | None = None
    not_attempted: int = 0
    input_tokens: int = 0             # measured, when the engine reports them
    output_tokens: int = 0
    written: int = 0                  # facts written
    pages_written: int = 0
    changed_since_read: int = 0
    committed: bool = False
    _batches: list[Batch] = field(default_factory=list, repr=False)
    _pages: dict = field(default_factory=dict, repr=False)      # stem -> (path, text as read)
    _models: set = field(default_factory=set, repr=False)

    def counts(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


def _words(predicate: str) -> str:
    return " ".join(str(predicate or "").replace("_", "-").split("-")).strip()


def _said(claim: Claim) -> str:
    return str(claim.valid_from or claim.recorded_at or "")[:10]


def _line(claim: Claim) -> str:
    said = _said(claim)
    return f"{_words(claim.predicate)}: {str(claim.object or '').strip()}" + (f" ({said})" if said else "")


def _fence_lines(body: str):
    """``(match, lines)`` of the page's claims fence when it is JSONL, else ``None`` (a legacy fence is
    `migrate_claims_jsonl`'s)."""
    match = claims._CLAIMS_BLOCK_RE.search(body or "")
    if match is None:
        return None
    payload = match.group("payload")
    if not payload.strip() or payload.strip() == "[]" or not claims.is_jsonl_payload(payload):
        return None
    return match, payload.split("\n")


def survey(memory_path, settings=None, *, limit: int | None = None) -> Survey:
    """The facts the pass would ask about. Read-only; no model call. ``limit`` caps the facts (a sample)."""
    memory_path = Path(memory_path)
    result = Survey()
    dirty: frozenset[str] = frozenset()
    if (memory_path / ".git").exists():
        try:
            dirty = git_service.dirty_paths_sync(memory_path, "entities")
        except git_service.GitError:
            dirty = frozenset()
    subject = decay_policy.subject_lookup(memory_path)
    todo: list[tuple[str, str, str, str]] = []   # (stem, heading, claim id, text)
    for path in sorted((memory_path / "entities").glob("*.md")):
        result.pages += 1
        try:
            text = path.read_text(encoding="utf-8")
            parsed = markdown_parser.parse(path)
        except Exception:  # noqa: BLE001 — a malformed page is skipped, never fatal
            continue
        fm = dict(parsed.frontmatter or {})
        about = subject(path.stem)
        if decay_policy.resolve(fm)[0] is not decay_policy.DecayClass.evergreen or about.entity_type == "media":
            continue
        result.eligible_pages += 1
        if f"entities/{path.name}" in dirty:
            result.dirty_pages += 1
            continue
        fence = _fence_lines(parsed.body)
        if fence is None:
            continue
        heading = f"About {str(fm.get('name') or path.stem)} ({about.entity_type})"
        result._pages[path.stem] = (path, text)
        for raw_line in fence[1]:
            if not raw_line.strip():
                continue
            try:
                claim = Claim.from_dict(json.loads(raw_line))
            except (ValueError, TypeError):
                continue
            if not open_(claim) or is_event(claim):
                continue
            result.facts_open += 1
            if claim.class_by == "user":
                result.kept_by_person += 1
            elif claim.decay_class:
                result.already_classed += 1
            else:
                todo.append((path.stem, heading, claim.id, _line(claim)))
    if limit is not None:
        todo = todo[:max(0, limit)]
    result.to_read = len(todo)
    # Batch by page, so a call's facts share one heading.
    by_page: dict[str, list[tuple[str, str, str]]] = {}
    heads: dict[str, str] = {}
    for stem, heading, claim_id, text in todo:
        by_page.setdefault(stem, []).append((stem, claim_id, text))
        heads[stem] = heading
    for stem, rows in by_page.items():
        for start in range(0, len(rows), BATCH_FACTS):
            chunk = rows[start:start + BATCH_FACTS]
            result._batches.append(Batch([Fact(i + 1, s, cid, t) for i, (s, cid, t) in enumerate(chunk)], heads[stem]))
    result.calls_estimated = len(result._batches)
    body_chars = sum(len(b.heading) + sum(len(f.text) + 6 for f in b.facts) for b in result._batches)
    result.input_tokens_estimated = result.calls_estimated * PROMPT_TOKENS + body_chars // 4
    result.output_tokens_estimated = result.to_read * OUTPUT_TOKENS_PER_FACT + result.calls_estimated * 12
    return result


def price(result: Survey, settings) -> None:
    """Fill the estimated cost at the model's list price (``None`` when it has none). On a plan nothing is billed per call
    — the figure is then what the same tokens would cost at list, so the load on the plan can be compared."""
    from api.services import engine_select, pricing

    model = str(getattr(settings, "effective_consolidation_model", "") or "")
    result.model = model or None
    try:
        cost = pricing.estimate_cost(model, result.input_tokens_estimated, result.output_tokens_estimated) if model else None
    except Exception:  # noqa: BLE001 — a model with no known price is no figure, not a failure
        cost = None
    result.cost_usd_estimated = None if cost is None else round(float(cost), 4)
    metered = engine_select.engine_label(settings) in ("litellm",)
    result.cost_basis = (None if cost is None else
                         "billed per call on the API key" if metered else "list price; a plan is not billed per call")


def messages(batch: Batch) -> list[dict]:
    lines = "\n".join(f"{f.n}. {f.text}" for f in batch.facts)
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"{batch.heading}\n\n{lines}"}]


def parse(content, batch: Batch) -> dict[str, str]:
    """``claim id -> class`` for the numbers the answer covers with one of the four classes; anything else is left out."""
    raw = json_parse.parse_json_object(content)
    table = raw.get("classes") if isinstance(raw, dict) and isinstance(raw.get("classes"), dict) else raw
    if not isinstance(table, dict):
        raise ValueError("no class table")
    out: dict[str, str] = {}
    for fact in batch.facts:
        cls = decay_policy.fact_class_proposal(table.get(str(fact.n)))
        if cls is not None:
            out[fact.claim_id] = cls.value
    return out


class _Stop(Exception):
    def __init__(self, sentence: str):
        super().__init__(sentence)
        self.sentence = sentence


async def read(result: Survey, settings) -> Survey:
    """One call a batch, at most ``agent_max_concurrency`` at once, on ``settings`` as :func:`resolve_engine` resolved
    them. A batch's own failure skips it and is counted; an engine failure every later call would meet, or
    :data:`MAX_FAILURES_IN_A_ROW` in a row, stops the run — no new call starts, the answers so far are kept."""
    from api.services import agent_engine, providers

    llm_fn = providers.resolve_llm_fn(settings, model=settings.effective_consolidation_model,
                                      completion=conflict_resolver._litellm().acompletion, stage="fact_class")
    in_a_row = {"n": 0}
    stopped: list[_Stop] = []

    async def one(batch: Batch) -> None:
        if stopped:
            return
        batch.attempted = True
        try:
            response = await llm_fn(messages=messages(batch), response_format={"type": "json_object"})
            result.calls += 1
            model = getattr(response, "model", None)
            if isinstance(model, str) and model.strip():
                result._models.add(model.strip())
            usage = getattr(response, "usage", None)
            result.input_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
            result.output_tokens += int(getattr(usage, "completion_tokens", 0) or 0)
            batch.answers = parse(response.choices[0].message.content, batch)
            in_a_row["n"] = 0
        except Exception as exc:  # noqa: BLE001 — sorted: one call's trouble, or the run's
            reason = _page_failure(exc)
            if reason is None:
                stopped.append(_Stop(f"{type(exc).__name__}: {str(exc).strip()[:300]}"))
                return
            result.call_failures[reason] = result.call_failures.get(reason, 0) + 1
            logger.warning(f"fact classes: one call skipped ({reason}: {type(exc).__name__})")
            in_a_row["n"] += 1
            if in_a_row["n"] >= MAX_FAILURES_IN_A_ROW:
                stopped.append(_Stop(f"{in_a_row['n']} calls in a row failed (last: {reason})"))

    concurrency = max(1, int(getattr(settings, "agent_max_concurrency", 1) or 1))
    import uuid

    with agent_engine.use_scope(f"fact-classes:{uuid.uuid4().hex}"):   # a plan throttle here never blocks Sleep's scope
        await conflict_resolver._overlap_pages(result._batches, one, concurrency=concurrency)
    if stopped:
        result.stopped = stopped[0].sentence
        logger.warning(f"fact classes: stopped early — {result.stopped}")
    result.not_attempted = sum(1 for b in result._batches if not b.attempted)
    for batch in result._batches:
        for cls in batch.answers.values():
            result.classes[cls] = result.classes.get(cls, 0) + 1
    result.answered = sum(len(b.answers) for b in result._batches)
    result.unanswered = sum(len(b.facts) for b in result._batches if b.attempted) - result.answered
    return result


def _write_page(body: str, answers: dict[str, str]) -> tuple[str, int]:
    """``(body, facts written)``: the fence lines whose fact is still open, classless and not the person's carry the
    answer; every other line is kept byte for byte."""
    fence = _fence_lines(body)
    if fence is None:
        return body, 0
    match, lines = fence
    changed = 0
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            claim = Claim.from_dict(raw)
        except (ValueError, TypeError):
            continue
        cls = answers.get(claim.id)
        if cls is None or not isinstance(raw, dict) or not open_(claim) or is_event(claim):
            continue
        if claim.decay_class or claim.class_by:   # set since the survey (a keep, a restatement): never replaced
            continue
        raw["decay_class"], raw["class_by"] = cls, "model"
        lines[i] = claims._jsonl_line(raw)
        changed += 1
    if not changed:
        return body, 0
    return body[:match.start("payload")] + "\n".join(lines) + body[match.end("payload"):], changed


def apply(memory_path, result: Survey, *, sleep_running: Callable[[], bool], settings=None,
          engine: str | None = None) -> Survey:
    """Write every answer in ONE commit authored by the model that answered. Raises :class:`SleepRunning` before writing
    anything when Sleep holds the pages or a run is in progress."""
    memory_path = Path(memory_path)
    answers: dict[str, dict[str, str]] = {}
    for batch in result._batches:
        for fact in batch.facts:
            if fact.claim_id in batch.answers:
                answers.setdefault(fact.page, {})[fact.claim_id] = batch.answers[fact.claim_id]
    rels: list[str] = []
    with write_admission.admitted(memory_path, refuse=lambda: SleepRunning("Sleep is holding this bank's pages")):
        if sleep_running():
            raise SleepRunning("a Sleep run is in progress; read the classes after it ends")
        with page_lock.page_lock(memory_path):
            for stem, page_answers in answers.items():
                path, surveyed = result._pages[stem]
                if path.read_text(encoding="utf-8") != surveyed:   # written since the survey: its writer's to commit
                    result.changed_since_read += len(page_answers)
                    continue
                parsed = markdown_parser.parse(path)
                body, n = _write_page(parsed.body, page_answers)
                if not n:
                    continue
                markdown_parser.write(path, dict(parsed.frontmatter or {}), body)
                rels.append(f"entities/{path.name}")
                result.written += n
            result.pages_written = len(rels)
            rels = claims_ledger.with_ledgers(memory_path, rels, existing_only=True)
            if rels and (memory_path / ".git").exists():
                message = git_service.build_commit_message(
                    f"Fact classes read once: {result.written} fact(s) on {result.pages_written} page(s)",
                    [f"{rel}: updated (fact classes, trigger: {TRIGGER})" for rel in rels],
                    authors=sorted(result._models) or ["cicada"], engine=engine)
                git_service.commit_paths_sync(memory_path, message, rels)
                result.committed = True
    if result.written:
        logger.info(f"fact classes: {result.written} fact(s) on {result.pages_written} page(s)")
    return result


def run(memory_path, settings, *, mode: str, sleep_running: Callable[[], bool] = lambda: True,
        limit: int | None = None, allow_metered: bool = False,
        backend_problem: Callable[[], str | None] = lambda: None) -> Survey:
    """``mode``: ``"dry"`` (counts and the estimate, no call) or ``"apply"`` (the calls, then one commit).

    The engine is resolved first, as a person-started Sleep resolves it (`resolve_engine`), and named in the counts; the
    dry run only reports it, ``apply`` raises :class:`EngineRefused` before any call (a metered key unless
    ``allow_metered``)."""
    result = survey(memory_path, settings, limit=limit)
    try:
        settings, result.engine, result.engine_reason = asyncio.run(resolve_engine(settings, allow_metered=allow_metered))
    except EngineRefused as exc:
        if mode != "dry":
            raise
        result.engine, result.engine_reason = exc.engine, f"refused: {exc}"
    price(result, settings)
    if mode == "dry" or not result._batches:
        return result
    if sleep_running():
        problem = backend_problem()
        raise SleepRunning(f"{problem}; nothing was written — run again once it answers" if problem
                           else "a Sleep run is in progress; read the classes after it ends")   # before spending a call
    asyncio.run(read(result, settings))
    if result.answered:
        apply(memory_path, result, sleep_running=sleep_running, settings=settings, engine=result.engine)
    return result


def dumps(result: Survey) -> str:
    return json.dumps(result.counts(), sort_keys=True)
