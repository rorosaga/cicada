# Sync Engine Implementation Plan (G58 + G52)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the companion app feel like Linear — instant renders from a local snapshot, background delta sync driven by a cheap change signal, optimistic mutations — and fix the backend hot paths that make it slow today.

**Architecture:** Backend: a parsed-frontmatter cache (`bank_index`), a memoised embedding model, a version vector + SSE `/sync/events`, ETags, and graph nodes that carry a summary + content hash. App: a single `Store` of per-domain `Snapshot`s hydrated from disk before the first frame, a `SyncEngine` that subscribes to SSE (polling fallback) and refreshes only changed domains with `If-None-Match`, view models as projections, a `Mutation` protocol for optimistic writes with rollback, and delta pushes to d3.

**Tech Stack:** Python 3.12 / FastAPI / Starlette `run_in_threadpool` + `StreamingResponse`; SwiftUI macOS 14, `@Observable`, `URLSession.bytes`, SwiftPM `CicadaAppTests`; d3 in `graph.js`.

**Spec:** `docs/superpowers/specs/2026-08-30-sync-engine-design.md`

## Global Constraints

- Backend stays the source of truth; every client cache is disposable (`~/Library/Application Support/Cicada/cache/<bank>/`).
- Never blank existing content while refreshing: `isLoading` may be true only when a snapshot has no value.
- Bearer auth stays on every route (tests: `CICADA_API_AUTH=off` via `api/tests/conftest.py`); SSE and conditional GETs send the header.
- Wire keys camelCase via `CamelModel`; Swift decoding tolerant (`decodeIfPresent … ?? default`).
- Tests: `api/.venv/bin/python -m pytest api/tests/<file> -v` from the repo root (no pytest-asyncio; `asyncio.run`); `cd app/CicadaApp && swift build && swift test`. Baseline: 664 passed / 8 failed (all 8 pre-existing in `test_calendar_registry.py`); those 8 remain the only failures.
- Measured targets (spec §8): `/status` < 30 ms, `/search` < 200 ms warm, `/origins` < 50 ms cached.
- Commits end with a blank line then `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`; never `git add -A`; never touch `.claude/settings.json`.

---

## File structure

| File | Responsibility |
|---|---|
| `api/services/bank_index.py` (new) | mtime/size-keyed frontmatter cache per bank; `IndexedFile` |
| `api/routers/status.py`, `api/services/sleep_cycle.py`, `api/services/origin_stats.py`, `api/routers/origins.py`, `api/routers/graph.py` (modify) | read through the index; threadpool |
| `api/services/providers.py`, `api/main.py` (modify) | embed-fn memo + warm-up |
| `api/services/pricing.py` (modify) | `free` plan |
| `api/services/sync_service.py` (new), `api/routers/sync.py` (new) | version vector, SSE, ETag helper |
| `api/routers/{graph,inbox,contributors,sources,origins,banks}.py` (modify) | ETag / 304 |
| `api/services/graph_builder.py`, `api/models/schemas.py` (modify) | `summary`, `content_hash` |
| `app/CicadaApp/Package.swift` (modify) | `CicadaAppTests` target |
| `app/…/Sync/Snapshot.swift`, `SnapshotCache.swift`, `SSEParser.swift`, `VersionVector.swift`, `Store.swift`, `SyncEngine.swift`, `Mutations.swift`, `GraphDiff.swift` (new) | the engine |
| `app/…/Services/APIClient.swift` (modify) | conditional GET, sync endpoints, ask, token cache |
| `app/…/ViewModels/*.swift` (modify) | projections over `Store` |
| `app/…/CicadaApp.swift`, `ContentView.swift`, views (modify) | injection, hydrate, no per-view refetch |
| `app/…/Resources/graph/graph.js`, `Views/Graph/GraphView.swift` (modify) | `updateGraphDelta` |
| `app/…/Views/Sidebar/SidebarView.swift` (modify) | Buttons + shortcuts |
| `app/…/Ask/AskViewModel.swift`, `AskPanel.swift` (new) | G52 |

---

### Task 1: `bank_index` — cached frontmatter; fast `/status` and `/origins`

**Files:**
- Create: `api/services/bank_index.py`, `api/tests/test_bank_index.py`
- Modify: `api/routers/status.py` (`_last_ingested_at`, `get_status`), `api/services/sleep_cycle.py:339` (`_get_unprocessed_episodes`), `api/services/origin_stats.py:25` (`aggregate_origins`), `api/routers/origins.py`, `api/routers/graph.py`

**Interfaces:**
- `bank_index.IndexedFile(path: Path, mtime_ns: int, size: int, frontmatter: dict)` with `.body() -> str` (reads + strips frontmatter lazily) and `.stem`.
- `bank_index.files(memory_path: Path, subdir: str) -> list[IndexedFile]` (sorted by path), `bank_index.dir_stamp(memory_path, subdir) -> tuple[int, int]` (count, max mtime_ns), `bank_index.invalidate(memory_path: Path | None = None)`.
- `bank_index.parse_count` — module-level int of real parses performed (tests assert on it).

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_bank_index.py
from __future__ import annotations

import os
import time

from api.services import bank_index


def _write(path, fm: str, body: str = "hello"):
    path.write_text(f"---\n{fm}\n---\n\n{body}\n", encoding="utf-8")


def test_parses_once_and_reuses(tmp_path):
    bank_index.invalidate()
    d = tmp_path / "episodes"; d.mkdir()
    _write(d / "ep1.md", "id: ep1\nprocessed: false\ntimestamp: '2026-08-01T10:00:00'")
    _write(d / "ep2.md", "id: ep2\nprocessed: true\ntimestamp: '2026-08-02T10:00:00'")
    before = bank_index.parse_count
    files = bank_index.files(tmp_path, "episodes")
    assert [f.stem for f in files] == ["ep1", "ep2"]
    assert files[0].frontmatter["processed"] is False
    assert bank_index.parse_count == before + 2
    bank_index.files(tmp_path, "episodes")
    assert bank_index.parse_count == before + 2  # no re-parse


def test_reparses_only_changed_file(tmp_path):
    bank_index.invalidate()
    d = tmp_path / "episodes"; d.mkdir()
    _write(d / "ep1.md", "id: ep1\nprocessed: false")
    _write(d / "ep2.md", "id: ep2\nprocessed: false")
    bank_index.files(tmp_path, "episodes")
    before = bank_index.parse_count
    time.sleep(0.01)
    _write(d / "ep2.md", "id: ep2\nprocessed: true")
    os.utime(d / "ep2.md", None)
    files = bank_index.files(tmp_path, "episodes")
    assert bank_index.parse_count == before + 1
    assert {f.stem: f.frontmatter["processed"] for f in files} == {"ep1": False, "ep2": True}


def test_deleted_file_disappears_and_body_is_lazy(tmp_path):
    bank_index.invalidate()
    d = tmp_path / "episodes"; d.mkdir()
    _write(d / "ep1.md", "id: ep1", body="the body")
    _write(d / "ep2.md", "id: ep2")
    assert bank_index.files(tmp_path, "episodes")[0].body() == "the body"
    (d / "ep2.md").unlink()
    assert [f.stem for f in bank_index.files(tmp_path, "episodes")] == ["ep1"]


def test_missing_dir_and_malformed_file(tmp_path):
    bank_index.invalidate()
    assert bank_index.files(tmp_path, "episodes") == []
    d = tmp_path / "episodes"; d.mkdir()
    (d / "bad.md").write_text("---\n: [unclosed\n---\n")
    _write(d / "ok.md", "id: ok")
    assert [f.stem for f in bank_index.files(tmp_path, "episodes")] == ["ok"]


