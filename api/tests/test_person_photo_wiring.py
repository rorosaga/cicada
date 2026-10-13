"""G159 amendment (owner 2026-10-09) — the public-profile rung on `/graph`, the card, `GET /entities/{id}/photo` and
`/sync/version`. Fake HTTP only: nothing here reaches a real service."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, graph_builder, logo_service, markdown_parser, person_photo, sync_service
from api.services.logo_service import FetchResult
from api.tests.test_person_photo import FakeHTTP, png_bytes

GITHUB = [{"ref": "https://github.com/bob-example", "kind": "url", "added_by": "user"}]


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
        "bob-example": {"name": "Bob Example", "type": "person", "sources": GITHUB},
        "carol-example": {"name": "Carol Example", "type": "person"},
        "dana-example": {"name": "Dana Example", "type": "person", "sources": GITHUB,
                         "picture": {"kind": "initials", "added": "2026-10-09"}},
    }
    for eid, fm in pages.items():
        markdown_parser.write(memory / "entities" / f"{eid}.md", fm, "## Summary\nA person.\n")
    monkeypatch.setattr(logo_service, "cached_ids", lambda bank: set())
    monkeypatch.setattr(logo_service, "missed_ids", lambda bank: {})
    config.get_settings.cache_clear()
    _reset()
    yield memory
    config.get_settings.cache_clear()
    _reset()


def _nodes(memory):
    _reset()
    return {n.id: n for n in graph_builder.build_graph(memory).nodes}


def _fetch(memory, monkeypatch, http):
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "on")
    monkeypatch.setenv("CICADA_ALLOW_PERSON_PHOTO_FETCH", "on")
    path = asyncio.run(person_photo.ensure_photo(memory, "bob-example", fetcher=http))
    monkeypatch.setenv("CICADA_ALLOW_PERSON_PHOTO_FETCH", "off")
    return path


def _key(memory, eid):
    fm = markdown_parser.parse(memory / "entities" / f"{eid}.md").frontmatter
    return person_photo.identity_key(person_photo.candidates(fm, owner={}))


def test_a_person_with_a_profile_link_is_offered_the_rung_and_one_without_is_not(bank):
    nodes = _nodes(bank)
    assert (nodes["bob-example"].picture, nodes["bob-example"].picture_source) == \
        (f"/entities/bob-example/photo?k={_key(bank, 'bob-example')}", "profile"), \
        "before a copy is stored, the URL names the identifier, so a new one is a new URL"
    assert nodes["carol-example"].picture is None, "no identifier: a monogram, never a guess"
    assert nodes["dana-example"].picture_source == "initials", "the person's choice outranks it"


def test_a_stored_photo_versions_the_url_and_moves_the_node_hash_and_the_stamp(bank, monkeypatch):
    before = _nodes(bank)["bob-example"].content_hash
    stamp = sync_service.components(bank)["photos"]
    http = FakeHTTP({"https://github.com/bob-example.png": FetchResult(200, png_bytes(), "image/png")})
    assert _fetch(bank, monkeypatch, http) is not None
    node = _nodes(bank)["bob-example"]
    sha = person_photo.read_meta("work")["bob-example"]["sha"]
    assert node.picture == f"/entities/bob-example/photo?v={sha}"
    assert node.content_hash != before
    assert sync_service.components(bank)["photos"] != stamp


def test_a_miss_drops_the_rung_until_its_window_passes(bank, monkeypatch):
    _fetch(bank, monkeypatch, FakeHTTP({}))
    assert _nodes(bank)["bob-example"].picture is None


def test_the_card_carries_the_twins_inputs(bank):
    with TestClient(main.app) as c:
        body = c.get("/entities/bob-example").json()
    assert body["pictureSource"] == "profile"
    assert body["pictureInputs"]["profile"] is True and body["pictureInputs"]["profileSha"] is None
    assert body["pictureInputs"]["profileKey"] == _key(bank, "bob-example")


def test_the_photo_route_serves_the_stored_copy_and_never_fetches_with_the_gate_off(bank, monkeypatch):
    with TestClient(main.app) as c:
        assert c.get("/entities/bob-example/photo").status_code == 404, "gate off: nobody is asked"
        assert c.get("/entities/nobody-example/photo").status_code == 404
    assert person_photo.read_meta("work") == {}
    http = FakeHTTP({"https://github.com/bob-example.png": FetchResult(200, png_bytes(), "image/png")})
    _fetch(bank, monkeypatch, http)
    with TestClient(main.app) as c:
        r = c.get("/entities/bob-example/photo")
        assert r.status_code == 200 and r.content == png_bytes()
        assert r.headers["content-type"] == "image/png"
        etag = r.headers["etag"]
        assert c.get("/entities/bob-example/photo", headers={"If-None-Match": etag}).status_code == 304
        # The person's choice wins: the stored copy is not served under initials.
        assert c.get("/entities/dana-example/photo").status_code == 404
    assert len(http.asked) == 1


def test_a_fetch_reaches_graph_through_its_etag_and_its_cache(bank, monkeypatch):
    """Review B1: the photos stamp must move `/graph`'s ETag AND `_build_full`'s cache — no `_reset` in between."""
    with TestClient(main.app) as c:
        first = c.get("/graph")
        etag = first.headers["etag"]
        bob = next(n for n in first.json()["nodes"] if n["id"] == "bob-example")
        assert "?k=" in bob["picture"]
        http = FakeHTTP({"https://github.com/bob-example.png": FetchResult(200, png_bytes(), "image/png")})
        _fetch(bank, monkeypatch, http)
        again = c.get("/graph", headers={"If-None-Match": etag})
        assert again.status_code == 200, "a stored photo moves the ETag"
        bob = next(n for n in again.json()["nodes"] if n["id"] == "bob-example")
        sha = person_photo.read_meta("work")["bob-example"]["sha"]
        assert bob["picture"] == f"/entities/bob-example/photo?v={sha}"


def test_a_changed_identifier_is_a_new_url(bank):
    before = _nodes(bank)["bob-example"].picture
    markdown_parser.write(bank / "entities" / "bob-example.md",
                          {"name": "Bob Example", "type": "person",
                           "sources": [{**GITHUB[0], "ref": "https://github.com/bob-other"}]}, "## Summary\nA person.\n")
    bank_index.invalidate()
    assert graph_builder.build_graph(bank).nodes and _nodes(bank)["bob-example"].picture != before
