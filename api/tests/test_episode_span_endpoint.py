"""G118 slice 1 — `GET /episodes/{id}/span`: slice a stored body back out.

Engine-free, a few ms, and honest about staleness: the caller's `hash` is
compared with the current body and `stale` says whether the offsets still
mean what they meant when the claim was written. Fixtures are synthetic.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import evidence, markdown_parser
from api.services.claims import Claim, write_claims

BODY = (
    "user: I moved alpha-project onto sqlite-vec last week.\n"
    "assistant: Noted — sqlite-vec replaces LEANN for alpha-project.\n"
    "user: bob-example reviewed it."
)


@pytest.fixture
def memory(tmp_path: Path, monkeypatch) -> Path:
    """The `home` fixture pattern from test_healthz_memory_root.py / test_auth.py:
    a tmp CICADA_HOME + memory root, settings cache cleared on both sides."""
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    markdown_parser.write(memory / "episodes" / "ep_2026-09-01_001.md", {"id": "ep_2026-09-01_001"}, BODY)
    # `decay_class: evergreen` up front: app startup runs `run_bank_migrations`
    # on this bank, and the decay-class backfill would otherwise rewrite this
    # media page's FRONTMATTER (body untouched — R1 — so the hash would still
    # match; declaring it just keeps the fixture byte-stable across the test).
    markdown_parser.write(memory / "entities" / "media-ros-guide.md",
                          {"name": "ROS guide", "type": "media", "decay_class": "evergreen"},
                          write_claims("## Summary\nSaved.\n\n## Description\nA guide to ROS.", [Claim(id="c", text="t")]))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    config.get_settings.cache_clear()
    yield memory
    config.get_settings.cache_clear()


def test_span_returns_text_and_context_for_an_episode(memory):
    start, end = BODY.find("sqlite-vec replaces"), BODY.find("LEANN") + 5
    with TestClient(main.app) as client:
        r = client.get("/episodes/ep_2026-09-01_001/span", params={"start": start, "end": end, "context": 12,
                                                                    "hash": evidence.body_hash(BODY)})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["episode"] == "ep_2026-09-01_001"
    assert data["text"] == "sqlite-vec replaces LEANN"
    assert data["before"] == BODY[start - 12:start] and data["after"] == BODY[end:end + 12]
    assert data["stale"] is False and data["kind"] == "assistant"
    assert data["start"] == start and data["end"] == end and data["length"] == len(BODY)


def test_span_defaults_context_to_240_and_clips_at_the_edges(memory):
    with TestClient(main.app) as client:
        r = client.get("/episodes/ep_2026-09-01_001/span", params={"start": 6, "end": 11})
    assert r.status_code == 200
    data = r.json()
    assert data["text"] == "I mov" and data["before"] == "user: " and data["after"] == BODY[11:251]
    assert data["stale"] is False  # no hash given -> nothing to be stale against


def test_span_marks_stale_on_hash_mismatch_but_still_slices(memory):
    with TestClient(main.app) as client:
        r = client.get("/episodes/ep_2026-09-01_001/span", params={"start": 6, "end": 11, "hash": "deadbeefcafe"})
    assert r.status_code == 200 and r.json()["stale"] is True and r.json()["text"] == "I mov"


def test_span_resolves_a_media_page_with_the_claims_block_excluded(memory):
    text = evidence.source_text(memory, "media-ros-guide")
    s = text.find("ROS")
    with TestClient(main.app) as client:
        r = client.get("/episodes/media-ros-guide/span",
                       params={"start": s, "end": s + 3, "hash": evidence.body_hash(text)})
    assert r.status_code == 200
    assert r.json()["text"] == "ROS" and r.json()["kind"] == "page" and r.json()["stale"] is False
    assert r.json()["length"] == len(text)  # the fence is not part of the addressable text


def test_span_404_on_unknown_or_traversing_ids(memory):
    with TestClient(main.app) as client:
        assert client.get("/episodes/ep_2026-01-01_999/span", params={"start": 0, "end": 1}).status_code == 404
        r = client.get("/episodes/..%2Fepisodes%2Fep_2026-09-01_001/span", params={"start": 0, "end": 1})
    assert r.status_code in (404, 422)


def test_span_422_on_bad_ranges(memory):
    with TestClient(main.app) as client:
        for params in ({"start": -1, "end": 5}, {"start": 5, "end": 5}, {"start": 5, "end": 4},
                       {"start": 0, "end": len(BODY) + 1}, {"start": 0, "end": 5, "context": 5000},
                       {"start": 0, "end": 5, "context": -1}, {"end": 5}):
            assert client.get("/episodes/ep_2026-09-01_001/span", params=params).status_code == 422, params


def test_span_endpoint_is_bearer_gated_like_every_other_route(memory, monkeypatch):
    # conftest turns auth off for the suite; flip it on the way test_auth.py does.
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.setenv("CICADA_API_TOKEN", "secret-token")
    with TestClient(main.app) as client:
        denied = client.get("/episodes/ep_2026-09-01_001/span", params={"start": 0, "end": 1})
        ok = client.get("/episodes/ep_2026-09-01_001/span", params={"start": 0, "end": 1},
                        headers={"Authorization": "Bearer secret-token"})
    assert denied.status_code == 401
    assert ok.status_code == 200
