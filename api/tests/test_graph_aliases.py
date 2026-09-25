"""G136 S6 — `GraphNode.aliases` on `/graph`, measured before it ships (plan R-SU23).

The design (round-3 §3.9 item 5) gates the field on its payload cost: `/graph`
is the app's largest snapshot. The fixture is pessimistic on purpose — every
one of 2,000 nodes carries aliases and there are no edges to dilute the ratio —
generated from a fixed seed and made-up syllables (no names, the same bank on
every machine; the G136 R18 rule). Run with `-s` to see the numbers.
"""
from __future__ import annotations

import json
import random

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.models.schemas import GraphResponse
from api.routers import graph as graph_router
from api.services import bank_index, graph_builder, markdown_parser, sync_service

N_NODES = 2000
_SYLLABLES = ["ka", "lo", "mi", "ra", "tu", "sen", "vel", "dor", "qui", "zan",
              "pe", "ri", "mo", "na", "tho", "gar", "lin", "bex", "sol", "fen"]


def _word(rng: random.Random) -> str:
    return "".join(rng.choice(_SYLLABLES) for _ in range(rng.randint(2, 4)))


def _bank(root, aliases_per_node: int):
    memory = root / f"aliases-{aliases_per_node}"
    (memory / "entities").mkdir(parents=True)
    rng = random.Random(7)
    types = ["project", "person", "concept", "tool"]
    for i in range(N_NODES):
        prose = " ".join(" ".join(_word(rng) for _ in range(12)).capitalize() + "." for _ in range(6))
        markdown_parser.write(
            memory / "entities" / f"e-{i}.md",
            {"name": f"{_word(rng)} {_word(rng)} {i}", "type": types[i % 4], "status": "active",
             "confidence": 0.5, "tags": [_word(rng)], "aliases": [_word(rng) for _ in range(aliases_per_node)]},
            f"## Summary\n{prose}\n",
        )
    return memory


def _build(memory) -> GraphResponse:
    bank_index.invalidate()
    graph_builder._CACHE.update({"key": None, "value": None})   # keyed on mtimes, not paths
    return graph_builder.build_graph(memory)


def _wire_bytes(resp: GraphResponse, *, with_aliases: bool) -> int:
    """What `GET /graph` sends: camelCase, compact separators (Starlette's JSONResponse)."""
    exclude = None if with_aliases else {"nodes": {"__all__": {"aliases"}}}
    body = resp.model_dump(mode="json", by_alias=True, exclude=exclude)
    return len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode())


def _growth(resp: GraphResponse) -> tuple[int, int, float]:
    base = _wire_bytes(resp, with_aliases=False)
    grown = _wire_bytes(resp, with_aliases=True)
    return base, grown, (grown - base) / base


def test_two_aliases_on_every_node_grow_the_graph_payload_by_at_most_ten_percent(tmp_path):
    base, grown, growth = _growth(_build(_bank(tmp_path, 2)))
    print(f"\nG136 S6 /graph, {N_NODES} nodes x 2 aliases: {base:,} -> {grown:,} bytes (+{growth:.1%})")
    assert grown > base, "the field must be on the wire to be measured"
    assert growth <= 0.10


def test_aliases_are_capped_at_eight_and_the_worst_case_is_recorded(tmp_path):
    resp = _build(_bank(tmp_path, 12))
    assert max(len(node.aliases) for node in resp.nodes) == graph_builder.MAX_NODE_ALIASES
    base, grown, growth = _growth(resp)
    print(f"\nG136 S6 /graph at the cap, {N_NODES} nodes x 8 aliases: {base:,} -> {grown:,} bytes (+{growth:.1%})")


def test_node_aliases_are_strings_only_blank_free_and_ordered():
    assert graph_builder.node_aliases({"aliases": ["alpha", " ", 7, True, None, "beta"]}) == ["alpha", "7", "beta"]
    assert graph_builder.node_aliases({"aliases": "alpha"}) == ["alpha"]
    assert graph_builder.node_aliases({}) == []
    assert graph_builder.node_aliases({"aliases": {"a": 1}}) == []


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    graph_builder._CACHE.update({"key": None, "value": None})
    (tmp_path / "entities").mkdir()
    markdown_parser.write(tmp_path / "entities" / "alpha-project.md",
                          {"name": "alpha-project", "type": "project", "aliases": ["alpha"]}, "About alpha-project.")
    with TestClient(main.app) as c:
        yield c, tmp_path
    config.get_settings.cache_clear()


def test_graph_serves_aliases_and_its_etag_moves_once_for_the_new_shape(client):
    c, mem = client
    r = c.get("/graph")
    node = next(n for n in r.json()["nodes"] if n["id"] == "alpha-project")
    assert node["aliases"] == ["alpha"]
    default_extra = "None|None|0.0|None|True|False"
    before = sync_service.etag_for(mem, "entities", "edges", "hubs", "inbox", "logos", extra=default_extra)
    assert r.headers["etag"] != before, "a pre-S6 client gets one 200, never a 304 into an alias-less cache"
    assert r.headers["etag"] == sync_service.etag_for(
        mem, "entities", "edges", "hubs", "inbox", "logos", extra=f"{default_extra}|{graph_router.NODE_SHAPE}")