def test_dir_stamp_changes_on_write(tmp_path):
    bank_index.invalidate()
    d = tmp_path / "entities"; d.mkdir()
    _write(d / "a.md", "id: a")
    s1 = bank_index.dir_stamp(tmp_path, "entities")
    time.sleep(0.01)
    _write(d / "b.md", "id: b")
    s2 = bank_index.dir_stamp(tmp_path, "entities")
    assert s1 != s2 and s2[0] == 2
```

Append to `api/tests/test_origin_stats.py` (read its existing fixture style first and mirror it):

```python
def test_aggregate_origins_uses_index_not_reparse(tmp_path, monkeypatch):
    from api.services import bank_index, origin_stats
    bank_index.invalidate()
    (tmp_path / "episodes").mkdir(); (tmp_path / "entities").mkdir()
    (tmp_path / "episodes" / "ep1.md").write_text("---\nid: ep1\norigin: claude-code\ntimestamp: '2026-08-01'\n---\nx\n")
    (tmp_path / "entities" / "a.md").write_text("---\nid: a\nsource_episodes: [ep1]\n---\nx\n")
    first = origin_stats.aggregate_origins(tmp_path)
    before = bank_index.parse_count
    second = origin_stats.aggregate_origins(tmp_path)
    assert first == second and bank_index.parse_count == before
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_bank_index.py api/tests/test_origin_stats.py -v`
Expected: `ModuleNotFoundError: api.services.bank_index`

- [ ] **Step 3: Implement `bank_index.py`**

```python
# api/services/bank_index.py
"""Per-bank cache of parsed markdown frontmatter, keyed by (mtime_ns, size).

`/status`, `/origins` and the Sleep queue used to re-parse every episode and
entity file on every call (2–3k YAML parses, ~1–3 s). One ``os.scandir`` per
directory (~5 ms) now decides what changed; only changed files are re-parsed,
bodies are read lazily. The cache is process-local and disposable.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from api.services import markdown_parser

parse_count = 0
_lock = threading.Lock()
# (bank path, subdir) -> {filename: IndexedFile}
_cache: dict[tuple[str, str], dict[str, "IndexedFile"]] = {}


@dataclass
class IndexedFile:
    path: Path
    mtime_ns: int
    size: int
    frontmatter: dict = field(default_factory=dict)

    @property
    def stem(self) -> str:
        return self.path.stem

    def body(self) -> str:
        return markdown_parser.parse(self.path).body


def invalidate(memory_path: Path | None = None) -> None:
    with _lock:
        if memory_path is None:
            _cache.clear()
        else:
            for key in [k for k in _cache if k[0] == str(memory_path)]:
                _cache.pop(key, None)


def _scan(directory: Path) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if entry.is_file() and entry.name.endswith(".md"):
                    st = entry.stat()
                    out[entry.name] = (st.st_mtime_ns, st.st_size)
    except FileNotFoundError:
        pass
    return out


def files(memory_path: Path, subdir: str) -> list[IndexedFile]:
    global parse_count
    directory = Path(memory_path) / subdir
    key = (str(memory_path), subdir)
    current = _scan(directory)
    with _lock:
        known = _cache.setdefault(key, {})
        for name in [n for n in known if n not in current]:
            known.pop(name)
        for name, (mtime_ns, size) in current.items():
            hit = known.get(name)
            if hit is not None and hit.mtime_ns == mtime_ns and hit.size == size:
                continue
            path = directory / name
            try:
                fm = markdown_parser.parse(path).frontmatter
            except Exception as exc:  # malformed file: skip, never crash a caller
                logger.warning(f"bank_index: skipping malformed {path}: {exc}")
                known.pop(name, None)
                continue
            parse_count += 1
            known[name] = IndexedFile(path=path, mtime_ns=mtime_ns, size=size, frontmatter=fm)
        return [known[n] for n in sorted(known)]


def dir_stamp(memory_path: Path, subdir: str) -> tuple[int, int]:
    """(file count, max mtime_ns) — a cheap change stamp, no parsing."""
    current = _scan(Path(memory_path) / subdir)
    return len(current), max((m for m, _ in current.values()), default=0)
```

- [ ] **Step 4: Route the hot paths through it**

`api/routers/status.py`:
- `_last_ingested_at(memory_path)` → `max((str(f.frontmatter.get("timestamp") or "") for f in bank_index.files(memory_path, "episodes")), default="") or None`.
- `get_status`: compute `unprocessed = sum(1 for f in bank_index.files(settings.memory_path, "episodes") if not f.frontmatter.get("processed", False))` instead of `_get_unprocessed_episodes` (which reads bodies); keep everything else. Wrap the file-scanning pieces: `items, unprocessed, last_ingested = await run_in_threadpool(_scan_bank, settings.memory_path)` where `_scan_bank` is a new sync helper returning the three values (import `from starlette.concurrency import run_in_threadpool`).

`api/services/sleep_cycle.py::_get_unprocessed_episodes`: iterate `bank_index.files(memory_path, "episodes")`, skip processed via frontmatter, and only for unprocessed call `f.body()`; keep the returned dict shape and the sort exactly as today.

`api/services/origin_stats.py::aggregate_origins`: iterate `bank_index.files(memory_path, "episodes")` / `files(memory_path, "entities")` using `f.frontmatter` and `f.stem` — same aggregation, no `markdown_parser.parse`.

`api/routers/origins.py` and `api/routers/graph.py`: wrap the builder calls in `await run_in_threadpool(...)`.

- [ ] **Step 5: Run tests, then measure**

Run: `api/.venv/bin/python -m pytest api/tests/test_bank_index.py api/tests/test_origin_stats.py api/tests/test_sleep_resumable.py -v` → PASS; full suite → only the 8 baseline failures.
Measure against the live bank: `CICADA_MEMORY_PATH=$PWD/memory CICADA_API_AUTH=off api/.venv/bin/python -c "from fastapi.testclient import TestClient; from api import main; import time
with TestClient(main.app) as c:
    for p in ('/status','/origins','/status','/origins'):
        t=time.perf_counter(); c.get(p); print(p, round((time.perf_counter()-t)*1000), 'ms')"`
Expected: second `/status` and `/origins` well under 50 ms (first call pays the scan once).

- [ ] **Step 6: Commit** — `feat(api): bank_index frontmatter cache; /status and /origins stop re-parsing every file`

---

### Task 2: Memoised embedding model + warm-up; `free` plan price

**Files:**
- Modify: `api/services/providers.py` (`resolve_embed_fn`, `resolve_embed_fn_for_model`), `api/main.py` (lifespan warm-up), `api/services/pricing.py`
- Create: `api/tests/test_embed_cache.py`; append to `api/tests/test_pricing.py`

**Interfaces:**
- `providers.cached_embed_fn_for_model(model_id, settings=None, **factories) -> tuple[EmbedFn, str]` — memo keyed `(model_id,)`; `providers.clear_embed_cache()`; `resolve_embed_fn_for_model` becomes a thin call into it **only when no injectable factory/transport is passed** (tests that inject fakes must keep getting fresh fns).
- `providers.warm_query_embedder(memory_path) -> None` (sync; loads the model recorded in the bank's index; swallows errors).

- [ ] **Step 1: Failing tests**

```python
# api/tests/test_embed_cache.py
from __future__ import annotations

import numpy as np

from api.config import Settings
from api.services import providers


class _ST:
    instances = 0

    def __init__(self, name):
        _ST.instances += 1
        self.name = name

    def encode_query(self, texts):
        return np.zeros((len(texts), 4), dtype=np.float32)

    def encode_document(self, texts):
        return np.zeros((len(texts), 4), dtype=np.float32)


def test_cached_embed_fn_builds_model_once(monkeypatch):
    providers.clear_embed_cache()
    _ST.instances = 0
    monkeypatch.setattr(providers, "_default_sentence_transformer_factory", lambda: _ST)
    fn1, m1 = providers.cached_embed_fn_for_model("google/embeddinggemma-300m", Settings())
    fn2, m2 = providers.cached_embed_fn_for_model("google/embeddinggemma-300m", Settings())
    assert fn1 is fn2 and m1 == m2 == "google/embeddinggemma-300m"
    assert _ST.instances == 1
    assert fn1(["q"], is_query=True).shape == (1, 4)


def test_injected_factory_bypasses_cache():
    providers.clear_embed_cache()
    _ST.instances = 0
    providers.resolve_embed_fn_for_model("local-x", Settings(), sentence_transformer_factory=_ST)
    providers.resolve_embed_fn_for_model("local-x", Settings(), sentence_transformer_factory=_ST)
    assert _ST.instances == 2


def test_warm_query_embedder_never_raises(tmp_path):
    providers.clear_embed_cache()
    providers.warm_query_embedder(tmp_path)  # no index on disk -> no-op
```

Append to `api/tests/test_pricing.py`:

```python
def test_chatgpt_free_is_zero():
    assert pricing.price_for("chatgpt-plan", "free") == (0.0, f"verified {pricing.PRICES_VERIFIED}")
    assert pricing.plan_label("chatgpt-plan", "free", None) == "ChatGPT Free"
```

- [ ] **Step 2: Run to verify failures** — `AttributeError: cached_embed_fn_for_model` / price test fails.

- [ ] **Step 3: Implement**

In `providers.py`: add at module level

```python
import threading

_EMBED_CACHE: dict[str, tuple[EmbedFn, str]] = {}
_EMBED_LOCK = threading.Lock()


def _default_sentence_transformer_factory():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer


def clear_embed_cache() -> None:
    with _EMBED_LOCK:
        _EMBED_CACHE.clear()


def cached_embed_fn_for_model(model_id: str, settings: Settings | None = None) -> tuple[EmbedFn, str]:
    """Memoised :func:`resolve_embed_fn_for_model` — the model is loaded once per process."""
    mid = (model_id or "").strip()
    with _EMBED_LOCK:
        hit = _EMBED_CACHE.get(mid)
        if hit is not None:
            return hit
    built = resolve_embed_fn_for_model(
        mid, settings, sentence_transformer_factory=_default_sentence_transformer_factory(), _skip_cache=True
    )
    with _EMBED_LOCK:
        return _EMBED_CACHE.setdefault(mid, built)


def warm_query_embedder(memory_path) -> None:
    """Preload the query embedder recorded in the bank's index (background, best effort)."""
    try:
        from api.services.vector_index import SqliteVecIndexer

        recorded = (SqliteVecIndexer(memory_path).index_info() or {}).get("model")
        if recorded and recorded != "unknown":
            cached_embed_fn_for_model(recorded)
            logger.info(f"Warmed query embedder: {recorded}")
    except Exception as exc:  # never fatal
        logger.warning(f"embedder warm-up skipped: {exc}")
