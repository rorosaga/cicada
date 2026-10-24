"""Memory and source-collection costs, measured in process on a scratch bank (synthetic text only).

    export SCALE_SCRATCH=<dir>
    api/.venv/bin/python -m benchmarks.perf.probe recall  --bank <bank> [--embedder hash|e5] [--out f.json]
    api/.venv/bin/python -m benchmarks.perf.probe ask     --bank <bank> [--questions benchmarks/newuser/questions.json]
    api/.venv/bin/python -m benchmarks.perf.probe primer  --bank <bank>
    api/.venv/bin/python -m benchmarks.perf.probe index   --bank <copy>  [--embedder hash|e5]   # mutates: a copy
    api/.venv/bin/python -m benchmarks.perf.probe sources --bank <copy>                          # mutates: a copy
    api/.venv/bin/python -m benchmarks.perf.probe memory  --bank <bank>

Every probe imports ``benchmarks.scale.isolate`` first: it refuses to run without ``SCALE_SCRATCH`` and pins HOME,
CICADA_HOME and the bank there, with capture, telemetry and every fetch off; sockets are blocked. ``--embedder e5``
uses the small on-device search model from ``$SCALE_SCRATCH/home/.cicada/models`` (copy a verify run's
``cicada-home/models`` there); ``hash`` is the deterministic offline embedder (no model cost). Reply and prompt sizes
are characters and ~tokens (characters / 4, the handshake's own proxy). Each probe prints one JSON object.
"""
from __future__ import annotations

from benchmarks.scale import isolate  # noqa: F401  (must be first: pins every root before any api import)

import argparse
import json
import os
import random
import resource
import statistics
import subprocess
import sys
import time
from pathlib import Path

from benchmarks.perf.sections import ask_sections, recall_sections

E5 = "intfloat/multilingual-e5-small"


def _offline() -> None:
    import socket

    def no_network(*args, **kwargs):
        raise RuntimeError("offline probe forbids network access")
    socket.socket.connect = no_network
    socket.create_connection = no_network


def _embedder(kind: str):
    """Point every embed seam at the probe's embedder; returns ``(embed_fn, model_name)``."""
    from api.services import providers

    if kind == "e5":
        fn, name = providers.resolve_embed_fn_for_model(E5)
    else:
        from benchmarks.system.engine import embed
        fn, name = embed, "fake-hash-v1"
    providers.resolve_embed_fn = lambda *a, **k: (fn, name)
    providers.resolve_embed_fn_for_model = lambda *a, **k: (fn, name)
    providers.cached_embed_fn_for_model = lambda *a, **k: (fn, name)
    return fn, name


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[max(0, min(len(ordered) - 1, round(q * (len(ordered) - 1))))]


def tok(chars: int) -> int:
    return round(chars / 4)


def _ensure_indexes(bank: Path, embed_fn, model: str) -> dict:
    """A copied bank's derived indexes read every file as changed: bring them current before timing reads."""
    from api.services import search_index
    from api.services.vector_index import SqliteVecIndexer

    t = time.perf_counter()
    search_index.refresh(bank)
    ix = SqliteVecIndexer(bank, embed_fn=embed_fn, model_name=model)
    ix.index_entities()
    ix.index_episodes()
    ix.index_claims()
    return {"index_prep_s": round(time.perf_counter() - t, 1)}


# --------------------------------------------------------------------------- queries


def synthetic_queries(bank: Path, n: int, seed: int = 7) -> list[str]:
    """Half page names, half a claim's own words (the recall_queries shapes), from the bank's own pages."""
    from api.services import claims as claims_mod
    from api.services import markdown_parser

    rng = random.Random(seed)
    pages = sorted(p for p in (bank / "entities").glob("*.md"))
    rng.shuffle(pages)
    out: list[str] = []
    for page in pages:
        if len(out) >= n:
            break
        parsed = markdown_parser.parse(page)
        name = str(parsed.frontmatter.get("name") or page.stem)
        if len(out) % 2 == 0:
            out.append(name)
            continue
        rows = claims_mod.parse_claims(parsed.body) or []
        texts = [str(getattr(c, "text", "") or "") for c in rows if getattr(c, "text", "")]
        if texts:
            words = rng.choice(texts).split()
            out.append(" ".join(words[: min(8, len(words))]))
    return out


def newuser_questions(path: Path, tool: str | None = None) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [q["args"]["query"] for q in data["questions"]
            if (tool is None or q["tool"] == tool) and isinstance(q.get("args"), dict) and q["args"].get("query")]


