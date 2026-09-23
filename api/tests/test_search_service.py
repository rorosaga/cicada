"""G136 — `GET /search` and `search_service` (round-3 design §3.9, §3.10).

Hermetic: a synthetic bank under tmp_path (alpha-project, bob-example,
example.com), a deterministic fake embedder where vectors are needed, no
network, no real model.
"""
from __future__ import annotations

import asyncio
import importlib
import time

import numpy as np
import pytest
from loguru import logger

from api.services import bank_index, evidence, markdown_parser, providers, search_index, search_service, text_fold

EP_PORTO = "ep_2026-09-01_002"


@pytest.fixture(autouse=True)
def _fresh_state():
    bank_index.invalidate()
    search_index.reset()
    yield
    search_index.reset()
    bank_index.invalidate()


def _entity(memory, eid, *, name, body="## Summary\nA synthetic fixture.\n", **fm):
    base = {"name": name, "type": "concept", "status": "active", "confidence": 0.5, "tags": [], "aliases": []}
    base.update(fm)
    markdown_parser.write(memory / "entities" / f"{eid}.md", base, body)


def _bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    porto_body = "user: I moved to Porto last spring\nassistant: noted"
    markdown_parser.write(memory / "episodes" / f"{EP_PORTO}.md",
                          {"id": EP_PORTO, "title": "Moving notes", "timestamp": "2026-09-01T10:00:00+00:00",
                           "session_id": "ses_2026-09-01_porto001", "harness": "codex"}, porto_body)
    text = evidence.source_text(memory, EP_PORTO)
    start = text.find("I moved to Porto")
    span = {"episode": EP_PORTO, "start": start, "end": start + len("I moved to Porto"),
            "kind": "user", "hash": evidence.body_hash(text)}
    claims = (
        "\n```claims\n"
        "- id: clm_porto\n  text: \"bob-example lives in Porto\"\n  subject: bob-example\n"
        "  predicate: lives_in\n  object: Porto\n  confidence: 0.9\n"
        f"  evidence:\n  - {{episode: {span['episode']}, start: {span['start']}, end: {span['end']}, kind: user, hash: {span['hash']}}}\n"
        "- id: clm_lisbon\n  text: \"bob-example lives in Lisbon\"\n  subject: bob-example\n"
        "  predicate: lives_in\n  object: Lisbon\n  valid_to: '2026-05-01'\n  superseded_by: clm_porto\n"
        "```\n"
    )
    _entity(memory, "bob-example", name="Bob Example", type="person", body="## Summary\nA friend.\n" + claims)
    _entity(memory, "alpha-project", name="Alpha Project", type="project", aliases=["Project A"], tags=["infra"],
            body="## Summary\nThe first project.\n\n## Key Facts\nUses sqlite-vec for retrieval.\n")
    _entity(memory, "alpha-archive", name="Alpha Archive", status="archived")
    _entity(memory, "zurich-office", name="Zürich Office", type="location", aliases=["HQ"])
    _entity(memory, "whiskers", name="Whiskers", body="## Summary\nA cat that sleeps all day.\n")
    _entity(memory, "media-wikiskill", name="WikiSkill paper", type="media",
            media={"url": "https://example.com/abs/2608.27454", "site": "example.com", "media_type": "url"},
            paper={"authors": ["Ada Example", "Bo Sample"], "arxiv_id": "2608.27454"})
    filler = "\n".join(f"user: unrelated line {i}" for i in range(60))
    markdown_parser.write(memory / "episodes" / "ep_2026-09-02_001.md",
                          {"id": "ep_2026-09-02_001", "title": "Index choice", "harness": "claude-code",
                           "timestamp": "2026-09-02T09:00:00+00:00",
                           "session_id": "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"},
                          f"{filler}\nassistant: we moved the index to sqlite-vec so search is fast\n{filler}")
    markdown_parser.write(memory / "inbox" / "inbox-001.md",
                          {"kind": "decay", "status": "pending", "entity_id": "alpha-project",
                           "entity_name": "Alpha Project", "created_date": "2026-08-01"}, "ctx")
    markdown_parser.write(memory / "inbox" / "inbox-002.md",
                          {"kind": "conflict", "status": "pending", "entity_id": "alpha-project",
                           "entity_name": "Alpha Project", "question": "Which alpha database?",
                           "remind_after": "2099-01-01", "created_date": "2026-08-01"}, "ctx")
    markdown_parser.write(memory / "inbox" / "inbox-003.md",
                          {"kind": "conflict", "status": "pending", "entity_id": "alpha-archive",
                           "entity_name": "Alpha Archive", "question": "Is alpha archive done?",
                           "created_date": "2026-08-01"}, "ctx")
    search_index.rebuild(memory)
    return memory


