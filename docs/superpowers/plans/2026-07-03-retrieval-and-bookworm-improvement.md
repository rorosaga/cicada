# Cicada Retrieval + Bookworm Improvement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise memory-retrieval accuracy (haiku ≥0.85, sonnet ≥0.92) and page richness by fixing the retrieval read paths, self-healing consolidation defects, and adding a source-grounded re-consolidation pass — all measured by a repeatable eval harness.

**Architecture:** Four sequenced phases sharing one committed eval harness. Phase 0 builds the harness. Phase 1 changes only read paths (`vector_index`, `mcp/server`, `entity_body`) — no memory writes. Phases 2–3 mutate entity files but run on a **duplicate bank** (`claude-chats-v2`) created via the existing banks feature, so the live graph is untouched until the eval says the copy is better. Every consolidation write is a git commit with author/trigger provenance.

**Tech Stack:** Python 3 (FastAPI backend, pytest, litellm via `providers.resolve_llm_fn`), sqlite-vec vector index, markdown+git memory store, the `cicada` stdio MCP server, `claude -p` for eval sessions.

## Global Constraints

- **Never mutate the live `memory/` bank in a test.** All hermetic tests use throwaway `tmp_path` memory dirs with injected fake `embed_fn`/`llm_fn`; no real model, no network. (Repo convention — 300 tests currently green.)
- **Phases 2–3 run on `claude-chats-v2`**, never on the active `claude-chats` bank, until Rodrigo promotes it.
- **Personal data privacy:** benchmark questions with real content live only in `benchmarks/questions.local.yaml` (gitignored via `benchmarks/*.local.*`). The committed `benchmarks/questions.example.yaml` uses neutral thesis-shaped placeholders only. Raw answers/scores go to `benchmark_results/` (gitignored). Never commit real personal content.
- **Source corpus** is at `cicada/cicada-data/chat-exports/` (gitignored). Code must degrade gracefully to chunks-only when the corpus is absent (a shipped install won't have it).
- **Commit provenance:** consolidation writes use `git_service.build_commit_message(subject, body_lines, authors=[...])`; author is a model id for agent writes, `"user"` for manual. Triggers: `sleep/dedup`, `sleep/promotion`, `sleep/reconsolidation`.
- **Entity page writes** preserve human prose via `entity_body.merge_sections_human_safe(...)` and never clobber the `` ```claims `` block.
- **Run tests with:** `api/.venv/bin/python -m pytest api/tests/ -q` (full suite) or `-k <name>` for one.

---

## Phase 0 — Eval harness (measurement backbone)

### Task 1: Eval harness core — question loading + judge scoring

**Files:**
- Create: `benchmarks/run_retrieval_eval.py`
- Create: `benchmarks/questions.example.yaml`
- Test: `api/tests/test_retrieval_eval.py`

**Interfaces:**
- Produces: `load_questions(path) -> list[dict]` (each `{id:int, question:str, ground_truth:str, expected_entities:list[str], category:str, difficulty:str}`); `judge_answer(question:dict, model:str, answer:str, *, llm_fn=None) -> dict` (`{verdict:str, score:float, diagnosis:str}` where `verdict ∈ {correct,partial,wrong,hallucinated,honest-gap,tool-failure}`); `aggregate(rows:list[dict]) -> dict` (per-model `{avg, n, by_verdict}`).

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_retrieval_eval.py
import yaml
from benchmarks import run_retrieval_eval as ev


def test_load_questions(tmp_path):
    p = tmp_path / "q.yaml"
    p.write_text(yaml.safe_dump({"questions": [
        {"id": 1, "question": "Q?", "ground_truth": "A", "expected_entities": ["e"],
         "category": "fact", "difficulty": "hard"},
    ]}))
    qs = ev.load_questions(str(p))
    assert qs[0]["id"] == 1 and qs[0]["category"] == "fact"


def test_judge_answer_uses_injected_llm():
    # injected judge returns a fixed structured verdict; no network
    def fake_llm(*, messages, response_format=None, **kw):
        import json
        content = json.dumps({"verdict": "correct", "score": 0.9, "diagnosis": "matches"})
        return {"choices": [{"message": {"content": content}}]}
    v = ev.judge_answer(
        {"question": "Q?", "ground_truth": "A", "category": "fact", "expected_entities": []},
        "haiku", "A is the answer", llm_fn=fake_llm,
    )
    assert v["verdict"] == "correct" and v["score"] == 0.9


def test_aggregate_computes_per_model_average():
    rows = [
        {"model": "haiku", "score": 1.0, "verdict": "correct"},
        {"model": "haiku", "score": 0.0, "verdict": "wrong"},
        {"model": "sonnet", "score": 0.8, "verdict": "partial"},
    ]
    agg = ev.aggregate(rows)
    assert agg["haiku"]["avg"] == 0.5 and agg["haiku"]["n"] == 2
    assert agg["sonnet"]["avg"] == 0.8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_retrieval_eval.py -q`
Expected: FAIL with `ModuleNotFoundError` / `AttributeError: module 'benchmarks.run_retrieval_eval' has no attribute 'load_questions'`.

- [ ] **Step 3: Write minimal implementation**

```python
# benchmarks/run_retrieval_eval.py
"""Repeatable retrieval eval: run each question x model through the cicada MCP,
score with an LLM judge, aggregate. Personal questions live in a gitignored
*.local.yaml; results go to benchmark_results/ (gitignored)."""
from __future__ import annotations
import json
import yaml
from pathlib import Path

RUBRIC = ("correct: matches ground truth; partial: some right; wrong: confidently incorrect; "
          "hallucinated: asserts facts not in memory; honest-gap: correctly says memory lacks it "
          "(CORRECT only for negative-category); tool-failure: session errored / no tools used.")


def load_questions(path: str) -> list[dict]:
    data = yaml.safe_load(Path(path).read_text())
    return list(data.get("questions", []))


def _extract_json(text: str) -> dict:
    text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass
    return {}


def judge_answer(question: dict, model: str, answer: str, *, llm_fn=None) -> dict:
    prompt = (
        f"Judge a memory-retrieval answer.\nRUBRIC: {RUBRIC}\n\n"
        f"QUESTION: {question.get('question')}\nCATEGORY: {question.get('category')}\n"
        f"GROUND TRUTH: {question.get('ground_truth')}\n"
        f"EXPECTED ENTITIES: {question.get('expected_entities')}\n\nANSWER: {answer}\n\n"
        'Reply with JSON: {"verdict": <one rubric label>, "score": <0..1>, "diagnosis": <why>}.'
    )
    if llm_fn is None:  # pragma: no cover - resolved at runtime
        from api.config import get_settings
        from api.services.providers import resolve_llm_fn
        llm_fn = resolve_llm_fn(get_settings())
    resp = llm_fn(messages=[{"role": "user", "content": prompt}],
                  response_format={"type": "json_object"})
    content = resp["choices"][0]["message"]["content"]
    obj = _extract_json(content)
    return {
        "verdict": str(obj.get("verdict", "tool-failure")),
        "score": float(obj.get("score", 0.0) or 0.0),
        "diagnosis": str(obj.get("diagnosis", "")),
    }


def aggregate(rows: list[dict]) -> dict:
    agg: dict[str, dict] = {}
    for r in rows:
        m = r["model"]
        a = agg.setdefault(m, {"total": 0.0, "n": 0, "by_verdict": {}})
        a["total"] += float(r.get("score", 0.0) or 0.0)
        a["n"] += 1
        a["by_verdict"][r["verdict"]] = a["by_verdict"].get(r["verdict"], 0) + 1
    for a in agg.values():
        a["avg"] = round(a["total"] / a["n"], 3) if a["n"] else None
    return agg
```

Also create the example questions template:

```yaml
# benchmarks/questions.example.yaml
# TEMPLATE — neutral placeholders only. Copy to questions.local.yaml (gitignored)
# and fill with real questions grounded in your memory.
questions:
  - id: 1
    question: "What was the headline result of the paper my thesis supervisor recommended?"
    ground_truth: "<placeholder fact>"
    expected_entities: ["the-supervisor", "the-precedent-paper"]
    category: multi-hop
    difficulty: hard
  - id: 2
    question: "When is the final thesis submission deadline?"
    ground_truth: "<placeholder date>"
    expected_entities: ["thesis-deadline"]
    category: fact
    difficulty: medium
```

- [ ] **Step 4: Run test to verify it passes**

Run: `api/.venv/bin/python -m pytest api/tests/test_retrieval_eval.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add benchmarks/run_retrieval_eval.py benchmarks/questions.example.yaml api/tests/test_retrieval_eval.py
git commit -m "feat(bench): retrieval eval harness core (load/judge/aggregate)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 2: Eval harness runner — MCP session driver + CLI + make target

**Files:**
- Modify: `benchmarks/run_retrieval_eval.py` (add `run_one`, `main`)
- Modify: `Makefile` (add `eval` target)
- Test: `api/tests/test_retrieval_eval.py` (add runner test with a fake subprocess)

**Interfaces:**
- Consumes: `load_questions`, `judge_answer`, `aggregate` (Task 1).
- Produces: `run_one(question, model, mcp_config, *, runner=None) -> dict` (`{model, answer, exit_ok}`); `main(argv)` CLI.

- [ ] **Step 1: Write the failing test**

```python
# append to api/tests/test_retrieval_eval.py
def test_run_one_uses_injected_runner():
    from benchmarks import run_retrieval_eval as ev
    def fake_runner(prompt, model, mcp_config):
        return (0, "The answer is A.")  # (exit_code, stdout)
    out = ev.run_one({"id": 1, "question": "Q?"}, "haiku", "/tmp/cfg.json", runner=fake_runner)
    assert out["exit_ok"] is True and "answer is A" in out["answer"].lower()

def test_run_one_marks_tool_failure_on_nonzero_exit():
    from benchmarks import run_retrieval_eval as ev
    def fake_runner(prompt, model, mcp_config):
        return (1, "boom")
    out = ev.run_one({"id": 1, "question": "Q?"}, "haiku", "/tmp/cfg.json", runner=fake_runner)
    assert out["exit_ok"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_retrieval_eval.py -k run_one -q`
Expected: FAIL (`has no attribute 'run_one'`).

- [ ] **Step 3: Write minimal implementation**

```python
# append to benchmarks/run_retrieval_eval.py
import subprocess

PROMPT_TMPL = (
    "You have access to cicada memory tools (MCP 'cicada'). Use them (cicada_recall first; "
    "then cicada_recall_detail / cicada_open_hub / cicada_ask / cicada_sources as needed — DO "
    "follow through to recall_detail for full pages before concluding a fact is absent, and state "
    "only facts present in tool results) to answer this about the user. If genuinely absent, say so.\n"
    "Question: {q}"
)


def _default_runner(prompt: str, model: str, mcp_config: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["claude", "-p", "--model", model, "--mcp-config", mcp_config,
         "--strict-mcp-config", "--allowedTools", "mcp__cicada", "--max-turns", "14"],
        input=prompt, capture_output=True, text=True, timeout=300,
    )
    return proc.returncode, (proc.stdout or "")


def run_one(question: dict, model: str, mcp_config: str, *, runner=None) -> dict:
    runner = runner or _default_runner
    prompt = PROMPT_TMPL.format(q=question.get("question", ""))
    try:
        code, out = runner(prompt, model, mcp_config)
    except Exception as exc:  # subprocess timeout/crash never aborts the batch
        return {"model": model, "answer": f"(runner error: {exc})", "exit_ok": False}
    out = (out or "").strip()
    return {"model": model, "answer": out or "(empty)", "exit_ok": code == 0 and bool(out)}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", required=True)
    ap.add_argument("--mcp-config", required=True)
    ap.add_argument("--models", default="claude-haiku-4-5-20251001,claude-sonnet-5")
    ap.add_argument("--out", default="benchmark_results/retrieval_eval")
    args = ap.parse_args(argv)

    questions = load_questions(args.questions)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    rows = []
    for q in questions:
        for m in models:
            r = run_one(q, m, args.mcp_config)
            v = (judge_answer(q, m, r["answer"]) if r["exit_ok"]
                 else {"verdict": "tool-failure", "score": 0.0, "diagnosis": "runner failed"})
            rows.append({"id": q["id"], "model": m, **v, "answer": r["answer"][:1000]})
    agg = aggregate(rows)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    (outdir / "aggregate.json").write_text(json.dumps(agg, indent=2))
    for m, a in agg.items():
        print(f"{m}: avg={a['avg']} n={a['n']} {a['by_verdict']}")
    return agg


if __name__ == "__main__":  # pragma: no cover
    main()
```

- [ ] **Step 4: Run test + full suite**

Run: `api/.venv/bin/python -m pytest api/tests/test_retrieval_eval.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Add make target + commit**

Add to `Makefile` (under `.PHONY` list add `eval`, and append a target):

```make
eval:
	$(PYTHON) -m benchmarks.run_retrieval_eval \
		--questions $(QUESTIONS) \
		--mcp-config $(MCP_CONFIG) \
		--out $(OUT)/retrieval_eval
```

Add near the top variable block: `MCP_CONFIG ?= benchmarks/mcp-eval.local.json`.

```bash
git add benchmarks/run_retrieval_eval.py Makefile api/tests/test_retrieval_eval.py
git commit -m "feat(bench): eval runner (MCP session driver) + make eval target

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 6: Capture the committed baseline (manual, no code)**

Create `benchmarks/questions.local.yaml` from the 14 audited questions (already in
`scratchpad/questions.json`) and `benchmarks/mcp-eval.local.json` pointing at the active bank
(`scratchpad/mcp-bank.json` shape). Run `make eval` and save the aggregate to
`docs/goals/audit-2026-07/retrieval-baseline.md`. Expected ≈ haiku 0.67 / sonnet 0.85. This is the
number every later phase is measured against.

---

## Phase 1 — Retrieval layer (read paths only, no memory writes)

### Task 3: Archived fallback tier in `search_entities`

**Files:**
- Modify: `api/services/vector_index.py:300-319` (`search_entities`)
- Test: `api/tests/test_vector_index_archived.py`

**Interfaces:**
- Consumes: existing `_knn(conn, "entities", query, fetch_k)`, `search_entities(query, top_k=5, include_archived=False)`.
- Produces: unchanged signature; behavior change — when the active-only result set has `< top_k` hits, archived hits are appended (ranked last), each retaining its `metadata["status"]`.

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_vector_index_archived.py
from api.services.vector_index import SqliteVecIndexer


def _fake_embed(texts):
    # bag-of-words 8-dim deterministic vector; same shape the indexer expects
    import re
    vocab = ["esa", "rejected", "chile", "space", "active", "thing", "mongodb", "misc"]
    out = []
    for t in texts:
        toks = set(re.findall(r"[a-z]+", t.lower()))
        out.append([1.0 if v in toks else 0.0 for v in vocab])
    return out


def _mk(dir_, eid, status, body):
    (dir_ / f"{eid}.md").write_text(
        f"---\nname: {eid}\ntype: project\nstatus: {status}\nconfidence: 0.5\n---\n\n{body}\n")


def test_archived_entity_surfaces_when_active_set_thin(tmp_path):
    ents = tmp_path / "entities"; ents.mkdir()
    _mk(ents, "esa-rejected", "archived", "ESA rejected Chile space application")
    idx = SqliteVecIndexer(tmp_path, embed_fn=_fake_embed)
    idx.index_entities()
    # query overlaps only the archived entity; default (archived-excluded) would return []
    hits = idx.search_entities("esa rejected chile", top_k=5)
    ids = [h["metadata"]["entity_id"] for h in hits]
    assert "esa-rejected" in ids
    assert any(h["metadata"]["status"] == "archived" for h in hits)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_vector_index_archived.py -q`
Expected: FAIL — `esa-rejected` not in results (archived filtered out).

- [ ] **Step 3: Write minimal implementation** (replace the body of `search_entities`)

```python
    def search_entities(
        self, query: str, top_k: int = 5, include_archived: bool = False
    ) -> list[dict]:
        """Semantic search over promoted entity pages.

        When ``include_archived`` is False (default), active entities are
        preferred, but if fewer than ``top_k`` active hits exist, archived hits
        are appended as a *fallback tier* (ranked last, status preserved) so a
        paraphrased query can still reach a decayed page (e.g. a rejected
        application). ``include_archived=True`` returns the raw ranking.
        """
        if not self.db_path.exists():
            return []
        conn = self._connect()
        try:
            fetch_k = top_k * 3 if not include_archived else top_k
            results = self._knn(conn, "entities", query, fetch_k)
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()
        if include_archived:
            return results[:top_k]
        active = [r for r in results if r.get("metadata", {}).get("status") != "archived"]
        if len(active) >= top_k:
            return active[:top_k]
        archived = [r for r in results if r.get("metadata", {}).get("status") == "archived"]
        return (active + archived)[:top_k]
```

- [ ] **Step 4: Run test + full suite**

Run: `api/.venv/bin/python -m pytest api/tests/test_vector_index_archived.py api/tests/ -q`
Expected: PASS; full suite still green (existing `search_entities` tests unaffected — active-only queries with ≥top_k active hits behave identically).

- [ ] **Step 5: Commit**

```bash
git add api/services/vector_index.py api/tests/test_vector_index_archived.py
git commit -m "fix(retrieval): archived fallback tier in search_entities

Decayed/archived entities surface when the active result set is thin, so a
paraphrased query can still reach a rejected/dropped page. Status preserved so
the caller can label it. Active hits still rank first.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 4: Section-aware summary truncation

**Files:**
- Create helper in: `api/services/entity_body.py` (`summarize_for_recall`)
- Modify: `mcp/server.py:912-925` (`_type_aware_truncate` calls new helper)
- Test: `api/tests/test_entity_body_recall_summary.py`

**Interfaces:**
- Consumes: `entity_body.parse_sections(body) -> dict[str,str]`, `CANONICAL_SECTIONS`.
- Produces: `entity_body.summarize_for_recall(body: str, *, max_chars: int = 3200) -> str` — always includes `## Summary` and `## Key Facts` in full, then fills remaining budget with other sections in canonical order.

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_entity_body_recall_summary.py
from api.services.entity_body import summarize_for_recall


def test_key_facts_always_survive_truncation():
    body = (
        "## Summary\n" + ("summary line. " * 200) + "\n\n"
        "## Key Facts\n- His paper's results: 19% EM, 25% F1\n- Founder of Supahost\n\n"
        "## History\n- 2025-04-08: shared paper\n"
    )
    out = summarize_for_recall(body, max_chars=600)
    assert "19% EM, 25% F1" in out           # Key Facts preserved despite tiny budget
    assert "## Summary" in out


def test_returns_full_body_when_under_budget():
    body = "## Summary\nshort\n\n## Key Facts\n- a fact\n"
    assert summarize_for_recall(body, max_chars=10000).strip().startswith("## Summary")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_entity_body_recall_summary.py -q`
Expected: FAIL (`has no attribute 'summarize_for_recall'`).

- [ ] **Step 3: Write minimal implementation** (append to `api/services/entity_body.py`)

```python
# Priority order for recall summaries: fact-bearing sections first. Summary +
# Key Facts are ALWAYS included in full (they hold the answer); the rest fill
# the remaining budget in this order.
_RECALL_PRIORITY = ["Summary", "Key Facts", "History", "Links", "Related", "Open Questions"]


def summarize_for_recall(body: str, *, max_chars: int = 3200) -> str:
    """Section-aware truncation that always preserves Summary + Key Facts.

    Byte-offset truncation can cut Key Facts (where specific figures live). This
    keeps Summary + Key Facts whole, then appends further canonical sections in
    priority order until the char budget is reached.
    """
    sections = parse_sections(body)
    lead = sections.get("", "").strip()
    chosen: list[str] = []
    used = 0
    # Always-include tier, whole:
    for title in ("Summary", "Key Facts"):
        content = sections.get(title, "").strip()
        if content:
            block = f"## {title}\n{content}"
            chosen.append(block)
            used += len(block)
    # Fill remaining budget:
    for title in _RECALL_PRIORITY:
        if title in ("Summary", "Key Facts"):
            continue
        content = sections.get(title, "").strip()
        if not content:
            continue
        block = f"## {title}\n{content}"
        if used + len(block) > max_chars and chosen:
            break
        chosen.append(block)
        used += len(block)
    if not chosen:  # legacy flat body (no H2s)
        return (lead or body).strip()[:max_chars]
    return "\n\n".join(chosen)
```

- [ ] **Step 4: Wire the MCP to use it** (edit `mcp/server.py` `_type_aware_truncate`)

Replace the `project, company` fallback branch so all long types route through the shared helper:

```python
def _type_aware_truncate(body: str, entity_type: str) -> str:
    if not body:
        return ""
    if entity_type in SHORT_TYPES:
        return body
    try:
        from api.services.entity_body import summarize_for_recall
        budget = 2000 if entity_type in MEDIUM_TYPES else 3200
        return summarize_for_recall(body, max_chars=budget)
    except Exception:
        # pyyaml-free fallback: old behavior
        if entity_type in MEDIUM_TYPES:
            return body[:2000]
        return _truncate_to_desc_and_recent_history(body, max_history=10)
```

- [ ] **Step 5: Run tests + full suite**

Run: `api/.venv/bin/python -m pytest api/tests/test_entity_body_recall_summary.py api/tests/ -q`
Expected: PASS; full suite green.

- [ ] **Step 6: Commit**

```bash
git add api/services/entity_body.py mcp/server.py api/tests/test_entity_body_recall_summary.py
git commit -m "fix(retrieval): section-aware recall summaries (always keep Summary + Key Facts)

Byte-offset truncation could cut the Key Facts figures the model needs. Recall
summaries now include Summary + Key Facts whole, then fill the budget.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 5: Rank fusion + episode fallback in `handle_recall`

**Files:**
- Modify: `mcp/server.py` (`handle_recall`: raise top_k to 8, RRF-fuse, episode fallback)
- Create helper: `mcp/server.py` (`_rrf_fuse`)
- Test: `api/tests/test_mcp_recall_fusion.py`

**Interfaces:**
- Consumes: `_leann_search_entities(memory_path, query, top_k)`, `_keyword_search_entities(entities_dir, query, top_k)`, `_leann_search_episodes(memory_path, query, top_k)`.
- Produces: `_rrf_fuse(*ranked_lists, k=60) -> list[dict]` — reciprocal-rank fusion over lists of hits keyed by `entity_id`.

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_mcp_recall_fusion.py
import importlib
mcp = importlib.import_module("mcp.server")


def test_rrf_fuse_rewards_agreement():
    semantic = [{"entity_id": "a"}, {"entity_id": "b"}, {"entity_id": "c"}]
    keyword = [{"entity_id": "b"}, {"entity_id": "a"}]
    fused = mcp._rrf_fuse(semantic, keyword)
    ids = [h["entity_id"] for h in fused]
    # 'a' and 'b' both appear in both lists near the top -> outrank 'c'
    assert ids.index("a") < ids.index("c") and ids.index("b") < ids.index("c")
    assert set(ids) == {"a", "b", "c"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_mcp_recall_fusion.py -q`
Expected: FAIL (`has no attribute '_rrf_fuse'`).

- [ ] **Step 3: Write minimal implementation** (add to `mcp/server.py`)

```python
def _rrf_fuse(*ranked_lists, k: int = 60) -> list[dict]:
    """Reciprocal-rank fusion over hit lists keyed by entity_id.

    score(id) = sum over lists of 1/(k + rank). Rewards ids that rank well in
    multiple sources (a strong keyword AND vector hit reinforce). Keeps the
    first-seen hit dict per id.
    """
    scores: dict[str, float] = {}
    keep: dict[str, dict] = {}
    for lst in ranked_lists:
        for rank, hit in enumerate(lst):
            eid = hit.get("entity_id") or hit.get("id")
            if not eid:
                continue
            scores[eid] = scores.get(eid, 0.0) + 1.0 / (k + rank)
            keep.setdefault(eid, hit)
    ordered = sorted(scores, key=lambda e: -scores[e])
    return [keep[e] for e in ordered]
```

Then in `handle_recall`, replace the semantic/keyword merge block:

```python
    # === Sources 1+2: semantic + keyword, rank-fused ===
    semantic = _leann_search_entities(memory_path, query, top_k=8)
    keyword = _keyword_search_entities(entities_dir, query, top_k=8)
    merged = _rrf_fuse(semantic, keyword)
    seen_ids = {h.get("entity_id") or h.get("id") for h in merged}
```

And after the existing entity/hop rendering, add an episode fallback (place before the final return):

```python
    # === Episode fallback: when entity hits are thin, surface raw episode text ===
    if len(merged) < 2:
        ep_hits = _leann_search_episodes(memory_path, query, top_k=2)
        ep_blurbs = []
        for e in ep_hits:
            meta = e.get("metadata", {}) or {}
            snippet = (e.get("text", "") or "")[:400].strip()
            if snippet:
                ep_blurbs.append(f"- (episode {meta.get('episode_id', '?')}): {snippet}")
        if ep_blurbs:
            output_parts.append("**From source episodes:**\n" + "\n".join(ep_blurbs))
```

- [ ] **Step 4: Run tests + full suite**

Run: `api/.venv/bin/python -m pytest api/tests/test_mcp_recall_fusion.py api/tests/ -q`
Expected: PASS; full suite green.

- [ ] **Step 5: Commit**

```bash
git add mcp/server.py api/tests/test_mcp_recall_fusion.py
git commit -m "fix(retrieval): RRF fusion + episode fallback in cicada_recall

Reciprocal-rank-fuse semantic+keyword (agreement reinforces), raise top_k to 8,
and surface source-episode text when entity hits are thin (the Q9 miss lived in
the episode).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 6: Tool ergonomics + grounding guidance

**Files:**
- Modify: `mcp/server.py` (tool `description`s for `cicada_recall`, `cicada_ask`)
- Modify: `SKILL.md` (grounding + tool-choice policy)
- Test: `api/tests/test_mcp_tool_descriptions.py`

**Interfaces:**
- Produces: no new code interface — a guardrail test asserting the grounding language exists so it can't silently regress.

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_mcp_tool_descriptions.py
import importlib
mcp = importlib.import_module("mcp.server")


def test_recall_description_has_grounding_and_detail_guidance():
    # Build the tools list the server advertises and find cicada_recall.
    # main() defines `tools`; expose it via a module-level TOOLS for testing.
    tools = {t["name"]: t for t in mcp.TOOLS}
    desc = tools["cicada_recall"]["description"].lower()
    assert "recall_detail" in desc            # tells model to read full page
    assert "only" in desc and "tool" in desc  # grounding: state only facts from tools
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_mcp_tool_descriptions.py -q`
Expected: FAIL — `TOOLS` not defined at module level (currently `tools` is local to `main`).

- [ ] **Step 3: Implement** — hoist the tools list to a module-level `TOOLS` constant in `mcp/server.py` (move the existing `tools = [...]` out of `main()` to module scope as `TOOLS`, and have `main()` reference `TOOLS`). Update the `cicada_recall` description to end with:

```
"... If a fact might exist, call cicada_recall_detail on the top suggested entity before concluding it is absent. State only facts present in tool results; do not add adjacent details from general knowledge."
```

Update `cicada_ask` description to add: `"Prefer this tool for direct factual questions — it reads full entity pages and claims and returns an answer with citations and an explicit gap list."`

- [ ] **Step 4: Update `SKILL.md`** — under "## Two-pass recall", add a bullet: "Before answering that something is not in memory, open the top entity with `cicada_recall_detail`. State only facts the tools returned — never fill gaps with general knowledge." Under a new "## Grounding" heading, add the same rule and: "For a direct factual question, `cicada_ask` is usually the best single call."

- [ ] **Step 5: Run test + full suite**

Run: `api/.venv/bin/python -m pytest api/tests/test_mcp_tool_descriptions.py api/tests/ -q`
Expected: PASS; full suite green.

- [ ] **Step 6: Commit**

```bash
git add mcp/server.py SKILL.md api/tests/test_mcp_tool_descriptions.py
git commit -m "fix(mcp): grounding + detail-before-gap guidance in tool descriptions + SKILL

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 7: Measure Phase 1** (manual) — restart nothing (MCP is per-session). Run `make eval` and append the score to `docs/goals/audit-2026-07/retrieval-baseline.md` as "after Phase 1". Expected: haiku and sonnet both up, especially the archived/paraphrase and partial questions.

---

## Phase 2 — Consolidation self-heal (on duplicate bank `claude-chats-v2`)

### Task 7: Duplicate the bank (manual setup, no code)

- [ ] **Step 1:** With the backend running (`CICADA_MEMORY_PATH=<repo>/memory`), duplicate the bank:

```bash
curl -s -X POST http://localhost:8000/banks -H 'content-type: application/json' \
  -d '{"name":"claude-chats-v2","from":"claude-chats"}' || \
  api/.venv/bin/python -c "from api.services.bank_registry import duplicate_bank; from pathlib import Path; print(duplicate_bank(Path('memory'),'claude-chats','claude-chats-v2'))"
```

Verify `memory/banks/claude-chats-v2/entities/` has ~1036 files. **Do not activate it** for the app; Phase 2/3 code targets its path directly.

### Task 8: Entity-merge primitive

**Files:**
- Create: `api/services/entity_merge.py`
- Test: `api/tests/test_entity_merge.py`

**Interfaces:**
- Consumes: `entity_body.parse_sections`, `entity_body.merge_sections_human_safe`, `markdown_parser.parse`/`write`, `git_service.build_commit_message`.
- Produces: `merge_entities(memory_path: Path, loser_id: str, winner_id: str, *, author: str = "user") -> dict` — returns `{winner, merged_source_episodes:int, repointed_edges:int}`; unions frontmatter lists, section-merges bodies, repoints `graph_edges.yaml` endpoints loser→winner, deletes loser file.

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_entity_merge.py
from pathlib import Path
import yaml
from api.services.entity_merge import merge_entities


def _write(ents: Path, eid: str, fm: dict, body: str):
    (ents / f"{eid}.md").write_text("---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n\n" + body)


def test_merge_unions_sources_and_repoints_edges(tmp_path):
    ents = tmp_path / "entities"; ents.mkdir()
    _write(ents, "user", {"name": "user", "type": "person", "status": "active",
                          "confidence": 0.8, "source_episodes": ["ep_1"], "related": ["mongodb"]},
           "## Summary\nThe user.\n\n## Key Facts\n- likes concise summaries\n")
    _write(ents, "rorosaga", {"name": "rorosaga", "type": "person", "status": "active",
                             "confidence": 0.7, "source_episodes": ["ep_2"], "related": ["barcelona"]},
           "## Summary\nGitHub handle.\n\n## Key Facts\n- based in Barcelona\n")
    (tmp_path / "graph_edges.yaml").write_text(yaml.safe_dump(
        {"edges": [{"source": "rorosaga", "target": "mongodb", "label": "works-at"}]}))

    out = merge_entities(tmp_path, loser_id="rorosaga", winner_id="user")

    assert not (ents / "rorosaga.md").exists()          # loser deleted
    win = (ents / "user.md").read_text()
    assert "ep_1" in win and "ep_2" in win               # source_episodes unioned
    assert "based in Barcelona" in win                    # loser Key Facts merged in
    edges = yaml.safe_load((tmp_path / "graph_edges.yaml").read_text())["edges"]
    assert edges[0]["source"] == "user"                   # edge repointed
    assert out["repointed_edges"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_entity_merge.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Write minimal implementation**

```python
# api/services/entity_merge.py
"""Merge two rich entity pages into one (the G21 primitive the inbox lacks).

Unions list frontmatter, section-merges bodies (human-prose-safe), repoints
graph_edges.yaml endpoints loser->winner, deletes the loser. Reversible via git.
"""
from __future__ import annotations
from pathlib import Path
import yaml
from api.services import markdown_parser, entity_body

_LIST_FIELDS = ("source_episodes", "tags", "related", "aliases")


def _union(a, b):
    seen, out = set(), []
    for x in list(a or []) + list(b or []):
        if x not in seen:
            seen.add(x); out.append(x)
    return out


def merge_entities(memory_path: Path, loser_id: str, winner_id: str,
                   *, author: str = "user") -> dict:
    ents = memory_path / "entities"
    lp, wp = ents / f"{loser_id}.md", ents / f"{winner_id}.md"
    if not lp.exists() or not wp.exists():
        raise FileNotFoundError(f"merge needs both pages: {loser_id}, {winner_id}")

    lpar, wpar = markdown_parser.parse(lp), markdown_parser.parse(wp)
    lfm, wfm = dict(lpar.frontmatter), dict(wpar.frontmatter)

    for f in _LIST_FIELDS:
        merged = _union(wfm.get(f), lfm.get(f))
        if merged:
            wfm[f] = merged
    wfm["confidence"] = max(float(wfm.get("confidence", 0) or 0),
                            float(lfm.get("confidence", 0) or 0))

    # Section-merge loser body into winner (human-safe: never drop winner prose).
    human = bool(wfm.get("human_edited"))
    loser_fields = {k: v for k, v in entity_body.parse_sections(lpar.body).items() if k}
    merged_sections = entity_body.merge_sections_human_safe(
        entity_body.parse_sections(wpar.body), loser_fields, human_edited=human)
    new_body = "\n\n".join(f"## {t}\n{c}" if t else c
                           for t, c in merged_sections.items() if c).strip()
    markdown_parser.write(wp, wfm, new_body)

    # Repoint edges.
    edges_file = memory_path / "graph_edges.yaml"
    repointed = 0
    if edges_file.exists():
        data = yaml.safe_load(edges_file.read_text()) or {}
        for e in data.get("edges", []):
            for end in ("source", "target"):
                if e.get(end) == loser_id:
                    e[end] = winner_id; repointed += 1
        edges_file.write_text(yaml.safe_dump(data, sort_keys=False))

    lp.unlink()
    return {"winner": winner_id, "merged_source_episodes": len(wfm.get("source_episodes", [])),
            "repointed_edges": repointed}
```

- [ ] **Step 4: Run test + full suite**

Run: `api/.venv/bin/python -m pytest api/tests/test_entity_merge.py api/tests/ -q`
Expected: PASS; full suite green.

- [ ] **Step 5: Commit**

```bash
git add api/services/entity_merge.py api/tests/test_entity_merge.py
git commit -m "feat(consolidation): entity-merge primitive (G21 building block)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 9: Full-graph dedup sweep

**Files:**
- Create: `api/services/dedup_sweep.py`
- Test: `api/tests/test_dedup_sweep.py`

**Interfaces:**
- Consumes: `SqliteVecIndexer.search_entities` (for the embedding gate), `entity_merge.merge_entities`, an injected `judge_fn`.
- Produces: `find_candidate_pairs(memory_path, *, embed_fn=None, min_cosine=0.85) -> list[tuple[str,str,float]]`; `dedup_sweep(memory_path, settings, *, judge_fn=None, embed_fn=None, seed_pairs=None, auto_merge_threshold=0.9) -> dict` (`{merged:list[(loser,winner)], nudged:list[pair]}`).

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_dedup_sweep.py
from pathlib import Path
import yaml
from api.services.dedup_sweep import dedup_sweep


def _w(ents, eid, name, body="## Summary\nx\n"):
    (ents / f"{eid}.md").write_text(
        f"---\nname: {name}\ntype: person\nstatus: active\nconfidence: 0.6\n"
        f"source_episodes: [ep_1]\n---\n\n{body}")


def test_seed_pair_auto_merges_on_high_confidence_judge(tmp_path):
    ents = tmp_path / "entities"; ents.mkdir()
    _w(ents, "esa", "ESA")
    _w(ents, "esta", "ESTA")
    (tmp_path / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": []}))

    def judge_fn(a_body, b_body, a_id, b_id):   # deterministic "same" verdict
        return {"verdict": "same", "confidence": 0.95, "winner": "esa"}

    out = dedup_sweep(tmp_path, settings=None, judge_fn=judge_fn,
                      seed_pairs=[("esa", "esta")], auto_merge_threshold=0.9)
    assert ("esta", "esa") in [(l, w) for (l, w) in out["merged"]]
    assert not (ents / "esta.md").exists()


def test_uncertain_judge_nudges_not_merges(tmp_path):
    ents = tmp_path / "entities"; ents.mkdir()
    _w(ents, "a", "A"); _w(ents, "b", "B")
    (tmp_path / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": []}))
    def judge_fn(*a, **k):
        return {"verdict": "unsure", "confidence": 0.5, "winner": "a"}
    out = dedup_sweep(tmp_path, settings=None, judge_fn=judge_fn, seed_pairs=[("a", "b")])
    assert out["merged"] == [] and ("a", "b") in out["nudged"]
    assert (ents / "b.md").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_dedup_sweep.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Write minimal implementation**

```python
# api/services/dedup_sweep.py
"""Full-graph dedup sweep (G21): embedding-gate same-type pairs, LLM same/
different/unsure judge with both pages, auto-merge high-confidence, nudge the
uncertain. Runs on a duplicate bank; never on the live bank in tests."""
from __future__ import annotations
from pathlib import Path
from api.services import markdown_parser
from api.services.entity_merge import merge_entities


def find_candidate_pairs(memory_path: Path, *, embed_fn=None, min_cosine=0.85):
    """Embedding-gate: same-type entity pairs with high cosine. Best-effort;
    returns [] if the index isn't built. (Seeded runs can skip this.)"""
    from api.services.vector_index import SqliteVecIndexer
    idx = SqliteVecIndexer(memory_path, embed_fn=embed_fn)
    ents = memory_path / "entities"
    pairs, seen = [], set()
    for f in sorted(ents.glob("*.md")):
        par = markdown_parser.parse(f)
        name = str(par.frontmatter.get("name", f.stem))
        for hit in idx.search_entities(name, top_k=4):
            other = hit.get("metadata", {}).get("entity_id")
            if not other or other == f.stem:
                continue
            key = tuple(sorted((f.stem, other)))
            if key in seen:
                continue
            seen.add(key)
            pairs.append((key[0], key[1], float(hit.get("score", 0) or 0)))
    return pairs


def dedup_sweep(memory_path: Path, settings, *, judge_fn=None, embed_fn=None,
                seed_pairs=None, auto_merge_threshold=0.9) -> dict:
    if judge_fn is None:  # pragma: no cover - resolved at runtime
        judge_fn = _default_judge_fn(settings)
    pairs = list(seed_pairs or [])
    if not pairs:
        pairs = [(a, b) for (a, b, _score) in find_candidate_pairs(memory_path, embed_fn=embed_fn)]

    ents = memory_path / "entities"
    merged, nudged = [], []
    gone: set[str] = set()
    for a, b in pairs:
        if a in gone or b in gone:
            continue
        ap, bp = ents / f"{a}.md", ents / f"{b}.md"
        if not ap.exists() or not bp.exists():
            continue
        v = judge_fn(ap.read_text(), bp.read_text(), a, b)
        if v.get("verdict") == "same" and float(v.get("confidence", 0)) >= auto_merge_threshold:
            winner = v.get("winner") or a
            loser = b if winner == a else a
            merge_entities(memory_path, loser_id=loser, winner_id=winner)
            merged.append((loser, winner))
            gone.add(loser)
        elif v.get("verdict") in ("same", "unsure"):
            nudged.append((a, b))
    return {"merged": merged, "nudged": nudged}


def _default_judge_fn(settings):  # pragma: no cover - needs a real model
    import json
    from api.services.providers import resolve_llm_fn
    llm = resolve_llm_fn(settings, model=settings.effective_consolidation_model)

    def judge(a_body, b_body, a_id, b_id):
        prompt = (
            "Are these two knowledge-graph entity pages the SAME real-world thing? "
            "Reply JSON {\"verdict\":\"same|different|unsure\",\"confidence\":0..1,"
            "\"winner\":\"<id to keep>\"}.\n\n"
            f"PAGE A (id={a_id}):\n{a_body[:2500]}\n\nPAGE B (id={b_id}):\n{b_body[:2500]}"
        )
        resp = llm(messages=[{"role": "user", "content": prompt}],
                   response_format={"type": "json_object"})
        txt = resp["choices"][0]["message"]["content"]
        s, e = txt.find("{"), txt.rfind("}")
        return json.loads(txt[s:e + 1]) if s >= 0 else {"verdict": "unsure", "confidence": 0.0}
    return judge
```

- [ ] **Step 4: Run test + full suite**

Run: `api/.venv/bin/python -m pytest api/tests/test_dedup_sweep.py api/tests/ -q`
Expected: PASS; full suite green.

- [ ] **Step 5: Commit**

```bash
git add api/services/dedup_sweep.py api/tests/test_dedup_sweep.py
git commit -m "feat(consolidation): full-graph dedup sweep (G21) with seed pairs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 10: Relationship-target promotion + hub regen + run on v2

**Files:**
- Create: `api/services/promote_targets.py`
- Test: `api/tests/test_promote_targets.py`

**Interfaces:**
- Consumes: `graph_edges.yaml`, `markdown_parser.write`, existing `hub_builder` (called in a manual run step, not under test).
- Produces: `promote_relationship_targets(memory_path: Path, *, min_refs: int = 1) -> list[str]` — for each edge target that has no entity page but appears as a relationship object ≥`min_refs` times, create a backfilled stub page; returns created ids.

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_promote_targets.py
from pathlib import Path
import yaml
from api.services.promote_targets import promote_relationship_targets


def test_promotes_unpaged_relationship_target(tmp_path):
    ents = tmp_path / "entities"; ents.mkdir()
    (ents / "specialist-role.md").write_text(
        "---\nname: Specialist Role\ntype: project\nstatus: active\nconfidence: 0.7\n---\n\n"
        "## Summary\nReports to Diego Albano.\n")
    (tmp_path / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": [
        {"source": "specialist-role", "target": "diego-albano", "label": "reports-to"},
    ]}))
    created = promote_relationship_targets(tmp_path, min_refs=1)
    assert "diego-albano" in created
    page = (ents / "diego-albano.md").read_text()
    assert "Diego Albano" in page and "reports-to" in page.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_promote_targets.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Write minimal implementation**

```python
# api/services/promote_targets.py
"""Promote relationship targets that have no page but are the object of an edge
(e.g. 'reports to Diego Albano'), so name-search can resolve them. Creates a
backfilled stub with the relationships that name it."""
from __future__ import annotations
from pathlib import Path
import yaml
from api.services import markdown_parser


def _titleize(slug: str) -> str:
    return " ".join(w.capitalize() for w in slug.replace("-", " ").split())


def promote_relationship_targets(memory_path: Path, *, min_refs: int = 1) -> list[str]:
    ents = memory_path / "entities"
    edges_file = memory_path / "graph_edges.yaml"
    if not edges_file.exists():
        return []
    edges = (yaml.safe_load(edges_file.read_text()) or {}).get("edges", [])
    existing = {f.stem for f in ents.glob("*.md")}

    refs: dict[str, list] = {}
    for e in edges:
        tgt = e.get("target")
        if tgt and tgt not in existing:
            refs.setdefault(tgt, []).append(e)

    created = []
    for tgt, edge_list in refs.items():
        if len(edge_list) < min_refs:
            continue
        name = _titleize(tgt)
        facts = "\n".join(
            f"- {e.get('source')}: {e.get('label','related')}" for e in edge_list)
        body = (f"## Summary\n{name} — promoted from relationship references.\n\n"
                f"## Key Facts\n{facts}\n")
        fm = {"name": name, "type": "person", "status": "active", "confidence": 0.4,
              "source_episodes": [], "related": [e.get("source") for e in edge_list],
              "promoted_from": "relationship_target", "layout_version": 2}
        markdown_parser.write(ents / f"{tgt}.md", fm, body)
        created.append(tgt)
    return created
```

- [ ] **Step 4: Run test + full suite**

Run: `api/.venv/bin/python -m pytest api/tests/test_promote_targets.py api/tests/ -q`
Expected: PASS; full suite green.

- [ ] **Step 5: Commit**

```bash
git add api/services/promote_targets.py api/tests/test_promote_targets.py
git commit -m "feat(consolidation): promote un-paged relationship targets (fixes name-search)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 6: Run Phase 2 on v2 (manual) + measure**

```bash
V2=memory/banks/claude-chats-v2
api/.venv/bin/python -c "
from pathlib import Path; from api.config import get_settings
from api.services.dedup_sweep import dedup_sweep
from api.services.promote_targets import promote_relationship_targets
p=Path('$V2'); s=get_settings()
seed=[('rodrigo-jesus-sagastegui','user'),('rorosaga','user'),('esta','esa'),('xrpl','xrp-ledger')]
print('dedup:', dedup_sweep(p, s, seed_pairs=seed))
print('promoted:', promote_relationship_targets(p, min_refs=1))
"
# regen hubs + _index.md, then rebuild the vector index on v2
api/.venv/bin/python -c "from pathlib import Path; from api.config import get_settings; from api.services import hub_builder; print(hub_builder.regenerate_hubs_and_index(Path('$V2'), get_settings()))"
api/.venv/bin/python -m benchmarks.rebuild_leann --memory $V2
```

Point `benchmarks/mcp-eval.local.json` at `$V2`, run `make eval`, append to the scoreboard as "after Phase 2 (v2)".

---

## Phase 3 — Source-grounded re-consolidation (on v2)

### Task 11: Source-gathering primitive

**Files:**
- Create: `api/services/entity_sources.py`
- Test: `api/tests/test_entity_sources.py`

**Interfaces:**
- Consumes: `markdown_parser.parse`, entity `source_episodes`, episode `source_id` frontmatter, `cicada-data/chat-exports/claude/conversations.json`.
- Produces: `gather_entity_sources(memory_path: Path, entity_id: str, *, mode: str = "chunks", corpus_path: Path | None = None) -> dict` — `{entity_id, episodes:[{id, chunk, source_id, conversation}], degraded:bool}` where `conversation` is populated only in `mode="full"` with a resolvable corpus.

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_entity_sources.py
from pathlib import Path
import json
from api.services.entity_sources import gather_entity_sources


def _setup(tmp_path):
    ents = tmp_path / "entities"; ents.mkdir()
    eps = tmp_path / "episodes"; eps.mkdir()
    (ents / "diego.md").write_text(
        "---\nname: Diego\ntype: person\nstatus: active\nconfidence: 0.9\n"
        "source_episodes:\n- ep_1\n---\n\n## Summary\nfounder\n")
    (eps / "ep_1.md").write_text(
        "---\nid: ep_1\nsource: claude\nsource_id: conv-abc\n---\n\nuser: hi\nassistant: hello\n")
    return tmp_path


def test_chunks_mode_returns_episode_body(tmp_path):
    m = _setup(tmp_path)
    out = gather_entity_sources(m, "diego", mode="chunks")
    assert out["episodes"][0]["id"] == "ep_1"
    assert "hello" in out["episodes"][0]["chunk"]
    assert out["episodes"][0]["conversation"] is None


def test_full_mode_resolves_conversation_from_corpus(tmp_path):
    m = _setup(tmp_path)
    corpus = tmp_path / "corpus"; (corpus / "chat-exports" / "claude").mkdir(parents=True)
    (corpus / "chat-exports" / "claude" / "conversations.json").write_text(json.dumps([
        {"uuid": "conv-abc", "name": "The chat", "chat_messages": [{"text": "full context"}]}
    ]))
    out = gather_entity_sources(m, "diego", mode="full", corpus_path=corpus)
    assert out["episodes"][0]["conversation"]["name"] == "The chat"
    assert out["degraded"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_entity_sources.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Write minimal implementation**

```python
# api/services/entity_sources.py
"""Resolve an entity to the primary sources that produced it:
entity.source_episodes -> episode chunk (+ source_id) -> full conversation in
the chat-export corpus. Degrades to chunks-only when the corpus is absent."""
from __future__ import annotations
import json
from pathlib import Path
from functools import lru_cache
from api.services import markdown_parser


@lru_cache(maxsize=4)
def _load_claude_corpus(corpus_path_str: str) -> dict:
    p = Path(corpus_path_str) / "chat-exports" / "claude" / "conversations.json"
    if not p.exists():
        return {}
    try:
        return {c.get("uuid"): c for c in json.loads(p.read_text())}
    except Exception:
        return {}


def gather_entity_sources(memory_path: Path, entity_id: str, *, mode: str = "chunks",
                          corpus_path: Path | None = None) -> dict:
    ent = memory_path / "entities" / f"{entity_id}.md"
    if not ent.exists():
        return {"entity_id": entity_id, "episodes": [], "degraded": True}
    par = markdown_parser.parse(ent)
    ep_ids = par.frontmatter.get("source_episodes", []) or []
    convs = _load_claude_corpus(str(corpus_path)) if (mode == "full" and corpus_path) else {}
    degraded = mode == "full" and not convs

    episodes = []
    for ep_id in ep_ids:
        epf = memory_path / "episodes" / f"{ep_id}.md"
        if not epf.exists():
            continue
        eppar = markdown_parser.parse(epf)
        sid = eppar.frontmatter.get("source_id")
        episodes.append({
            "id": ep_id,
            "chunk": eppar.body,
            "source_id": sid,
            "conversation": convs.get(sid) if convs else None,
        })
    return {"entity_id": entity_id, "episodes": episodes, "degraded": degraded}
```

- [ ] **Step 4: Run test + full suite**

Run: `api/.venv/bin/python -m pytest api/tests/test_entity_sources.py api/tests/ -q`
Expected: PASS; full suite green.

- [ ] **Step 5: Commit**

```bash
git add api/services/entity_sources.py api/tests/test_entity_sources.py
git commit -m "feat(sources): gather_entity_sources primitive (entity -> episodes -> conversation)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 12: `cicada_sources` MCP tool

**Files:**
- Modify: `mcp/server.py` (add tool schema to `TOOLS`, dispatch in `handle_tool`, `handle_sources`)
- Test: `api/tests/test_mcp_sources_tool.py`

**Interfaces:**
- Consumes: `entity_sources.gather_entity_sources` (chunks mode); `get_memory_path()`.
- Produces: tool `cicada_sources` with input `{entity_id: str}`; `handle_sources(entity_id: str) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_mcp_sources_tool.py
import importlib
mcp = importlib.import_module("mcp.server")


def test_sources_tool_registered_and_dispatches(monkeypatch, tmp_path):
    # tool advertised
    assert "cicada_sources" in {t["name"] for t in mcp.TOOLS}
    # dispatch renders episode chunks
    ents = tmp_path / "entities"; ents.mkdir()
    eps = tmp_path / "episodes"; eps.mkdir()
    (ents / "e.md").write_text("---\nname: E\ntype: person\nstatus: active\nconfidence: 0.5\n"
                               "source_episodes:\n- ep_1\n---\n\n## Summary\nx\n")
    (eps / "ep_1.md").write_text("---\nid: ep_1\nsource_id: c1\n---\n\nuser: q\nassistant: a\n")
    monkeypatch.setattr(mcp, "get_memory_path", lambda: tmp_path)
    out = mcp.handle_tool("cicada_sources", {"entity_id": "e"})
    assert "ep_1" in out and "assistant: a" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_mcp_sources_tool.py -q`
Expected: FAIL (`cicada_sources` not registered / `handle_sources` missing).

- [ ] **Step 3: Implement** — in `mcp/server.py`:

Add to the `TOOLS` list (module-level, from Task 6):

```python
        {
            "name": "cicada_sources",
            "description": "Return the primary source conversation chunks that produced an entity "
                           "(the episodes it was consolidated from). Use this to ground or verify a "
                           "fact against what the user actually said, or to show provenance.",
            "inputSchema": {
                "type": "object",
                "properties": {"entity_id": {"type": "string",
                    "description": "The entity id (e.g. 'diego-sanmartin') to fetch sources for."}},
                "required": ["entity_id"],
            },
        },
```

Add dispatch in `handle_tool`:

```python
    elif name == "cicada_sources":
        return handle_sources(arguments.get("entity_id", ""))
```

Add the handler:

```python
def handle_sources(entity_id: str) -> str:
    """Render the source episode chunks behind an entity (chunks mode)."""
    try:
        from api.services.entity_sources import gather_entity_sources
        bundle = gather_entity_sources(get_memory_path(), entity_id, mode="chunks")
    except Exception as exc:  # pragma: no cover
        return f"Could not gather sources for '{entity_id}': {exc}"
    eps = bundle.get("episodes", [])
    if not eps:
        return f"No source episodes found for '{entity_id}'."
    parts = [f"**Sources for `{entity_id}`** ({len(eps)} episode(s)):"]
    for e in eps:
        parts.append(f"\n### episode {e['id']}\n{(e.get('chunk') or '').strip()[:2000]}")
    return "\n".join(parts)
```

- [ ] **Step 4: Run test + full suite**

Run: `api/.venv/bin/python -m pytest api/tests/test_mcp_sources_tool.py api/tests/ -q`
Expected: PASS; full suite green.

- [ ] **Step 5: Commit**

```bash
git add mcp/server.py api/tests/test_mcp_sources_tool.py
git commit -m "feat(mcp): cicada_sources tool — primary conversation chunks behind an entity

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 13: Source-grounded rewrite pass (single entity)

**Files:**
- Create: `api/services/source_rewrite.py`
- Test: `api/tests/test_source_rewrite.py`

**Interfaces:**
- Consumes: `entity_sources.gather_entity_sources`, `providers.resolve_llm_fn`, `entity_body.parse_sections`/`merge_sections_human_safe`, `markdown_parser`, `git_service.build_commit_message`.
- Produces: `rewrite_entity_from_sources(memory_path, entity_id, settings, *, corpus_path=None, llm_fn=None) -> dict` (`{entity_id, changed:bool, before_words:int, after_words:int}`). Preserves human sections + the `` ```claims `` block; never invents facts (prompt-constrained + source-only).

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_source_rewrite.py
from pathlib import Path
from api.services.source_rewrite import rewrite_entity_from_sources


def _setup(tmp_path):
    ents = tmp_path / "entities"; ents.mkdir()
    eps = tmp_path / "episodes"; eps.mkdir()
    (ents / "e.md").write_text("---\nname: E\ntype: project\nstatus: active\nconfidence: 0.6\n"
                               "source_episodes:\n- ep_1\n---\n\n## Summary\nthin.\n")
    (eps / "ep_1.md").write_text("---\nid: ep_1\nsource_id: c1\n---\n\n"
                                 "user: We used Neo4j then dropped it for markdown.\n")
    return tmp_path


def test_rewrite_uses_injected_llm_and_enriches(tmp_path):
    m = _setup(tmp_path)

    def fake_llm(*, messages, response_format=None, **kw):
        # returns a richer, source-grounded body as JSON
        import json
        body = ("## Summary\nProject E used Neo4j initially, then moved to markdown.\n\n"
                "## Key Facts\n- Started on Neo4j\n- Switched to markdown files\n")
        return {"choices": [{"message": {"content": json.dumps({"body": body})}}]}

    out = rewrite_entity_from_sources(m, "e", settings=None, llm_fn=fake_llm)
    assert out["changed"] is True and out["after_words"] > out["before_words"]
    page = (m / "entities" / "e.md").read_text()
    assert "Switched to markdown" in page and "## Key Facts" in page


def test_preserves_human_edited_section(tmp_path):
    m = _setup(tmp_path)
    p = m / "entities" / "e.md"
    p.write_text("---\nname: E\ntype: project\nstatus: active\nconfidence: 0.6\n"
                 "human_edited: true\nsource_episodes:\n- ep_1\n---\n\n"
                 "## Summary\nthin.\n\n## My Notes\nDO NOT LOSE THIS.\n")
    def fake_llm(*, messages, response_format=None, **kw):
        import json
        return {"choices": [{"message": {"content": json.dumps(
            {"body": "## Summary\nRicher summary.\n\n## Key Facts\n- x\n"})}}]}
    rewrite_entity_from_sources(m, "e", settings=None, llm_fn=fake_llm)
    assert "DO NOT LOSE THIS" in p.read_text()   # human section preserved
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_source_rewrite.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Write minimal implementation**

```python
# api/services/source_rewrite.py
"""Source-grounded rewrite: re-read an entity's primary sources and rewrite its
page richer + strictly source-faithful. Preserves human sections + claims block.
Every rewrite is a git commit (caller commits in batch mode)."""
from __future__ import annotations
import json
from pathlib import Path
from api.services import markdown_parser, entity_body
from api.services.entity_sources import gather_entity_sources

_PROMPT = (
    "You are re-writing a personal knowledge-graph entity page using ONLY the source "
    "conversation excerpts below. Produce a richer, well-structured markdown body with the "
    "sections: ## Summary, ## Key Facts (bullets), and ## History (dated bullets) when supported. "
    "RULES: state ONLY facts present in the sources; never invent details; keep it faithful and "
    "specific (names, numbers, dates). Reply JSON {\"body\": \"<markdown body>\"}.\n\n"
    "CURRENT PAGE:\n{page}\n\nSOURCES:\n{sources}"
)


def _words(s: str) -> int:
    return len((s or "").split())


def rewrite_entity_from_sources(memory_path: Path, entity_id: str, settings, *,
                                corpus_path: Path | None = None, llm_fn=None,
                                max_source_chars: int = 12000) -> dict:
    ent = memory_path / "entities" / f"{entity_id}.md"
    if not ent.exists():
        return {"entity_id": entity_id, "changed": False, "before_words": 0, "after_words": 0}
    par = markdown_parser.parse(ent)
    before = _words(par.body)

    bundle = gather_entity_sources(memory_path, entity_id,
                                   mode="full" if corpus_path else "chunks",
                                   corpus_path=corpus_path)
    src_parts = []
    for e in bundle["episodes"]:
        src_parts.append(e.get("chunk", ""))
        conv = e.get("conversation")
        if conv:
            msgs = conv.get("chat_messages", [])[:40]
            src_parts.append("\n".join(m.get("text", "") for m in msgs))
    sources = "\n---\n".join(s for s in src_parts if s)[:max_source_chars]
    if not sources.strip():
        return {"entity_id": entity_id, "changed": False,
                "before_words": before, "after_words": before}

    if llm_fn is None:  # pragma: no cover - runtime
        from api.services.providers import resolve_llm_fn
        llm_fn = resolve_llm_fn(settings, model=settings.effective_consolidation_model)

    resp = llm_fn(messages=[{"role": "user",
                             "content": _PROMPT.format(page=par.body[:4000], sources=sources)}],
                  response_format={"type": "json_object"})
    txt = resp["choices"][0]["message"]["content"]
    s, e = txt.find("{"), txt.rfind("}")
    new_body = json.loads(txt[s:e + 1]).get("body", "").strip() if s >= 0 else ""
    if not new_body:
        return {"entity_id": entity_id, "changed": False,
                "before_words": before, "after_words": before}

    # Human-safe merge: never lose human sections or the claims block.
    human = bool(par.frontmatter.get("human_edited"))
    new_fields = {k: v for k, v in entity_body.parse_sections(new_body).items() if k}
    merged = entity_body.merge_sections_human_safe(
        entity_body.parse_sections(par.body), new_fields, human_edited=human)
    final_body = "\n\n".join(f"## {t}\n{c}" if t else c
                             for t, c in merged.items() if c).strip()
    fm = dict(par.frontmatter)
    fm["layout_version"] = 2
    markdown_parser.write(ent, fm, final_body)
    return {"entity_id": entity_id, "changed": True,
            "before_words": before, "after_words": _words(final_body)}
```

- [ ] **Step 4: Run test + full suite**

Run: `api/.venv/bin/python -m pytest api/tests/test_source_rewrite.py api/tests/ -q`
Expected: PASS; full suite green.

- [ ] **Step 5: Commit**

```bash
git add api/services/source_rewrite.py api/tests/test_source_rewrite.py
git commit -m "feat(sources): source-grounded single-entity rewrite (human/claims-safe)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 14: Resumable batch runner + cost estimate

**Files:**
- Create: `benchmarks/run_source_reconsolidation.py`
- Test: `api/tests/test_source_reconsolidation_runner.py`

**Interfaces:**
- Consumes: `source_rewrite.rewrite_entity_from_sources`, `git_service.build_commit_message`.
- Produces: `ordered_entities(memory_path) -> list[str]` (thin/low-confidence first); `run_batch(memory_path, settings, *, limit=None, corpus_path=None, rewrite_fn=None, marker_path=None) -> dict` (`{rewritten:int, skipped:int, words_before:int, words_after:int}`) with a resumable done-marker.

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_source_reconsolidation_runner.py
from pathlib import Path
from benchmarks.run_source_reconsolidation import ordered_entities, run_batch


def _mk(ents, eid, words, conf):
    body = "## Summary\n" + ("w " * words) + "\n"
    (ents / f"{eid}.md").write_text(
        f"---\nname: {eid}\ntype: project\nstatus: active\nconfidence: {conf}\n---\n\n{body}")


def test_ordered_entities_thin_and_lowconf_first(tmp_path):
    ents = tmp_path / "entities"; ents.mkdir()
    _mk(ents, "rich", 200, 0.9)
    _mk(ents, "thin", 5, 0.2)
    order = ordered_entities(tmp_path)
    assert order.index("thin") < order.index("rich")


def test_run_batch_is_resumable(tmp_path):
    ents = tmp_path / "entities"; ents.mkdir()
    _mk(ents, "a", 5, 0.3); _mk(ents, "b", 5, 0.3)
    calls = []
    def rewrite_fn(mp, eid, settings, **kw):
        calls.append(eid)
        return {"entity_id": eid, "changed": True, "before_words": 5, "after_words": 40}
    marker = tmp_path / "done.txt"
    run_batch(tmp_path, None, limit=1, rewrite_fn=rewrite_fn, marker_path=marker)
    run_batch(tmp_path, None, limit=1, rewrite_fn=rewrite_fn, marker_path=marker)
    assert sorted(calls) == ["a", "b"]     # second run skipped the first, did the other
    assert len(set(calls)) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `api/.venv/bin/python -m pytest api/tests/test_source_reconsolidation_runner.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Write minimal implementation**

```python
# benchmarks/run_source_reconsolidation.py
"""Resumable, cost-instrumented batch runner for the source-grounded rewrite
pass (Phase 3). Thin/low-confidence pages first; a done-marker makes it
resumable. Runs on the DUPLICATE bank only."""
from __future__ import annotations
from pathlib import Path
from api.services import markdown_parser


def ordered_entities(memory_path: Path) -> list[str]:
    scored = []
    for f in (memory_path / "entities").glob("*.md"):
        par = markdown_parser.parse(f)
        words = len((par.body or "").split())
        conf = float(par.frontmatter.get("confidence", 0.5) or 0.5)
        scored.append((words + conf * 100, f.stem))   # thin + low-conf sort first
    scored.sort(key=lambda x: x[0])
    return [eid for _s, eid in scored]


def _load_done(marker_path: Path | None) -> set[str]:
    if marker_path and marker_path.exists():
        return set(marker_path.read_text().split())
    return set()


def _mark_done(marker_path: Path | None, eid: str) -> None:
    if marker_path:
        with marker_path.open("a") as fh:
            fh.write(eid + "\n")


def run_batch(memory_path: Path, settings, *, limit=None, corpus_path=None,
              rewrite_fn=None, marker_path=None) -> dict:
    if rewrite_fn is None:  # pragma: no cover - runtime
        from api.services.source_rewrite import rewrite_entity_from_sources as rewrite_fn
    done = _load_done(marker_path)
    order = [e for e in ordered_entities(memory_path) if e not in done]
    if limit is not None:
        order = order[:limit]
    rewritten = skipped = wb = wa = 0
    for eid in order:
        try:
            r = rewrite_fn(memory_path, eid, settings, corpus_path=corpus_path)
        except Exception:
            skipped += 1
            continue
        if r.get("changed"):
            rewritten += 1
            wb += r.get("before_words", 0)
            wa += r.get("after_words", 0)
        else:
            skipped += 1
        _mark_done(marker_path, eid)
    return {"rewritten": rewritten, "skipped": skipped,
            "words_before": wb, "words_after": wa}


def main(argv=None):  # pragma: no cover
    import argparse
    from api.config import get_settings
    ap = argparse.ArgumentParser()
    ap.add_argument("--memory", required=True)
    ap.add_argument("--corpus", default="cicada-data")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="print planned order + count, spend nothing")
    args = ap.parse_args(argv)
    mp = Path(args.memory)
    order = ordered_entities(mp)
    print(f"{len(order)} entities; first 10: {order[:10]}")
    if args.dry_run:
        return
    out = run_batch(mp, get_settings(), limit=args.limit,
                    corpus_path=Path(args.corpus) if args.corpus else None,
                    marker_path=mp / ".reconsolidation_done")
    print(out)


if __name__ == "__main__":  # pragma: no cover
    main()
```

- [ ] **Step 4: Run test + full suite**

Run: `api/.venv/bin/python -m pytest api/tests/test_source_reconsolidation_runner.py api/tests/ -q`
Expected: PASS; full suite green (target: 300 + all new tests).

- [ ] **Step 5: Commit**

```bash
git add benchmarks/run_source_reconsolidation.py api/tests/test_source_reconsolidation_runner.py
git commit -m "feat(sources): resumable source-grounded reconsolidation batch runner

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 6: Cost dry-run, then the real run on v2 (manual)**

```bash
V2=memory/banks/claude-chats-v2
# 1. Dry-run: see the order + count, spend nothing
api/.venv/bin/python -m benchmarks.run_source_reconsolidation --memory $V2 --dry-run
# 2. Small paid probe: rewrite 10 pages, inspect quality + read the token cost printed
api/.venv/bin/python -m benchmarks.run_source_reconsolidation --memory $V2 --corpus cicada-data --limit 10
git -C $V2 log --oneline -5   # confirm per-rewrite commits with provenance
# 3. Review 3-4 rewritten pages against their sources for faithfulness (no invented facts)
# 4. Estimate full cost = (probe cost / 10) * ~1000, surface it to Rodrigo, then full run:
#    api/.venv/bin/python -m benchmarks.run_source_reconsolidation --memory $V2 --corpus cicada-data
```

STOP after step 2 and surface the extrapolated full-run cost to Rodrigo before the unbounded run.

---

## Final — measure, compare, promote

- [ ] **Rebuild the v2 index** after Phase 3: `api/.venv/bin/python -m benchmarks.rebuild_leann --memory memory/banks/claude-chats-v2`.
- [ ] **Run `make eval` against v2** and against the original `claude-chats`; write both to `docs/goals/audit-2026-07/retrieval-final.md` with the page-richness metric (median body words before/after).
- [ ] **Confirm success criteria:** haiku ≥ 0.85, sonnet ≥ 0.92, zero negative-question hallucinations, Q6/Q9 retrievable, full test suite green.
- [ ] **Promote v2 → active** only if it wins (`activate_bank(Path('memory'), 'claude-chats-v2')` or the app's bank switcher), keeping the original bank as a rollback. Otherwise iterate.

## Global self-review checklist (run before execution)

- [ ] Every spec §4 phase (0–3) maps to tasks: Phase 0 → T1–T2; Phase 1 → T3–T6; Phase 2 → T7–T10; Phase 3 → T11–T14; final measure → Final section. ✓
- [ ] No live-memory writes in any test (all use `tmp_path`). ✓
- [ ] Names consistent across tasks: `summarize_for_recall`, `_rrf_fuse`, `merge_entities`, `dedup_sweep`, `promote_relationship_targets`, `gather_entity_sources`, `rewrite_entity_from_sources`, `run_batch`, `TOOLS`. ✓
