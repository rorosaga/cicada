"""G207 (ruling 36 D2): a conversation is recallable as soon as it lands, before Sleep reads it.

Step 0 embeds the new conversation's passages right after capture (no model). Step 1, the quick read, writes
provisional claims that Sleep settles. Hermetic: a bag-of-words embedder, a stub extractor, scratch banks.
"""
from __future__ import annotations

import asyncio
import re
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest

from api.services import awake_read, bank_registry, vector_index
from api.services.claims import Claim, Evidence, write_claims

VOCAB = ["alpha", "beta", "harbor", "violin", "deadline", "moved", "friday", "garden", "misc"]


def _embed(texts, *, is_query: bool = False):
    rows = []
    for t in texts:
        toks = set(re.findall(r"[a-z]+", t.lower()))
        v = np.array([1.0 if w in toks else 0.0 for w in VOCAB], dtype=np.float32)
        n = float(np.linalg.norm(v))
        rows.append(v / n if n > 0 else np.ones(len(VOCAB), dtype=np.float32) / np.sqrt(len(VOCAB)))
    return np.vstack(rows).astype(np.float32)


def _page(bank: Path, eid: str, name: str, body: str = "", claims: list[Claim] | None = None, aliases=()):
    (bank / "entities").mkdir(parents=True, exist_ok=True)
    alias_yaml = "".join(f"\n  - {a}" for a in aliases)
    text = (f"---\nname: {name}\ntype: project\nstatus: active\nconfidence: 0.7\n"
            f"aliases:{alias_yaml or ' []'}\n---\n\n{body}\n")
    if claims:
        text = write_claims(text, claims)
    (bank / "entities" / f"{eid}.md").write_text(text, encoding="utf-8")


def _episode(bank: Path, eid: str, body: str, *, processed: bool = False):
    (bank / "episodes").mkdir(parents=True, exist_ok=True)
    (bank / "episodes" / f"{eid}.md").write_text(
        f"---\nid: {eid}\nsource: claude-code\ntimestamp: '2026-10-22T10:00:00Z'\nprocessed: "
        f"{'true' if processed else 'false'}\ntitle: t\n---\n\n{body}\n", encoding="utf-8")


@pytest.fixture
def bank(tmp_path):
    b = tmp_path / "bank"
    _page(b, "alpha-project", "Alpha Project", "A project about a harbor.", aliases=("alpha",))
    _episode(b, "ep_2026-10-22_001", "user: the alpha deadline moved to friday\n\nassistant: noted, friday it is")
    return b


@pytest.fixture
def awake_on(monkeypatch):
    monkeypatch.setenv("CICADA_AWAKE_READ", "on")
    awake_read.QUEUE.jobs.clear()
    awake_read.QUEUE.reads.clear()
    yield
    awake_read.QUEUE.jobs.clear()


# --------------------------------------------------------------------------- the trigger


def test_mode_reads_the_env(monkeypatch):
    monkeypatch.setenv("CICADA_AWAKE_READ", "off")
    assert awake_read.mode() == "off"
    monkeypatch.setenv("CICADA_AWAKE_READ", "index")
    assert awake_read.mode() == "index"
    monkeypatch.delenv("CICADA_AWAKE_READ")
    assert awake_read.mode() == ("on" if awake_read.QUICK_READ_DEFAULT else "index")


def test_after_capture_only_queues_and_debounces(bank, awake_on, monkeypatch):
    ran = []
    monkeypatch.setattr(awake_read, "run_job", lambda job: ran.append(job))
    monkeypatch.setattr(awake_read._Queue, "_loop", lambda self: None)   # no worker: nothing runs in the caller
    for _ in range(3):
        awake_read.after_capture(bank, "ep_2026-10-22_001", status="updated")
    assert ran == []
    kinds = sorted(k for (_b, _e, k) in awake_read.QUEUE.jobs)
    assert kinds == ["index", "read"]   # three captures, one job of each kind
    read = awake_read.QUEUE.jobs[(str(bank), "ep_2026-10-22_001", "read")]
    assert read.due - time.monotonic() > awake_read.QUIET_S - 5   # a Stop is not an end: it waits for quiet


