"""The web lookup on Sleep's tail: who searches, on which engine, under which gate (owner ruling 2026-10-16, G61).

The owner, 2026-10-16: "Runs from your Claude plan in runs you start; a scheduled metered run costs a few cents more."

After the last batch's nudges, a bounded step looks up public-thing questions (``web_settle.classify``) and settles
the ones the search answers. The rules, each enforced here:

* **The gate.** ``CICADA_ALLOW_CONNECTOR_FETCH`` governs it: a lookup Sleep starts on its own is an unattended fetch.
* **Ruling 4.** A run the person started may use their Claude plan: one ``claude -p`` per question whose ONE tool is
  the plan's web search (``agent_engine.CallPolicy.web_search``). A scheduled run never uses a plan — not even an
  explicit ``CICADA_LLM_MODE`` pin. On a metered engine (an API key) either run may use that provider's own search
  (litellm's ``web_search_options``) at its price, recorded as an ``llm_call`` of stage ``web_check`` tagged with the
  run, so Past reads shows it with its basis (ruling 12) — but only a provider whose searches litellm REPORTS
  (:data:`SEARCH_REPORTED_PROVIDERS`: Anthropic's ``server_tool_use`` blocks come back as tool calls with their query).
  Any other metered engine (OpenRouter, OpenAI's search models, Gemini, xAI…) skips the step with
  ``search_unreported`` before any paid call: its searches could never pass the pinned-query check, so every lookup
  would be paid for and thrown away. The ChatGPT plan and a local model get no search: skipped.
* **Nothing dangles.** Every file a settle touches is snapshotted first; when the run's commit fails, :func:`restore`
  puts them back and unstages them, so a later ``git add -A`` never commits a settle under the wrong author.
* **What leaves the machine.** The search query is ``web_settle.query_for`` — the subject's name and at most one
  generic category word (none when unsure; none on a question about what the thing IS) — pinned in the prompt, and
  every search the engine reports is held to it: a call that searched anything else (or nothing) is discarded,
  nothing is settled from it. Unchanged by the context below: what reaches the search provider is the pinned query.
* **The local context (owner ruling 2026-10-16, amends ruling 27: "Yes, use local context").** The prompt — to the
  same engine that read those conversations during Sleep — also carries what Cicada already knows about the subject
  (``web_settle.local_context``: its one-line description and up to two lines where it was mentioned, ≤ 600
  characters, scrubbed, people's names and paths out), so the model can tell WHICH result is the thing the person
  meant: a name can be a restaurant, a town and a product at once. It is never searched for. The option labels ride
  too; a label naming a person, or saying "my"/"her", keeps the question home (``web_settle.classify``).
* **Order.** Clarifications ("what is X") first; then conflicts, those with a mention line before those without — a
  "which of two different things" conflict is answerable only through the context, otherwise the model is unsure.
* **What a thing is** (owner, 2026-10-16). A type or description conflict (``is-a`` included, though multi-valued)
  settles on one option only when the answer says the page rules the others out, and on the item's own "both" option
  when the page says it is all of them; never on an option the item does not have.
* **Caps.** ``web_check_per_run`` questions a run (default 8), at most two searches a call; a question already looked
  up and left open is not looked up again for 30 days (a memo outside every bank, ids and enums only).
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from api.services import web_settle

STAGE = "web_check"
DEFAULT_PER_RUN = 8
#: Metered providers whose web searches litellm reports with their query (``tool_calls`` named ``web_search``), so the
#: pinned-query check can pass. Keyed by ``byok.provider_for_model`` — the router is who answers, so
#: ``openrouter/anthropic/…`` is OpenRouter (its web plugin reports no query) and skips.
SEARCH_REPORTED_PROVIDERS = frozenset({"anthropic"})
MAX_SEARCHES = 2
RETRY_DAYS = 30
TIMEOUT_S = 120.0

SYSTEM_PROMPT = (
    "You look up ONE public thing on the web to answer one question about it. Use the web search tool with exactly "
    "the query you are given, word for word, at most twice; never add, remove or change a word, and never search for "
    "anything else. You may also be given the person's own notes about the subject. They are only for telling which "
    "result is about the thing the person meant (one name can belong to a restaurant, a town and a product at once): "
    "never search for their words, and never answer from them. Answer only from what a result about that thing says. "
    "If the results are about other things with the same name, if you cannot tell which thing is meant, if they do "
    "not clearly answer the question, or if the subject could be a private person, someone's own file or project, "
    "answer {\"sure\": false}. Reply with one "
    "JSON object and nothing else: {\"sure\": true, \"option_key\": <the key of the option that is true, for a "
    "choice>, \"answer\": <one short phrase, at most 25 words, for a 'what is it' question>, \"url\": <the link of the "
    "page that says it>, \"quote\": <that page's own words that say it, verbatim, at most 240 characters>}."
)


#: A question about what the thing IS (``web_settle.TYPE_PREDICATES``; owner, 2026-10-16): one option settles only when
#: the page rules the others out; the item's own "both" option when the page says it is all of them at once.
TYPE_RULES = (
    "Rules for this question: choose a single option only when the page says the subject is that AND its words rule "
    "out every other option; then add \"others_ruled_out\": true. When the page says this one subject is all of the "
    "options at once, choose option_key {both!r}. When the name belongs to different things, the notes decide which "
    "one the person meant: judge the options only against a page about that one, and cite it; if the notes do not "
    "say which one, or the page does not rule the other options out, answer {{\"sure\": false}}. Never answer with "
    "an option that is not listed."
)


@dataclass
class Answer:
    item_id: str
    ok: bool
    reason: str = ""
    option_key: str | None = None
    answer: str | None = None
    url: str = ""
    quote: str = ""


@dataclass
class Report:
    looked_up: int = 0
    settled: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    paths: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    engine: str | None = None
    models: list[str] = field(default_factory=list)
    reason: str | None = None   # why the whole step did nothing (an enum), when it did nothing
    #: What each touched path held before the first settle wrote it (``None``: it did not exist) — for :func:`restore`.
    before: dict[str, bytes | None] = field(default_factory=dict)
    settled_items: list[str] = field(default_factory=list)

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1


def build_messages(c: web_settle.Candidate, context: list[str] | None = None) -> list[dict]:
    query = web_settle.query_for(c)
    lines = [f"Subject: {c.name}", f"Search query (use exactly this): {query}"]
    if context:
        lines.append("The person's own notes about this subject (only for telling which result is the one they "
                     "meant; never search for these words):")
        lines += [f"  {line}" for line in context]
    if c.kind == "conflict":
        lines.append(f"Question: which of these is true of {c.name}?")
        lines += [f"  option_key {key!r}: {label}" for key, label in c.options]
        if c.type_question:
            if c.both_key:
                lines.append(f"  option_key {c.both_key!r}: all of the above are true of this one {c.name}")
            lines.append(TYPE_RULES.format(both=c.both_key or "(none)"))
    else:
        lines.append(f"Question: what is {c.name}? Answer in one short phrase.")
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "\n".join(lines)}]


def _content(resp: Any) -> str:
    try:
        return str(resp["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError):
        try:
            return str(resp.choices[0].message.content or "")
        except Exception:  # noqa: BLE001
            return ""


def searched_queries(resp: Any) -> list[str]:
    """Every search the call made, as its query: the plan's stream (``tool_uses``) or a metered response's tool calls."""
    out: list[str] = []
    # A litellm ModelResponse raises AttributeError on a missing key: read a dict as a dict, anything else by attribute.
    uses = resp.get("tool_uses") if isinstance(resp, dict) else getattr(resp, "tool_uses", None)
    for row in uses or []:
        if isinstance(row, (list, tuple)) and len(row) == 2 and "search" in str(row[0]).lower():
            out.append(str((row[1] or {}).get("query") or ""))
    if uses is None:
        try:
            calls = resp.choices[0].message.tool_calls or []
        except Exception:  # noqa: BLE001
            try:
                calls = resp["choices"][0]["message"].get("tool_calls") or []
            except Exception:  # noqa: BLE001
                calls = []
        for call in calls:
            fn = call.get("function") if isinstance(call, dict) else getattr(call, "function", None)
            name = (fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", "")) or ""
            if "search" not in str(name).lower():
                continue
            raw = (fn.get("arguments") if isinstance(fn, dict) else getattr(fn, "arguments", "")) or "{}"
            try:
                args = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except (ValueError, TypeError):
                args = {}
            out.append(str(args.get("query") or ""))
    return out


def _norm(q: str) -> str:
    return " ".join(re.sub(r"[\"'`]", "", q or "").split()).lower()


def queries_ok(queries: list[str], pinned: str) -> bool:
    """At least one search, at most :data:`MAX_SEARCHES`, every one the pinned query word for word (case and quotes
    aside). An answer from no search is no lookup; a search for anything else may have carried something else."""
    return 0 < len(queries) <= MAX_SEARCHES and all(_norm(q) == _norm(pinned) for q in queries)


def parse_answer(c: web_settle.Candidate, text: str) -> Answer:
    from api.services.json_parse import parse_json_object

    try:
        data = parse_json_object(text)
    except Exception:  # noqa: BLE001
        data = None
    if not isinstance(data, dict):
        return Answer(c.item_id, False, "unreadable")
    if data.get("sure") is not True:
        return Answer(c.item_id, False, "unsure")
    url, quote = str(data.get("url") or "").strip(), str(data.get("quote") or "").strip()
    if not url or not quote:
        return Answer(c.item_id, False, "no_citation")
    if c.kind == "conflict":
        key = str(data.get("option_key") or "").strip()
        if c.both_key and key == c.both_key:
            return Answer(c.item_id, True, option_key=key, url=url, quote=quote)
        if key not in {k for k, _ in c.options}:
            return Answer(c.item_id, False, "no_option")
        if c.type_question and data.get("others_ruled_out") is not True:
            # What a thing is may be several things: one option settles only on a page that rules the others out.
            return Answer(c.item_id, False, "not_exclusive")
        return Answer(c.item_id, True, option_key=key, url=url, quote=quote)
    answer = " ".join(str(data.get("answer") or "").split())
    if not answer:
        return Answer(c.item_id, False, "no_answer")
    return Answer(c.item_id, True, answer=answer, url=url, quote=quote)


# --------------------------------------------------------------------------- the memo (outside every bank)


def _memo_path(memory_path: Path) -> Path:
    from api.services.auth import cicada_home

    return cicada_home() / "web_check" / f"{Path(memory_path).name}.json"


def load_memo(memory_path: Path) -> dict[str, dict]:
    try:
        raw = json.loads(_memo_path(memory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def save_memo(memory_path: Path, memo: dict[str, dict]) -> None:
    path = _memo_path(memory_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(memo, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.debug(f"web check memo not saved: {type(exc).__name__}")


def _recent(memo: dict[str, dict], item_id: str, today: date) -> bool:
    at = str((memo.get(item_id) or {}).get("at") or "")
    return bool(at) and at >= (today - timedelta(days=RETRY_DAYS)).isoformat()


# --------------------------------------------------------------------------- the engine


async def engine_for(settings, *, user_triggered: bool) -> tuple[Any, str | None, str]:
    """``(resolved settings, engine label, reason)``; settings ``None`` when no engine may search here."""
    from api.services import engine_select

    resolved, _why = await engine_select.resolve_settings(settings, user_triggered=user_triggered)
    mode = str(getattr(resolved, "llm_mode", "byok") or "byok").strip().lower()
    label = engine_select.engine_label(resolved)
    if mode in engine_select.SUBSCRIPTION_MODES:
        if not user_triggered:
            return None, label, "scheduled_plan"     # ruling 4 — even under an explicit env pin
        if mode != "agent":
            return None, label, "no_search_tool"
        return resolved, label, "plan"
    if mode != "byok":
        return None, label, "no_search_tool"
    model = str(getattr(resolved, "litellm_model", "") or "")
    from api.services.connections import byok

    if byok.provider_for_model(model) not in SEARCH_REPORTED_PROVIDERS:
        return None, label, "search_unreported"   # decided before any paid call
    try:
        import litellm

        can = bool(litellm.supports_web_search(model=model))
    except Exception:  # noqa: BLE001 — an unknown model has no known search
        can = False
    return (resolved, label, "metered") if can else (None, label, "no_search_tool")


def default_llm_fn(resolved, *, sink: Callable[..., None] | None = None) -> Callable[..., Any]:
    """The engine call; ``sink`` replaces the usage ledger (the dry run passes a no-op: it writes nothing)."""
    from api.services import providers

    if str(getattr(resolved, "llm_mode", "")).lower() == "agent":
        return providers.resolve_llm_fn(resolved, stage=STAGE, is_async=False, sink=sink)
    import litellm

    return providers.resolve_llm_fn(resolved, stage=STAGE, completion=litellm.completion, sink=sink)


def _model_of(resp: Any) -> str | None:
    try:
        return str(resp["model"] or "") or None
    except (KeyError, TypeError):
        return str(getattr(resp, "model", "") or "") or None


def _snapshot(memory_path: Path, report: Report, rels: list[str]) -> None:
    for rel in rels:
        if rel in report.before:
            continue   # the first snapshot is the state before this run
        path = memory_path / rel
        try:
            report.before[rel] = path.read_bytes() if path.is_file() else None
        except OSError:
            report.before[rel] = None


def restore(memory_path: Path, report: Report) -> None:
    """Undo this run's settles after a failed commit: every touched file goes back to what it held (a new one is
    removed), the paths are unstaged, and the memo forgets them so the next run may look again. Never raises."""
    from api.services import bank_index, git_service

    memory_path = Path(memory_path)
    for rel, data in report.before.items():
        path = memory_path / rel
        try:
            if data is None:
                path.unlink(missing_ok=True)
            else:
                tmp = path.with_name(path.name + ".restore.tmp")
                tmp.write_bytes(data)
                tmp.replace(path)
        except OSError as exc:
            logger.warning(f"web check restore: a file was not put back ({type(exc).__name__})")
    if report.before and (memory_path / ".git").exists():
        try:   # a failed commit may have staged them: the index goes back to HEAD for these paths only
            git_service.run_git_write_sync(memory_path, "reset", "-q", "--", *sorted(report.before))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"web check restore: unstage failed ({type(exc).__name__})")
    bank_index.invalidate(memory_path)
    if report.settled_items:
        memo = load_memo(memory_path)
        for item_id in report.settled_items:
            memo.pop(item_id, None)
        save_memo(memory_path, memo)


def _order(item: tuple[web_settle.Candidate, list[str]]) -> tuple[int, int]:
    """Clarifications first; then conflicts with a line where the subject was mentioned, then those without (a
    "which of two different things did you mean" conflict is answerable only through that line)."""
    c, context = item
    rank = web_settle.KIND_ORDER.get(c.kind, 2)
    return (rank, 0 if c.kind != "conflict" or web_settle.has_mentions(context) else 1)


def select(memory_path: Path, facts: web_settle.BankFacts, memo: dict[str, dict], today: date, *, cap: int,
           skip: frozenset[str] = frozenset(), include_recent: bool = False,
           ) -> tuple[list[tuple[web_settle.Candidate, list[str]]], int]:
    """``(the next ``cap`` questions with their local context, how many were eligible)`` — read-only, engine-free.
    A question looked up in the last 30 days waits (unless ``include_recent``: the dry run's re-measure); a page or item
    with someone's uncommitted edit is not ours to commit (the G85 smear) and waits."""
    from api.services import inbox_context, pending_store

    def _dirty(c: web_settle.Candidate) -> bool:
        return bool(skip & {f"entities/{c.entity_id}.md", f"inbox/{c.item_id}.md", pending_store.PENDING_STORE_FILE})

    eligible = [c for c in web_settle.candidates(memory_path, facts=facts)
                if (include_recent or not _recent(memo, c.item_id, today)) and not _dirty(c)]
    if not eligible:
        return [], 0
    ctx = inbox_context.InboxContext(Path(memory_path), today=today.isoformat())
    picked: list[tuple[web_settle.Candidate, list[str]]] = []
    for c in eligible:
        picked.append((c, web_settle.local_context(memory_path, c, facts, ctx=ctx)))
    picked.sort(key=_order)   # stable: priority, then age, within each rank
    return picked[:cap], len(eligible)


async def look_up(fn: Callable[..., Any], todo: list[tuple[web_settle.Candidate, list[str]]], report: Report,
                  ) -> list[tuple[web_settle.Candidate, Answer]]:
    """One engine call per question; an answer counts only when every search was the pinned query. Writes nothing."""
    answers: list[tuple[web_settle.Candidate, Answer]] = []
    for c, context in todo:
        report.looked_up += 1
        try:
            resp = await asyncio.to_thread(fn, messages=build_messages(c, context), web_search=True,
                                           timeout=TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 — one failed lookup never stops the rest
            from api.services import engine_errors

            logger.info(f"web check: a lookup failed ({type(exc).__name__})")
            answers.append((c, Answer(c.item_id, False, "engine_error")))
            if isinstance(exc, (engine_errors.EngineThrottled, engine_errors.EngineExhausted,
                                engine_errors.EngineOverage)):
                break   # a plan limit is a pause: the rest waits for the next run
            continue
        model = _model_of(resp)
        if model and model not in report.models:
            report.models.append(model)
        if not queries_ok(searched_queries(resp), web_settle.query_for(c)):
            answers.append((c, Answer(c.item_id, False, "query_strayed")))
            continue
        answers.append((c, parse_answer(c, _content(resp))))
    return answers


async def run_tail(
    memory_path: Path, settings, *, user_triggered: bool, llm_fn: Callable[..., Any] | None = None,
    engine: tuple[Any, str | None, str] | None = None, today: date | None = None, skip: frozenset[str] = frozenset(),
    report: Report | None = None,
) -> Report:
    """Look up and settle this run's public-thing questions. Never raises; the caller commits ``report.paths``.
    ``llm_fn``/``engine`` are test seams (a fake search tool); production resolves both here, lazily — no engine is
    resolved, and no registry touched, when there is nothing to look up."""
    from api.services.connectors.base import network_allowed

    report = report if report is not None else Report()
    memory_path = Path(memory_path)
    today = today or date.today()
    cap = int(getattr(settings, "web_check_per_run", DEFAULT_PER_RUN) or 0)
    if cap <= 0:
        report.reason = "off"
        return report
    if not network_allowed():
        report.reason = "gate"
        return report
    facts = web_settle.bank_facts(memory_path)
    memo = load_memo(memory_path)
    from api.services import pending_store

    todo, _eligible = select(memory_path, facts, memo, today, cap=cap, skip=skip)
    if not todo:
        report.reason = "nothing"
        return report
    resolved, label, why = engine if engine is not None else await engine_for(settings, user_triggered=user_triggered)
    report.engine = label
    if resolved is None:
        report.reason = why
        for c, _ in todo:
            web_settle.record_event(memory_path, action="skip", item_id=c.item_id, entity_id=c.entity_id,
                                    by_kind="sleep", reason=why, engine=label)
        return report
    fn = llm_fn or default_llm_fn(resolved)
    answers = await look_up(fn, todo, report)
    by = report.models[0] if report.models else (label or "agent")
    for c, a in answers:
        # An engine that never answered (a plan limit, a timeout, a signed-out CLI) looked nothing up: the question is
        # offered again next run, never held for RETRY_DAYS (a plan limit is a pause, not a failure).
        if a.reason != "engine_error":
            memo[c.item_id] = {"at": today.isoformat(), "outcome": "settled" if a.ok else a.reason}
        if not a.ok:
            report.skip(a.reason)
            web_settle.record_event(memory_path, action="skip", item_id=c.item_id, entity_id=c.entity_id,
                                    by_kind="sleep", reason=a.reason, engine=label)
            continue
        _snapshot(memory_path, report, [
            f"entities/{c.entity_id}.md", f"entities/{c.entity_id}.claims.jsonl", pending_store.PENDING_STORE_FILE,
            f"inbox/{c.item_id}.md", f"inbox/{web_settle.SETTLED_DIR}/{c.item_id}.md"])
        try:
            done = await asyncio.to_thread(
                web_settle.settle, memory_path, c.item_id, ref=a.url, quote=a.quote, option_key=a.option_key,
                answer=a.answer, checker=by, checker_kind="sleep", origin="sleep", engine=label, facts=facts)
        except web_settle.NotSettleable:
            memo[c.item_id]["outcome"] = "refused"
            report.skip("refused")
            web_settle.record_event(memory_path, action="skip", item_id=c.item_id, entity_id=c.entity_id,
                                    by_kind="sleep", reason="refused", engine=label)
            continue
        facts = web_settle.bank_facts(memory_path)   # a settle may have changed the pending store
        report.settled += 1
        report.settled_items.append(c.item_id)
        report.before[f"episodes/{done.episode_id}.md"] = None   # new: it did not exist before
        report.paths += [p for p in done.paths if p not in report.paths]
        report.lines += done.lines
        web_settle.record_event(memory_path, action="settle", item_id=c.item_id, entity_id=c.entity_id,
                                by_kind="sleep", engine=label)
    save_memo(memory_path, memo)
    return report


def scope_name(cycle_id: str | None) -> str:
    return f"sleep:{cycle_id}" if cycle_id else f"web:{uuid.uuid4().hex}"


# --------------------------------------------------------------------------- the dry run (owner brief, 2026-10-16)


async def dry_run(memory_path: Path, settings, *, limit: int, include_recent: bool = False,
                  llm_fn: Callable[..., Any] | None = None, engine: tuple[Any, str | None, str] | None = None,
                  today: date | None = None) -> dict:
    """Run the real engine on the next ``limit`` questions a person-started run would look up and return COUNTS only
    — looked up, would settle, and the reasons by kind — writing nothing: no settle, no memo, no ledger row (the
    engine's usage sink is a no-op), no commit. Not behind ``CICADA_ALLOW_CONNECTOR_FETCH``: a person runs it by hand,
    as a click is never gated; the gate's state is reported. ``include_recent`` re-measures questions a run already
    looked up in the last 30 days (the memo is read, never written)."""
    from api.services.connectors.base import network_allowed

    memory_path = Path(memory_path)
    today = today or date.today()
    out: dict[str, Any] = {"gate": "on" if network_allowed() else "off", "eligible": 0, "looked_up": 0,
                           "would_settle": 0, "with_mentions": 0, "with_description": 0, "bare_name_queries": 0,
                           "by_kind": {}}
    facts = web_settle.bank_facts(memory_path)
    todo, out["eligible"] = select(memory_path, facts, load_memo(memory_path), today, cap=max(0, int(limit)),
                                   include_recent=include_recent)
    if not todo:
        out["reason"] = "nothing"
        return out
    for c, context in todo:
        out["with_mentions"] += int(web_settle.has_mentions(context))
        out["with_description"] += int(any(line.startswith("Cicada's description: ") for line in context))
        out["bare_name_queries"] += int(not c.category)
    resolved, label, why = engine if engine is not None else await engine_for(settings, user_triggered=True)
    out["engine"] = label
    if resolved is None:
        out["reason"] = why
        return out
    report = Report(engine=label)
    fn = llm_fn or default_llm_fn(resolved, sink=lambda _event: None)
    answers = await look_up(fn, todo, report)
    out["looked_up"] = report.looked_up
    for c, a in answers:
        kind = "type_conflict" if c.type_question else c.kind
        row = out["by_kind"].setdefault(kind, {"looked_up": 0, "would_settle": 0, "reasons": {}})
        row["looked_up"] += 1
        if a.ok:
            row["would_settle"] += 1
            out["would_settle"] += 1
        else:
            row["reasons"][a.reason] = row["reasons"].get(a.reason, 0) + 1
    return out