```

Change `resolve_embed_fn_for_model` signature to add `_skip_cache: bool = False` and, at its top: `if not _skip_cache and transport is None and openai_client_factory is None and sentence_transformer_factory is None: return cached_embed_fn_for_model(model_id, settings)`. Inside the local branch keep using the passed `sentence_transformer_factory` (the cache passes the real one). `vector_index._query_embed_fn` needs no change (it calls `resolve_embed_fn_for_model(recorded)` with no factories → cached).

In `api/main.py` `lifespan`, after the secrets block: `asyncio.get_running_loop().run_in_executor(None, warm_query_embedder, settings.memory_path)` (import `warm_query_embedder` from providers; do not await it).

`pricing.py`: add `"free": 0.0` to `"chatgpt-plan"`.

- [ ] **Step 4: Run tests + measure** — `test_embed_cache.py`, `test_pricing.py`, `test_providers.py`, `test_local_llm.py` PASS; full suite baseline. Measure `/search?q=thesis` twice via the TestClient snippet from Task 1 (call `/search?q=robotics` first as warm-up): second call < 200 ms.

- [ ] **Step 5: Commit** — `perf(search): memoise the embedding model per process + warm it at startup; ChatGPT Free = $0`

---

### Task 3: Version vector, SSE `/sync/events`, ETags

**Files:**
- Create: `api/services/sync_service.py`, `api/routers/sync.py`, `api/tests/test_sync.py`
- Modify: `api/services/graph_builder.py` (make `_dir_mtime`, `_mtime`, `_inbox_mtime` public aliases `dir_mtime`, `file_mtime`, `inbox_mtime`), `api/main.py` (mount), `api/routers/{graph,inbox,contributors,sources,origins,banks}.py` (ETag)

**Interfaces:**
- `sync_service.components(memory_path, *, sleep_state) -> dict[str, str]` keys `entities, edges, hubs, inbox, episodes, sources, git_head, bank, sleep`.
- `sync_service.version(memory_path, sleep_state) -> VersionInfo(version: str, components: dict)`; `sync_service.etag_for(memory_path, *keys) -> str` (sha1 over the named components, quoted).
- `sync_service.git_head(memory_path) -> str` (reads `.git/HEAD` → ref file / `packed-refs`; no subprocess).
- `sync_service.conditional(request, response, etag) -> Response | None` helper: sets `ETag`; returns a 304 `Response` when `If-None-Match` matches.
- Routes: `GET /sync/version`, `GET /sync/events` (SSE).

- [ ] **Step 1: Failing tests**

```python
# api/tests/test_sync.py
from __future__ import annotations

import json
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, sync_service


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    with TestClient(main.app) as c:
        yield c, tmp_path
    config.get_settings.cache_clear()