def _search(memory, q, **kw):
    kw.setdefault("freshness_ttl_s", 0)
    return search_service.search(memory, q, **kw)


def _by_kind(resp, kind):
    return [h for h in resp.results if h.kind == kind]


# --- pure helpers ---------------------------------------------------------------


def test_parse_kinds_accepts_palette_names_and_keeps_group_order():
    assert search_service.parse_kinds("inbox,papers,beliefs,conversations,entities") == [
        "entity", "claim", "episode", "media", "inbox"]
    assert search_service.parse_kinds(None) == ["entity"]
    assert search_service.parse_kinds(None, "entities,claims") == ["entity", "claim"], "legacy `indexes`"
    assert search_service.parse_kinds("episode", "entities") == ["episode"], "`kinds` wins"
    assert search_service.parse_kinds("nonsense") == ["entity"]


def test_rrf_fuse_matches_the_mcp_helper_exactly():
    mcp = importlib.import_module("mcp.server")
    semantic = [{"entity_id": "a"}, {"entity_id": "b"}, {"entity_id": "c"}]
    keyword = [{"entity_id": "b"}, {"entity_id": "a"}, {"id": "d"}]
    assert search_service.rrf_fuse(semantic, keyword) == mcp._rrf_fuse(semantic, keyword)


def test_quick_score_orders_exact_then_prefix_then_word_start():
    fields = lambda name: [(name, 1.0, "name")]  # noqa: E731
    exact, _ = search_service.quick_score(["alpha"], fields("Alpha"))
    prefix, _ = search_service.quick_score(["alpha"], fields("Alphabet soup"))
    word, _ = search_service.quick_score(["alpha"], fields("Project alpha"))
    body, label = search_service.quick_score(["alpha"], fields("Unrelated"))
    assert exact > prefix > word > body and label == "body"
    assert search_service.quick_score(["hq"], [("Zürich Office", 1.0, "name"), ("HQ", 0.9, "alias")])[1] == "alias"


def test_snippet_window_centres_on_the_match_and_offsets_slice_the_snippet():
    text = ("lorem ipsum " * 40) + "the sqlite-vec index " + ("dolor sit " * 40)
    snippet, offsets = search_service.snippet_window(text, ["sqlite"])
    assert len(snippet) <= search_service.SNIPPET_CHARS + 2
    assert snippet.startswith("…") and snippet.endswith("…")
    assert [snippet[s:e] for s, e in offsets] == ["sqlite"]


# --- the service ---------------------------------------------------------------------


def test_default_call_is_entities_only_in_the_legacy_shape(tmp_path):
    memory = _bank(tmp_path)
    resp = _search(memory, "alpha")
    assert {h.kind for h in resp.results} == {"entity"}
    assert resp.results[0].id == "alpha-project", "live exact-prefix name first"
    assert resp.results[-1].id == "alpha-archive", "archived pages rank after live ones"
    assert resp.totals == {"entity": 2}
    assert resp.index_state == "ready"


def test_kinds_are_honoured_and_totals_are_per_kind(tmp_path):
    memory = _bank(tmp_path)
    resp = _search(memory, "alpha", kinds=search_service.KINDS, mode="prefix")
    kinds = [h.kind for h in resp.results]
    assert kinds == sorted(kinds, key=search_service.KINDS.index), "grouped in the fixed order"
    assert [h.id for h in _by_kind(resp, "inbox")] == ["inbox-001"], "deferred and subject-gone items are not served"
    assert _by_kind(resp, "inbox")[0].name == "Still tracking Alpha Project?"
    assert resp.totals["inbox"] == 1
    assert set(resp.totals) == {"entity", "claim", "episode", "media", "inbox"}


