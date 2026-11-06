"""ROR-135 — a book's node carries its authors (`byline`) for the graph's hover card; nothing else does."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.routers import graph as graph_router
from api.services import bank_index, graph_builder, logo_service, markdown_parser


def _reset():
    bank_index.invalidate()
    graph_builder._CACHE.update({"key": None, "value": None})


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = tmp_path / "banks" / "work"
    (memory / "entities").mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    pages = {
        "alpha-book": ({"name": "Alpha Book", "type": "media", "media": {"kind": "book"},
                        "book": {"title": "Alpha Book", "authors": ["Author One", "Author Two"]}}, "## Summary\nA book.\n"),
        "no-author-book": ({"name": "No Author", "type": "media", "media": {"kind": "book"}, "book": {"title": "No Author"}},
                           "## Summary\nA book.\n"),
        "a-video": ({"name": "A video", "type": "media", "media": {"kind": "video"}, "book": {"authors": ["Not Shown"]}},
                    "## Summary\nA video.\n"),
        "bob-example": ({"name": "Bob Example", "type": "person"}, "## Summary\nA person.\n"),
    }
    for eid, (fm, body) in pages.items():
        markdown_parser.write(memory / "entities" / f"{eid}.md", fm, body)
    monkeypatch.setattr(logo_service, "cached_ids", lambda bank: set())
    monkeypatch.setattr(logo_service, "missed_ids", lambda bank: {})
    config.get_settings.cache_clear()
    _reset()
    yield memory
    config.get_settings.cache_clear()
    _reset()


def test_only_a_book_with_authors_has_a_byline(bank):
    nodes = {n.id: n for n in graph_builder.build_graph(bank).nodes}
    assert nodes["alpha-book"].byline == "Author One, Author Two"
    assert nodes["no-author-book"].byline is None and nodes["a-video"].byline is None and nodes["bob-example"].byline is None


def test_the_wire_omits_an_absent_byline_and_the_shape_names_it(bank):
    with TestClient(main.app) as c:
        by_id = {n["id"]: n for n in c.get("/graph").json()["nodes"]}
    assert by_id["alpha-book"]["byline"] == "Author One, Author Two"
    assert "byline" not in by_id["bob-example"] and "byline" not in by_id["a-video"]
    assert "+byline" in graph_router.NODE_SHAPE and graph_router.NODE_SHAPE.endswith("+source-links")


def test_a_new_author_moves_the_node_hash_and_a_long_list_is_capped(bank):
    before = {n.id: n.content_hash for n in graph_builder.build_graph(bank).nodes}["alpha-book"]
    page = bank / "entities" / "alpha-book.md"
    parsed = markdown_parser.parse(page)
    fm, body = parsed.frontmatter, parsed.body
    fm["book"]["authors"] = [f"Author Number {i}" for i in range(30)]
    markdown_parser.write(page, fm, body)
    _reset()
    node = {n.id: n for n in graph_builder.build_graph(bank).nodes}["alpha-book"]
    assert node.content_hash != before
    assert len(node.byline) <= graph_builder.BYLINE_MAX and node.byline.endswith("…")
