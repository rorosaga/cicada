"""The web lookup on Sleep's tail: who searches, on which engine, under which gate (owner ruling 2026-10-16, G61).

Rodrigo, 2026-10-16: "Runs from your Claude plan in runs you start; a scheduled metered run costs a few cents more."

After the last batch's nudges, a bounded step looks up public-thing questions (``web_settle.classify``) and settles
the ones the search answers. The rules, each enforced here:

* **The gate.** ``CICADA_ALLOW_CONNECTOR_FETCH`` governs it: a lookup Sleep starts on its own is an unattended fetch.
* **Ruling 4.** A run the person started may use their Claude plan: one ``claude -p`` per question whose ONE tool is
  the plan's web search (``agent_engine.CallPolicy.web_search``). A scheduled run never uses a plan — not even an
  explicit ``CICADA_LLM_MODE`` pin. On a metered engine (an API key) either run may use that provider's own search
  (litellm's ``web_search_options``) at its price, recorded as an ``llm_call`` of stage ``web_check`` tagged with the
  run, so Past reads shows it with its basis (ruling 12). The ChatGPT plan and a local model get no search: skipped.
* **What leaves the machine.** The search query is ``web_settle.query_for`` — the subject's name and generic category
  words — pinned in the prompt, and every search the engine reports is held to it: a call that searched anything
  else (or nothing) is discarded, nothing is settled from it. The prompt carries the name, the category words and, for
  a conflict, its option labels; never a conversation's text, never another name from the bank.
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
MAX_SEARCHES = 2
RETRY_DAYS = 30
TIMEOUT_S = 120.0

SYSTEM_PROMPT = (
    "You look up ONE public thing on the web to answer one question about it. Use the web search tool with exactly "
    "the query you are given, word for word, at most twice; never add, remove or change a word, and never search for "
    "anything else. Answer only from what the results say. If the results do not clearly answer the question, or "
    "the subject could be a private person, someone's own file or project, answer {\"sure\": false}. Reply with one "
    "JSON object and nothing else: {\"sure\": true, \"option_key\": <the key of the option that is true, for a "
    "choice>, \"answer\": <one short phrase, at most 25 words, for a 'what is it' question>, \"url\": <the link of the "
    "page that says it>, \"quote\": <that page's own words that say it, verbatim, at most 240 characters>}."
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

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1


def build_messages(c: web_settle.Candidate) -> list[dict]:
    query = web_settle.query_for(c)
    lines = [f"Subject: {c.name}", f"Search query (use exactly this): {query}"]
    if c.kind == "conflict":
        lines.append(f"Question: which of these is true of {c.name}?")
        lines += [f"  option_key {key!r}: {label}" for key, label in c.options]
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
    uses = None
    try:
        uses = resp["tool_uses"]
    except (KeyError, TypeError):
        uses = getattr(resp, "tool_uses", None)
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
        if key not in {k for k, _ in c.options}:
            return Answer(c.item_id, False, "no_option")
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
    try:
        import litellm

        can = bool(litellm.supports_web_search(model=model))
    except Exception:  # noqa: BLE001 — an unknown model has no known search
        can = False
    return (resolved, label, "metered") if can else (None, label, "no_search_tool")


def default_llm_fn(resolved) -> Callable[..., Any]:
    from api.services import providers

    if str(getattr(resolved, "llm_mode", "")).lower() == "agent":
        return providers.resolve_llm_fn(resolved, stage=STAGE, is_async=False)
    import litellm

    return providers.resolve_llm_fn(resolved, stage=STAGE, completion=litellm.completion)


def _model_of(resp: Any) -> str | None:
    try:
        return str(resp["model"] or "") or None
    except (KeyError, TypeError):
        return str(getattr(resp, "model", "") or "") or None


async def run_tail(
    memory_path: Path, settings, *, user_triggered: bool, llm_fn: Callable[..., Any] | None = None,
    engine: tuple[Any, str | None, str] | None = None, today: date | None = None, skip: frozenset[str] = frozenset(),
) -> Report:
    """Look up and settle this run's public-thing questions. Never raises; the caller commits ``report.paths``.
    ``llm_fn``/``engine`` are test seams (a fake search tool); production resolves both here, lazily — no engine is
    resolved, and no registry touched, when there is nothing to look up."""
    from api.services.connectors.base import network_allowed

    report = Report()
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

    def _dirty(c: web_settle.Candidate) -> bool:
        # A page or item with someone's uncommitted edit is not ours to commit (the G85 smear): it waits.
        return bool(skip & {f"entities/{c.entity_id}.md", f"inbox/{c.item_id}.md", pending_store.PENDING_STORE_FILE})

    todo = [c for c in web_settle.candidates(memory_path, facts=facts)
            if not _recent(memo, c.item_id, today) and not _dirty(c)][:cap]
    if not todo:
        report.reason = "nothing"
        return report
    resolved, label, why = engine if engine is not None else await engine_for(settings, user_triggered=user_triggered)
    report.engine = label
    if resolved is None:
        report.reason = why
        for c in todo:
            web_settle.record_event(memory_path, action="skip", item_id=c.item_id, entity_id=c.entity_id,
                                    by_kind="sleep", reason=why, engine=label)
        return report
    fn = llm_fn or default_llm_fn(resolved)
    answers: list[tuple[web_settle.Candidate, Answer]] = []
    for c in todo:
        report.looked_up += 1
        try:
            resp = await asyncio.to_thread(fn, messages=build_messages(c), web_search=True, timeout=TIMEOUT_S)
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
    by = report.models[0] if report.models else (label or "agent")
    for c, a in answers:
        memo[c.item_id] = {"at": today.isoformat(), "outcome": "settled" if a.ok else a.reason}
        if not a.ok:
            report.skip(a.reason)
            web_settle.record_event(memory_path, action="skip", item_id=c.item_id, entity_id=c.entity_id,
                                    by_kind="sleep", reason=a.reason, engine=label)
            continue
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
        report.paths += [p for p in done.paths if p not in report.paths]
        report.lines += done.lines
        web_settle.record_event(memory_path, action="settle", item_id=c.item_id, entity_id=c.entity_id,
                                by_kind="sleep", engine=label)
    save_memo(memory_path, memo)
    return report


def scope_name(cycle_id: str | None) -> str:
    return f"sleep:{cycle_id}" if cycle_id else f"web:{uuid.uuid4().hex}"