def test_session_end_reads_soon_and_unchanged_queues_nothing(bank, awake_on, monkeypatch):
    monkeypatch.setattr(awake_read._Queue, "_loop", lambda self: None)
    awake_read.after_capture(bank, "ep_x", status="unchanged")
    assert awake_read.QUEUE.jobs == {}
    awake_read.after_capture(bank, "ep_x", status="updated", hook_event="SessionEnd")
    read = awake_read.QUEUE.jobs[(str(bank), "ep_x", "read")]
    assert read.due - time.monotonic() <= awake_read.ENDED_S + 1


def test_off_queues_nothing(bank, monkeypatch):
    monkeypatch.setenv("CICADA_AWAKE_READ", "off")
    awake_read.QUEUE.jobs.clear()
    awake_read.after_capture(bank, "ep_2026-10-22_001", status="created")
    assert awake_read.QUEUE.jobs == {}


def test_a_held_back_job_is_retried_then_dropped(bank, awake_on, monkeypatch):
    monkeypatch.setattr(awake_read._Queue, "_loop", lambda self: None)
    monkeypatch.setattr(awake_read, "index_now", lambda *a, **k: "reindexing")
    job = awake_read._Job(0.0, str(bank), "ep_2026-10-22_001", "index")
    assert awake_read.run_job(job) == "reindexing"
    again = awake_read.QUEUE.jobs.pop((str(bank), "ep_2026-10-22_001", "index"))
    assert again.tries == 1 and again.due > time.monotonic() + awake_read.RETRY_S - 5
    awake_read.run_job(awake_read._Job(0.0, str(bank), "ep_2026-10-22_001", "index", tries=awake_read.MAX_TRIES - 1))
    assert awake_read.QUEUE.jobs == {}


def test_a_big_import_is_indexed_not_read(bank, awake_on, monkeypatch):
    monkeypatch.setattr(awake_read._Queue, "_loop", lambda self: None)
    ids = [f"ep_2026-10-22_{i:03d}" for i in range(awake_read.IMPORT_READ_MAX + 1)]
    awake_read.after_import(bank, ids)
    jobs = list(awake_read.QUEUE.jobs.values())
    assert [j.kind for j in jobs] == ["index"] and jobs[0].many == tuple(ids)   # one upsert, no read


# --------------------------------------------------------------------------- step 0


def test_targeted_upsert_touches_only_the_named_episode(tmp_path):
    b = tmp_path / "bank"
    _episode(b, "ep_2026-10-21_001", "user: the garden plan", processed=True)
    _episode(b, "ep_2026-10-21_002", "user: violin lessons", processed=True)
    idx = vector_index.SqliteVecIndexer(b, embed_fn=_embed, model_name="fake")
    idx.index_episodes()

    def rows():
        import sqlite3
        conn = sqlite3.connect(idx.db_path)
        try:
            return sorted(conn.execute("SELECT key, hash FROM meta_episodes").fetchall())
        finally:
            conn.close()

    before = rows()
    _episode(b, "ep_2026-10-22_001", "user: the alpha harbor deadline moved")
    (b / "episodes" / "ep_2026-10-21_002.md").unlink()   # gone: only Sleep's whole sync removes it
    stats = vector_index.SqliteVecIndexer(b, embed_fn=_embed, model_name="fake").index_episode_stems(
        ["ep_2026-10-22_001"])
    after = rows()
    assert stats["embedded"] == 1 and stats["removed"] == 0
    assert set(before) < set(after)
    hits = vector_index.SqliteVecIndexer(b, embed_fn=_embed, model_name="fake").search_episodes("harbor deadline")
    assert hits[0]["metadata"]["episode_id"] == "ep_2026-10-22_001"


def test_targeted_upsert_never_rebuilds_another_models_table(tmp_path):
    b = tmp_path / "bank"
    _episode(b, "ep_2026-10-21_001", "user: the garden plan", processed=True)
    vector_index.SqliteVecIndexer(b, embed_fn=_embed, model_name="old-model").index_episodes()
    _episode(b, "ep_2026-10-22_001", "user: alpha harbor")
    stats = vector_index.SqliteVecIndexer(b, embed_fn=_embed, model_name="new-model").index_episode_stems(
        ["ep_2026-10-22_001"])
    assert stats.get("skipped") == 1
    assert vector_index.SqliteVecIndexer(b, embed_fn=_embed, model_name="old-model").index_info(
        "episodes")["model"] == "old-model"


