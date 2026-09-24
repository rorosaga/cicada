"""C11 on `/graph` and `GET /entities/{id}` (plan R-PE5): the resolved picture, its rung, the node's last mention, the
shape bump, the hash fold — and what it costs the app's largest payload, measured the G136 S6 way."""
from __future__ import annotations

import json
import random

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.routers import graph as graph_router
from api.services import bank_index, graph_builder, logo_service, markdown_parser, sync_service

UPLOAD = {"kind": "upload", "sha": "3f9a1c0b2d4e", "ext": "jpg", "added": "2026-09-24"}


def _reset():
    bank_index.invalidate()
    graph_builder._CACHE.update({"key": None, "value": None})   # keyed on mtimes, not on the patched logo index


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = tmp_path / "banks" / "work"
    (memory / "entities").mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    pages = {
        "bob-example": ({"name": "Bob Example", "type": "person", "last_referenced": "2026-09-20", "picture": UPLOAD},
                        "## Summary\nRuns the lab.\n"),
        "acme": ({"name": "Acme", "type": "company", "last_referenced": "2026-09-01"}, "## Summary\nA client.\n"),
        "video-example": ({"name": "A robot arm video", "type": "media", "last_referenced": "2026-09-19",
                           "media": {"url": "https://video.example.com/v/1", "media_type": "youtube",
                                     "thumbnail": "https://img.example.com/1.jpg"}}, "## Summary\nA video.\n"),
        "alpha-project": ({"name": "Alpha Project", "type": "project"}, "## Summary\nA side project.\n"),
    }
    for eid, (fm, body) in pages.items():
        markdown_parser.write(memory / "entities" / f"{eid}.md", fm, body)
    monkeypatch.setattr(logo_service, "cached_ids", lambda bank: {"acme"})
    monkeypatch.setattr(logo_service, "missed_ids", lambda bank: {})
    config.get_settings.cache_clear()
    _reset()
    yield memory
    config.get_settings.cache_clear()
    _reset()


def _nodes(memory):
    return {n.id: n for n in graph_builder.build_graph(memory).nodes}


def test_every_node_carries_its_resolved_picture_and_last_mention(bank):
    nodes = _nodes(bank)
    assert (nodes["bob-example"].picture, nodes["bob-example"].picture_source) == \
        ("/entities/bob-example/picture?v=3f9a1c0b2d4e", "upload")
    assert (nodes["acme"].picture, nodes["acme"].picture_source) == ("/entities/acme/logo", "logo")
    assert (nodes["video-example"].picture, nodes["video-example"].picture_source) == \
        ("https://img.example.com/1.jpg", "thumbnail")
    assert nodes["alpha-project"].picture is None and nodes["alpha-project"].picture_source is None
    assert nodes["bob-example"].last_referenced == "2026-09-20" and nodes["alpha-project"].last_referenced is None


def test_the_wire_omits_an_absent_picture_and_names_the_new_shape(bank):
    with TestClient(main.app) as c:
        r = c.get("/graph")
    by_id = {n["id"]: n for n in r.json()["nodes"]}
    assert "picture" not in by_id["alpha-project"] and "pictureSource" not in by_id["alpha-project"]
    assert by_id["bob-example"]["pictureSource"] == "upload" and by_id["bob-example"]["lastReferenced"] == "2026-09-20"
    assert "pictures" in graph_router.NODE_SHAPE and "aliases" in graph_router.NODE_SHAPE, "the shape tag is cumulative"
    default_extra = "None|None|0.0|None|True|False"
    old = sync_service.etag_for(bank, "entities", "edges", "hubs", "inbox", "logos",
                                extra=f"{default_extra}|aliases+f1-facets")
    assert r.headers["etag"] != old, "an app holding the pre-picture graph gets one 200, never a 304"


def test_a_new_picture_moves_the_node_hash(bank):
    before = _nodes(bank)["alpha-project"].content_hash
    page = bank / "entities" / "alpha-project.md"
    fm = markdown_parser.parse(page).frontmatter
    fm["picture"] = {"kind": "initials", "added": "2026-09-24"}
    markdown_parser.write(page, fm, "## Summary\nA side project.\n")
    _reset()
    after = _nodes(bank)["alpha-project"]
    assert (after.picture_source, after.picture) == ("initials", None)
    assert after.content_hash != before


def test_a_logo_known_to_miss_is_not_offered(bank, monkeypatch):
    monkeypatch.setattr(logo_service, "cached_ids", lambda bank: set())
    monkeypatch.setattr(logo_service, "missed_ids", lambda bank: {"acme": 9e12})
    _reset()
    assert _nodes(bank)["acme"].picture is None


def test_the_entity_carries_its_picture_and_the_twins_inputs(bank):
    with TestClient(main.app) as c:
        person = c.get("/entities/bob-example").json()
        project = c.get("/entities/alpha-project").json()
    assert person["picture"] == "/entities/bob-example/picture?v=3f9a1c0b2d4e" and person["pictureSource"] == "upload"
    assert person["pictureInputs"] == {"type": "person", "choice": "upload", "uploadSha": "3f9a1c0b2d4e",
                                       "contactsSha": None, "logo": False, "thumbnail": None}
    assert project["picture"] is None and project["pictureSource"] is None
    assert project["pictureInputs"]["type"] == "project"


N_NODES = 2000
_SYLLABLES = ["ka", "lo", "mi", "ra", "tu", "sen", "vel", "dor", "qui", "zan",
              "pe", "ri", "mo", "na", "tho", "gar", "lin", "bex", "sol", "fen"]


def _word(rng: random.Random) -> str:
    return "".join(rng.choice(_SYLLABLES) for _ in range(rng.randint(2, 4)))


def _size(body) -> int:
    return len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode())


def test_pictures_and_last_mentions_grow_the_graph_payload_by_at_most_ten_percent(tmp_path, monkeypatch):
    """Pessimistic like G136 S6's fixture: every node carries `lastReferenced`, one in ten an upload, no edges to
    dilute the ratio, made-up syllables from a fixed seed. Run with `-s` to see the numbers."""
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = tmp_path / "pictures-payload"
    (memory / "entities").mkdir(parents=True)
    rng = random.Random(7)
    types = ["project", "person", "concept", "tool"]
    for i in range(N_NODES):
        prose = " ".join(" ".join(_word(rng) for _ in range(12)).capitalize() + "." for _ in range(6))
        fm = {"name": f"{_word(rng)} {_word(rng)} {i}", "type": types[i % 4], "status": "active", "confidence": 0.5,
              "tags": [_word(rng)], "last_referenced": f"2026-09-{1 + i % 28:02d}"}
        if i % 10 == 0:
            fm["picture"] = {"kind": "upload", "sha": f"{i:012x}", "ext": "jpg", "added": "2026-09-24"}
        markdown_parser.write(memory / "entities" / f"e-{i}.md", fm, f"## Summary\n{prose}\n")
    _reset()
    body = graph_builder.build_graph(memory).model_dump(mode="json", by_alias=True)
    grown = _size(body)
    for node in body["nodes"]:
        for key in ("picture", "pictureSource", "lastReferenced"):
            node.pop(key, None)
    base = _size(body)
    growth = (grown - base) / base
    print(f"\nC11 /graph, {N_NODES} nodes, 1 in 10 with a picture: {base:,} -> {grown:,} bytes (+{growth:.1%})")
    assert grown > base, "the fields must be on the wire to be measured"
    assert growth <= 0.10