def test_aliases_and_diacritics_find_the_page_and_say_why(tmp_path):
    memory = _bank(tmp_path)
    hq = _search(memory, "hq", mode="prefix").results
    assert [h.id for h in hq] == ["zurich-office"]
    assert hq[0].matched_field == "alias" and hq[0].subtitle == "HQ"
    assert [h.id for h in _search(memory, "zurich", mode="prefix").results] == ["zurich-office"]


def test_media_is_its_own_group_only_when_asked_for(tmp_path):
    memory = _bank(tmp_path)
    legacy = _search(memory, "wikiskill", mode="prefix")
    assert [(h.kind, h.id) for h in legacy.results] == [("entity", "media-wikiskill")]
    split = _search(memory, "wikiskill", kinds=("entity", "media"), mode="prefix")
    assert [(h.kind, h.id) for h in split.results] == [("media", "media-wikiskill")]
    by_author = _search(memory, "sample", kinds=("media",), mode="prefix").results
    assert by_author[0].subtitle == "Ada Example, Bo Sample"
    assert _search(memory, "2608.27454", kinds=("media",), mode="prefix").results[0].id == "media-wikiskill"


def test_claim_hits_carry_their_evidence_span_and_history_ranks_after_the_present(tmp_path):
    memory = _bank(tmp_path)
    claims = _by_kind(_search(memory, "bob lives", kinds=("claim",), mode="prefix"), "claim")
    assert [c.id for c in claims] == ["clm_porto", "clm_lisbon"]
    porto, lisbon = claims
    assert porto.subject_id == "bob-example" and porto.subtitle == "Bob Example"
    text = evidence.source_text(memory, porto.episode_id)
    assert text[porto.start:porto.end] == "I moved to Porto"
    assert porto.hash == evidence.body_hash(text) and porto.evidence_kind == "user"
    assert lisbon.valid_to == "2026-05-01" and lisbon.superseded_by == "clm_porto"


def test_a_page_is_reached_through_one_of_its_claims(tmp_path):
    memory = _bank(tmp_path)
    hits = _search(memory, "porto", mode="prefix").results
    assert [h.id for h in hits] == ["bob-example"]
    assert hits[0].matched_field == "claim" and hits[0].subtitle == "bob-example lives in Porto"
    assert _search(memory, "lisbon", mode="prefix").results == [], "a superseded claim never leads to its subject"


def test_episode_hits_carry_a_verifiable_span_around_the_match(tmp_path):
    memory = _bank(tmp_path)
    [hit] = _by_kind(_search(memory, "sqlite vec", kinds=("episode",), mode="prefix"), "episode")
    text = evidence.source_text(memory, hit.episode_id)
    assert "sqlite-vec" in text[hit.start:hit.end]
    assert text[hit.start:hit.end].startswith("assistant:"), "the span is the matching line"
    assert hit.hash == evidence.body_hash(text) and hit.evidence_kind == "assistant"
    assert hit.conversation_id == "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b" and hit.harness == "claude-code"
    assert [hit.snippet[s:e] for s, e in hit.snippet_offsets] == ["sqlite", "vec"]
    title = _by_kind(_search(memory, "index choice", kinds=("episode",), mode="prefix"), "episode")[0]
    assert title.matched_field == "name" and title.start is None and title.hash is None, "a title match claims no span"


def test_prefix_mode_never_builds_an_indexer_or_touches_the_embed_cache(tmp_path, monkeypatch):
    memory = _bank(tmp_path)

    class Tripwire(dict):
        def __getitem__(self, key):
            raise AssertionError("prefix mode touched _EMBED_CACHE")

        get = __contains__ = __setitem__ = __getitem__

    class NoIndexer:
        def __init__(self, *a, **k):
            raise AssertionError("prefix mode built a vector indexer")

    monkeypatch.setattr(providers, "_EMBED_CACHE", Tripwire())
    monkeypatch.setattr("api.services.vector_index.SqliteVecIndexer", NoIndexer)
    resp = _search(memory, "alpha", kinds=search_service.KINDS, mode="prefix")
    assert resp.mode == "prefix" and resp.results


def _fake_embed(texts, *, is_query=False):
    """Deterministic: "cat" and "feline" share a direction (the semantic
    link no lexical index can see), "alpha" has its own, every vector has a
    small constant so none is zero."""
    rows = []
    for text in texts:
        words = set(text_fold.words(text))
        v = np.array([1.0 if words & {"cat", "feline"} else 0.0,
                      1.0 if "alpha" in words else 0.0, 0.1], dtype=np.float32)
        rows.append(v / np.linalg.norm(v))
    return np.stack(rows)