# --------------------------------------------------------------------------- recall

def _recall_ctx(bank: Path):
    from api.services import mcp_tools

    return mcp_tools.ToolContext(memory_path=lambda: bank, session_id="ses_perf_probe", harness="claude-code",
                                 post=lambda *a, **k: {}, headers=lambda: {})


def _render(out) -> str:
    """A tool reply as the stdio door sends it: a ``Reply`` is its text."""
    return str(out)


def cmd_recall(a) -> dict:
    bank = a.bank.resolve()
    isolate.pin_bank(bank)
    _offline()
    fn, model = _embedder(a.embedder)
    from api.services import mcp_tools

    queries = (newuser_questions(a.questions) if a.questions else synthetic_queries(bank, a.n))
    result: dict = {"bank": bank.name, "embedder": model, "queries": len(queries)}
    if a.prep:
        result.update(_ensure_indexes(bank, fn, model))
    # Cold: a fresh process's first recall (imports + index open + first embed), a few distinct queries.
    cold = []
    for q in queries[: a.cold]:
        proc = subprocess.run([sys.executable, "-m", "benchmarks.perf.probe", "recall-once", "--bank", str(bank),
                               "--embedder", a.embedder, "--query", q], capture_output=True, text=True,
                              env=os.environ.copy(), timeout=600)
        try:
            cold.append(json.loads(proc.stdout.strip().splitlines()[-1]))
        except (ValueError, IndexError):
            cold.append({"error": (proc.stderr or "")[-300:]})
    ctx = _recall_ctx(bank)
    mcp_tools.recall(ctx, queries[0])           # warm the process once
    times, sizes, sections = [], [], {}
    for q in queries:
        ctx = _recall_ctx(bank)
        t = time.perf_counter()
        text = _render(mcp_tools.recall(ctx, q))
        times.append((time.perf_counter() - t) * 1000)
        sizes.append(len(text))
        for k, v in recall_sections(text).items():
            sections[k] = sections.get(k, 0) + v
    total = sum(sizes) or 1
    result.update({
        "cold_first_call_ms": [c.get("first_ms") for c in cold],
        "cold_process_ms": [c.get("process_ms") for c in cold],
        "warm_p50_ms": round(statistics.median(times), 1), "warm_p95_ms": round(pct(times, 0.95), 1),
        "reply_p50_tokens": tok(statistics.median(sizes)), "reply_p95_tokens": tok(pct(sizes, 0.95)),
        "reply_max_tokens": tok(max(sizes)),
        "share_by_section_pct": {k: round(100 * v / total, 1) for k, v in sorted(sections.items(), key=lambda kv: -kv[1])},
    })
    return result


def cmd_recall_once(a) -> dict:
    started = time.perf_counter()
    bank = a.bank.resolve()
    isolate.pin_bank(bank)
    _offline()
    _embedder(a.embedder)
    from api.services import mcp_tools

    t = time.perf_counter()
    text = _render(mcp_tools.recall(_recall_ctx(bank), a.query))
    return {"first_ms": round((time.perf_counter() - t) * 1000, 1),
            "process_ms": round((time.perf_counter() - started) * 1000, 1), "chars": len(text)}


# --------------------------------------------------------------------------- ask

def cmd_ask(a) -> dict:
    bank = a.bank.resolve()
    isolate.pin_bank(bank)
    _offline()
    fn, model = _embedder(a.embedder)
    from api.services import ask_service

    questions = newuser_questions(a.questions, "cicada_ask") if a.questions else [
        f"What is {q}?" for q in synthetic_queries(bank, a.n)]
    result: dict = {"bank": bank.name, "embedder": model, "questions": len(questions)}
    if a.prep:
        result.update(_ensure_indexes(bank, fn, model))
    canned = json.dumps({"answer": "probe", "confidence": 0.5, "used_entities": [], "used_conversations": [],
                         "gaps": []})
    retrieval, prompts, sections, dumped = [], [], {}, []
    system = len(ask_service.ASK_SYSTEM_PROMPT)
    for q in questions:
        seen: dict = {}

        def capture(prompt: str, _seen=seen) -> str:
            _seen["t"] = time.perf_counter()
            _seen["prompt"] = prompt
            return canned
        t = time.perf_counter()
        ask_service.answer_query(bank, q, llm_fn=capture, no_engine=False)
        if "prompt" not in seen:
            continue   # an honest-gap answer: no model call
        retrieval.append((seen["t"] - t) * 1000)
        prompts.append(len(seen["prompt"]))
        dumped.append({"q": q, "prompt": seen["prompt"]})
        for k, v in ask_sections(seen["prompt"]).items():
            sections[k] = sections.get(k, 0) + v
    if a.dump:
        a.dump.write_text("\n".join(json.dumps(d) for d in dumped) + "\n", encoding="utf-8")
    total = sum(prompts) or 1
    result.update({
        "model_calls": len(prompts),
        "retrieval_p50_ms": round(statistics.median(retrieval), 1) if retrieval else None,
        "retrieval_p95_ms": round(pct(retrieval, 0.95), 1) if retrieval else None,
        "system_prompt_tokens": tok(system),
        "user_prompt_p50_tokens": tok(statistics.median(prompts)) if prompts else None,
        "user_prompt_max_tokens": tok(max(prompts)) if prompts else None,
        "share_by_block_pct": {k: round(100 * v / total, 1) for k, v in sorted(sections.items(), key=lambda kv: -kv[1])},
    })
    return result