def _patch_indexer(monkeypatch, model="fake-device", on_device=True):
    real = vector_index.SqliteVecIndexer
    monkeypatch.setattr(vector_index, "SqliteVecIndexer",
                        lambda path, **kw: real(path, embed_fn=_embed, model_name=model))
    monkeypatch.setattr(vector_index, "runs_on_device", lambda m: on_device)
    from api.services import embedding_models
    monkeypatch.setattr(embedding_models, "pending_switch", lambda *a, **k: None)


def test_index_now_embeds_a_new_conversation(bank, monkeypatch):
    _patch_indexer(monkeypatch)
    assert awake_read.index_now(bank, "ep_2026-10-22_001") == "indexed"
    assert awake_read.index_now(bank, "ep_2026-10-22_001") == "unchanged"


@pytest.mark.parametrize("why", ["sleep", "reindex", "hosted", "demo"])
def test_index_now_holds_back(bank, monkeypatch, why):
    _patch_indexer(monkeypatch, on_device=(why != "hosted"))
    from api.services import demo_guard, embedding_models
    if why == "sleep":
        monkeypatch.setattr(awake_read, "_sleep_running", lambda: True)
    if why == "reindex":
        monkeypatch.setattr(embedding_models, "pending_switch", lambda *a, **k: ("other-model", ["episodes"]))
    if why == "demo":
        demo_guard.write_manifest(bank)
    want = {"sleep": "sleep_running", "reindex": "reindexing", "hosted": "hosted_model", "demo": "demo_bank"}[why]
    assert awake_read.index_now(bank, "ep_2026-10-22_001") == want
    assert not (bank / vector_index.INDEX_DB_FILE).exists()


# --------------------------------------------------------------------------- step 1


class _Engine:
    """The resolved engine stand-in: a plan with a small model, never a real call."""

    def __init__(self):
        self.calls = 0

    async def resolve(self, settings, registry=None, *, user_triggered=True):
        assert user_triggered is False   # ruling 4: an automatic run, judged like a scheduled one
        return settings, "test"


def _stub_extract(calls: list):
    async def extract(episodes, settings, *, stage="extraction", **_kw):
        calls.append((stage, getattr(settings, "agent_model", None)))
        ep = episodes[0]
        quote = "the alpha deadline moved to friday"
        start = ep["content"].index(quote)
        ev = {"episode": ep["id"], "start": start, "end": start + len(quote), "kind": "user", "hash": "h"}
        return [{
            "episode_id": ep["id"], "episode_timestamp": ep["timestamp"], "origin": "claude-code",
            "entities": [{"name": "Alpha Project", "type": "project"}, {"name": "Beta Harbor", "type": "place"}],
            "relationships": [
                {"source": "alpha", "target": "friday", "label": "deadline", "evidence": [ev],
                 "source_episode": ep["id"], "source_episode_timestamp": ep["timestamp"]},
                {"source": "Beta Harbor", "target": "Alpha Project", "label": "hosts", "evidence": [ev],
                 "source_episode": ep["id"], "source_episode_timestamp": ep["timestamp"]},
            ],
        }]
    return extract


@pytest.fixture
def engine(monkeypatch):
    from api.config import Settings
    from api.services import engine_select

    eng = _Engine()
    monkeypatch.setattr(engine_select, "resolve_settings", eng.resolve)
    monkeypatch.setattr(engine_select, "no_engine", lambda s: False)
    return Settings(llm_mode="agent", agent_model="sonnet", agent_disambiguation_model="haiku")


def _git(bank: Path, *args) -> str:
    return subprocess.run(["git", "-C", str(bank), *args], capture_output=True, text=True, check=True).stdout