def _vectors(memory):
    from api.services.vector_index import SqliteVecIndexer

    indexer = SqliteVecIndexer(memory, embed_fn=_fake_embed)
    indexer.index_entities()
    indexer.index_claims()
    indexer.index_episodes()


def test_hybrid_fuses_the_stored_vectors_and_labels_semantic_only_rows(tmp_path):
    memory = _bank(tmp_path)
    _vectors(memory)
    resp = _search(memory, "feline", mode="hybrid", embed_fn=_fake_embed)
    assert resp.mode == "hybrid"
    assert resp.results[0].id == "whiskers" and resp.results[0].matched_field == "semantic"
    assert resp.totals == {"entity": 0}, "semantic neighbours are ranked, never counted"


def test_hybrid_embeds_the_query_once_for_every_kind(tmp_path):
    memory = _bank(tmp_path)
    _vectors(memory)
    calls = []

    def counting(texts, *, is_query=False):
        calls.append(is_query)
        return _fake_embed(texts, is_query=is_query)

    _search(memory, "alpha", kinds=search_service.KINDS, mode="hybrid", embed_fn=counting)
    assert calls.count(True) == 1


def test_hybrid_keeps_history_after_every_current_claim(tmp_path):
    """G136 R10 in hybrid too: the vector claims index holds current claims
    only, so a superseded claim can only arrive lexically — and RRF alone
    would tie it with the first semantic neighbour. History sinks below
    every current claim before the cut, like the archived tier for pages."""
    memory = _bank(tmp_path)
    _vectors(memory)
    claims = _by_kind(_search(memory, "lisbon", kinds=("claim",), mode="hybrid", embed_fn=_fake_embed), "claim")
    assert [c.id for c in claims] == ["clm_porto", "clm_lisbon"]
    assert claims[0].matched_field == "semantic" and claims[1].valid_to == "2026-05-01"


def test_hybrid_without_a_vector_index_says_lexical(tmp_path):
    memory = _bank(tmp_path)
    resp = _search(memory, "alpha", mode="hybrid")
    assert resp.mode == "lexical" and resp.results[0].id == "alpha-project"