def test_git_head_reads_ref_without_subprocess(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x"], cwd=tmp_path, check=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True).stdout.strip()
    assert sync_service.git_head(tmp_path) == sha
    assert sync_service.git_head(tmp_path / "nope") == ""


def test_version_stable_then_changes(client):
    c, mem = client
    v1 = c.get("/sync/version").json()
    v2 = c.get("/sync/version").json()
    assert v1["version"] == v2["version"] and set(v1["components"]) >= {"entities", "inbox", "episodes", "git_head", "bank", "sleep"}
    time.sleep(0.01)
    (mem / "entities" / "new.md").write_text("---\ntype: concept\n---\nx\n")
    v3 = c.get("/sync/version").json()
    assert v3["version"] != v1["version"] and v3["components"]["entities"] != v1["components"]["entities"]


def test_etag_304_on_graph_and_inbox(client):
    c, _ = client
    for path in ("/graph", "/inbox", "/contributors", "/banks"):
        r1 = c.get(path)
        assert r1.status_code == 200 and r1.headers.get("etag"), path
        r2 = c.get(path, headers={"If-None-Match": r1.headers["etag"]})
        assert r2.status_code == 304, path


def test_sse_first_event_is_version(client):
    c, _ = client
    with c.stream("GET", "/sync/events") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        got = {}
        for line in r.iter_lines():
            if line.startswith("event:"):
                got["event"] = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                got["data"] = json.loads(line.split(":", 1)[1])
                break
    assert got["event"] == "version" and "version" in got["data"]
```

- [ ] **Step 2: Run to verify failures** — `ModuleNotFoundError: sync_service`.

- [ ] **Step 3: Implement**

```python
# api/services/sync_service.py
"""Cheap change detection for the companion app's sync engine (G58).

A version vector built from directory mtimes + git HEAD (read from
``.git/HEAD``, no subprocess) + sleep state. Sub-10 ms, so the app can poll
it or subscribe to ``/sync/events`` and refresh only what changed.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from fastapi import Request, Response

from api.services import bank_index
from api.services.graph_builder import dir_mtime, file_mtime, inbox_mtime


@dataclass
class VersionInfo:
    version: str
    components: dict


def git_head(memory_path: Path) -> str:
    git_dir = Path(memory_path) / ".git"
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if not head.startswith("ref:"):
        return head
    ref = head.split(":", 1)[1].strip()
    ref_file = git_dir / ref
    try:
        return ref_file.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    try:
        for line in (git_dir / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + ref):
                return line.split(" ", 1)[0]
    except OSError:
        pass
    return ""


def components(memory_path: Path, *, sleep_state=None) -> dict[str, str]:
    mp = Path(memory_path)
    ep_count, ep_max = bank_index.dir_stamp(mp, "episodes")
    src_count, src_max = bank_index.dir_stamp(mp, "sources")
    return {
        "entities": f"{dir_mtime(mp / 'entities'):.6f}",
        "edges": f"{file_mtime(mp / 'graph_edges.yaml'):.6f}",
        "hubs": f"{dir_mtime(mp / 'hubs'):.6f}",
        "inbox": f"{inbox_mtime(mp):.6f}",
        "episodes": f"{ep_count}:{ep_max}",
        "sources": f"{src_count}:{src_max}:{file_mtime(mp / 'sources' / 'url_index.json'):.6f}",
        "git_head": git_head(mp),
        "bank": mp.name,
        "sleep": f"{getattr(sleep_state, 'status', 'idle')}:{getattr(sleep_state, 'cycle_id', '') or ''}",
    }


def _digest(parts: dict) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16]


def version(memory_path: Path, sleep_state=None) -> VersionInfo:
    comps = components(memory_path, sleep_state=sleep_state)
    return VersionInfo(version=_digest(comps), components=comps)


def etag_for(memory_path: Path, *keys: str) -> str:
    comps = components(memory_path)
    return '"' + _digest({k: comps[k] for k in keys}) + '"'


def conditional(request: Request, response: Response, etag: str) -> Response | None:
    """Set ``ETag``; return a 304 response when the client already has it."""
    response.headers["ETag"] = etag
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return None
```

```python
# api/routers/sync.py
"""Version vector + SSE change stream for the app's sync engine (G58)."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.services import sync_service
from api.services.sleep_cycle import get_sleep_state

router = APIRouter(prefix="/sync")
POLL_SECONDS = 1.0
PING_SECONDS = 15.0


@router.get("/version")
async def get_version(settings: Settings = Depends(get_settings)):
    info = await run_in_threadpool(sync_service.version, settings.memory_path, get_sleep_state())
    return {"version": info.version, "components": info.components}


def _event(name: str, payload) -> str:
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n"


@router.get("/events")
async def events(settings: Settings = Depends(get_settings)):
    async def stream():
        last = None
        last_sleep = None
        since_ping = 0.0
        while True:
            info = await run_in_threadpool(sync_service.version, settings.memory_path, get_sleep_state())
            if info.version != last:
                last = info.version
                yield _event("version", {"version": info.version, "components": info.components})
                since_ping = 0.0
            state = get_sleep_state()
            sleep_key = (state.status, state.cycle_id, state.stage, state.progress)
            if sleep_key != last_sleep:
                last_sleep = sleep_key
                yield _event("sleep", {"status": state.status, "cycleId": state.cycle_id, "stage": state.stage,
                                       "totalStages": state.total_stages, "progress": state.progress, "error": state.error})
            if since_ping >= PING_SECONDS:
                yield "event: ping\ndata: {}\n\n"
                since_ping = 0.0
            await asyncio.sleep(POLL_SECONDS)
            since_ping += POLL_SECONDS

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

`graph_builder.py`: add `dir_mtime = _dir_mtime`, `file_mtime = _mtime`, `inbox_mtime = _inbox_mtime` after the helper definitions. Mount `sync.router` in `main.py`.

ETags — in each router, add `request: Request, response: Response` params and, before computing the body:
- `/graph` → `etag_for(mp, "entities", "edges", "hubs", "inbox")`; `/inbox` → `("inbox",)`; `/contributors` → `("git_head",)`; `/sources` → `("sources", "episodes")`; `/origins` → `("episodes", "entities")`; `/banks` → `("bank",)` plus the registry file mtime (append `file_mtime(settings.memory_root / "banks.yaml")` to the digest by passing an extra key — simplest: compute `etag = '"' + hashlib.sha1((etag_for(...) + str(file_mtime(...))).encode()).hexdigest()[:16] + '"'`).
- `if (early := sync_service.conditional(request, response, etag)) is not None: return early`.

- [ ] **Step 4: Run tests** — `test_sync.py` PASS; full suite baseline. Note: the SSE test's `iter_lines` breaks after the first `data:` line; the generator is cancelled when the stream closes.

- [ ] **Step 5: Commit** — `feat(api): /sync/version + /sync/events SSE + ETags — cheap change detection for the app`

---

### Task 4: Graph nodes carry `summary` + `content_hash`; builder reads the index

**Files:**
- Modify: `api/models/schemas.py` (`GraphNode`), `api/services/graph_builder.py` (`_build_full`), `api/tests/test_graph_builder.py` (append; read its existing fixture helper first)

**Interfaces:** `GraphNode.summary: Optional[str] = None` (≤ 200 chars: the first non-empty line under a `## Summary` heading, else the first 200 chars of the body with newlines collapsed); `GraphNode.content_hash: str = ""` (sha1 of frontmatter JSON + body, 12 hex chars). `graph_builder.summarize(body: str) -> str | None`, `graph_builder.content_hash(fm: dict, body: str) -> str`.

- [ ] **Step 1: Failing tests** (append to `api/tests/test_graph_builder.py`)

```python
def test_summarize_prefers_summary_section():
    from api.services.graph_builder import summarize
    body = "# Title\n\n## Summary\n\nA person who does robotics.\nMore.\n\n## Key Facts\n- x"
    assert summarize(body) == "A person who does robotics."
    assert summarize("just\nplain text here") == "just plain text here"
    assert summarize("") is None
    assert len(summarize("x" * 500)) == 200


def test_graph_nodes_have_summary_and_hash(tmp_path):
    from api.services import bank_index
    from api.services.graph_builder import build_graph
    bank_index.invalidate()
    (tmp_path / "entities").mkdir()
    (tmp_path / "entities" / "a.md").write_text("---\nname: A\ntype: concept\n---\n## Summary\n\nAbout A.\n")
    g = build_graph(tmp_path)
    node = next(n for n in g.nodes if n.id == "a")
    assert node.summary == "About A." and len(node.content_hash) == 12
    (tmp_path / "entities" / "a.md").write_text("---\nname: A\ntype: concept\n---\n## Summary\n\nAbout A, changed.\n")
    import time; time.sleep(0.01)
    g2 = build_graph(tmp_path)
    assert next(n for n in g2.nodes if n.id == "a").content_hash != node.content_hash
```

- [ ] **Step 2: Run → fails** (`ImportError: summarize`).

- [ ] **Step 3: Implement** — in `graph_builder.py`:

```python
import hashlib, json, re

_SUMMARY_RE = re.compile(r"^##\s+Summary\s*$", re.IGNORECASE | re.MULTILINE)


def summarize(body: str) -> str | None:
    text = (body or "").strip()
    if not text:
        return None
    m = _SUMMARY_RE.search(text)
    if m:
        rest = text[m.end():]
        for line in rest.splitlines():
            s = line.strip()
            if s.startswith("#"):
                break
            if s:
                return s[:200]
    flat = " ".join(l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#"))
    return flat[:200] or None


def content_hash(fm: dict, body: str) -> str:
    return hashlib.sha1((json.dumps(fm, sort_keys=True, default=str) + "\n" + (body or "")).encode()).hexdigest()[:12]
```

In `_build_full`, replace the `for filepath in sorted(entities_dir.glob("*.md")): parsed = parse(filepath)` loop head with `for f in bank_index.files(memory_path, "entities"): fm = f.frontmatter; body = f.body(); eid = f.stem` (bodies are needed for claims anyway) and pass `summary=summarize(body), content_hash=content_hash(fm, body)` into `GraphNode(...)`. Add the two fields to `GraphNode` in `schemas.py` (`summary: Optional[str] = None`, `content_hash: str = ""`).

- [ ] **Step 4: Run** `test_graph_builder.py` + full suite → baseline. **Commit** — `feat(graph): nodes carry summary + content_hash; builder reads bank_index`

---

### Task 5: Swift test target + engine primitives (`Snapshot`, `SnapshotCache`, `SSEParser`, `VersionVector`)

**Files:**
- Modify: `app/CicadaApp/Package.swift` (add `.testTarget(name: "CicadaAppTests", dependencies: ["CicadaApp"])`)
- Create: `Sources/CicadaApp/Sync/Snapshot.swift`, `SnapshotCache.swift`, `SSEParser.swift`, `VersionVector.swift`; `Tests/CicadaAppTests/SnapshotCacheTests.swift`, `SSEParserTests.swift`, `VersionVectorTests.swift`

**Interfaces:**
```swift
struct Snapshot<T: Codable> { var value: T?; var etag: String?; var loadedAt: Date?; var isRefreshing = false }
enum SyncDomain: String, CaseIterable, Codable { case graph, inbox, banks, sources, feeds, calendars, contributors, origins, connections, status }
actor SnapshotCache {
    init(root: URL)                                 // default: Application Support/Cicada/cache
    func load<T: Codable>(_ domain: SyncDomain, bank: String, as: T.Type) async -> (value: T, etag: String?)?
    func save<T: Codable>(_ value: T, etag: String?, domain: SyncDomain, bank: String) async   // debounced 500 ms
    func flush() async
    func clear(bank: String) async
}
struct SSEEvent: Equatable { let name: String; let data: String }
struct SSEParser { mutating func feed(_ line: String) -> SSEEvent? }   // handles "event:", "data:", blank-line dispatch, ignores comments/ids
struct VersionVector: Codable, Equatable { let version: String; let components: [String: String]
    func changedDomains(since old: VersionVector?) -> Set<SyncDomain> }
```
Domain mapping (`changedDomains`): `entities|edges|hubs → graph, contributors, origins`; `inbox → inbox, graph, status`; `episodes → status, origins, sources`; `sources → sources, feeds`; `git_head → contributors`; `sleep → status`; `bank → all domains`. `old == nil → all`.

- [ ] **Step 1: Tests**

```swift
// Tests/CicadaAppTests/SSEParserTests.swift
import XCTest
@testable import CicadaApp

final class SSEParserTests: XCTestCase {
    func testDispatchesOnBlankLine() {
        var p = SSEParser()
        XCTAssertNil(p.feed("event: version"))
        XCTAssertNil(p.feed("data: {\"version\":\"abc\"}"))
        XCTAssertEqual(p.feed(""), SSEEvent(name: "version", data: "{\"version\":\"abc\"}"))
        XCTAssertNil(p.feed(""))
    }
    func testMultiLineDataAndComments() {
        var p = SSEParser()
        _ = p.feed(": keepalive"); _ = p.feed("data: a"); _ = p.feed("data: b")
        XCTAssertEqual(p.feed(""), SSEEvent(name: "message", data: "a\nb"))
    }
}
```

```swift
// Tests/CicadaAppTests/VersionVectorTests.swift
import XCTest
@testable import CicadaApp

final class VersionVectorTests: XCTestCase {
    func testNilOldMeansEverything() {
        let v = VersionVector(version: "1", components: ["entities": "a"])
        XCTAssertEqual(v.changedDomains(since: nil), Set(SyncDomain.allCases))
    }
    func testMapsComponents() {
        let old = VersionVector(version: "1", components: ["entities": "a", "inbox": "1", "bank": "x", "sleep": "idle:"])
        let new = VersionVector(version: "2", components: ["entities": "b", "inbox": "1", "bank": "x", "sleep": "idle:"])
        XCTAssertEqual(new.changedDomains(since: old), [.graph, .contributors, .origins])
        let bank = VersionVector(version: "3", components: ["entities": "b", "inbox": "1", "bank": "y", "sleep": "idle:"])
        XCTAssertEqual(bank.changedDomains(since: new), Set(SyncDomain.allCases))
        XCTAssertEqual(new.changedDomains(since: new), [])
    }
}
```

```swift
// Tests/CicadaAppTests/SnapshotCacheTests.swift
import XCTest
@testable import CicadaApp

final class SnapshotCacheTests: XCTestCase {
    struct Thing: Codable, Equatable { let a: Int }
    func testRoundTripAndClear() async {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let cache = SnapshotCache(root: root)
        await cache.save([Thing(a: 1)], etag: "\"e1\"", domain: .inbox, bank: "b")
        await cache.flush()
        let hit = await cache.load(.inbox, bank: "b", as: [Thing].self)
        XCTAssertEqual(hit?.value, [Thing(a: 1)]); XCTAssertEqual(hit?.etag, "\"e1\"")
        let miss = await cache.load(.graph, bank: "b", as: [Thing].self)
        XCTAssertNil(miss)
        await cache.clear(bank: "b")
        let gone = await cache.load(.inbox, bank: "b", as: [Thing].self)
        XCTAssertNil(gone)
    }
    func testSchemaMismatchIsAMiss() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let dir = root.appendingPathComponent("b"); try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try "{\"schema\":0,\"payload\":[]}".write(to: dir.appendingPathComponent("inbox.json"), atomically: true, encoding: .utf8)
        let cache = SnapshotCache(root: root)
        let hit = await cache.load(.inbox, bank: "b", as: [Thing].self)
        XCTAssertNil(hit)
    }
}
```

- [ ] **Step 2: `swift test` → compile errors.**

- [ ] **Step 3: Implement**

```swift
// Sources/CicadaApp/Sync/Snapshot.swift
import Foundation

struct Snapshot<T: Codable> {
    var value: T?
    var etag: String?
    var loadedAt: Date?
    var isRefreshing = false
    var isEmpty: Bool { value == nil }
}

enum SyncDomain: String, CaseIterable, Codable {
    case graph, inbox, banks, sources, feeds, calendars, contributors, origins, connections, status
}
```

```swift
// Sources/CicadaApp/Sync/VersionVector.swift
import Foundation

struct VersionVector: Codable, Equatable {
    let version: String
    let components: [String: String]

    static let mapping: [String: Set<SyncDomain>] = [
        "entities": [.graph, .contributors, .origins], "edges": [.graph, .contributors, .origins], "hubs": [.graph, .contributors, .origins],
        "inbox": [.inbox, .graph, .status], "episodes": [.status, .origins, .sources],
        "sources": [.sources, .feeds], "git_head": [.contributors], "sleep": [.status],
    ]

    func changedDomains(since old: VersionVector?) -> Set<SyncDomain> {
        guard let old else { return Set(SyncDomain.allCases) }
        if old.version == version { return [] }
        if components["bank"] != old.components["bank"] { return Set(SyncDomain.allCases) }
        var out = Set<SyncDomain>()
        for (key, domains) in Self.mapping where components[key] != old.components[key] { out.formUnion(domains) }
        return out
    }
}
```

```swift
// Sources/CicadaApp/Sync/SSEParser.swift
import Foundation

struct SSEEvent: Equatable { let name: String; let data: String }

/// Minimal text/event-stream parser: feed one line at a time; an event is
/// returned on the blank line that terminates it.
struct SSEParser {
    private var name = "message"
    private var data: [String] = []

    mutating func feed(_ rawLine: String) -> SSEEvent? {
        let line = rawLine.hasSuffix("\r") ? String(rawLine.dropLast()) : rawLine
        if line.isEmpty {
            guard !data.isEmpty else { name = "message"; return nil }
            let event = SSEEvent(name: name, data: data.joined(separator: "\n"))
            name = "message"; data = []
            return event
        }
        if line.hasPrefix(":") { return nil }
        let parts = line.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false)
        let field = String(parts[0])
        var value = parts.count > 1 ? String(parts[1]) : ""
        if value.hasPrefix(" ") { value.removeFirst() }
        switch field {
        case "event": name = value
        case "data": data.append(value)
        default: break
        }
        return nil
    }
}
```

```swift
// Sources/CicadaApp/Sync/SnapshotCache.swift
import Foundation

/// Disk persistence for Store snapshots — disposable cache, versioned envelope.
actor SnapshotCache {
    static let schema = 1
    private struct Envelope<T: Codable>: Codable { let schema: Int; let etag: String?; let savedAt: Date; let payload: T }

    private let root: URL
    private var pending: [String: Task<Void, Never>] = [:]
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    init(root: URL? = nil) {
        self.root = root ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Cicada/cache", isDirectory: true)
    }

    private func url(_ domain: SyncDomain, bank: String) -> URL {
        let safe = bank.replacingOccurrences(of: "/", with: "_")
        return root.appendingPathComponent(safe, isDirectory: true).appendingPathComponent("\(domain.rawValue).json")
    }

    func load<T: Codable>(_ domain: SyncDomain, bank: String, as: T.Type) -> (value: T, etag: String?)? {
        guard let data = try? Data(contentsOf: url(domain, bank: bank)),
              let env = try? decoder.decode(Envelope<T>.self, from: data),
              env.schema == Self.schema else { return nil }
        return (env.payload, env.etag)
    }

    func save<T: Codable>(_ value: T, etag: String?, domain: SyncDomain, bank: String) {
        let key = "\(bank)/\(domain.rawValue)"
        pending[key]?.cancel()
        let env = Envelope(schema: Self.schema, etag: etag, savedAt: Date(), payload: value)
        guard let data = try? encoder.encode(env) else { return }
        let target = url(domain, bank: bank)
        pending[key] = Task { [target] in
            try? await Task.sleep(for: .milliseconds(500))
            guard !Task.isCancelled else { return }
            try? FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
            try? data.write(to: target, options: .atomic)
        }
    }

    func flush() async {
        for (_, task) in pending { _ = await task.value }
        pending.removeAll()
    }

    func clear(bank: String) {
        for (key, task) in pending where key.hasPrefix("\(bank)/") { task.cancel(); pending[key] = nil }
        try? FileManager.default.removeItem(at: root.appendingPathComponent(bank.replacingOccurrences(of: "/", with: "_")))
    }
}
```

Note: `flush()` must await the debounce; the test calls `flush()` right after `save()`. Keep the sleep inside the task so `flush` observes completion.

- [ ] **Step 4: `swift build && swift test` → green. Commit** — `feat(app): sync primitives — Snapshot, SnapshotCache, SSEParser, VersionVector (+ CicadaAppTests target)`

---

### Task 6: `Store` + `SyncEngine` + API client support; hydrate before first frame

**Files:**
- Create: `Sources/CicadaApp/Sync/Store.swift`, `Sources/CicadaApp/Sync/SyncEngine.swift`, `Tests/CicadaAppTests/StoreTests.swift`
- Modify: `Services/APIClient.swift` (`getConditional`, `fetchSyncVersion`, `syncEventLines`, token cache), `CicadaApp.swift` (create + inject `Store`; hydrate; start engine; remove the 30 s menu-bar loop)

**Interfaces:**
```swift
// APIClient
struct Conditional<T> { let value: T?; let etag: String?; let notModified: Bool }
func getConditional<T: Decodable>(_ path: String, etag: String?) async throws -> Conditional<T>
func fetchSyncVersion() async throws -> VersionVector
func syncEventLines() async throws -> (AsyncLineSequence<URLSession.AsyncBytes>, HTTPURLResponse)   // GET /sync/events with bearer

// Store (@Observable @MainActor final class)
var bank: String
var graph: Snapshot<GraphResponse>; var inbox: Snapshot<[InboxItem]>; var banks: Snapshot<BanksResponse>
var sources: Snapshot<[MediaFeedItem]>; var feeds: Snapshot<[FeedSubscription]>; var calendars: Snapshot<[CalendarSubscription]>
var contributors: Snapshot<[Contributor]>; var origins: Snapshot<[OriginStat]>; var connections: Snapshot<[ConnectionStatus]>
var status: Snapshot<StatusSnapshot>; var entities: [String: Entity]; var toast: String?
var version: VersionVector?; var isConnected: Bool
init(cache: SnapshotCache = SnapshotCache(), api: APIClient = .shared)
func hydrate() async                              // disk → snapshots (bank from banks snapshot or "default")
func refresh(_ domains: Set<SyncDomain>) async    // conditional GETs; never blanks; persists
func refreshAll() async
func entity(_ id: String) async -> Entity?        // cached full entity (LRU 200)
func apply(version: VersionVector) async          // diff → refresh changed domains
```
`SyncEngine` (`@MainActor final class`, owned by Store): `start()` opens SSE via `api.syncEventLines()`, parses with `SSEParser`, on `version` → `store.apply(version:)`, on `sleep` → updates `store.status.value?.sleep` fields; reconnect backoff 1→30 s; while disconnected, polls `fetchSyncVersion()` every 3 s; `stop()`.

- [ ] **Step 1: Tests** (`StoreTests.swift`): inject a fake `APIClient`-like protocol? `APIClient` is an actor with a static shared — introduce `protocol SyncAPI` with the methods Store needs (`fetchGraphConditional(etag:)`, `fetchInboxConditional(etag:)`, … one per domain, plus `fetchEntity`) implemented by `APIClient` via an extension, and a `FakeSyncAPI` in tests returning canned values and recording calls. Tests: (a) `hydrate` loads from a pre-seeded `SnapshotCache`; (b) `refresh([.inbox])` with the fake returning `notModified` keeps the existing value and does not flip it to nil; (c) `apply(version:)` with only `inbox` changed calls only the inbox/graph/status fetches; (d) a failing fetch keeps the old value and sets `toast`.

- [ ] **Step 2: `swift test` → fails** (missing types).

- [ ] **Step 3: Implement** — key parts:

`APIClient`:
```swift
    private static var cachedToken: String?
    private static func loadToken() -> String? {
        if let cachedToken { return cachedToken }
        // existing file/env read …
        cachedToken = token; return token
    }
    // on any 401 in the generic helpers: `Self.cachedToken = nil` before throwing.

    func getConditional<T: Decodable>(_ path: String, etag: String?) async throws -> Conditional<T> {
        var request = makeRequest(path, method: "GET", json: false)
        if let etag { request.setValue(etag, forHTTPHeaderField: "If-None-Match") }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.serverUnreachable }
        if http.statusCode == 304 { return Conditional(value: nil, etag: etag, notModified: true) }
        guard (200...299).contains(http.statusCode) else { throw APIError.httpError(http.statusCode, String(data: data, encoding: .utf8) ?? "") }
        return Conditional(value: try decoder.decode(T.self, from: data), etag: http.value(forHTTPHeaderField: "ETag"), notModified: false)
    }

    func syncEventLines() async throws -> (URLSession.AsyncBytes.Lines, HTTPURLResponse) {
        var request = makeRequest("/sync/events", method: "GET", json: false)
        request.timeoutInterval = 3600
        let (bytes, response) = try await URLSession.shared.bytes(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else { throw APIError.serverUnreachable }
        return (bytes.lines, http)
    }
```
(`GET /inbox` returns `[InboxItem]` via `fetchInbox`; reuse the same response types the existing `fetch*` methods decode — `GraphResponse`, `BanksResponse`, etc.; for endpoints wrapped in a response object (`/contributors` → `ContributorsResponse`), decode the wrapper then unwrap.)

`Store.refresh(_:)`: for each domain, mark `isRefreshing = true`, call the conditional fetch with the snapshot's etag, on `notModified` just clear `isRefreshing`; on value: assign `value`, `etag`, `loadedAt = Date()`, then `await cache.save(value, etag:, domain:, bank:)`; on error: keep value, `isRefreshing = false`, set `toast` only if the snapshot was empty. `.status` uses a plain (non-conditional) `fetchStatus()`. `.banks` also updates `bank` from the response's active name; if it changed, `hydrate()` the new bank from cache before refreshing everything.

`SyncEngine.start()`:
```swift
    func start() {
        task?.cancel()
        task = Task { [weak self] in
            var backoff: Double = 1
            while !Task.isCancelled {
                guard let self else { return }
                do {
                    let (lines, _) = try await api.syncEventLines()
                    await MainActor.run { self.store.isConnected = true }; backoff = 1
                    var parser = SSEParser()
                    for try await line in lines {
                        if Task.isCancelled { return }
                        guard let event = parser.feed(line) else { continue }
                        await self.handle(event)
                    }
                } catch { /* fall through to reconnect */ }
                await MainActor.run { self.store.isConnected = false }
                // poll fallback while waiting to reconnect
                let until = Date().addingTimeInterval(backoff)
                while Date() < until, !Task.isCancelled {
                    if let v = try? await api.fetchSyncVersion() { await self.store.apply(version: v) }
                    try? await Task.sleep(for: .seconds(3))
                }
                backoff = min(30, backoff * 2)
            }
        }
    }
```
`handle(event)`: `"version"` → decode `VersionVector` from `event.data` → `store.apply(version:)`; `"sleep"` → decode `{status, cycleId, stage, totalStages, progress, error}` and merge into `store.status.value?.sleep` (mirror `StatusSnapshot`'s sleep struct fields — read `Models` to match) and set `store.sleepEvent = decoded` (a published field the Sleep view model observes).

`CicadaApp.swift`: `@State private var store = Store()`; `.environment(store)`; in `.onAppear`: `Task { await store.hydrate(); await store.refreshAll(); store.engine.start() }`; delete the `menuPollTask` loop and instead `withObservationTracking`-style: the `MenuBarManager` gets fed from `store.status` changes — simplest: in `Store.refresh(.status)` after assigning, call `onStatus?(snapshot)`; wire `store.onStatus = { menuBarManager.apply(snapshot: $0, justFinishedAt: …) }` keeping the running→idle edge logic that lived in the loop.

- [ ] **Step 4: `swift build && swift test` green; launch the app (backend running) and confirm it renders immediately from cache on second launch. Commit** — `feat(app): Store + SyncEngine — disk-hydrated snapshots, SSE-driven conditional refresh`

---

### Task 7: View models become projections; no per-view refetch; no blanking

**Files:** `ViewModels/GraphViewModel.swift`, `InboxViewModel.swift`, `SleepViewModel.swift`, `BanksViewModel.swift`, `FeedViewModel.swift`, `ContributorsViewModel.swift`, `ConnectionsViewModel.swift`; `CicadaApp.swift` (inject Feed/Contributors/Connections VMs too); `ContentView.swift`, `Views/Feed/FeedView.swift`, `Views/Contributors/ContributorsView.swift`, `Views/Connections/ConnectionsView.swift`, `Views/Inbox/InboxListView.swift`, `Views/Sleep/SleepView.swift`, `Views/Capture/SourcesView.swift` (its four `load*` read from `store` and the sync/poll buttons call `store.refresh`)

**Rules (apply to every VM):** `init(store: Store)`; data properties become computed over `store.<domain>.value ?? []`; `isLoading` = `store.<domain>.isEmpty && store.<domain>.isRefreshing`; `load()` = `await store.refresh([.x])`; `@MainActor` on all; delete every polling loop except `SleepViewModel`'s 1 s poll while a cycle runs (keep it — it's the live progress bar; but stop it when `store.sleepEvent` reports idle). Views: remove `@State private var viewModel = X()` in favour of `@Environment(X.self)`; remove `.task { await viewModel.load() }` where the store already refreshes on version changes; keep explicit refresh buttons. `FeedViewModel` must never assign `items = []` on error (computed over the snapshot, so this falls out). `GraphViewModel.entities` is derived from `store.graph.value?.nodes` (with `summary` → `markdownContent` placeholder, next task) and recomputed only when the snapshot changes (store a private cached array keyed on `store.graph.loadedAt`).

- [ ] Build after each VM conversion; `swift test`; launch and click through every tab: no spinner on revisits, no empty flashes. Commit — `refactor(app): view models are projections over Store; tab switches render instantly`

---

### Task 8: Optimistic mutations with rollback

**Files:**
- Create: `Sources/CicadaApp/Sync/Mutations.swift`, `Tests/CicadaAppTests/MutationTests.swift`
- Modify: `Store.swift` (`perform`), `InboxViewModel.resolve`, `ConnectionsViewModel.{setTier,saveKey,removeKey,logout}`, `BanksViewModel.activate`, `SleepViewModel.triggerManually`, `SourcesView` feed/calendar subscribe/unsubscribe, `ContentView`/root view (toast banner)

**Interfaces:**
```swift
protocol Mutation { func optimistic(_ store: Store); func request(_ api: SyncAPI) async throws; func rollback(_ store: Store); var failureMessage: String { get } }
extension Store { func perform(_ m: Mutation) async -> Bool }   // apply → request in background → rollback + toast on failure; returns success
struct InboxResolve: Mutation   // removes item (non-skip) optimistically; rollback reinserts at its index
struct SetConnectionTier: Mutation  // patches plan_label/price locally via pricing table client-side (5x→100, 20x→200 for Claude Max; ChatGPT Pro same) then PUT; rollback restores the old status
struct RemoveConnectionKey / LogoutConnection: Mutation   // flips connected=false locally; rollback restores
struct SubscribeFeed / UnsubscribeFeed / SubscribeCalendar / UnsubscribeCalendar: Mutation
struct ActivateBank: Mutation      // sets store.bank + hydrates target bank from cache immediately, marks banks active locally; request POST activate; rollback re-hydrates previous bank
struct TriggerSleep: Mutation      // status.sleep.status = "running" locally
```

- [ ] Tests: `InboxResolve` optimistic removal + rollback reinsertion at the same index when the fake API throws; `perform` returns false and sets `toast`; `ActivateBank` swaps `store.bank` immediately (fake cache pre-seeded for both banks) and rolls back on failure.
- [ ] Implement; wire each call site; toast banner: a small capsule at the bottom of `ContentView`'s detail area that shows `store.toast` for 4 s (`.task(id: store.toast)` clears it).
- [ ] Build/test green; live check: resolve an inbox item → card disappears immediately; kill the backend, resolve another → card returns with a toast. Commit — `feat(app): optimistic mutations with rollback (inbox, connections, feeds, calendars, banks, sleep)`

---

### Task 9: Graph delta transport + instant detail cards

**Files:**
- Modify: `Models/Entity.swift` (`GraphNode` + `summary`, `contentHash` tolerant), `ViewModels/GraphViewModel.swift`, `Views/Graph/GraphView.swift`, `Resources/graph/graph.js`, `Views/Graph/EntityDetailCard.swift`
- Create: `Sources/CicadaApp/Sync/GraphDiff.swift`, `Tests/CicadaAppTests/GraphDiffTests.swift`

**Interfaces:**
```swift
struct GraphDelta { var added: [GraphNode]; var updated: [GraphNode]; var removed: [String]; var links: [GraphEdge]; var isFull: Bool }
enum GraphDiff { static func diff(old: GraphResponse?, new: GraphResponse) -> GraphDelta }   // by id + contentHash; links replaced wholesale when their set changed; old == nil → isFull
```
graph.js: `function updateGraphDelta(dataStr)` — parse `{added, updated, removed, links}`; remove nodes by id (and dangling links), upsert updated nodes' fields in place (keep x/y/vx/vy), push added nodes seeded via `seedPositionFor`, replace `links` when provided, then `computeDegree(); buildHubIndex(); rebuildVisible(); rebuildNeighborsIndex(); startSimulation({ reheat: 0.3 }); scheduleRedraw();`.
`GraphView.updateNSView`: if `viewModel.pendingDelta` is set and `!pendingDelta.isFull` → `updateGraphDelta(json)`, else `updateGraph(json)`; JSON strings are prepared by `GraphViewModel` in a `Task.detached` when the snapshot changes (`prepareGraphPush()`), stored as `pendingPushJSON: String?` + `pendingPushIsDelta: Bool`; `updateNSView` only evaluates the string.
Detail cards: `Entity` stubs get `markdownContent = node.summary ?? ""`; `EntityDetailCard` shows the summary immediately and, in `.task(id: entity.id)`, awaits `store.entity(id)` and swaps in the full entity.

- [ ] Tests: `GraphDiffTests` — added/updated/removed detection via `contentHash`; unchanged → empty delta with `links` nil; `old == nil` → `isFull`.
- [ ] Implement; verify live: run a Sleep cycle (or touch an entity file) → graph updates in place (nodes keep positions); click a node → card shows summary instantly. Commit — `feat(graph): delta pushes to d3 + instant detail cards from node summaries`

---

### Task 10: Polish — sidebar buttons/shortcuts/AX, image cache, main-actor VMs

**Files:** `Views/Sidebar/SidebarView.swift`, `Views/Connections/ConnectionsView.swift`, `Views/Connect/ConnectView.swift`, `Views/Connect/SyncSetupView.swift`, new `Views/Common/LogoImage.swift`

- [ ] `SidebarRow` wrapped in `Button(action:) { … }.buttonStyle(.plain).keyboardShortcut(KeyEquivalent(Character("\(index + 1)")), modifiers: .command)` for the first nine tabs, `.accessibilityLabel(tab.rawValue)`, `.accessibilityAddTraits(isSelected ? .isSelected : [])`.
- [ ] `LogoImage(name:)` view with a `static var cache: [String: NSImage]` loading once off the main thread (`Task.detached` → `MainActor`); replace the three `NSImage(contentsOf:)` sites.
- [ ] Confirm every VM is `@MainActor` (Task 7) and `GraphViewModel.selectEntity` no longer needs the manual hop.
- [ ] Build; harness check: `mac.ax.query(text: "Connections")` now returns an `AXButton` with `AXPress`. Commit — `feat(app): sidebar buttons with ⌘1-9 + accessibility; cached logos`

---

### Task 11: In-app Ask (G52)

**Files:**
- Create: `Sources/CicadaApp/Ask/AskViewModel.swift`, `Sources/CicadaApp/Ask/AskPanel.swift`, `Tests/CicadaAppTests/AskHistoryTests.swift`
- Modify: `Models/*` (add `AskResponse`, `AskCitation` matching `api/models/schemas.py::AskResponse` — `answer, confidence, citations[{entityId, entityName, filePath, snippet, sourceEpisodes}], gaps, usedEntities`), `Services/APIClient.swift` (`ask(query:topK:)` → `POST /ask` `{query, topK}`), `ContentView.swift` (⌘K → `.sheet` with `AskPanel`; toolbar "Ask" button on the graph page header)

**Behaviour:** question field (focused on open) → Enter → `POST /ask` → answer markdown rendered with `MarkdownBody`; citations rendered as a row of chips styled like wikilinks (`[[Entity name]]`) — clicking calls `graphVM.selectEntity(id:)` and closes the panel; `gaps` listed under "I don't know:" ; `confidence` shown as a subtle meter; recent questions (last 20, per bank) persisted via `SnapshotCache` under a new domain case `askHistory` (add to `SyncDomain`, exclude it from `refresh`); while a request is in flight the previous answer stays visible dimmed; errors show inline, never blank.

- [ ] Tests: history ring-buffer (max 20, most recent first, dedup by question) + `AskResponse` tolerant decoding with missing `gaps`.
- [ ] Implement; live check with the backend (OpenRouter key present): ask "what is my thesis about?" → answer + chips → chip opens the entity. Commit — `feat(app): ⌘K Ask panel — grounded answers with wikilink citations and gaps (G52)`

---

### Task 12: Verification, docs, backlog

- [ ] Re-measure with the Task 1 snippet: `/status`, `/origins`, `/search` (warm), `/graph` with `If-None-Match` (expect 304 in < 10 ms). Record numbers in the commit message.
- [ ] Live smoke via the harness (window capture): cold launch → data visible before any network round-trip completes (kill the backend, launch the app: pages render from cache with a "reconnecting" state; start the backend: the SSE connects and refreshes).
- [ ] `CLAUDE.md`: add `GET /sync/version`, `GET /sync/events` to the API list; note ETags and the app-side Store/SnapshotCache in the Companion App section. `docs/goals/memory-evolution.md`: add **G58** row (sync engine — status ✅ with commits) and set **G52** ✅.
- [ ] Full suite + `swift build && swift test`. Commit — `docs: sync engine + ask panel; G58/G52 status`

---

## Self-review
- Spec §4.1→T1, §4.2/4.6→T2, §4.3→T3, §4.4→T4, §4.5→T1/T3 (threadpool), §5.1–5.3→T5/T6, §5.4→T8, §5.5→T7, §5.6–5.7→T9, §5.8→T10 (+T6 token cache, T7 main-actor), §5.9→T11, §8→T12.
- Type consistency: `SyncDomain` cases used identically in `VersionVector.mapping`, `SnapshotCache`, `Store`; `Conditional<T>` produced by `APIClient.getConditional` and consumed by `Store.refresh`; `GraphNode.contentHash`/`summary` camelCase from `content_hash`/`summary` via `CamelModel`.
- Placeholders: none; T7/T10/T12 are edit lists over named files with explicit rules rather than full code, deliberately — each conversion is mechanical against the interfaces defined in T5/T6/T8.

## Execution handoff
Subagent-driven, in order T1→T2→T3→T4 (backend, independent of each other except T4 needs T1), T5→T6→T7→T8→T9→T10→T11→T12 (each builds on the previous). Backend tasks 1–3 can be batched; Swift tasks run one at a time.