# --------------------------------------------------------------------------- primer


def cmd_primer(a) -> dict:
    bank = a.bank.resolve()
    isolate.pin_bank(bank)
    _offline()
    _embedder("hash")
    from api.services import handshake, hook_recall

    out = {"bank": bank.name, "max_tokens": handshake.MAX_TOKENS}
    for client in ("claude-code", "codex", None):
        text, _meta = handshake.load_or_build(bank, client)
        out[f"handshake_{client or 'default'}_tokens"] = tok(len(text))
    primer = hook_recall.session_primer(bank, "claude-code")
    out["session_start_note_tokens"] = tok(len(getattr(primer, "text", "") or str(primer)))
    sizes = []
    for q in (newuser_questions(a.questions, "cicada_ask") if a.questions else synthetic_queries(bank, 12)):
        inj = hook_recall.prompt_context(bank, q)
        sizes.append(len(getattr(inj, "text", "") or ""))
    out["prompt_note_p50_tokens"] = tok(statistics.median(sizes)) if sizes else 0
    out["prompt_note_max_tokens"] = tok(max(sizes)) if sizes else 0
    out["prompt_note_empty"] = sum(1 for s in sizes if not s)
    return out


# --------------------------------------------------------------------------- index


def _decay_touch(bank: Path, pages: int) -> int:
    """What a night's decay does to a page that it charges: the page's and its claims' confidence move and their
    ``decayed_through`` advances — the words stay. ``pages`` of them (0 = all)."""
    from api.services import claims as claims_mod
    from api.services import markdown_parser

    touched = 0
    for page in sorted((bank / "entities").glob("*.md")):
        if pages and touched >= pages:
            break
        parsed = markdown_parser.parse(page)
        fm = dict(parsed.frontmatter)
        fm["confidence"] = round(max(0.0, float(fm.get("confidence") or 0.5) - 0.01), 2)
        rows = claims_mod.parse_claims(parsed.body) or []
        for c in rows:
            c.confidence = round(max(0.0, float(c.confidence or 0.5) - 0.01), 2)
            c.decayed_through = "2026-10-24"
        body = claims_mod.write_claims(parsed.body, rows) if rows else parsed.body
        markdown_parser.write(page, fm, body)
        touched += 1
    return touched