def test_while_the_index_builds_pages_come_from_the_frontmatter_cache(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setattr(search_index, "ensure_fresh", lambda *a, **k: "building")
    _search(memory, "hq", mode="prefix")  # warm bank_index
    parses = bank_index.parse_count
    resp = _search(memory, "hq", kinds=("entity", "claim", "episode"), mode="prefix")
    assert bank_index.parse_count == parses, "no page is parsed per request (R6 §4.2)"
    assert [h.id for h in resp.results] == ["zurich-office"]
    assert resp.index_state == "building" and resp.totals == {"entity": 1}


def test_a_broken_index_file_degrades_to_the_fallback_not_a_500(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setattr(search_index, "ensure_fresh", lambda *a, **k: "ready")
    # A hand-edited page the fallback must read without a 500 (it builds a
    # meta for every page, matching or not).
    _entity(memory, "odd-page", name="Odd Page", confidence="high")
    (memory / search_index.DB_FILE).write_bytes(b"garbage" * 1000)
    for suffix in ("-wal", "-shm"):
        (memory / f"{search_index.DB_FILE}{suffix}").unlink(missing_ok=True)
    resp = _search(memory, "alpha", mode="prefix")
    assert resp.index_state == "unavailable" and resp.results[0].id == "alpha-project"


def test_the_query_is_never_logged(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    records: list[str] = []
    sink = logger.add(lambda msg: records.append(msg.record["message"]), level="DEBUG")
    try:
        _search(memory, "zebracorn alpha", kinds=search_service.KINDS, mode="hybrid")
        monkeypatch.setattr(search_index, "ensure_fresh", lambda *a, **k: "ready")
        (memory / search_index.DB_FILE).write_bytes(b"garbage" * 1000)
        _search(memory, "zebracorn alpha", mode="prefix")
    finally:
        logger.remove(sink)
    assert records, "the failure path logged something"
    assert not any("zebracorn" in r for r in records)


def test_the_access_log_never_carries_the_query():
    """K9 at the HTTP layer (G136 R22): uvicorn's access log writes the
    request line with its query string; the filter `api.main` attaches
    strips it for the two query-bearing paths and leaves every other line."""
    import logging

    from api import main  # noqa: F401  (importing it attaches the filter)

    access = logging.getLogger("uvicorn.access")
    lines: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())

    handler = Capture(level=logging.INFO)
    saved = (access.level, access.disabled)
    access.addHandler(handler)
    access.setLevel(logging.INFO)
    access.disabled = False
    try:
        for path in ("/search?q=zebracorn&mode=prefix", "/conversations/recent?limit=5&q=zebracorn",
                     "/graph?bank=alpha"):
            access.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET", path, "1.1", 200)
    finally:
        access.removeHandler(handler)
        access.setLevel(saved[0])
        access.disabled = saved[1]
    assert lines == [
        '127.0.0.1:5000 - "GET /search?… HTTP/1.1" 200',
        '127.0.0.1:5000 - "GET /conversations/recent?… HTTP/1.1" 200',
        '127.0.0.1:5000 - "GET /graph?bank=alpha HTTP/1.1" 200',
    ]


def test_mcp_legs_come_back_in_the_rrf_shape(tmp_path):
    memory = _bank(tmp_path)
    assert search_service.lexical_entity_hits(memory, "hq")[0] == {
        "entity_id": "zurich-office", "source": "keyword",
        "score": pytest.approx(search_service.lexical_entity_hits(memory, "hq")[0]["score"])}
    assert search_service.lexical_entity_hits(memory, "porto") == [], "claim-reached rows are the claim leg's"
    assert search_service.claim_subject_hits(memory, "porto") == [
        {"entity_id": "bob-example", "source": "claim", "score": 0.0}]


# --- the router --------------------------------------------------------------------------


def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app), memory


def test_router_keeps_the_old_call_shape_and_speaks_camel_case(tmp_path, monkeypatch):
    client, _memory = _client(tmp_path, monkeypatch)
    old = client.get("/search", params={"q": "alpha", "top_k": 8, "indexes": "entities"})
    assert old.status_code == 200, old.text
    body = old.json()
    first = body["results"][0]
    assert {"id", "name", "type", "status", "confidence", "score", "snippet"} <= set(first)
    assert first["kind"] == "entity" and "snippetOffsets" in first and "matchedField" in first
    assert body["totals"] == {"entity": 2} and body["indexState"] == "ready"
    new = client.get("/search", params={"q": "sqlite", "kinds": "entity,claim,episode,media", "mode": "prefix",
                                        "per_kind": 5}).json()
    assert {h["kind"] for h in new["results"]} == {"entity", "episode"}
    ep = next(h for h in new["results"] if h["kind"] == "episode")
    assert {"episodeId", "conversationId", "start", "end", "hash", "evidenceKind"} <= set(ep)


def test_router_validates_mode_and_per_kind(tmp_path, monkeypatch):
    client, _memory = _client(tmp_path, monkeypatch)
    assert client.get("/search", params={"q": "alpha", "mode": "fuzzy"}).status_code == 422
    assert client.get("/search", params={"q": "alpha", "per_kind": 21}).status_code == 422


def test_search_does_not_block_the_event_loop(tmp_path, monkeypatch):
    """R6 §4.2: /search was blocking work inside `async def`. With the body in
    the threadpool, a concurrent /healthz answers while a slow search runs."""
    import httpx

    from api import main
    from api.routers import search as search_router

    _client(tmp_path, monkeypatch)

    def slow(*a, **k):
        time.sleep(0.6)
        return search_service.SearchResponse(results=[])

    monkeypatch.setattr(search_router.search_service, "search", slow)

    async def run():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            started = time.perf_counter()
            pending = asyncio.create_task(ac.get("/search", params={"q": "alpha"}))
            await asyncio.sleep(0.05)
            health = await ac.get("/healthz")
            healthz_after = time.perf_counter() - started
            return health, await pending, healthz_after

    health, slow_resp, healthz_after = asyncio.run(run())
    assert health.status_code == 200 and slow_resp.status_code == 200
    assert healthz_after < 0.5
