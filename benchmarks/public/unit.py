"""One unit, in its own process: ingest → Sleep → answer → judge, each step checkpointed. Launch through ``run``.

The launcher (``benchmarks.public.run``) has already isolated this process: ``HOME``/``CICADA_HOME`` are the
benchmark home, ``CICADA_MEMORY_PATH`` is this unit's marked throwaway bank, capture/telemetry/fetches are off and no
provider key is present. Its one job description arrives as JSON on stdin.

**Production paths, nothing re-implemented.** Sessions become episodes through ``episode_staging.stage`` (the stager
every importer shares), dated with the session's own day; Sleep is ``sleep_cycle.run(drain=True)`` — all five stages
and the tail; the answer is ``ask_service.answer_query`` (``cicada_ask``'s body). The only substitutions are the
benchmark clock (``benchmarks.system.runtime.Runtime.frozen``: Sleep and Ask run on the dataset's day, not 2026's) and
where a ``claude`` child finds its sign-in (below).

**The plan.** ``CICADA_LLM_MODE=agent``: every model call is a ``claude -p`` on the person's own plan, through
Cicada's own engine (``--safe-mode``, no tools, no settings, no session persistence, ``CICADA_CAPTURE=off``). Its
sign-in lives under the person's real home, so ``claude`` children — and only they — get ``HOME`` set to
``CICADA_BENCH_CLAUDE_HOME``; Cicada itself never sees that folder. A plan limit pauses Sleep (exit 3) and a
re-run continues it.

**No settings file.** Before anything from ``api.services`` is imported, ``isolate_settings`` turns off both ways a
checkout's ``api/.env`` reaches a process (``api.settings_file`` and ``Settings``' ``env_file``): every ``get_settings()``
the production paths call (Ask's engine, the embedder) then reads this child's allowlisted environment alone, so a
score never depends on whose machine ran it.

Exit codes: 0 done; 3 paused on a plan limit (re-run to continue); 4 Sleep stopped for another resumable reason
(engine signed out or unavailable, bank busy, cancelled — the reason is printed); 5 every step ran but some answers
or judgments failed (re-run retries exactly those); 1 failed.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

PAUSED = 3          # a plan limit (window, weekly, overage) or Cicada's reserve
STOPPED = 4         # resumable, not a plan limit: engine signed out/unavailable, bank busy, cancelled
INCOMPLETE = 5      # some answers or judgments failed; a re-run retries them
PLAN_STOPS = ("plan_limit", "reserve")


def stop_exit(leg: dict, *, paused: bool) -> int | None:
    """How a drain leg ends the unit: ``None`` to go on, ``PAUSED`` for a plan limit, ``STOPPED`` for any other
    resumable stop; a failure raises (exit 1) — never reported as a plan limit."""
    if leg["stop"] == "error" or (leg["error"] and not leg["stop"]):
        raise RuntimeError(f"Sleep failed: {leg['error']}")
    if leg["stop"] or paused:
        return PAUSED if leg["stop"] in PLAN_STOPS else STOPPED
    return None


def answers_to_do(questions: list[dict], paths: list[str], rows: dict[str, dict]) -> list[tuple[dict, str]]:
    """Every (question, path) with no answer yet or whose last answer failed: a failure is retried on every run."""
    return [(q, p) for q in questions for p in paths
            if f"{q['qid']}|{p}" not in rows or rows[f"{q['qid']}|{p}"].get("error")]


def isolate_settings() -> None:
    """Read no ``api/.env``: call before anything from ``api.services`` is imported (see the module docstring)."""
    from api import settings_file
    from api.config import disable_dotenv

    settings_file.disable()
    disable_dotenv()


def _jsonl(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                out[row["key"]] = row
    return out


class Checkpoint:
    """Append-only rows keyed by ``key``; the last row for a key wins. A re-run skips every key already done."""

    def __init__(self, path: Path):
        self.path, self.rows, self.lock = path, _jsonl(path), threading.Lock()

    def add(self, row: dict) -> None:
        with self.lock:
            self.rows[row["key"]] = row
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------------------------------------------- #
# The plan engine: claude children find the person's sign-in; every call is counted
# --------------------------------------------------------------------------------------------------------------- #

class Calls:
    def __init__(self, path: Path, unit_id: str):
        self.path, self.unit_id, self.lock = path, unit_id, threading.Lock()
        self.phase = "setup"

    def record(self, stage, model, seconds, ok, error=None, tokens=None):
        row = {"unit": self.unit_id, "phase": self.phase, "stage": stage, "model": model,
               "seconds": round(seconds, 3), "ok": ok, "error": error, "tokens": tokens}
        with self.lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")


def install_engine(calls: Calls) -> None:
    from unittest.mock import patch

    from api.services import agent_engine, providers
    from api.services.connections import base

    claude_home = os.environ.get("CICADA_BENCH_CLAUDE_HOME", "").strip()
    real_scrubbed = base.scrubbed_env

    def scrubbed(name=None):
        env = real_scrubbed(name)
        if claude_home and name and os.path.basename(name) == "claude":
            env["HOME"] = claude_home   # the plan's sign-in; Cicada's own process keeps the benchmark home
        return env

    patch.object(base, "scrubbed_env", scrubbed).start()

    original = providers.resolve_llm_fn

    def counted(settings, **kwargs):
        if settings.llm_mode != "agent":
            raise RuntimeError(f"benchmark engine pin lost (llm_mode={settings.llm_mode}); refusing any other engine")
        fn = original(settings, **kwargs)
        stage = kwargs.get("stage")
        model = agent_engine.model_for_stage(settings, stage)
        is_async = kwargs.get("is_async")
        if is_async is None:
            import inspect
            is_async = inspect.iscoroutinefunction(kwargs.get("completion"))

        def usage(resp):
            try:
                from api.services import telemetry
                return telemetry.usage_from_response(resp)
            except Exception:  # noqa: BLE001
                return None

        if is_async:
            async def acall(**kw):
                started = time.perf_counter()
                try:
                    resp = await fn(**kw)
                except Exception as exc:
                    calls.record(stage, model, time.perf_counter() - started, False, type(exc).__name__)
                    raise
                calls.record(stage, model, time.perf_counter() - started, True, tokens=usage(resp))
                return resp
            return acall

        def call(**kw):
            started = time.perf_counter()
            try:
                resp = fn(**kw)
            except Exception as exc:
                calls.record(stage, model, time.perf_counter() - started, False, type(exc).__name__)
                raise
            calls.record(stage, model, time.perf_counter() - started, True, tokens=usage(resp))
            return resp
        return call

    for name, module in list(sys.modules.items()):
        if name.startswith("api.services.") and getattr(module, "resolve_llm_fn", None) is original:
            patch.object(module, "resolve_llm_fn", counted).start()


def install_fake_engine() -> None:
    """Offline proof only (the harness's own test): the plan's ``claude -p`` call is replaced BELOW the production
    provider seam by the system benchmark's deterministic grammar engine, and the search model by feature hashing.
    Every network connection fails closed. Never a score."""
    import socket
    from unittest.mock import patch

    from api.services import agent_engine, providers

    from benchmarks.system.engine import FakeEngine, embed

    fake = FakeEngine()

    def complete(*, messages, model=None, stage=None, **_unused):
        text = messages[-1]["content"] if messages else ""
        if stage == "judge":
            # The prompt's own worked example also has a "Gold answer:" line: the question's is the last one.
            gold = re.findall(r"Gold answer: (.*)\n", text)
            hyp = re.findall(r"Generated answer: (.*)\n", text)
            ok = bool(gold and hyp and gold[-1].strip().lower() in hyp[-1].lower())
            return {"result": json.dumps({"label": "CORRECT" if ok else "WRONG"})}
        call = fake.completion(stage=stage, is_async=False)
        resp = call(model=model, messages=messages)
        return {"result": resp.choices[0].message.content}

    patch.object(agent_engine, "complete", complete).start()

    async def signed_in(settings):
        return True, "offline benchmark engine"

    from api.services import sleep_cycle
    patch.object(sleep_cycle, "_probe_engine_cheaply", signed_in).start()
    patch.object(providers, "resolve_embed_fn", lambda *a, **k: (embed, "fake-hash-v1")).start()
    patch.object(providers, "resolve_embed_fn_for_model", lambda *a, **k: (embed, "fake-hash-v1")).start()

    def no_network(*args, **kwargs):
        raise RuntimeError("the offline benchmark forbids network access")

    patch.object(socket.socket, "connect", no_network).start()
    patch.object(socket, "create_connection", no_network).start()


# --------------------------------------------------------------------------------------------------------------- #
# Bank
# --------------------------------------------------------------------------------------------------------------- #

def _git_commit(bank: Path, paths: list[str], subject: str) -> None:
    from api.services import git_service

    if paths:
        git_service.commit_paths_sync(bank, git_service.build_commit_message(subject, [], authors=["user"]), paths)


def setup_bank(bank: Path, unit: dict) -> None:
    """A fresh marked bank, initialised like the system benchmark's, with this unit's owner named."""
    from api.services import owner_identity

    from benchmarks.system.workload import initialize

    if not (bank / ".git").exists():
        initialize(bank)
    owner = unit.get("owner")
    if owner:
        entity_id, _ = owner_identity.ensure_owner_entity(bank, owner["name"])
        owner_identity.save_owner({"name": owner["name"], "entity_id": entity_id})
    else:
        try:
            owner_identity.owner_json_path().unlink()
        except FileNotFoundError:
            pass
        owner_identity.ensure_default_owner(bank)
    import subprocess

    # Sleep runs in a clean-tree-guarded slot: the owner page is committed before anything is read.
    dirty = subprocess.run(["git", "-C", str(bank), "status", "--porcelain", "--untracked-files=all"], text=True,
                           capture_output=True, check=True).stdout.splitlines()
    _git_commit(bank, [line[3:] for line in dirty if line.strip()], "Benchmark owner")


def drafts(unit: dict, sessions: list[dict]):
    from api.services.episode_staging import EpisodeDraft, Turn
    from api.services.id_utils import sanitize_id

    other = unit.get("other")
    marker = f"speaker:{sanitize_id(other['name'])}" if other else "assistant"
    extra = {"correspondent": {"name": other["name"], "kind": other.get("kind", "person"), "decided_by": "person"}} \
        if other else {}
    out = []
    for s in sessions:
        out.append(EpisodeDraft(
            title=s["title"], source_id=s["source_id"], timestamp=s["date"], original_date=s["date"][:10],
            source="import", origin="benchmark", extra=dict(extra),
            turns=[Turn(text=t["text"], speaker=marker if t["speaker"] == "other" else t["speaker"], ts=t["ts"])
                   for t in s["turns"]]))
    return out


def stage_sessions(bank: Path, unit: dict, sessions: list[dict]) -> dict:
    from api.services import episode_staging

    result = episode_staging.stage(drafts(unit, sessions), bank / "episodes")
    _git_commit(bank, result.paths, "Benchmark intake")
    return {"created": result.created, "updated": result.updated, "skipped": result.skipped}


# --------------------------------------------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------------------------------------------- #

def _clock(iso: str) -> datetime:
    return datetime.fromisoformat(iso).astimezone(timezone.utc)


async def run_unit(job: dict) -> int:
    from api.config import Settings
    from benchmarks.system.runtime import CLOCK_MODULES, Runtime

    from . import judges

    unit = json.loads(Path(job["unit_path"]).read_text(encoding="utf-8"))
    bank, out = Path(job["bank"]), Path(job["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    calls = Calls(out / "calls.jsonl", unit["unit_id"])
    state_path = out / "state.json"
    state = json.loads(state_path.read_text()) if state_path.is_file() else {}

    def save_state():
        state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")

    for name in CLOCK_MODULES:
        importlib.import_module("api.services." + name)
    if job.get("fake_engine"):
        install_fake_engine()
    install_engine(calls)

    settings = Settings(_env_file=None, CICADA_MEMORY_PATH=str(bank), llm_mode="agent",
                        agent_model=job["sleep_model"], agent_disambiguation_model=job["disambiguation_model"],
                        sleep_max_episodes_per_cycle=int(job["batch_size"]), link_enrich_enabled=False)
    if settings.memory_path != bank:
        raise RuntimeError("the active bank is not this unit's throwaway bank — refusing")
    answer_settings = settings.model_copy(update={"agent_model": job["answer_model"]})
    judge_settings = settings.model_copy(update={"agent_model": job["judge_model"]})

    # ---- ingest + Sleep, on the dataset's own clock -------------------------------------------------------------
    from api.services import sleep_cycle, sleep_paused

    if not state.get("slept"):
        calls.phase = "sleep"
        with Runtime(_clock(unit["clock"]), settings).frozen():
            setup_bank(bank, unit)
        if job["sleep_schedule"] == "none":
            # The control for "what do the raw conversations alone give Ask": stage and index, never consolidate.
            with Runtime(_clock(unit["clock"]), settings).frozen():
                staged = stage_sessions(bank, unit, unit["sessions"])
                started = time.perf_counter()
                build_indexes(bank)
            state["sleep"] = {"skipped": True, "staged": staged, "drains": [],
                              "index_seconds": round(time.perf_counter() - started, 2), "seconds": 0.0}
            steps = []
        elif job["sleep_schedule"] == "per-session":
            steps = [[s] for s in unit["sessions"]]
        else:
            steps = [unit["sessions"]]
        state.setdefault("sleep", {"drains": [], "seconds": 0.0})
        for i, sessions in enumerate(steps):
            if i < len(state["sleep"]["drains"]) and state["sleep"]["drains"][i].get("finished"):
                continue
            last = max(_clock(s["date"]) for s in sessions)
            now = _clock(unit["clock"]) if job["sleep_schedule"] == "once" else last + timedelta(hours=1)
            runtime = Runtime(now, settings)
            with runtime.frozen():
                staged = stage_sessions(bank, unit, sessions)
                record = sleep_paused.get_paused(bank)
                started = time.perf_counter()
                cycle_id = f"sleep_bench_{i:03d}"
                await sleep_cycle.run(settings, cycle_id, user_triggered=True, drain=True, continue_from=record)
                seconds = time.perf_counter() - started
            st = sleep_cycle.get_sleep_state()
            ds = st.drain
            leg = {"step": i, "clock": now.isoformat(), "staged": staged, "seconds": round(seconds, 2),
                   "error": st.error, "stop": ds.stop.reason if ds and ds.stop else None,
                   "filed": ds.filed if ds else 0, "finished": bool(ds.finished) if ds else True,
                   "waiting": len(sleep_cycle._get_unprocessed_episodes(bank))}
            state["sleep"]["seconds"] = round(state["sleep"]["seconds"] + seconds, 2)
            if i < len(state["sleep"]["drains"]):
                state["sleep"]["drains"][i] = leg
            else:
                state["sleep"]["drains"].append(leg)
            save_state()
            code = stop_exit(leg, paused=bool(sleep_paused.get_paused(bank)))
            if code is not None:
                print(f"[{unit['unit_id']}] Sleep stopped ({leg['stop']}: {leg['error'] or 'no detail'}); "
                      "re-run with --resume to continue", file=sys.stderr)
                return code
        state["slept"] = True
        state["bank"] = bank_stats(bank)
        save_state()

    # ---- answer -----------------------------------------------------------------------------------------------
    answers = Checkpoint(out / "answers.jsonl")
    judged = Checkpoint(out / "judgments.jsonl")
    paths = [p for p in job["paths"] if p]
    # A failed answer is retried on every run until it succeeds; it is never silently dropped.
    todo = answers_to_do(unit["questions"], paths, answers.rows)
    calls.phase = "answer"
    if todo and "ask" in paths:
        from api.services import search_index

        search_index.ensure_fresh(bank, wait=True)   # what the running backend keeps fresh; never a half-built index
    prompts = Checkpoint(out / "prompts.jsonl")
    transcript = full_transcript(unit) if "full-context" in paths else ""
    answer_fn = make_answerers(bank, answer_settings, transcript)

    def answer_one(item):
        q, path = item
        clock = _clock(q["question_date"] or unit["clock"])
        started = time.perf_counter()
        try:
            response = answer_fn[path](q["question"])
            err = None
        except Exception as exc:  # noqa: BLE001 — one failed answer is recorded, never fatal
            response, err = {"answer": ""}, f"{type(exc).__name__}: {exc}"[:300]
        seen = response.pop("_bench", None) or {}
        prompt = seen.get("prompt")
        extra = {}
        if path == "ask":
            extra = {"prompt_chars": len(prompt) if prompt is not None else 0,
                     "model_called": prompt is not None, "context_ms": seen.get("context_ms"),
                     **evidence_shown(unit, q, prompt or "")}
            prompts.add({"key": f"{q['qid']}|{path}", "prompt": prompt})
        answers.add({"key": f"{q['qid']}|{path}", "qid": q["qid"], "path": path, "clock": clock.isoformat(),
                     "answer": str(response.get("answer", "")), "confidence": response.get("confidence"),
                     "gaps": response.get("gaps"), "cited": len(response.get("citations") or []),
                     "used_entities": response.get("used_entities"), "error": err,
                     "seconds": round(time.perf_counter() - started, 2), **extra})

    if todo:
        # Questions share one clock per unit except LongMemEval, where a unit is one question.
        with Runtime(_clock(unit["questions"][0]["question_date"] or unit["clock"]), settings).frozen():
            with ThreadPoolExecutor(max_workers=int(job["concurrency"])) as pool:
                list(pool.map(answer_one, todo))

    # ---- judge ------------------------------------------------------------------------------------------------
    calls.phase = "judge"
    from api.services import providers

    judge_llm = providers.resolve_llm_fn(judge_settings, stage="judge", is_async=False)
    by_qid = {q["qid"]: q for q in unit["questions"]}

    def judge_one(row):
        q = by_qid[row["qid"]]
        hyp = row["answer"]
        if unit["dataset"] == "locomo":
            if q["abstention"]:
                prompt = judges.lme_prompt("abstention", q["question"], "The conversation never says this; the "
                                           "question's premise is not supported.", hyp, abstention=True)
            else:
                prompt = judges.mem0_prompt(q["question"], q["answer"], hyp)
        else:
            prompt = judges.lme_prompt(q["category"], q["question"], q["answer"], hyp, abstention=q["abstention"])
        try:
            resp = judge_llm(messages=[{"role": "user", "content": prompt}])
            reply = resp.choices[0].message.content or ""
            err = None
        except Exception as exc:  # noqa: BLE001
            reply, err = "", f"{type(exc).__name__}: {exc}"[:300]
        if unit["dataset"] == "locomo" and not q["abstention"]:
            label = judges.parse_mem0(reply)
        else:
            label = judges.parse_lme(reply) if reply else None
        f1 = judges.locomo_f1(hyp, q["answer"], q["category_id"]) if unit["dataset"] == "locomo" else None
        judged.add({"key": row["key"], "qid": row["qid"], "path": row["path"], "category": q["category"],
                    "abstention": q["abstention"], "correct": label, "f1": f1, "reply": reply[:400], "error": err})

    pending = [r for r in answers.rows.values() if r["key"] not in judged.rows or judged.rows[r["key"]]["correct"] is None]
    pending = [r for r in pending if not r.get("error")]
    if pending:
        with ThreadPoolExecutor(max_workers=int(job["concurrency"])) as pool:
            list(pool.map(judge_one, pending))
    keys = [f"{q['qid']}|{p}" for q in unit["questions"] for p in paths]
    state["unanswered"] = sum(1 for k in keys if k not in answers.rows or answers.rows[k].get("error"))
    state["ungraded"] = sum(1 for k in keys if k in answers.rows and not answers.rows[k].get("error")
                            and (k not in judged.rows or judged.rows[k]["correct"] is None))
    state["done"] = not state["unanswered"] and not state["ungraded"]
    save_state()
    if not state["done"]:
        print(f"[{unit['unit_id']}] {state['unanswered']} unanswered, {state['ungraded']} ungraded; "
              "re-run with --resume to retry them", file=sys.stderr)
        return INCOMPLETE
    return 0


def make_answerers(bank: Path, settings, transcript: str) -> dict:
    from api.services import ask_service, providers

    def ask(question: str) -> dict:
        """``cicada_ask``'s body; the prompt the model read and the time spent before the model call are kept beside
        the answer (``_bench``) — the retrieval stats read them. No model call (an honest gap) leaves no prompt."""
        real = ask_service._default_llm_fn(settings)
        seen: dict = {}
        started = time.perf_counter()

        def llm(prompt: str) -> str:
            seen["context_ms"] = round((time.perf_counter() - started) * 1000, 1)
            seen["prompt"] = prompt
            return real(prompt)

        response = ask_service.answer_query(bank, question, top_k=6, llm_fn=llm, no_engine=False)
        return {**response, "_bench": seen}

    def full_context(question: str) -> dict:
        """The control: the whole conversation history, raw, with the same answer prompt Ask uses."""
        from api.services import json_parse
        from api.services.claims import current_day

        prompt = (f"QUESTION:\n{question}\n\nCURRENT LOCAL DAY: {current_day().isoformat()}\n"
                  f"FULL CONVERSATION HISTORY (raw, oldest first):\n\n{transcript}")
        fn = providers.resolve_llm_fn(settings, stage="answer_control", is_async=False)
        resp = fn(messages=[{"role": "system", "content": ask_service.ASK_SYSTEM_PROMPT},
                            {"role": "user", "content": prompt}], response_format={"type": "json_object"})
        parsed = json_parse.parse_json_object(resp.choices[0].message.content or "")
        return parsed if isinstance(parsed, dict) else {"answer": resp.choices[0].message.content or ""}

    return {"ask": ask, "full-context": full_context}


def build_indexes(bank: Path) -> None:
    """The derived indexes Sleep's tail would build (episode vectors, the word index), with no model call."""
    from api.services import search_index, vector_index

    vector_index.SqliteVecIndexer(bank).index_episodes()
    search_index.ensure_fresh(bank, wait=True)


def _norm(text: str) -> str:
    return " ".join(str(text).split()).lower()


def evidence_turns(unit: dict, q: dict) -> list[str]:
    """The dataset's own answer turns for a question: LoCoMo's ``evidence`` dialogue ids; LongMemEval's
    ``has_answer`` turns inside its answer sessions."""
    if unit["dataset"] == "locomo":
        wanted = {e.strip() for raw in q.get("evidence") or [] for e in str(raw).replace(",", ";").split(";")
                  if e.strip()}
        return [t["text"] for s in unit["sessions"] for t in s["turns"] if t.get("dia_id") in wanted]
    sids = set(q.get("evidence") or [])
    return [t["text"] for s in unit["sessions"] if s["source_id"].rsplit(":", 1)[-1] in sids
            for t in s["turns"] if t.get("has_answer")]


def evidence_shown(unit: dict, q: dict, prompt: str, *, window: int = 40, step: int = 20) -> dict:
    """Whether an answer turn's own words reached the prompt: any ``window``-character stretch of the turn (case and
    spacing folded) appearing verbatim. A clipped turn still counts; a paraphrase on a page never does."""
    turns = evidence_turns(unit, q)
    text = _norm(prompt)
    shown = 0
    for turn in turns:
        t = _norm(turn)
        pieces = [t] if len(t) <= window else [t[i:i + window] for i in range(0, len(t) - window + 1, step)]
        shown += any(p and p in text for p in pieces)
    return {"evidence_turns": len(turns), "evidence_shown": shown}


def full_transcript(unit: dict) -> str:
    owner = (unit.get("owner") or {}).get("name") or "user"
    other = (unit.get("other") or {}).get("name") or "assistant"
    blocks = []
    for s in unit["sessions"]:
        lines = [f"[{s['date'][:16].replace('T', ' ')}] {s['title']}"]
        for t in s["turns"]:
            who = owner if t["speaker"] == "user" else other
            lines.append(f"{who}: {t['text']}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def bank_stats(bank: Path) -> dict:
    from api.services import claims, markdown_parser

    pages = sorted((bank / "entities").glob("*.md"))
    n_claims = 0
    status: dict[str, int] = {}
    for page in pages:
        try:
            parsed = markdown_parser.parse(page)
        except Exception:  # noqa: BLE001
            continue
        st = str((parsed.frontmatter or {}).get("status") or "?")
        status[st] = status.get(st, 0) + 1
        n_claims += len(claims.parse_claims(parsed.body))
    pending = bank / "pending_entities.jsonl"
    return {"pages": len(pages), "claims": n_claims, "status": status,
            "pending_lines": sum(1 for _ in pending.open()) if pending.is_file() else 0,
            "episodes": len(list((bank / "episodes").glob("*.md")))}


def main() -> int:
    isolate_settings()   # before run_unit imports anything from api.services
    job = json.loads(sys.stdin.read())
    try:
        return asyncio.run(run_unit(job))
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