def cmd_index(a) -> dict:
    bank = a.bank.resolve()
    isolate.pin_bank(bank)
    _offline()
    fn, model = _embedder(a.embedder)
    from api.services import search_index
    from api.services.vector_index import SqliteVecIndexer

    counted = {"texts": 0, "chars": 0}

    def counting(batch, *, is_query=False):
        counted["texts"] += len(batch)
        counted["chars"] += sum(map(len, batch))
        return fn(batch, is_query=is_query)

    def sync(label: str) -> dict:
        row = {}
        t = time.perf_counter()
        search_index.refresh(bank)
        row["fts_s"] = round(time.perf_counter() - t, 2)
        for kind in ("index_entities", "index_episodes", "index_claims"):
            before = dict(counted)
            ix = SqliteVecIndexer(bank, embed_fn=counting, model_name=model)
            t = time.perf_counter()
            getattr(ix, kind)()
            row[f"{kind}_s"] = round(time.perf_counter() - t, 2)
            row[f"{kind}_embedded"] = counted["texts"] - before["texts"]
        return {label: row}

    out: dict = {"bank": bank.name, "embedder": model}
    out.update(sync("first_sync"))
    out.update(sync("idle_sync"))
    t = time.perf_counter()
    out["decay_touched_pages"] = _decay_touch(bank, a.pages)
    out["decay_touch_s"] = round(time.perf_counter() - t, 1)
    out.update(sync("after_decay_sync"))
    out["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6)
    return out


def cmd_embedcost(a) -> dict:
    """What re-embedding a bank's entity pages costs with the real on-device model: every page's embed text (the
    ``entity_embed_text`` the bank uses), embedded in the indexer's own batches. ``--pages`` caps the sample."""
    bank = a.bank.resolve()
    isolate.pin_bank(bank)
    _offline()
    fn, model = _embedder(a.embedder)
    from api.services import markdown_parser, vector_index

    mode = vector_index.entity_text_mode(None)
    texts = []
    for page in sorted((bank / "entities").glob("*.md")):
        if a.pages and len(texts) >= a.pages:
            break
        parsed = markdown_parser.parse(page)
        text = vector_index._entity_embed_text(parsed.frontmatter or {}, parsed.body, page.stem, mode=mode)
        if text:
            texts.append(text)
    fn(texts[:4])   # load the model before the clock starts
    t = time.perf_counter()
    for start in range(0, len(texts), 64):
        fn(texts[start:start + 64])
    took = time.perf_counter() - t
    return {"bank": bank.name, "embedder": model, "mode": mode, "pages": len(texts),
            "chars_p50": int(statistics.median(len(x) for x in texts)) if texts else 0,
            "embed_s": round(took, 1), "per_page_ms": round(1000 * took / max(1, len(texts)), 1)}


# --------------------------------------------------------------------------- sources


def _git_commits(bank: Path) -> int:
    proc = subprocess.run(["git", "-C", str(bank), "rev-list", "--count", "HEAD"], capture_output=True, text=True)
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return -1


def _chrome_bookmarks(n: int) -> bytes:
    """A Chrome ``Bookmarks`` JSON with ``n`` synthetic links (``example.com``), each with its own ``date_added``."""
    base = 13_380_000_000_000_000   # Chrome's microseconds since 1601, mid-2025
    children = [{"type": "url", "name": f"Synthetic link {i}", "url": f"https://site{i % 50}.example.com/p/{i}",
                 "date_added": str(base + i * 60_000_000), "id": str(100 + i)} for i in range(n)]
    doc = {"roots": {"bookmark_bar": {"type": "folder", "name": "Bookmarks bar", "children": children},
                     "other": {"type": "folder", "name": "Other", "children": []},
                     "synced": {"type": "folder", "name": "Mobile", "children": []}}, "version": 1}
    return json.dumps(doc).encode("utf-8")


def _transcript(path: Path, turns: int, words: int) -> None:
    """A Claude Code JSONL: person turns, tool calls, the agent's final replies (synthetic words)."""
    rng = random.Random(turns)
    vocab = "alpha beta gamma delta parser cache index drain batch claim page owner trailer span vector".split()
    lines = []
    for i in range(turns):
        ts = f"2026-10-20T{10 + i // 3600 % 10:02d}:{i // 60 % 60:02d}:{i % 60:02d}.000Z"
        say = " ".join(rng.choice(vocab) for _ in range(words))
        lines.append({"type": "user", "timestamp": ts, "sessionId": "perf-session-0001",
                      "message": {"role": "user", "content": f"Question {i}: {say}"}})
        lines.append({"type": "assistant", "timestamp": ts, "sessionId": "perf-session-0001",
                      "message": {"role": "assistant", "model": "claude-haiku", "content": [
                          {"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {"command": "ls"}}]}})
        lines.append({"type": "user", "timestamp": ts, "sessionId": "perf-session-0001",
                      "message": {"role": "user", "content": [
                          {"type": "tool_result", "tool_use_id": f"t{i}", "content": say * 3}]}})
        lines.append({"type": "assistant", "timestamp": ts, "sessionId": "perf-session-0001",
                      "message": {"role": "assistant", "model": "claude-haiku",
                                  "content": [{"type": "text", "text": f"Answer {i}: {say}"}]}})
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")


def cmd_sources(a) -> dict:
    import asyncio

    bank = a.bank.resolve()
    isolate.pin_bank(bank)
    _offline()
    _embedder("hash")
    from api.services import bookmark_sync, episode_staging

    out: dict = {"bank": bank.name, "episodes": sum(1 for _ in (bank / "episodes").glob("*.md"))}

    # Chrome bookmarks: a first sync, then the same file again (what every FSEvents wake of an unchanged file does).
    data = _chrome_bookmarks(a.bookmarks)
    rows = []
    for label in ("first", "unchanged", "unchanged_again"):
        commits = _git_commits(bank)
        seen = bank / "sources" / "bookmark_seen.json"
        before = seen.stat().st_mtime_ns if seen.exists() else None
        t = time.perf_counter()
        res = asyncio.run(bookmark_sync.sync_bookmarks(bank, chrome_data=data))
        rows.append({"sync": label, "s": round(time.perf_counter() - t, 2), "new": res["new"],
                     "skipped": res["skipped"], "commits_added": _git_commits(bank) - commits,
                     "seen_file_rewritten": (seen.stat().st_mtime_ns if seen.exists() else None) != before})
    out["chrome_bookmarks"] = rows

    # The per-request bank scan every source-keyed writer pays.
    from api.services import bank_index
    t = time.perf_counter()
    episode_staging.scan(bank / "episodes")
    out["staging_scan_warm_ms"] = round((time.perf_counter() - t) * 1000, 1)
    bank_index.invalidate(bank)
    t = time.perf_counter()
    episode_staging.scan(bank / "episodes")
    out["staging_scan_cold_ms"] = round((time.perf_counter() - t) * 1000, 1)

    # Claude Code capture: the same session growing, the backend re-reading the whole transcript each Stop.
    from api.services import transcript_capture

    root = transcript_capture.harness_root("claude-code") / "perf"
    root.mkdir(parents=True, exist_ok=True)
    cap = []
    sid = "perf-session-0001"
    for turns in a.turns:
        path = root / f"{sid}.jsonl"
        _transcript(path, turns, 60)
        t = time.perf_counter()
        try:
            res = transcript_capture.capture_transcript(bank, harness="claude-code", session_id=sid,
                                                        transcript_path=str(path), cwd=None, keep_assistant=True)
            status = getattr(res, "status", None) or str(res)
        except TypeError as exc:
            status = f"signature: {exc}"
        cap.append({"turns": turns, "transcript_mb": round(path.stat().st_size / 1e6, 2),
                    "s": round(time.perf_counter() - t, 3), "status": status})
    out["claude_code_capture"] = cap
    return out


# --------------------------------------------------------------------------- memory


def _rss_mb() -> float:
    # ru_maxrss is bytes on macOS, KiB on Linux.
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (1e6 if sys.platform == "darwin" else 1e3), 1)


def cmd_memory(a) -> dict:
    bank = a.bank.resolve()
    isolate.pin_bank(bank)
    _offline()
    out = {"bank": bank.name, "python_mb": _rss_mb()}
    import api.main  # noqa: F401  (the backend's whole import graph, as uvicorn loads it)
    out["after_app_import_mb"] = _rss_mb()
    _embedder(a.embedder)
    from api.services import mcp_tools
    for q in synthetic_queries(bank, 6):
        mcp_tools.recall(_recall_ctx(bank), q)
    out["after_recalls_mb"] = _rss_mb()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("recall", "recall-once", "ask", "primer", "index", "embedcost", "sources", "memory"):
        p = sub.add_parser(name)
        p.add_argument("--bank", required=True, type=Path)
        p.add_argument("--embedder", choices=("hash", "e5"), default="hash")
        p.add_argument("--questions", type=Path)
        p.add_argument("--n", type=int, default=40)
        p.add_argument("--cold", type=int, default=3)
        p.add_argument("--prep", action="store_true", help="bring a copied bank's derived indexes current first")
        p.add_argument("--query")
        p.add_argument("--pages", type=int, default=0, help="index: pages decay touches (0 = all)")
        p.add_argument("--bookmarks", type=int, default=2000)
        p.add_argument("--turns", type=int, nargs="+", default=[50, 200, 800])
        p.add_argument("--out", type=Path)
        p.add_argument("--dump", type=Path, help="ask: write every prompt (synthetic text) to compare two runs")
    a = ap.parse_args()
    fn = {"recall": cmd_recall, "recall-once": cmd_recall_once, "ask": cmd_ask, "primer": cmd_primer,
          "index": cmd_index, "embedcost": cmd_embedcost, "sources": cmd_sources, "memory": cmd_memory}[a.cmd]
    result = fn(a)
    text = json.dumps(result, indent=None if a.cmd == "recall-once" else 1, default=str)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