def test_quick_read_writes_a_provisional_record_and_nothing_else(bank, engine):
    subprocess.run(["git", "init", "-q", str(bank)], check=True)
    _git(bank, "add", "-A")
    _git(bank, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "seed")
    page_before = (bank / "entities" / "alpha-project.md").read_text()
    calls: list = []
    out = asyncio.run(awake_read.quick_read(bank, "ep_2026-10-22_001", settings=engine,
                                            extract=_stub_extract(calls)))
    assert out == "read"
    assert calls == [("quick_read", "haiku")]   # the engine's small model, its own usage stage
    rec = awake_read.load_record(bank, "ep_2026-10-22_001")
    assert [c["subject"] for c in rec["claims"]] == ["alpha-project"]   # only a page that exists
    claim = Claim.from_dict(rec["claims"][0])
    assert claim.evidence and claim.evidence[0].is_span()               # G118 span, not a copy
    assert [h["name"] for h in rec["held"]] == ["Beta Harbor"]          # held for Sleep, never minted
    assert (bank / "entities" / "alpha-project.md").read_text() == page_before
    assert not (bank / "entities" / "beta-harbor.md").exists()
    assert not (bank / "pending_entities.jsonl").exists()
    assert _git(bank, "log", "--oneline").count("\n") == 1               # no commit
    # the same revision is never read twice; a newer one is
    assert asyncio.run(awake_read.quick_read(bank, "ep_2026-10-22_001", settings=engine,
                                             extract=_stub_extract(calls))) == "unchanged"
    assert len(calls) == 1


def test_the_record_is_never_committed(bank, engine):
    assert ".awake" in bank_registry.DERIVED_ARTIFACTS


@pytest.mark.parametrize("why", ["sleep", "processed", "demo", "no_engine"])
def test_quick_read_holds_back(bank, engine, monkeypatch, why):
    from api.services import demo_guard, engine_select
    if why == "sleep":
        monkeypatch.setattr(awake_read, "_sleep_running", lambda: True)
    if why == "processed":
        _episode(bank, "ep_2026-10-22_001", "user: the alpha deadline moved to friday", processed=True)
    if why == "demo":
        demo_guard.write_manifest(bank)
    if why == "no_engine":
        monkeypatch.setattr(engine_select, "no_engine", lambda s: True)
    calls: list = []
    out = asyncio.run(awake_read.quick_read(bank, "ep_2026-10-22_001", settings=engine,
                                            extract=_stub_extract(calls)))
    assert out == {"sleep": "sleep_running", "processed": "processed", "demo": "demo_bank",
                   "no_engine": "no_engine"}[why]
    assert calls == [] and awake_read.load_record(bank, "ep_2026-10-22_001") is None


def test_quick_read_refuses_while_sleep_holds_the_pages(bank, engine, monkeypatch):
    from api.services import write_admission
    calls: list = []
    real = write_admission.holding
    monkeypatch.setattr(write_admission, "holding", lambda: len(calls) > 0 or real())
    out = asyncio.run(awake_read.quick_read(bank, "ep_2026-10-22_001", settings=engine,
                                            extract=_stub_extract(calls)))
    assert out == "admission" and awake_read.load_record(bank, "ep_2026-10-22_001") is None


def test_the_hourly_budget_stops_reads(bank, engine, monkeypatch):
    monkeypatch.setattr(awake_read, "READS_PER_HOUR", 0)
    calls: list = []
    assert asyncio.run(awake_read.quick_read(bank, "ep_2026-10-22_001", settings=engine,
                                             extract=_stub_extract(calls))) == "budget"
    assert calls == []


# --------------------------------------------------------------------------- Sleep settles


def test_settle_counts_confirmed_corrected_dropped_and_removes_the_record(bank, engine):
    calls: list = []
    asyncio.run(awake_read.quick_read(bank, "ep_2026-10-22_001", settings=engine, extract=_stub_extract(calls)))
    rec = awake_read.load_record(bank, "ep_2026-10-22_001")
    provisional = Claim.from_dict(rec["claims"][0])
    # Sleep wrote the same claim id (confirmed) — then another case where it wrote a different object (corrected).
    _page(bank, "alpha-project", "Alpha Project", "A project.", claims=[provisional], aliases=("alpha",))
    _episode(bank, "ep_2026-10-22_001", "user: the alpha deadline moved to friday\n\nassistant: noted, friday it is",
             processed=True)
    assert awake_read.settle(bank, ["ep_2026-10-22_001"]) == {
        "confirmed": 1, "corrected": 0, "dropped": 0, "records": 1}
    assert awake_read.load_record(bank, "ep_2026-10-22_001") is None

    _episode(bank, "ep_2026-10-22_001", "user: the alpha deadline moved to friday\n\nassistant: ok")
    asyncio.run(awake_read.quick_read(bank, "ep_2026-10-22_001", settings=engine, extract=_stub_extract(calls)))
    other = Claim(id="clm_other", text="x", subject="alpha-project", predicate=provisional.predicate,
                  object="saturday", source_episodes=["ep_2026-10-22_001"], evidence=[Evidence()])
    _page(bank, "alpha-project", "Alpha Project", "A project.", claims=[other], aliases=("alpha",))
    _episode(bank, "ep_2026-10-22_001", "user: the alpha deadline moved to friday\n\nassistant: ok", processed=True)
    assert awake_read.settle(bank, ["ep_2026-10-22_001"])["corrected"] == 1


def test_settle_leaves_a_newer_revisions_record(bank, engine):
    calls: list = []
    asyncio.run(awake_read.quick_read(bank, "ep_2026-10-22_001", settings=engine, extract=_stub_extract(calls)))
    assert awake_read.settle(bank, ["ep_2026-10-22_001"])["records"] == 0   # still unread: kept
    assert awake_read.load_record(bank, "ep_2026-10-22_001") is not None


# --------------------------------------------------------------------------- recall


def _recall(monkeypatch, bank, query):
    from _stdio_server import stdio_server

    from api.services import search_index

    mcp = stdio_server()
    search_index.ensure_fresh(bank, wait=True)   # the backend's lifespan warms it; a capture after is read inline
    monkeypatch.setattr(mcp, "get_memory_path", lambda: bank)
    monkeypatch.setattr(mcp.mcp_tools, "_leann_search_entities", lambda *a, **k: [])
    monkeypatch.setattr(mcp.mcp_tools, "_leann_search_episodes", lambda *a, **k: [])
    return mcp.handle_recall(query)


def test_recall_finds_an_unread_conversation_by_its_words_and_says_so(bank, monkeypatch):
    out = _recall(monkeypatch, bank, "deadline friday")
    assert "ep_2026-10-22_001" in out
    assert "not yet read by Sleep" in out
    assert "alpha deadline moved to friday" in out


def test_recall_does_not_label_a_read_conversation(bank, monkeypatch):
    _episode(bank, "ep_2026-10-22_001", "user: the alpha deadline moved to friday", processed=True)
    out = _recall(monkeypatch, bank, "deadline friday")
    assert "ep_2026-10-22_001" in out and "not yet read by Sleep" not in out


def test_recall_shows_provisional_claims_until_sleep_reads_the_conversation(bank, engine, monkeypatch):
    calls: list = []
    asyncio.run(awake_read.quick_read(bank, "ep_2026-10-22_001", settings=engine, extract=_stub_extract(calls)))
    out = _recall(monkeypatch, bank, "alpha project")
    assert "Not yet read by Sleep (provisional" in out
    assert "[[Alpha Project]] alpha deadline friday" in out
    _episode(bank, "ep_2026-10-22_001", "user: the alpha deadline moved to friday", processed=True)
    assert "Not yet read by Sleep (provisional" not in _recall(monkeypatch, bank, "alpha project")


def test_recall_with_many_records_stays_in_budget(bank, engine, monkeypatch):
    from api.services import mcp_tools
    rec = {"episode": "", "revision": "r", "read_at": "2026-10-22T10:00:00Z", "held": [{"name": "Alpha x" * 50}],
           "claims": [{"id": f"clm_{i}", "subject": "alpha-project", "text": "alpha " + "word " * 200,
                       "predicate": "p", "object": "o"} for i in range(40)]}
    for i in range(50):
        ep = f"ep_2026-10-22_{i + 100:03d}"
        _episode(bank, ep, "user: alpha")
        awake_read._write_record(bank, ep, {**rec, "episode": ep})
    out = _recall(monkeypatch, bank, "alpha")
    assert len(out) <= mcp_tools.RECALL_BUDGET + 2_000   # fenced markers ride outside the budgeted text
    block = out.split("Not yet read by Sleep (provisional")[1]
    assert block.count("\n- [[") <= 12
